"""A list's history, gathered from its saved sources for the completeness check.

The list's folder holds:
  sources/              the notices the current list rests on
  history/              earlier annual lists (Federal Register text)
  history/notices/      earlier amendment notices (removals, designations)
  dow-pdf/              the Department's own list PDFs, with their text and both hashes
  notices.json          the notice log (metadata for every Federal Register document)
  history-decisions.json  the editor's decisions for companies no document removes
The rules module names the snapshots (HISTORY_LISTS) and the amendment notices (HISTORY_NOTICES).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import ListwatchError, SourceError, completeness, detect, pdfsource, sources

DECISIONS_FILE = "history-decisions.json"


def has_history(rules, folder: Path) -> bool:
    """A list keeps a history when its rules name snapshots and its folder holds decisions."""
    return hasattr(rules, "HISTORY_LISTS") and (folder / DECISIONS_FILE).exists()


def notice_text(folder: Path, doc: str) -> tuple[str, dict]:
    """A saved Federal Register notice from wherever it is kept, hash-checked, with its metadata
    from the notice log."""
    meta = detect.load_log(folder)["documents"].get(doc)
    if not meta:
        raise SourceError(f"{doc} is not in the notice log")
    for sub in ("sources", "history", "history/notices"):
        if (folder / sub / f"{doc}.json").exists():
            text, _ = sources.load(folder / sub, doc)
            return text, {**meta, "document_number": doc}
    raise SourceError(f"{doc}: no saved copy")


def inputs(rules, folder: Path, current: list[dict], current_date: str) -> tuple[list[dict], list[dict]]:
    """(lists, statements): every snapshot from the first list to the current one, and every
    removal or listing any saved document states."""
    pdf_dir = folder / pdfsource.FOLDER
    lists, statements = [], []
    for snap in rules.HISTORY_LISTS:
        if snap.get("fr"):
            text, meta = notice_text(folder, snap["fr"])
            names = rules.earlier_names(text, meta)
        else:
            pages, _ = pdfsource.load(pdf_dir, snap["pdf"])
            names = rules.pdf_roster(pages, snap["pdf"])
        prior = lists[-1]["names"] if lists else []
        if snap.get("fr") and meta.get("kind") == "annual":      # the 2021 list is filed as a designation
            statements += rules.fr_statements(text, meta, prior)
        if snap.get("pdf"):
            statements += rules.pdf_statements(*pdfsource.load(pdf_dir, snap["pdf"]))
        lists.append({"id": snap["id"], "date": snap["date"], "names": names})
    lists.append({"id": "current", "date": current_date, "names": current})
    for doc in rules.HISTORY_NOTICES:
        text, meta = notice_text(folder, doc)
        in_force = [x for x in lists if x["date"] < meta["publication_date"]][-1]
        statements += rules.fr_statements(text, meta, in_force["names"])
    return lists, statements


def read_decisions(folder: Path) -> list[dict]:
    p = folder / DECISIONS_FILE
    return json.loads(p.read_text())["decisions"] if p.exists() else []


def evidence_problems(rules, folder: Path, decisions: list[dict]) -> list[str]:
    """Every quote a decision cites must appear word for word in the saved document it names."""
    out = []
    for dec in decisions:
        if not dec.get("evidence"):
            out.append(f"decision {dec['id']}: no evidence")
        for ev in dec.get("evidence", []):
            try:
                if ev["source_doc"].startswith("dow-"):
                    pages, _ = pdfsource.load(folder / pdfsource.FOLDER, ev["source_doc"])
                    text = "\f".join(pages)
                else:
                    text, _ = notice_text(folder, ev["source_doc"])
                rules.verbatim(ev["quote"], text, f"decision {dec['id']}")
            except ListwatchError as e:
                out.append(str(e))
    return out


def report(rules, folder: Path, current: list[dict], current_date: str,
           equivalents: list[tuple[str, str]] = ()) -> completeness.Report:
    """The completeness check with every decision's evidence re-checked."""
    lists, statements = inputs(rules, folder, current, current_date)
    decisions = read_decisions(folder)
    rep = completeness.check(lists, statements, decisions, equivalents)
    rep.problems += evidence_problems(rules, folder, decisions)
    return rep


