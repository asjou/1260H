"""Rules for the DoW Section 1260H list of Chinese military companies.

Everything this package knows about Section 1260H lives here: the Federal Register query, the four
notice phrasings DoW has used since 2021, and the layout of the 2026 annual notice. Any other
layout raises LayoutError: the notice then goes to the fallback reader or to a human, never to a
guess.

Layout of the 2026 annual notice (91 FR 35189), as read from the Federal Register full text:
  - each company starts a flush-left block: "Name (Short) (and Short subsidiaries: A, B, and C)";
  - a block indented four spaces is a company listed under the one above it (Autel Robotics);
  - each company is followed by a reason paragraph indented five spaces;
  - "[[Page N]]" markers sit on their own between blocks; a reason paragraph cut by a marker
    continues, unindented, after it (the two "page-break fragments" removed by hand in Sept. 2026);
  - a closing section lists "previously listed entities" removed from the last list.
"""
from __future__ import annotations

import re

from .. import LayoutError
from ..names import key, parse_entry, split_companies, split_top, squash
from ..rules import Parsed

SLUG = "dow-1260h"
QUERY = {"agency": "defense-department", "term": "1260H"}
CITE = "FY2021 NDAA \u00a7 1260H, Pub. L. 116-283"
DEFAULTS = {"country": "China", "category": "Chinese military company (Section 1260H)",
            "cite": CITE, "listing_basis": "direct", "date_added": ""}

_TITLES = (
    ("annual", re.compile(r"^Notice of Availability of Designation of Chinese Military Compan", re.I)),
    ("mixed", re.compile(r"^Notice of Removal of Designated Chinese Military Compan.*\band Notice of Designation", re.I)),
    ("removal", re.compile(r"^Notice of Removal of Designated Chinese Military Compan", re.I)),
    ("addition", re.compile(r"^Notice of Designation of Chinese Military Compan", re.I)),
)
# Known slips in a notice's own text, corrected openly here rather than silently in the data. Each is
# keyed by document number; the editor reviews this table like any other rule.
ERRATA = {
    "2026-11571": {
        # 91 FR 35192 omits the comma between two COMAC subsidiaries (the DoW PDF lists them apart).
        "COMAC America Corporation Shanghai Aircraft Design and Research Institute":
            ["COMAC America Corporation", "Shanghai Aircraft Design and Research Institute"],
    },
}

_UNRELATED = re.compile(r"Defense Federal Acquisition Regulation Supplement|\bDFARS\b", re.I)

_ANNUAL_LEAD = re.compile(r"the\s+following\s+entities\s+qualify\s+for\s+designation\s+as[\s\S]{0,600}?section\s+1260H:\s*\n", re.I)
_ANNUAL_END = re.compile(r"\n {4}(The Deputy Secretary of (Defense|War) has determined that the following\s+"
                         r"previously listed|The list of entities designated)", re.I)
_REMOVALS_LEAD = re.compile(r"following\s+previously\s+listed\s+entities\s+should\s+be\s+removed[\s\S]{0,300}?:\s*\n", re.I)
_REMOVALS_END = re.compile(r"\n {4}(The list of entities|Reconsideration)", re.I)
_AMEND_LEAD = re.compile(r"the\s+following\s+(?:previously\s+listed\s+)?entit(?:y|ies)\b[\s\S]{0,500}?:\s*\n", re.I)
_AMEND_END = re.compile(r"\n\s*(Dated:|The list of entities|Reconsideration)")
_MARKER = re.compile(r"^\s*\[\[Page (\d+)\]\]\s*$")
_INLINE_MARKER = re.compile(r"\[\[Page (\d+)\]\]")
_SUBS = re.compile(r"^and\s+(.+?)\s+subsidiar(?:y|ies):\s*(.+)$", re.S | re.I)
_REASONISH = re.compile(r"military-civil fusion|Section 1260H\(|is (directly|indirectly) (owned|affiliated)", re.I)


def classify(doc: dict) -> str | None:
    title = doc.get("title") or ""
    for kind, pat in _TITLES:
        if pat.search(title):
            return kind
    return None


def unrelated(doc: dict) -> bool:
    return bool(_UNRELATED.search(doc.get("title") or ""))


# ---- provenance ----

