"""The event log: every removal and re-listing a list has ever had, in the order it happened.

The removal register (`removed.json`) answers "who is off the list now". It keeps one entry per
company and drops it when the company comes back, so on its own it cannot show a company that was
removed and later re-listed (Hesai, October 2024). The event log keeps everything and is only ever
added to; the register is derived from it, so the two can never disagree.

Events are plain dicts:
  {"event": "removal", "name", "aka", "removed_on", "reason", "cite", "source_doc", "source_url", ...}
  {"event": "relisting", "name", "date", "cite", "source_doc", "source_url"}
Every event also carries `entered_by` ("rule", "editor", or "migrated" for entries copied from a
register written before the log existed). Pure functions; the caller writes the file.
"""
from __future__ import annotations

from .names import key

EVENTS_FILE = "events.json"
REMOVAL, RELISTING = "removal", "relisting"


def _keys(e: dict) -> set[str]:
    return {k for k in (key(s) for s in [e.get("name", ""), *e.get("aka", [])]) if k}


def _date(e: dict) -> str:
    return e.get("removed_on") if e.get("event") == REMOVAL else e.get("date", "")


def migrate(register: list[dict]) -> list[dict]:
    """A log that reproduces an existing register: one removal event per entry."""
    return [{"event": REMOVAL, **e, "entered_by": "migrated"} for e in register]


def register_from(events: list[dict], rows: list[dict]) -> list[dict]:
    """The removal register the log implies: each company's latest removal, unless a later
    re-listing cancels it or the company is on the list now. Same order as the register file."""
    listed = set().union(*(_keys(r) for r in rows)) if rows else set()
    latest: dict[str, dict] = {}
    for e in sorted(events, key=_date):          # stable: same-day events keep log order
        k = key(e["name"])
        if e["event"] == REMOVAL:
            latest[k] = e
        elif e["event"] == RELISTING:
            latest.pop(k, None)
    out = []
    for k, e in latest.items():
        if k in listed:
            continue
        out.append({f: v for f, v in e.items() if f not in ("event", "entered_by", "recorded_at")})
    return sorted(out, key=lambda e: (e["removed_on"], e["name"]))


def diff(old_register: list[dict], new_register: list[dict], rows: list[dict], *,
         date: str, doc: dict, entered_by: str = "rule") -> list[dict]:
    """The events one approval adds: a removal for each new or changed register entry, and a
    re-listing for each company that leaves the register because it is back on the list."""
    old = {key(e["name"]): e for e in old_register}
    new = {key(e["name"]): e for e in new_register}
    listed = set().union(*(_keys(r) for r in rows)) if rows else set()
    out = []
    for k, e in new.items():
        if old.get(k) != e:
            out.append({"event": REMOVAL, **e, "entered_by": entered_by})
    for k, e in old.items():
        if k not in new and k in listed:
            out.append({"event": RELISTING, "name": e["name"], "aka": e.get("aka", []), "date": date,
                        "cite": doc.get("citation", ""), "source_doc": doc.get("document_number", ""),
                        "source_url": doc.get("html_url", ""), "entered_by": entered_by})
    return out


def check(events: list[dict], register: list[dict], rows: list[dict]) -> list[str]:
    """Differences between the stored register and the one the log implies (empty when they agree)."""
    want = {key(e["name"]): e for e in register_from(events, rows)}
    have = {key(e["name"]): e for e in register}
    probs = [f"in the register but not implied by the log: {have[k]['name']}" for k in have.keys() - want.keys()]
    probs += [f"implied by the log but not in the register: {want[k]['name']}" for k in want.keys() - have.keys()]
    probs += [f"register entry differs from the log: {have[k]['name']}" for k in have.keys() & want.keys()
              if have[k] != want[k]]
    return sorted(probs)