def first_listed(rules, folder: Path, current: list[dict], current_date: str,
                 equivalents: list[tuple[str, str]] = ()) -> list[dict]:
    """The date each company was first printed, back to the first list: the Department's release
    date of the first list that prints it, where that list's PDF is saved (2024: released January
    31, printed in the Federal Register April 2), else the list's own date. Followed through
    approved renames; a company printed again after a gap keeps its first date. A company whose
    spellings fell into another's on one list is left out rather than shown with a date that may
    be another company's."""
    lists, _ = inputs(rules, folder, current, current_date)
    pdf_dir = folder / pdfsource.FOLDER
    released = {}
    for snap in rules.HISTORY_LISTS:
        p = pdf_dir / f"{snap.get('pdf', '')}.json"
        if snap.get("pdf") and p.exists():
            released[snap["id"]] = json.loads(p.read_text()).get("release_date", "")
    lists = [{**x, "date": min(x["date"], released.get(x["id"]) or x["date"])} for x in lists]
    chains = completeness.first_listed(lists, read_decisions(folder), equivalents)
    return [{k: c[k] for k in ("names", "first_listed", "list")} for c in chains if not c["merged"]]


def listed_on(chains: list[dict], row: dict) -> str:
    """A row's first-listed date from `first_listed`, matched by any spelling; "" if none."""
    ks = completeness.keys(row)
    hit = next((c for c in chains if any(completeness.keys({"name": n}) & ks for n in c["names"])), None)
    return hit["first_listed"] if hit else ""


_SHOWN = ("removed", "not printed, no notice", "listed elsewhere")


def removals(rules, folder: Path, current: list[dict], current_date: str,
             equivalents: list[tuple[str, str]] = ()) -> list[dict]:
    """Every company that left the list since the first one, newest first, as a page shows it:
    {"name", "listed", "removed", "relisted", "statements": [the removing documents' statements],
    "documents": [{"cite", "url"}], "note"}. Removal
    dates follow the removal register: the Federal Register notice where one removes the company,
    else the DoW PDF; a company no document removes is dated by the first list that no longer
    prints it."""
    lists, statements = inputs(rules, folder, current, current_date)
    decisions = read_decisions(folder)
    rep = completeness.check(lists, statements, decisions, equivalents)
    chains = first_listed(rules, folder, current, current_date, equivalents)
    snaps = {x["id"]: x for x in lists}
    notes = {d["name"]: d.get("reader_note", "") for d in decisions if d.get("status") == "approved"}
    out = []
    for it in rep.items:
        if it["outcome"] not in _SHOWN:
            continue
        a, b = it["transition"].split("→")
        row = next(r for r in snaps[a]["names"] if r["name"] == it["name"])
        mine = [s for s in statements if snaps[a]["date"] < s["published"] <= snaps[b]["date"]
                and completeness.keys(s) & completeness.keys(row)]
        gone = [s for s in mine if s["event"] == "removal"]
        back = [s for s in mine if s["event"] == "listing"]
        out.append({"name": it["name"], "aka": row.get("aka", []), "outcome": it["outcome"],
                    "listed": listed_on(chains, row),
                    # dated by the Federal Register notice where one removes it (as the removal
                    # register is), else by the DoW PDF that does
                    "removed": min((s["published"] for s in gone if s["source_kind"] == "federal_register"),
                                   default=min((s["published"] for s in gone), default=snaps[b]["date"])),
                    "relisted": min((s["published"] for s in back), default=""),
                    "statements": [x for s in gone for x in s["statements"]],
                    "documents": [{"cite": s["cite"], "url": _doc_link(folder, s)} for s in gone],
                    "note": notes.get(it["name"], "")})
    return sorted(out, key=lambda r: (r["removed"], r["name"]), reverse=True)


def _doc_link(folder: Path, s: dict) -> str:
    """The official page a statement is printed on: the DoW PDF's page, or the notice's page."""
    if s["source_kind"] == "dow_pdf":
        _, rec = pdfsource.load(folder / pdfsource.FOLDER, s["source_doc"])
        return pdfsource.page_link(rec, s["page"])["official"]
    return s.get("html_url", "")