def _volume(doc: dict) -> str:
    m = re.match(r"(\d+)\s+FR", doc.get("citation") or "")
    if not m:
        raise LayoutError(f"{doc.get('document_number')}: no Federal Register citation")
    return m.group(1)


def provenance(doc: dict, page: int) -> dict:
    """Source fields for a row read from `doc` at Federal Register page `page`."""
    start = int(doc.get("start_page") or page)
    cite = f"{_volume(doc)} FR {page}"
    pdf = doc.get("pdf_url") or ""
    return {"source_doc": doc["document_number"], "source_cite": cite, "source_page": page,
            "source_url": f"{pdf}#page={page - start + 1}" if pdf else doc.get("html_url", ""),
            "cite": f"{CITE}; {cite}"}


def _row(name: str, aka: list[str], parent: str, doc: dict, page: int) -> dict:
    return {"name": name, "aka": aka, **DEFAULTS, "parent": parent, **provenance(doc, page)}


# ---- blocks ----

def _segments(raw: str) -> list[tuple[int, str]]:
    """Split one blank-line block into (indent, text) segments. The Federal Register text does not
    always put a blank line between a reason paragraph and the next company, so a new segment also
    starts at a line indented 4 or 5+ spaces, or at an unindented line after a reason paragraph
    that has reached its full stop."""
    segs: list[list] = []
    for line in raw.split("\n"):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        cur = segs[-1] if segs else None
        done_reason = cur and cur[0] >= 5 and _closed(" ".join(cur[1]))
        if cur is None or indent >= 4 or done_reason:
            segs.append([indent, [line.strip()]])
        else:
            cur[1].append(line.strip())
    return [(i, squash(" ".join(ls))) for i, ls in segs]


def _closed(text: str) -> bool:
    text = text.rstrip()
    return text.endswith(".") and text.count("(") <= text.count(")")


def _blocks(text: str, start_page: int) -> list[dict]:
    """Split a section into blocks with their indent and page. Page markers move the page; a block
    a marker cut in two is joined back to the part after it."""
    out: list[dict] = []
    page, after_marker = start_page, False
    for raw in re.split(r"\n[ \t]*\n", text):
        if not raw.strip():
            continue
        m = _MARKER.match(raw)
        if m:
            page, after_marker = int(m.group(1)), True
            continue
        inline = _INLINE_MARKER.findall(raw)
        for n, (indent, seg) in enumerate(_segments(_INLINE_MARKER.sub(" ", raw))):
            prev = out[-1] if out else None
            if n == 0 and after_marker and prev and _unfinished(prev):
                prev["text"] += " " + seg
            else:
                out.append({"indent": indent, "text": seg, "page": page})
        if inline:
            page = int(inline[-1])
        after_marker = False
    return out


def _unfinished(block: dict) -> bool:
    """A block a page marker cut in two: a name with an open parenthesis, or a reason paragraph
    that has not reached its full stop."""
    text = block["text"].rstrip()
    if text.count("(") > text.count(")"):
        return True
    return block["indent"] >= 5 and not text.endswith(".")


def _split_subsidiaries(entry: str) -> tuple[str, list[str]]:
    """'Parent (P) (and P subsidiaries: A, B)' -> ('Parent (P)', ['A', 'B'])."""
    groups, depth, start = [], 0, None
    for i, ch in enumerate(entry):
        if ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                groups.append((start, i))
    for s, e in reversed(groups):
        m = _SUBS.match(entry[s + 1:e].strip())
        if m:
            # 91 FR 35191 types ". " for ", " once ("Co., Ltd. . Kiekert USA Inc."): read it as a comma.
            return entry[:s].rstrip(), split_companies(re.sub(r"\s\.\s", ", ", m.group(2)))
    return entry, []


def _errata(doc: dict, names: list[str]) -> list[str]:
    fixes = ERRATA.get(doc.get("document_number", ""), {})
    out: list[str] = []
    for n in names:
        out.extend(fixes.get(n.rstrip(" ."), [n]))
    return out


def _section(text: str, lead: re.Pattern, end: re.Pattern, what: str) -> tuple[int, str]:
    m = lead.search(text)
    if not m:
        raise LayoutError(f"{what}: lead sentence not found")
    rest = text[m.end():]
    e = end.search(rest)
    return m.end(), rest[: e.start()] if e else rest


