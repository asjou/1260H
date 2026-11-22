"""DoW list PDFs as saved sources.

The Department's own list PDF sometimes says more than the Federal Register copy: the January 2024
PDF names three removals and their reasons that the Federal Register version (89 FR 22698) leaves
out, and the 2025 and 2026 PDFs give the reason for a removal section the Federal Register prints
bare. So a PDF can be a source, read the same way as the notices: save first, read only what was
saved, re-check the hash every time.

Each PDF is kept as three files under the list's `dow-pdf/` folder:
  <doc>.pdf    the exact bytes, unchanged
  <doc>.txt    the text, made once by `pdftotext -layout` (pages separated by form feeds)
  <doc>.json   the record: official URL, archived copy, both SHA-256s, the extractor used
This package never runs pdftotext (it is not standard library); the caller does, once, and the text
is kept beside the PDF so anyone can replay without it.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import SCHEMA_PDF_SOURCE, SourceError
from .sources import check_url

FOLDER = "dow-pdf"
_ARCHIVE = re.compile(r"https://web\.archive\.org/web/(\d{14})/(https://.+)$")


def check_archive(archived_url: str, official_url: str) -> str:
    """An archived copy must be a Wayback capture of the official URL. Returns the capture time."""
    m = _ARCHIVE.match(archived_url or "")
    if not m or m.group(2) != official_url:
        raise SourceError(f"archived copy must be https://web.archive.org/web/<timestamp>/<official URL>: {archived_url!r}")
    return m.group(1)


def _paths(folder: Path, doc: str) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"[0-9A-Za-z-]+", doc or ""):
        raise SourceError(f"bad document name: {doc!r}")
    return folder / f"{doc}.pdf", folder / f"{doc}.txt", folder / f"{doc}.json"


def record(doc: str, pdf: bytes, text: bytes, *, official_url: str, archived_url: str = "",
           release_date: str, title: str, extractor: str, saved_at: str) -> dict:
    check_url(official_url)
    if not pdf.startswith(b"%PDF"):
        raise SourceError(f"{doc}: not a PDF")
    if not text.strip():
        raise SourceError(f"{doc}: no text came out of the PDF")
    rec = {"schema": SCHEMA_PDF_SOURCE, "document": doc, "title": title, "release_date": release_date,
           "official_url": official_url, "sha256": hashlib.sha256(pdf).hexdigest(), "bytes": len(pdf),
           "text_sha256": hashlib.sha256(text).hexdigest(), "extractor": extractor, "saved_at": saved_at}
    if archived_url:
        ts = check_archive(archived_url, official_url)
        rec.update(archived_url=archived_url, archived_at=f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:]}Z")
    return rec


def write(folder: Path, rec: dict, pdf: bytes, text: bytes) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    p, t, j = _paths(folder, rec["document"])
    p.write_bytes(pdf)
    t.write_bytes(text)
    j.write_text(json.dumps(rec, indent=2) + "\n")


def load(folder: Path, doc: str) -> tuple[list[str], dict]:
    """Return (pages, record) for a saved PDF after re-checking both hashes. `pages[0]` is page 1."""
    p, t, j = _paths(folder, doc)
    try:
        pdf, text, rec = p.read_bytes(), t.read_bytes(), json.loads(j.read_text())
    except FileNotFoundError:
        raise SourceError(f"{doc}: no saved PDF in {folder}")
    if hashlib.sha256(pdf).hexdigest() != rec.get("sha256"):
        raise SourceError(f"{doc}: saved PDF does not match its recorded SHA-256")
    if hashlib.sha256(text).hexdigest() != rec.get("text_sha256"):
        raise SourceError(f"{doc}: saved text does not match its recorded SHA-256")
    pages = text.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages, rec


def saved(folder: Path) -> list[str]:
    """Saved PDF documents, oldest first (names start with the release date)."""
    return sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []


def page_link(rec: dict, page: int) -> dict:
    """Links to one page: the official file first, then the archived copy (KD3)."""
    out = {"official": f"{rec['official_url']}#page={page}"}
    if rec.get("archived_url"):
        out["archived"] = f"{rec['archived_url']}#page={page}"
    return out
