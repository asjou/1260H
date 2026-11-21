"""A standard-library fetcher for running this package on its own: https only,
the .gov/.mil allowlist checked on every redirect hop, a byte cap and a timeout."""
from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urljoin

from . import SourceError
from .sources import check_url

USER_AGENT = "listwatch/1.0 (public-records research)"
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT_S = 30
MAX_REDIRECTS = 5


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None          # we follow redirects ourselves, re-checking each hop


_OPENER = urllib.request.build_opener(_NoRedirect)


def fetch(url: str, *, max_bytes: int = MAX_BYTES, timeout_s: int = TIMEOUT_S) -> bytes:
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with _OPENER.open(req, timeout=timeout_s) as resp:
                body = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                url = urljoin(url, e.headers["Location"])
                continue
            raise SourceError(f"HTTP {e.code} for {url}")
        except urllib.error.URLError as e:
            raise SourceError(f"cannot fetch {url}: {e.reason}")
        if len(body) > max_bytes:
            raise SourceError(f"response larger than {max_bytes} bytes: {url}")
        return body
    raise SourceError(f"too many redirects: {url}")
