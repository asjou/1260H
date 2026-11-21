"""Proposals: what one notice (or the one-time starting replay) would change, and how an approved
proposal is applied. Pure functions over plain dicts; nothing here writes the list or publishes.

A proposal holds what the notice says (`roster`, `adds`, `removes`, `register`). The comparison
with the current list is never stored as truth: `compare` recomputes it against the list as it is
now, each time the proposal is shown and again at approval.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path

from . import SCHEMA_PROPOSAL, ListwatchError
from .names import key

# Fields a row carries that no notice supplies; an approval must never drop them.
CARRY = ("verified", "basis_note", "country", "category")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _keys(row: dict) -> set[str]:
    return {k for k in (key(s) for s in [row.get("name", ""), *row.get("aka", [])]) if k}


def build(list_slug: str, kind: str, docs: list[dict], parsed, *, machine_read: bool = False,
          pid: str | None = None, note: str = "") -> dict:
    """A new open proposal. `docs` are the Federal Register records it rests on, each carrying the
    saved source's sha256."""
    if not docs:
        raise ListwatchError("a proposal needs at least one source document")
    latest = max(d["publication_date"] for d in docs)
    return {
        "schema": SCHEMA_PROPOSAL, "id": pid or docs[-1]["document_number"], "list": list_slug,
        "kind": kind, "publication_date": latest, "machine_read": machine_read, "note": note,
        "documents": [{k: d.get(k, "") for k in ("document_number", "title", "type", "publication_date", "citation",
                                                 "start_page", "html_url", "pdf_url", "raw_text_url", "sha256")}
                      for d in docs],
        "roster": parsed.roster, "adds": parsed.adds, "removes": parsed.removes,
        "register": parsed.register, "leftover": parsed.leftover,
        "status": "open", "published": None, "created_at": _now(), "decided_at": None,
    }


# ---- comparison ----

def _match(targets: list[dict], current: list[dict], equivalents: list[tuple[str, str]]) -> dict[int, int]:
    """Pair target rows with current rows: same name first, then an editor-listed equivalent, then
    a shared alias when exactly one candidate shares it. Returns {target index: current index}."""
    pairs: dict[int, int] = {}
    by_name = {key(c["name"]): j for j, c in enumerate(current)}
    for i, t in enumerate(targets):
        j = by_name.get(key(t["name"]))
        if j is not None:
            pairs[i] = j
    used = set(pairs.values())
    eq = {}
    for a, b in equivalents:
        eq[key(a)], eq[key(b)] = key(b), key(a)
    for i, t in enumerate(targets):
        if i in pairs:
            continue
        j = by_name.get(eq.get(key(t["name"]), ""))
        if j is not None and j not in used:
            pairs[i] = j
            used.add(j)
    for i, t in enumerate(targets):
        if i in pairs:
            continue
        cands = [j for j, c in enumerate(current) if j not in used and _keys(t) & _keys(c)]
        if len(cands) == 1:
            pairs[i] = cands[0]
            used.add(cands[0])
    return pairs


def target_rows(prop: dict, current: list[dict]) -> list[dict]:
    """The list as it would stand after this proposal (before carrying fields across)."""
    if prop.get("roster") is not None:
        return list(prop["roster"])
    gone = {key(r["name"]) for r in prop.get("removes", [])}
    kept = [r for r in current if not (_keys(r) & gone)]
    have = set().union(*(_keys(r) for r in kept)) if kept else set()
    return kept + [a for a in prop.get("adds", []) if key(a["name"]) not in have]


def compare(prop: dict, current: list[dict], equivalents: list[tuple[str, str]] = ()) -> dict:
    """What approving `prop` would change in `current`, recomputed now."""
    targets = target_rows(prop, current)
    pairs = _match(targets, current, list(equivalents))
    matched = set(pairs.values())
    added = [t for i, t in enumerate(targets) if i not in pairs]
    removed = [c for j, c in enumerate(current) if j not in matched]
    renamed = [{"from": current[j]["name"], "to": targets[i]["name"]}
               for i, j in pairs.items() if key(current[j]["name"]) != key(targets[i]["name"])]
    cur_keys = set().union(*(_keys(c) for c in current)) if current else set()
    unmatched = [r["name"] for r in prop.get("removes", []) if not (key(r["name"]) in cur_keys)]
    return {"added": added, "removed": removed, "renamed": renamed, "unmatched_removals": unmatched,
            "kept": len(pairs), "total_after": len(targets)}


def holds(prop: dict, comparison: dict, *, earlier_open: list[str] = ()) -> list[str]:
    """Reasons this proposal cannot be approved now (generic ones; the caller adds its own)."""
    out = []
    if earlier_open:
        out.append(f"approve the earlier notice first: {', '.join(earlier_open)}")
    if comparison["unmatched_removals"]:
        out.append("the notice removes a company not on the list: " + "; ".join(comparison["unmatched_removals"]))
    if prop.get("leftover"):
        out.append(f"text in the notice's list matched no company on the list: {prop['leftover'][:200]!r}")
    if prop.get("status") != "open":
        out.append(f"proposal is {prop.get('status')}")
    return out


