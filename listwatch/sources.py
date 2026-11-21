"""Save a source before reading it; read only what was saved (design rule 2).

Each source is stored as two files under the list's `sources/` folder: the exact bytes fetched
(`<doc>.txt`) and a small record (`<doc>.json`) with the URL, SHA-256, size and fetch time. Every
parse reads back through `load`, which re-checks the hash, so the same saved input always gives the
same output.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import SCHEMA_SOURCE, SourceError

_ALLOWED = re.compile(r"(^|\.)[a-z0-9-]+\.(gov|mil)$")
_TAG = re.compile(r"<[^>]+>")
_PAGE = re.compile(r"\[\[Page (\d+)\]\]")


def allowed_host(host: str) -> bool:
    """True for a .gov or .mil host name (the authoritative-government allowlist)."""
    return bool(_ALLOWED.search((host or "").lower().rstrip(".")))


def check_url(url: str) -> str:
    """Refuse anything that is not https on a .gov/.mil host. Returns the URL unchanged."""
    parts = urlsplit(url or "")
    if parts.scheme != "https":
        raise SourceError(f"https only: {url!r}")
    if not allowed_host(parts.hostname or ""):
        raise SourceError(f"host not on the .gov/.mil allowlist: {parts.hostname!r}")
    return url


def looks_like_botwall(body: bytes) -> bool:
    """The Federal Register answers some scripted requests with a 200 'Request Access' page."""
    head = body[:4000].lower()
    return b"request access" in head and b"automated" in head


def _paths(folder: Path, doc: str) -> tuple[Path, Path]:
    if not re.fullmatch(r"[0-9A-Za-z-]+", doc or ""):
        raise SourceError(f"bad document number: {doc!r}")
    return folder / f"{doc}.txt", folder / f"{doc}.json"


def save(folder: Path, doc: str, url: str, body: bytes, fetched_at: str) -> dict:
    """Write the fetched bytes and their record. Refuses an empty body or a bot-wall page."""
    check_url(url)
    if not body:
        raise SourceError(f"{doc}: empty response")
    if looks_like_botwall(body):
        raise SourceError(f"{doc}: the server returned an access-check page, not the document")
    folder.mkdir(parents=True, exist_ok=True)
    txt, meta = _paths(folder, doc)
    record = {"schema": SCHEMA_SOURCE, "document_number": doc, "url": url,
              "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "fetched_at": fetched_at}
    txt.write_bytes(body)
    meta.write_text(json.dumps(record, indent=2) + "\n")
    return record


def load(folder: Path, doc: str) -> tuple[str, dict]:
    """Return (cleaned text, record) for a saved source, after re-checking its hash."""
    txt, meta = _paths(folder, doc)
    try:
        body = txt.read_bytes()
        record = json.loads(meta.read_text())
    except FileNotFoundError:
        raise SourceError(f"{doc}: no saved source in {folder}")
    if hashlib.sha256(body).hexdigest() != record.get("sha256"):
        raise SourceError(f"{doc}: saved source does not match its recorded SHA-256")
    return clean(body), record


def saved(folder: Path) -> list[str]:
    """Document numbers with a saved source, sorted."""
    return sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []


def clean(body: bytes) -> str:
    """Federal Register full text arrives wrapped in a little HTML. Strip tags, unescape entities,
    and normalise line endings. `[[Page N]]` markers are kept: they give each row its page."""
    text = body.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return html.unescape(_TAG.sub("", text))


def page_markers(text: str) -> list[tuple[int, int]]:
    """(character offset, page number) for every `[[Page N]]` marker, in order."""
    return [(m.start(), int(m.group(1))) for m in _PAGE.finditer(text)]
