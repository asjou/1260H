"""Earlier lists, kept to compare spellings across years. They never build the list.

Each earlier annual notice is saved under the list's `history/` folder exactly like a source
(`<doc>.txt` plus a `<doc>.json` record with its URL, SHA-256 and citation), so the comparison
reads the same bytes every time. The check is plain string comparison, no AI: a name in the newest
notice that no earlier list prints exactly, but that is close to a name an earlier list does print,
is worth a person's look. It may be a typo, a rename, or a different company; the person decides.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from . import sources
from .names import key

CUTOFF = 0.85       # how alike two names must be (0 to 1, on letters and digits only) to be shown


def load(rules, folder: Path) -> list[dict]:
    """Every saved earlier list, newest first: {"doc", "date", "cite", "url", "names"}."""
    out = []
    for doc in sources.saved(folder):
        text, rec = sources.load(folder, doc)
        out.append({"doc": doc, "date": rec.get("publication_date", ""), "cite": rec.get("citation", ""),
                    "url": rec.get("html_url") or rec["url"],
                    "names": rules.earlier_names(text, {**rec, "document_number": doc})})
    return sorted(out, key=lambda h: (h["date"], h["doc"]), reverse=True)


def _keys(h: dict) -> set[str]:
    return {key(n) for r in h["names"] for n in [r["name"], *r.get("aka", [])]}


def printed_before(name: str, earlier: list[dict]) -> list[dict]:
    """The earlier lists that print `name` exactly (letters and digits compared), newest first."""
    return [h for h in earlier if key(name) in _keys(h)]


def earlier_spellings(name: str, earlier: list[dict], cutoff: float = CUTOFF) -> list[dict]:
    """How earlier lists printed a name close to `name` but not the same. Empty when any earlier
    list prints `name` exactly: then the spelling is not new."""
    k = key(name)
    if printed_before(name, earlier):
        return []
    hits = []
    for h in earlier:
        by = {}
        for r in h["names"]:
            by.setdefault(key(r["name"]), r["name"])
        m = difflib.get_close_matches(k, list(by), n=1, cutoff=cutoff)
        if m:
            hits.append({"spelling": by[m[0]], "doc": h["doc"], "date": h["date"], "cite": h["cite"], "url": h["url"]})
    return hits


def near_misses(names: list[str], earlier: list[dict], cutoff: float = CUTOFF) -> list[dict]:
    """Each name with a new spelling close to an earlier one: {"name", "earlier": [...]}."""
    return [{"name": n, "earlier": hits} for n in names if (hits := earlier_spellings(n, earlier, cutoff))]
