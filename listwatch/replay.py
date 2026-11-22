"""The replay check (design rule 3): read every saved source the list rests on, in publication
order, and compare the result with the list as it stands. It is the parser's answer key.

Two files make the check honest:
  - `replay-exceptions.json`: each difference between the replay and the list, with the editor's
    resolution ("same entity", "add", "keep"). An unresolved difference fails the replay.
  - `answer-key.json`: parent and page for chosen rows, checked once by hand against the official
    PDF. Name equality says nothing about parent or page; the key does. Unchecked entries fail it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import ListwatchError
from . import proposal as P
from . import sources
from .detect import classify
from .names import key
from .rules import Parsed

RESOLUTIONS = ("same entity", "add", "keep")


def _read_json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def load_exceptions(folder: Path) -> list[dict]:
    return _read_json(folder / "replay-exceptions.json", {"differences": []})["differences"]


def equivalents(folder: Path) -> list[tuple[str, str]]:
    return [(d["parsed"], d["store"]) for d in load_exceptions(folder)
            if d.get("resolution") == "same entity" and d.get("parsed") and d.get("store")]


def no_alias(folder: Path) -> set[str]:
    """Notice spellings the editor chose not to show as aliases ("alias": false)."""
    return {key(d["parsed"]) for d in load_exceptions(folder)
            if d.get("resolution") == "same entity" and d.get("alias") is False and d.get("parsed")}


def rebuild(rules, folder: Path, docs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Read `docs` (Federal Register records with a saved source) in date order. Returns
    (rows, register entries, the records with their sha256)."""
    ordered = sorted(docs, key=lambda d: (d["publication_date"], d["document_number"]))
    rows: list[dict] | None = None
    register: list[dict] = []
    used = []
    for d in ordered:
        text, rec = sources.load(folder / "sources", d["document_number"])
        kind = classify(d, rules)
        parsed: Parsed = rules.parse(kind, text, d, rows or [])
        if parsed.roster is not None:
            rows = parsed.roster
            register = [e for e in register if key(e["name"]) not in {key(r["name"]) for r in rows}]
            register += parsed.register
        else:
            if rows is None:
                raise ListwatchError(f"{d['document_number']}: an amendment before any annual list")
            if parsed.leftover:
                raise ListwatchError(f"{d['document_number']}: unmatched text {parsed.leftover[:120]!r}")
            gone = {key(r["name"]) for r in parsed.removes}
            for r in rows:
                if key(r["name"]) in gone:
                    match = next(x for x in parsed.removes if key(x["name"]) == key(r["name"]))
                    register.append({**match, "name": r["name"], "aka": r.get("aka", []),
                                     "country": r.get("country", ""), "last_listed_in": r.get("source_doc", "")})
            rows = P.target_rows({"roster": None, "removes": parsed.removes, "adds": parsed.adds}, rows)
        used.append({**d, "sha256": rec["sha256"]})
    return rows or [], register, used


def _annual_rows(rules, folder: Path, docs: list[dict]) -> list[dict]:
    annuals = sorted((d for d in docs if classify(d, rules) == "annual"), key=lambda d: d["publication_date"])
    if not annuals:
        return []
    d = annuals[-1]
    text, _ = sources.load(folder / "sources", d["document_number"])
    return rules.parse("annual", text, d, []).roster or []


