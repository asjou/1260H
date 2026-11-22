"""The completeness check: every company that left the list is accounted for (plan 2026-11-22-001
KD8, U5).

Walk the list's snapshots in date order. For each pair (an earlier list, the next one):
  - every company on the earlier list and not on the next must be explained, by a document that
    removes it in between, or by an editor decision (a rename, or a name kept as an alias);
  - every company a document removes in between must have been on the earlier list, and must be
    gone from the next one unless a document re-lists it;
  - a company removed and re-listed in between should be on the next list; if that list does not
    print it, an editor decision must say why (Hesai: the 2025 notice names it only in a footnote).
Anything else fails. Decisions the editor has not approved count as unexplained.

Pure functions over plain dicts; the caller loads the lists, the statements and the decisions.
  list       {"id", "date", "names": [{"name", "aka"}]}
  statement  {"event": "removal" | "listing", "name", "aka", "published", "source_doc", "cite", ...}
  decision   {"id", "kind", "name", "to", "transition", "basis", "status": "proposed" | "approved",
              "evidence": [...]}
             kind: "rename" (a document states it), "different_name" (printed under another name,
             same parent, no removal), "alias" (folded into a parent entry), "listed_elsewhere"
             (still listed though the name block omits it), "withheld" (accounted for, not shown
             as a removal; held for later checking), "no_notice" (left the list with no
             removal notice; shown as a removal with the fixed marker)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import re

from .names import key


def keys(row: dict) -> set[str]:
    """Every spelling of a row, with and without a trailing short name in brackets: the 2026 list's
    "(formerly Zhonghang Electronic Measuring Instruments Company Limited (ZEMIC))" is the 2025 list's
    "Zhonghang Electronic Measuring Instruments Company Limited"."""
    names = [row.get("name", ""), *row.get("aka", [])]
    names += [re.sub(r"\s*\([^()]*\)\s*$", "", n) for n in names]
    return {k for k in (key(n) for n in names) if k}


def _find(row: dict, rows: list[dict]) -> dict | None:
    ks = keys(row)
    return next((r for r in rows if keys(r) & ks), None)


LABELS = {"rename": "renamed", "different_name": "different name", "alias": "kept as an alias",
          "listed_elsewhere": "listed elsewhere", "withheld": "withheld (editor)",
          "no_notice": "dropped without notice"}
TARGETED = ("rename", "different_name", "alias")


@dataclass
class Report:
    items: list[dict] = field(default_factory=list)       # one per company that left, or was expected back
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def lines(self) -> list[str]:
        out = []
        for it in self.items:
            by = "; ".join(it["by"]) or "-"
            out.append(f"{it['transition']:13} {it['outcome']:17} {it['name'][:60]:60} {by}")
        out += [f"PROBLEM: {p}" for p in self.problems]
        out.append("completeness: OK" if self.ok else f"completeness: {len(self.problems)} problem(s)")
        return out


def _with_equivalents(rows: list[dict], equivalents: list[tuple[str, str]]) -> list[dict]:
    """Rows with each recorded "same company" spelling added as an alias (the editor's replay
    decisions, e.g. Addsino / Addisino)."""
    out = []
    for r in rows:
        ks, aka = keys(r), list(r.get("aka", []))
        for a, b in equivalents:
            if key(a) in ks:
                aka.append(b)
            elif key(b) in ks:
                aka.append(a)
        out.append({**r, "aka": aka})
    return out


def check(lists: list[dict], statements: list[dict], decisions: list[dict],
          equivalents: list[tuple[str, str]] = ()) -> Report:
    rep = Report()
    lists = sorted(({**x, "names": _with_equivalents(x["names"], list(equivalents))} for x in lists),
                   key=lambda x: x["date"])
    for prev, nxt in zip(lists, lists[1:]):
        tr = f"{prev['id']}→{nxt['id']}"
        inside = [s for s in statements if prev["date"] < s["published"] <= nxt["date"]]
        decs = [d for d in decisions if d.get("transition") == tr]
        used: set[str] = set()

        def decision_for(row, kinds):
            for d in decs:
                if d["kind"] in kinds and key(d["name"]) in keys(row):
                    if d["kind"] in TARGETED and not _find({"name": d["to"]}, nxt["names"]):
                        rep.problems.append(f"{tr}: decision {d['id']} points to {d['to']!r}, not on the {nxt['id']} list")
                    if d["kind"] in ("rename", "different_name") and _find({"name": d["to"]}, prev["names"]):
                        # both names on one list are two companies, not one renamed
                        rep.problems.append(f"{tr}: decision {d['id']}: {d['to']!r} is already on the {prev['id']} list")
                    used.add(d["id"])
                    if d.get("status") != "approved":
                        rep.problems.append(f"{tr}: decision {d['id']} ({d['kind']}: {d['name']}) awaits the editor")
                    return d
            return None

        removed = [s for s in inside if s["event"] == "removal"]
        listed = [s for s in inside if s["event"] == "listing"]
        for s in removed:
            if not _find(s, prev["names"]):
                rep.problems.append(f"{tr}: {s['source_doc']} removes {s['name']!r}, not on the {prev['id']} list")
        for row in prev["names"]:
            if _find(row, nxt["names"]):
                continue
            rm = [s for s in removed if keys(s) & keys(row)]
            back = [s for s in listed if keys(s) & keys(row)]
            if rm and not back:
                rep.items.append({"transition": tr, "name": row["name"], "outcome": "removed",
                                  "by": sorted({f"{s['source_doc']} ({s['cite']})" for s in rm})})
                continue
            d = decision_for(row, tuple(LABELS))
            if d:
                label = LABELS[d["kind"]]
                rep.items.append({"transition": tr, "name": row["name"], "outcome": label,
                                  "by": [f"decision {d['id']}" + (f" → {d['to']}" if d.get("to") else "")],
                                  "relisted_by": sorted({s["source_doc"] for s in back})})
                continue
            if rm and back:
                rep.problems.append(f"{tr}: {row['name']!r} was removed and re-listed, but the {nxt['id']} "
                                    "list does not print it; a decision must say where it is listed")
            else:
                rep.problems.append(f"{tr}: {row['name']!r} left the list and nothing explains it")
        for s in removed:
            row = _find(s, prev["names"])
            if row and _find(row, nxt["names"]) and not any(keys(x) & keys(row) for x in listed):
                rep.problems.append(f"{tr}: {s['source_doc']} removes {s['name']!r}, but the {nxt['id']} list still prints it")
        for d in decs:
            if d["id"] not in used:
                rep.problems.append(f"{tr}: decision {d['id']} ({d['name']}) explains nothing")
    known = {f"{a['id']}→{b['id']}" for a, b in zip(lists, lists[1:])}
    for d in decisions:
        if d.get("transition") not in known:
            rep.problems.append(f"decision {d['id']}: unknown transition {d.get('transition')!r}")
    for s in statements:
        if not any(a["date"] < s["published"] <= b["date"] for a, b in zip(lists, lists[1:])):
            rep.problems.append(f"{s['source_doc']}: {s['name']!r} falls outside every pair of lists ({s['published']})")
    return rep