def _page_at(text: str, offset: int, start_page: int) -> int:
    pages = [int(p) for p in _INLINE_MARKER.findall(text[:offset])]
    return pages[-1] if pages else start_page


# ---- parsers ----

def _parse_annual(text: str, doc: dict) -> Parsed:
    start = int(doc.get("start_page") or 0)
    offset, body = _section(text, _ANNUAL_LEAD, _ANNUAL_END, "annual list")
    blocks = _blocks(body, _page_at(text, offset, start))
    rows: list[dict] = []
    parent = ""
    reasons = 0
    for i, b in enumerate(blocks):
        if b["indent"] >= 5:
            reasons += 1
            continue
        nxt = blocks[i + 1] if i + 1 < len(blocks) else None
        if not nxt or nxt["indent"] < 5:
            raise LayoutError(f"annual list: no reason paragraph after {b['text'][:80]!r} "
                              "(this is not the 2026 layout)")
        head, subs = _split_subsidiaries(b["text"])
        name, aka = parse_entry(head)
        top = b["indent"] == 0
        rows.append(_row(name, aka, "" if top else parent, doc, b["page"]))
        for s in _errata(doc, subs):
            sname, saka = parse_entry(s)
            rows.append(_row(sname, saka, name, doc, b["page"]))
        if top:
            parent = name
    if not reasons:
        raise LayoutError("annual list: no reason paragraphs (this is not the 2026 layout)")
    _check_rows(rows)

    register: list[dict] = []
    m = _REMOVALS_LEAD.search(text)
    if m:
        rest = text[m.end():]
        e = _REMOVALS_END.search(rest)
        page = _page_at(text, m.end(), start)
        for line in (rest[: e.start()] if e else rest).split("\n"):
            if not line.strip() or _MARKER.match(line):
                continue
            name, aka = parse_entry(line)
            register.append({"name": name, "aka": aka,
                             "reason": f"Removed when the annual list of {doc['publication_date']} was published.",
                             **_removal_source(doc, page)})
    return Parsed(roster=rows, register=register)


def _removal_source(doc: dict, page: int) -> dict:
    p = provenance(doc, page)
    return {"removed_on": doc["publication_date"], "cite": p["source_cite"], "source_doc": p["source_doc"],
            "source_url": doc.get("html_url") or p["source_url"], "pdf_url": p["source_url"]}


def _amendment_blocks(text: str, doc: dict) -> tuple[list[dict], str, int]:
    offset, body = _section(text, _AMEND_LEAD, _AMEND_END, doc.get("document_number", "notice"))
    start = int(doc.get("start_page") or 0)
    blocks = _blocks(body, _page_at(text, offset, start))
    # In an amendment notice the names are flush left; any indented paragraph (four spaces is the
    # Federal Register's ordinary paragraph indent) is the notice explaining itself.
    heads = [b for b in blocks if b["indent"] == 0]
    if not heads:
        raise LayoutError(f"{doc.get('document_number')}: no entity names after the lead sentence")
    reason = " ".join(b["text"] for b in blocks if b["indent"] > 0)
    return heads, reason, _page_at(text, offset, start)


def _parse_removal(text: str, doc: dict, current: list[dict]) -> Parsed:
    heads, reason, page = _amendment_blocks(text, doc)
    names_text = " ".join(h["text"] for h in heads)
    left = key(names_text)
    found: list[dict] = []
    # Longest names first, so "China Mobile Limited" does not eat part of a longer name.
    candidates = sorted(((key(s), r) for r in current for s in [r["name"], *r.get("aka", [])] if key(s)),
                        key=lambda kr: -len(kr[0]))
    seen = set()
    for k, r in candidates:
        if k in left and key(r["name"]) not in seen:
            seen.add(key(r["name"]))
            found.append(r)
            for s in [r["name"], *r.get("aka", [])]:
                left = left.replace(key(s), "")
    left = re.sub(r"and|china|inc|ltd|co", "", left) if len(left) < 12 else left
    removes = [{"name": r["name"], "reason": reason, **_removal_source(doc, page)} for r in found]
    return Parsed(removes=removes, leftover=names_text if len(left) > 3 else "")