@dataclass
class Report:
    differences: list[dict] = field(default_factory=list)   # unresolved
    resolved: list[dict] = field(default_factory=list)
    key_mismatches: list[str] = field(default_factory=list)
    key_unchecked: int = 0
    key_checked: int = 0
    key_missing: bool = False
    rows: int = 0
    require_key: bool = True
    register_mismatches: list[str] = field(default_factory=list)   # rebuilt removals vs removed.json
    history_problems: list[str] = field(default_factory=list)      # the completeness check, if run

    @property
    def ok(self) -> bool:
        key_problem = self.key_unchecked or self.key_missing if self.require_key else False
        return not (self.differences or self.key_mismatches or key_problem or self.register_mismatches
                    or self.history_problems)

    def lines(self) -> list[str]:
        out = [f"replay: {self.rows} rows" + (f"; answer key {self.key_checked} checked, {self.key_unchecked} unchecked"
                                               if self.require_key or self.key_checked else "")]
        if self.key_unchecked and self.require_key:
            out.append(f"  ANSWER KEY: {self.key_unchecked} entries not yet checked against the official PDF")
        if self.key_missing and self.require_key:
            out.append("  ANSWER KEY: none yet (draft one with replay.draft_answer_key, then check it)")
        out += [f"  resolved: {d['parsed'] or '—'} / {d['store'] or '—'} → {d['resolution']}" for d in self.resolved]
        for d in self.differences:
            where = f"  ({d['cite']}, {d['url']})" if d.get("url") else ""
            if d.get("parsed") and d.get("store"):
                out.append(f"  UNRESOLVED: the notice prints {d['parsed']!r}, the list has {d['store']!r}{where}")
            elif d.get("parsed"):
                out.append(f"  UNRESOLVED: in the notice, not on the list: {d['parsed']}{where}")
            else:
                out.append(f"  UNRESOLVED: on the list, not in the notices: {d['store']}")
        out += [f"  ANSWER KEY: {m}" for m in self.key_mismatches]
        out += [f"  REGISTER: {m}" for m in self.register_mismatches]
        out += [f"  HISTORY: {m}" for m in self.history_problems]
        out.append("replay: PASS" if self.ok else "replay: FAIL")
        return out


def compare_register(rebuilt: list[dict], stored: list[dict], history: set[str] = frozenset()) -> list[str]:
    """The removals the replayed notices make must all be in the stored register, with the same
    date and document. A stored entry the notices do not make is allowed only when the list's
    history accounts for it (`history`: name keys removed by earlier documents)."""
    have = {key(e["name"]): e for e in stored}
    out = []
    for e in rebuilt:
        s = have.get(key(e["name"]))
        if s is None:
            out.append(f"{e['name']}: removed by {e.get('source_doc', '?')}, not in removed.json")
        elif (s.get("removed_on"), s.get("source_doc")) != (e.get("removed_on"), e.get("source_doc")):
            out.append(f"{e['name']}: removed.json says {s.get('removed_on')} / {s.get('source_doc')}, "
                       f"the notices say {e.get('removed_on')} / {e.get('source_doc')}")
    made = {key(e["name"]) for e in rebuilt}
    out += [f"{s['name']}: in removed.json, but no saved document removes it" for k, s in have.items()
            if k not in made and k not in history]
    return out


