"""The per-list rules interface. A list's rules module provides exactly these names; the rest of
the package calls nothing else list-specific (requirement R18).

    SLUG      the list's slug
    QUERY     {"agency": ..., "term": ...} for the Federal Register search
    DEFAULTS  fields every new row carries (country, category, cite, listing_basis)
    classify(doc) -> "annual" | "addition" | "removal" | "mixed" | None
    unrelated(doc) -> bool      positive evidence that a document changes nothing on the list
    parse(kind, text, doc, current) -> Parsed   raises LayoutError when the layout is not recognised
"""
from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("annual", "addition", "removal", "mixed")


@dataclass
class Parsed:
    """What one notice says. `roster` is set only for an annual list (it replaces the list)."""
    roster: list[dict] | None = None
    adds: list[dict] = field(default_factory=list)          # rows to add
    removes: list[dict] = field(default_factory=list)       # {"name", "reason"} to remove
    register: list[dict] = field(default_factory=list)      # removals the notice records (annual list)
    leftover: str = ""                                       # text in a removal list that matched no row


REQUIRED = ("SLUG", "QUERY", "DEFAULTS", "classify", "unrelated", "parse")


def check(rules) -> None:
    missing = [n for n in REQUIRED if not hasattr(rules, n)]
    if missing:
        raise TypeError(f"rules module {getattr(rules, '__name__', rules)!r} lacks {missing}")
