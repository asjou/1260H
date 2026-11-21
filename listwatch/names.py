"""Company-name helpers shared by every list's rules: comparison keys, splitting a comma list of
company names without breaking "Co., Ltd.", and reading trailing "(Short name)" groups."""
from __future__ import annotations

import re

# Words that follow a comma inside one company name ("Huawei Technologies Co., Ltd.").
_SUFFIX = re.compile(r"^(ltd|limited|inc|incorporated|llc|plc|corp|corporation|co|company|s\.?a|"
                     r"gmbh|pte|pty|ag|n\.?v|b\.?v|l\.?p)\b\.?", re.I)


def key(name: str) -> str:
    """Comparison key: lowercase letters and digits only ("360 Security Technology, Inc." and
    "360 Security Technology Inc." compare equal)."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def squash(text: str) -> str:
    """Collapse whitespace, including line breaks inside a wrapped name."""
    return re.sub(r"\s+", " ", text or "").strip()


def split_top(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` only outside parentheses."""
    out, depth, cur = [], 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def split_companies(text: str) -> list[str]:
    """Split "A Co., Ltd., B Inc., and C" into company names. A piece that is only a corporate
    suffix ("Ltd.", "Inc.") is joined back to the name before it."""
    pieces = [squash(p) for p in split_top(text)]
    names: list[str] = []
    for p in pieces:
        if not p:
            continue
        p = re.sub(r"^and\s+", "", p)
        bare = re.sub(r"\s*\(.*\)\s*$", "", p)      # "Ltd. (AVIC Jonhon)" -> "Ltd."
        if names and _SUFFIX.match(bare) and len(bare) <= 14:
            names[-1] = f"{names[-1]}, {p}"
        elif names and " " not in names[-1] and " " not in p:
            names[-1] = f"{names[-1]}, {p}"           # "SMIC, Americas": two single words are one name
        else:
            names.append(p)
    return [n.rstrip(" .;") if not n.endswith((".)", "Ltd.", "Inc.", "Co.", "Corp.")) else n for n in names]


def parse_entry(text: str) -> tuple[str, list[str]]:
    """Read "Name (Short) (formerly Old Name)" into (name, aliases). Trailing parenthesised groups
    become aliases; "formerly X" yields X. A group inside the name ("(Group) Co.") stays in it."""
    s = _trim(squash(text))
    aliases: list[str] = []
    while s.endswith(")"):
        depth, i = 0, len(s) - 1
        while i >= 0:
            if s[i] == ")":
                depth += 1
            elif s[i] == "(":
                depth -= 1
                if depth == 0:
                    break
            i -= 1
        if i <= 0:
            break
        inner, rest = s[i + 1:-1].strip(), s[:i].rstrip()
        if not rest or inner.lower() in ("group", "holdings", "limited", "ltd", "ltd."):
            break      # "(Group) Co." / "Group (Limited)": part of the name, not a short name
        aliases.insert(0, re.sub(r"^formerly\s+", "", inner, flags=re.I))
        s = rest
    return _trim(s), [_trim(a) for a in aliases if a]


_ABBREV = re.compile(r"\b(ltd|inc|co|corp|llc|plc|s\.a|l\.p|n\.v|b\.v|u\.s\.a|jr|no)\.$", re.I)


def _trim(s: str) -> str:
    """Drop trailing separators and a sentence full stop, but keep the stop of "Ltd." or "Inc."."""
    s = s.rstrip(" ,;")
    while s.endswith(".") and not _ABBREV.search(s):
        s = s[:-1].rstrip(" ,;")
    return s