def check(rules, folder: Path, docs: list[dict], current: list[dict], *, require_key: bool = True,
          register: list[dict] | None = None, history: set[str] = frozenset()) -> Report:
    """`require_key=False` skips the answer-key gate (a copy that ships no answer key); every other
    check is the same. With `register` (the stored removed.json entries), the removals the notices
    make are compared with it too; `history` names the removals earlier documents account for."""
    rows, rebuilt_register, _used = rebuild(rules, folder, docs)
    rep = Report(rows=len(rows), require_key=require_key)
    if register is not None:
        rep.register_mismatches = compare_register(rebuilt_register, register, history)
    exc = load_exceptions(folder)
    cmp = P.compare({"roster": rows, "removes": []}, current, equivalents(folder))
    found = [{"parsed": r["name"], "store": None, "cite": r.get("source_cite", ""), "url": r.get("source_url", "")}
             for r in cmp["added"]]
    found += [{"parsed": None, "store": r["name"]} for r in cmp["removed"]]
    paired: set[int] = set()
    for f in found:
        side = "parsed" if f["parsed"] else "store"
        hit = next((e for e in exc if key(e.get(side) or "") == key(f[side] or "")
                    and (e.get("parsed") and e.get("store") or
                         key(e.get("parsed") or "") == key(f["parsed"] or "")
                         and key(e.get("store") or "") == key(f["store"] or ""))), None)
        if hit and hit.get("resolution") in RESOLUTIONS:
            if id(hit) not in paired:
                paired.add(id(hit))
                rep.resolved.append(hit)
        elif hit and hit.get("parsed") and hit.get("store"):
            # a listed pair (two spellings), not yet decided: report it once, as a pair
            if id(hit) not in paired:
                paired.add(id(hit))
                url = next((g["url"] for g in found if g["parsed"] and key(g["parsed"]) == key(hit["parsed"])), "")
                cite = next((g["cite"] for g in found if g["parsed"] and key(g["parsed"]) == key(hit["parsed"])), "")
                rep.differences.append({"parsed": hit["parsed"], "store": hit["store"], "cite": cite, "url": url})
        else:
            rep.differences.append(f)
    for e in exc:
        if e.get("resolution") == "same entity" and id(e) not in paired and e not in rep.resolved:
            rep.resolved.append(e)

    # history entries (kind "history") are checked by the caller against the history statements
    answer = [e for e in _read_json(folder / "answer-key.json", {"entries": []})["entries"]
              if e.get("kind") != "history"]
    rep.key_missing = not answer
    # The key checks how the annual notice was read, so it is compared with that notice's rows,
    # not with the list after later removals.
    annual = _annual_rows(rules, folder, docs) or rows
    by = {key(r["name"]): r for r in annual}
    for e in answer:
        if not e.get("checked"):
            rep.key_unchecked += 1
            continue
        rep.key_checked += 1
        r = by.get(key(e["name"]))
        if r is None:
            rep.key_mismatches.append(f"{e['name']}: not in the replay")
            continue
        if int(r.get("source_page", 0)) != int(e["page"]):
            rep.key_mismatches.append(f"{e['name']}: replay says page {r.get('source_page')}, key says {e['page']}")
        if "subsidiaries" in e:
            got = sorted(key(x["name"]) for x in annual if key(x.get("parent", "")) == key(r["name"]))
            want = sorted(key(s) for s in e["subsidiaries"])
            if got != want:
                rep.key_mismatches.append(f"{e['name']}: replay lists {len(got)} companies under it, key lists {len(want)}")
    return rep


def starting_proposal(rules, folder: Path, docs: list[dict]) -> dict:
    """The one proposal that covers several notices: the latest annual list with the
    amendments since, read from saved sources. Its removals all go to the register."""
    rows, register, used = rebuild(rules, folder, docs)
    parsed = Parsed(roster=rows, register=register)
    return P.build(rules.SLUG, "start", used, parsed, pid=f"start-{max(d['publication_date'] for d in used)}",
                   note="Starting proposal: the saved notices replayed in order. Approving it adds page and "
                        "parent to every row and records the removals; check the differences first.")


def draft_answer_key(rows: list[dict]) -> dict:
    """What the editor checks once against the official PDF: each parent with the companies listed
    under it (one glance per group), and the first and last company on each page."""
    pick: dict[str, dict] = {}
    for r in rows:
        subs = [x["name"] for x in rows if key(x.get("parent", "")) == key(r["name"])]
        if subs:
            pick[key(r["name"])] = {"name": r["name"], "page": int(r["source_page"]), "subsidiaries": subs,
                                    "pdf": r["source_url"], "checked": False}
    pages: dict[int, list[dict]] = {}
    for r in rows:
        if not r.get("parent"):
            pages.setdefault(int(r["source_page"]), []).append(r)
    for rs in pages.values():
        for r in (rs[0], rs[-1]):
            pick.setdefault(key(r["name"]), {"name": r["name"], "page": int(r["source_page"]),
                                             "pdf": r["source_url"], "checked": False})
    return {"note": "Check each entry once against the official PDF (the pdf link opens the page): the "
                    "company is on that page and, for a group, exactly these companies are listed under "
                    "it. Set \"checked\": true when right; correct the entry if not.",
            "entries": sorted(pick.values(), key=lambda e: (e["page"], e["name"]))}
