"""A list's history, gathered from its saved sources for the completeness check (plan 2026-11-22-001
U5, U9). Shared by every caller: the same code runs in the app and in a standalone copy.

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