def _parse_addition(text: str, doc: dict) -> Parsed:
    heads, _reason, _page = _amendment_blocks(text, doc)
    rows: list[dict] = []
    for h in heads:
        for line in [h["text"]]:
            head, subs = _split_subsidiaries(line)
            name, aka = parse_entry(head)
            rows.append(_row(name, aka, "", doc, h["page"]))
            for s in subs:
                sname, saka = parse_entry(s)
                rows.append(_row(sname, saka, name, doc, h["page"]))
    _check_rows(rows)
    return Parsed(adds=rows)


def _check_rows(rows: list[dict]) -> None:
    seen: dict[str, str] = {}
    for r in rows:
        n = r["name"]
        if not key(n):
            raise LayoutError("a parsed row has an empty name")
        if len(n) > 160 or _REASONISH.search(n):
            raise LayoutError(f"reason text read as a name: {n[:90]!r}")
        k = key(n)
        if k in seen:
            raise LayoutError(f"duplicate name in one notice: {seen[k]!r} and {n!r}")
        seen[k] = n


def parse(kind: str, text: str, doc: dict, current: list[dict]) -> Parsed:
    if kind == "annual":
        return _parse_annual(text, doc)
    if kind == "removal":
        return _parse_removal(text, doc, current)
    if kind == "addition":
        return _parse_addition(text, doc)
    raise LayoutError(f"{kind} notices are read by a human (no rule for this kind yet)")


__all__ = ["SLUG", "QUERY", "DEFAULTS", "classify", "unrelated", "parse", "provenance", "split_top"]


# ---- earlier annual lists, read only to compare spellings across years ----
# The 2021, 2024 and 2025 notices print one company per line: a long name wraps onto the next line,
# a footnote sits between two dashed rules, and the list ends at the first indented paragraph or
# section heading. These rows never build the list; they are evidence for a person deciding.

_OLD_LEAD = re.compile(r"has\s+determined\s+that\s+the\s+following\s+entities\s+qualify[\s\S]{0,400}?:\s*\n", re.I)
_FOOTNOTE = re.compile(r"\n-{20,}\n[\s\S]*?\n-{20,}\n")
_PAGE_LINE = re.compile(r"\[\[Page \d+\]\]")
_OLD_END = re.compile(r"^(\s+\S|\*|The (Deputy )?Secretary\b|Reconsideration\b|Dated:)")
_BAD_CLOSE = re.compile(r"\(([^()\]]*)\]")          # "(SMIC Tianjin]": a misprinted bracket, 90 FR 1106


def _wraps(s: str) -> bool:
    """True when a line is cut mid-name: an open parenthesis, a trailing comma or a hyphen."""
    return s.count("(") > s.count(")") or s.endswith((",", "-"))


def earlier_names(text: str, doc: dict) -> list[dict]:
    """Every company an annual list prints, as {"name", "aka"}. The 2026 layout goes through the full
    parser; the older one-per-line layout through a line reader. Any other layout raises LayoutError."""
    try:
        return [{"name": r["name"], "aka": r.get("aka", [])} for r in _parse_annual(text, doc).roster or []]
    except LayoutError:
        pass
    m = _OLD_LEAD.search(text)
    if not m:
        raise LayoutError(f"{doc.get('document_number', 'notice')}: no list of entities found")
    lines, cur = [], ""
    for line in _BAD_CLOSE.sub(r"(\1)", _FOOTNOTE.sub("\n", "\n" + text[m.end():])).split("\n"):
        if _PAGE_LINE.fullmatch(line.strip()):
            continue
        if not line.strip():
            if cur and not _wraps(cur):
                lines.append(cur)
                cur = ""
            continue
        if cur and _wraps(cur):
            cur = cur + line.strip() if cur.endswith("-") else f"{cur} {line.strip()}"
            continue
        if _OLD_END.match(line):
            break
        if cur:
            lines.append(cur)
        cur = line.strip()
    if cur:
        lines.append(cur)
    out = []
    for s in lines:
        s = re.sub(r"\)\s*\d+$", ")", s)                    # a footnote number after the name: "(BGI)9"
        name, aka = parse_entry(s)
        if len(name) > 120 or not re.search(r"[A-Za-z]", name):
            raise LayoutError(f"{doc.get('document_number', 'notice')}: not a company name: {name[:80]!r}")
        out.append({"name": name, "aka": aka})
    if len(out) < 5:
        raise LayoutError(f"{doc.get('document_number', 'notice')}: list too short ({len(out)} names)")
    return out
