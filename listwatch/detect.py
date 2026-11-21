"""Find new notices, classify them, save their sources, and write proposals (diagram 2 of plan
2026-11-20-001). The caller supplies the fetch function, the folder, and (optionally) a fallback
reader; this module reads no configuration and never touches the list itself.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from . import SCHEMA_NOTICES, LayoutError, ListwatchError, SourceError
from . import proposal as P
from . import sources
from .names import key
from .rules import Parsed, check as check_rules

FR_API = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = ("document_number", "title", "action", "type", "publication_date", "citation",
          "html_url", "pdf_url", "raw_text_url", "start_page")
NON_NOTICE_TYPES = ("Rule", "Proposed Rule")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def query_url(query: dict, per_page: int = 50) -> str:
    params = [("per_page", str(per_page)), ("order", "newest")]
    if query.get("agency"):
        params.append(("conditions[agencies][]", query["agency"]))
    if query.get("term"):
        params.append(("conditions[term]", query["term"]))
    params += [("fields[]", f) for f in FIELDS]
    return f"{FR_API}?{urlencode(params)}"


def classify(doc: dict, rules) -> str:
    """'annual' | 'addition' | 'removal' | 'mixed' | 'no_change' | 'unreadable'. A document counts
    as 'no_change' only on positive evidence; anything the rules do not recognise is 'unreadable'."""
    if doc.get("type") in NON_NOTICE_TYPES or rules.unrelated(doc):
        return "no_change"
    return rules.classify(doc) or "unreadable"


# ---- the notice log: every document seen, and what became of it ----

def load_log(folder: Path) -> dict:
    p = folder / "notices.json"
    if not p.exists():
        return {"schema": SCHEMA_NOTICES, "documents": {}}
    data = json.loads(p.read_text())
    if data.get("schema") != SCHEMA_NOTICES:
        raise ListwatchError(f"{p}: unexpected schema {data.get('schema')!r}")
    return data


def save_log(folder: Path, log: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    log["schema"] = SCHEMA_NOTICES
    (folder / "notices.json").write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n")


def mark_reviewed(folder: Path, doc: str) -> None:
    """The editor read a 'no list change' or 'needs human reading' notice and found no change."""
    log = load_log(folder)
    entry = log["documents"].get(doc)
    if not entry or entry.get("outcome") not in ("no_change", "needs_reading"):
        raise ListwatchError(f"{doc} is not awaiting review")
    entry["outcome_before_review"] = entry["outcome"]
    entry["outcome"], entry["reviewed_at"] = "reviewed", _now()
    save_log(folder, log)


@dataclass
class CheckResult:
    baselined: int = 0
    new: list[str] = field(default_factory=list)
    proposals: list[str] = field(default_factory=list)
    needs_reading: list[str] = field(default_factory=list)
    no_change: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.baselined:
            return f"baseline: {self.baselined} existing notice(s) recorded"
        if not self.new:
            return "no new notices"
        parts = [f"{len(self.new)} new notice(s)"]
        for label, xs in (("proposal", self.proposals), ("needs human reading", self.needs_reading),
                          ("no list change", self.no_change), ("error", self.errors)):
            if xs:
                parts.append(f"{label}: {', '.join(xs)}")
        return "; ".join(parts)


def check(rules, folder: Path, fetch, current: list[dict], *, reader=None, dry_run: bool = False,
          log=print, retry_reading: bool = False) -> CheckResult:
    """One pass: query, record new documents, save and read each relevant one, write proposals.

    `fetch(url) -> bytes` must enforce https and the .gov/.mil allowlist on every redirect hop.
    `reader(text, doc) -> {"kind": ..., "names": [...]}` is the optional fallback for a notice the
    rules cannot read; its answer is checked here before anything is proposed.
    `retry_reading=True` (a person at the keyboard) also offers notices earlier left for reading.
    """
    check_rules(rules)
    res = CheckResult()
    nlog = load_log(folder)
    raw = fetch(sources.check_url(query_url(rules.QUERY)))
    try:
        results = json.loads(raw).get("results", [])
    except (json.JSONDecodeError, AttributeError) as e:
        raise SourceError(f"Federal Register response is not valid JSON: {e}")
    docs = {r["document_number"]: r for r in results if r.get("document_number")}
    known = nlog["documents"]
    if not known:
        for n, d in docs.items():
            known[n] = {**_meta(d), "kind": classify(d, rules), "outcome": "baseline", "logged_at": _now()}
        res.baselined = len(docs)
        if not dry_run:
            save_log(folder, nlog)
        return res

    def todo(n):
        if n not in known:
            return True
        e = known[n]          # a person is here with the AI step on: offer the notices left for reading
        return bool(retry_reading and reader is not None and isinstance(e, dict)
                    and e.get("outcome") == "needs_reading" and not e.get("reviewed"))

    for n in sorted((n for n in docs if todo(n)), key=lambda n: (docs[n].get("publication_date", ""), n)):
        d = docs[n]
        res.new.append(n)
        kind = classify(d, rules)
        entry = {**_meta(d), "kind": kind, "logged_at": _now()}
        if kind == "no_change":
            entry["outcome"] = "no_change"
            res.no_change.append(n)
        else:
            try:
                entry.update(_read(rules, folder, fetch, d, kind, current, reader, dry_run, log))
            except (SourceError, ListwatchError) as e:
                entry.update(outcome="error", error=str(e))
                res.errors.append(n)
                log(f"listwatch: {n}: {e}")
            if entry.get("outcome") == "proposal":
                res.proposals.append(n)
            elif entry.get("outcome") == "needs_reading":
                res.needs_reading.append(n)
        if entry.get("outcome") != "error":
            known[n] = entry        # an error is retried on the next run
    if not dry_run:
        save_log(folder, nlog)
    return res


def _meta(d: dict) -> dict:
    return {k: d.get(k, "") for k in ("title", "action", "type", "publication_date", "citation", "start_page",
                                      "html_url", "pdf_url", "raw_text_url")}


def _read(rules, folder, fetch, d, kind, current, reader, dry_run, log) -> dict:
    url = d.get("raw_text_url") or ""
    body = fetch(sources.check_url(url))
    if dry_run:
        rec = {"sha256": "(dry run)"}
        text = sources.clean(body)
    else:
        rec = sources.save(folder / "sources", d["document_number"], url, body, _now())
        text, rec = sources.load(folder / "sources", d["document_number"])
    doc = {**d, "sha256": rec["sha256"]}
    machine = False
    try:
        if kind == "unreadable":
            raise LayoutError("the rules do not recognise this notice")
        parsed = rules.parse(kind, text, d, current)
    except LayoutError as e:
        if reader is None:
            return {"outcome": "needs_reading", "reason": str(e)}
        try:
            parsed, kind = fallback(reader, text, d, current, rules)
        except (LayoutError, ListwatchError) as e2:
            return {"outcome": "needs_reading", "reason": f"{e}; fallback: {e2}"}
        machine = True
    prop = P.build(rules.SLUG, kind, [doc], parsed, machine_read=machine)
    if not dry_run:
        P.save(folder / "proposals", prop)
    log(f"listwatch: {d['document_number']}: {kind} proposal" + (" (machine-read)" if machine else ""))
    return {"outcome": "proposal", "proposal": prop["id"]}


def fallback(reader, text: str, doc: dict, current: list[dict], rules) -> tuple[Parsed, str]:
    """The one LLM step. The reader proposes; this code decides. Every name must appear
    word-for-word in the notice text; a removal must match a company on the list. A machine-read
    proposal is always an amendment, never a replacement of the whole list."""
    try:
        ans = reader(text, doc)
    except Exception as e:  # any reader failure leaves the notice for a human
        raise ListwatchError(f"reader failed: {e}")
    if not isinstance(ans, dict) or not isinstance(ans.get("names"), list):
        raise ListwatchError("reader returned no usable answer")
    kind = ans.get("kind")
    if kind not in ("addition", "removal"):
        kind = "removal" if kind == "annual_removal" else kind
    if kind not in ("addition", "removal"):
        raise ListwatchError(f"reader kind {ans.get('kind')!r} is not an addition or a removal")
    flat = " ".join(text.split()).lower()
    names = [" ".join(str(n).split()) for n in ans["names"] if str(n).strip()]
    if not names:
        raise ListwatchError("reader found no names")
    missing = [n for n in names if n.lower() not in flat]
    if missing:
        raise ListwatchError(f"reader named something not in the notice: {missing}")
    from .names import parse_entry
    defaults = getattr(rules, "DEFAULTS", {})
    prov = getattr(rules, "provenance", None)
    page = int(doc.get("start_page") or 0)
    if kind == "removal":
        cur = {k: r for r in current for k in [key(r["name"]), *(key(a) for a in r.get("aka", []))]}
        unmatched = [n for n in names if key(parse_entry(n)[0]) not in cur]
        if unmatched:
            raise ListwatchError(f"reader removes companies not on the list: {unmatched}")
        removes = [{"name": cur[key(parse_entry(n)[0])]["name"], "reason": "Read by machine; see the notice.",
                    "removed_on": doc["publication_date"], "cite": doc.get("citation", ""),
                    "source_doc": doc["document_number"], "source_url": doc.get("html_url", "")} for n in names]
        return Parsed(removes=removes), "removal"
    adds = []
    for n in names:
        name, aka = parse_entry(n)
        row = {"name": name, "aka": aka, **defaults, "parent": ""}
        if prov:
            row.update(prov(doc, page))
        adds.append(row)
    return Parsed(adds=adds), "addition"


def notice_present(results: list[dict], log: dict) -> list[str]:
    """Document numbers the Federal Register returns that the notice log has not handled."""
    return [r["document_number"] for r in results if r.get("document_number") not in log.get("documents", {})]