# ---- applying an approved proposal ----

def apply(prop: dict, current: list[dict], register: list[dict], *,
          equivalents: list[tuple[str, str]] = (), no_alias: set[str] = frozenset()) -> tuple[list[dict], list[dict]]:
    """Return (new rows, new register). A matched row keeps its current name (so the registry and the
    public page stay stable), gains the notice's spelling as an alias when it differs, takes the
    notice's provenance, and keeps the fields no notice supplies."""
    targets = target_rows(prop, current)
    pairs = _match(targets, current, list(equivalents))
    rename = {key(targets[i]["name"]): current[j]["name"] for i, j in pairs.items()}
    rows: list[dict] = []
    doc_dates = {d["document_number"]: d.get("publication_date", "") for d in prop.get("documents", [])}
    for i, t in enumerate(targets):
        row = dict(t)
        if t.get("parent"):
            row["parent"] = rename.get(key(t["parent"]), t["parent"])
        if i in pairs:
            old = current[pairs[i]]
            row["name"] = old["name"]
            aka = [*old.get("aka", []), *t.get("aka", [])]
            if key(t["name"]) != key(old["name"]) and key(t["name"]) not in no_alias:
                aka.append(t["name"])
            row["aka"] = _dedupe(aka, exclude=key(old["name"]))
            for f in CARRY:
                if old.get(f) not in (None, "", []):
                    row[f] = old[f]
            row["date_added"] = old.get("date_added") or ""
        elif prop["kind"] == "start":
            # A starting proposal rebuilds the list from saved notices; it cannot tell a newly listed
            # company from one an earlier copy missed, so it does not invent a date.
            row["date_added"] = row.get("date_added") or ""
        else:
            # the date of the notice that lists it, not the date of the proposal
            row["date_added"] = row.get("date_added") or doc_dates.get(row.get("source_doc", ""), prop["publication_date"])
        rows.append(row)

    matched = set(pairs.values())
    entries = list(prop.get("register", []))
    by_removal = {key(r["name"]): r for r in prop.get("removes", [])}
    for j, c in enumerate(current):
        if j in matched:
            continue
        why = next((by_removal[k] for k in _keys(c) if k in by_removal), None)
        base = why or {"reason": f"Not on the list published {prop['publication_date']}.",
                       "removed_on": prop["publication_date"],
                       "cite": prop["documents"][-1].get("citation", ""),
                       "source_doc": prop["documents"][-1]["document_number"],
                       "source_url": prop["documents"][-1].get("html_url", "")}
        entries.append({**base, "name": c["name"], "aka": c.get("aka", []), "country": c.get("country", ""),
                        "last_listed_in": c.get("source_doc", "")})
    new_reg = _merge_register(register, entries, rows)
    return rows, new_reg


def _dedupe(names: list[str], exclude: str = "") -> list[str]:
    """Drop repeats, treating "formerly X" and "X" as the same alias (the shorter form wins)."""
    out, seen = [], {exclude}
    for n in sorted(names, key=lambda s: s.lower().startswith("formerly ")):
        k = key(re.sub(r"^formerly\s+", "", n, flags=re.I))
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out


def _merge_register(register: list[dict], entries: list[dict], rows: list[dict]) -> list[dict]:
    """Add new removal entries (a later removal of the same name replaces the earlier entry) and
    drop entries for any company now back on the list."""
    listed = set().union(*(_keys(r) for r in rows)) if rows else set()
    out = {key(e["name"]): e for e in register}
    for e in entries:
        e = {**e, "country": e.get("country") or "China"}
        out[key(e["name"])] = e
    return sorted((e for k, e in out.items() if k not in listed), key=lambda e: (e["removed_on"], e["name"]))


def currency_date(current: str, prop: dict) -> str:
    """Approval moves the date to the notice's date, never backward."""
    return max(current or "", prop["publication_date"])


# ---- files ----

def path(folder: Path, pid: str) -> Path:
    return folder / f"{pid}.json"


def save(folder: Path, prop: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = path(folder, prop["id"])
    p.write_text(json.dumps(prop, ensure_ascii=False, indent=2) + "\n")
    return p


def load_all(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    props = [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]
    return sorted(props, key=lambda p: (p["publication_date"], p["id"]))


def earlier_open(props: list[dict], prop: dict) -> list[str]:
    return [p["id"] for p in props if p["status"] == "open" and p["id"] != prop["id"]
            and (p["publication_date"], p["id"]) < (prop["publication_date"], prop["id"])]
