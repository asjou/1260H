"""Build one self-contained HTML page of a list: every row rendered in the HTML itself, a
small inline script for sorting and filtering, inline CSS, no outside requests except the source
links a reader clicks. The same input always gives the same bytes."""
from __future__ import annotations

import re
from html import escape

from .sources import allowed_host
from urllib.parse import urlsplit

_CSS = """
:root{color-scheme:dark;--ink:#e6e9f0;--mute:#9aa3b6;--line:#2c3446;--bg:#0f141f;--accent:#8fb4ff;--warn:#f2a58e}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 Georgia,"Times New Roman",serif;color:var(--ink);background:var(--bg)}
main{max-width:1180px;margin:0 auto;padding:28px 18px 60px}
h1{font-size:1.7rem;margin:0 0 4px}h2{font-size:1.2rem;margin:38px 0 8px;border-top:1px solid var(--line);padding-top:16px}
p.lede{color:var(--mute);margin:0 0 16px}.facts{display:flex;flex-wrap:wrap;gap:8px 22px;color:var(--mute);font-size:.92rem;margin:0 0 18px}
.facts b{color:var(--ink)}input[type=search]{width:100%;max-width:420px;padding:8px 10px;font:inherit;border:1px solid var(--line);border-radius:4px;background:#161d2b;color:var(--ink)}
.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.93rem;margin-top:10px}
th,td{text-align:left;vertical-align:top;padding:7px 8px;border-bottom:1px solid var(--line)}
th{font-weight:600;white-space:nowrap}th button{all:unset;cursor:pointer}th button:after{content:" \\2195";color:var(--mute)}
td.sub{color:var(--mute)}a{color:var(--accent)}tr.removed td{color:var(--warn)}
code{font-size:.85em}.note{color:var(--mute);font-size:.9rem}ol li{margin:4px 0}
"""

_JS = """
(function(){
  var q=document.getElementById('q'),rows=[].slice.call(document.querySelectorAll('#list tbody tr')),n=document.getElementById('n');
  q.addEventListener('input',function(){var s=q.value.toLowerCase(),k=0;rows.forEach(function(r){var on=r.textContent.toLowerCase().indexOf(s)>=0;r.hidden=!on;if(on)k++});n.textContent=k});
  [].forEach.call(document.querySelectorAll('th button'),function(b){b.addEventListener('click',function(){
    var t=b.closest('table'),i=[].indexOf.call(b.closest('tr').children,b.parentNode),body=t.tBodies[0],
        rs=[].slice.call(body.rows),asc=b.dataset.asc!=='1';b.dataset.asc=asc?'1':'0';
    rs.sort(function(x,y){var a=x.cells[i].dataset.v||x.cells[i].textContent,c=y.cells[i].dataset.v||y.cells[i].textContent;
      return (a.localeCompare(c,undefined,{numeric:true}))*(asc?1:-1)});rs.forEach(function(r){body.appendChild(r)});});});
})();
"""

_FORBIDDEN = re.compile(r"<link\b|<img\b|<iframe\b|<script[^>]+src=|@import|url\(", re.I)


_REGISTER = """<h2>Removed from the list</h2>
<p class="note">Companies the Department removed, with the notice that removed them. Kept here with no time limit.</p>
<div class="wrap"><table><thead><tr><th><button>Company</button></th><th><button>Removed</button></th><th>Reason</th><th>Notice</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>"""

_HISTORY = """<h2>Removed since the first list (June 2021)</h2>
<p class="note">\u201cListed\u201d is the date the Department released the first list that prints the company,
followed through renames; a company removed and listed again keeps its first date. \u201cRemoved\u201d is the
date of the Federal Register notice that removed it, or of the Department\u2019s list PDF where no notice did.
Reasons are copied word for word from the linked document; \u2026 marks words left out. Bold text is this
page\u2019s own marker: the absence of a stated reason implies nothing.</p>
<div class="wrap"><table><thead><tr><th><button>Company</button></th><th><button>Listed</button></th><th><button>Removed</button></th><th>Reason</th><th>Sources</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>"""


def _a(url: str, text: str) -> str:
    """A link only to an https .gov/.mil address; anything else renders as plain text."""
    parts = urlsplit(url or "")
    if parts.scheme == "https" and allowed_host(parts.hostname or ""):
        return f'<a href="{escape(url)}" rel="noopener">{escape(text)}</a>'
    return escape(text)


def brief(statements: list[dict], max_len: int = 110) -> dict | None:
    """The one quote that best says why a company left, cut for a table cell: a company's own note
    beats a heading over a group, a stated ground beats a notice's operative text. A long quote is
    cut to a word-for-word excerpt with ellipses; the full text is in the linked document."""
    if not statements:
        return None
    best = min(statements, key=lambda x: (0 if x["role"] == "reason" else 2) + (0 if x["scope"] == "entity note" else 1))
    q = re.sub(r"\s+", " ", best["quote"].replace("``", "\u201c").replace("''", "\u201d")).strip()
    if len(q) > max_len:
        m = re.search(r"\b((?:Because|in compliance with) .*?)(?:,? as Mandated\b|, which\b|$)", q, re.I)
        if m and len(m.group(1)) <= 150:
            q = ("\u2026 " if m.start(1) else "") + m.group(1) + (" \u2026" if m.end(1) < len(q) else "")
        else:
            q = q[:q.rfind(" ", 0, max_len)].rstrip(",;:") + " \u2026"
    return {"quote": q, "role": best["role"], "scope": best["scope"], "over": best.get("over", 1)}


def _removal_row(e: dict) -> str:
    b = brief(e["statements"])
    if b and b["role"] == "reason":
        why = f'\u201c{escape(b["quote"])}\u201d'
        kind = f'stated ground \u00b7 {b["scope"]}' + (f' over {b["over"]} names' if b["over"] > 1 else "")
    else:
        cites = sorted({d["cite"] for d in e["documents"]})
        why = ("<b>No specific reason stated in " + escape(", ".join(cites)) + ".</b>") if cites \
            else "<b>No removal notice; no reason stated.</b>"
        kind = ""
    extra = [kind] if kind else []
    if e.get("relisted"):
        extra.append(f'listed again {e["relisted"]}')
    note = (e.get("note") or "").replace("No removal notice; no reason stated.", "").strip()
    if note and len(note) <= 200:                 # a longer note stays in the history commands
        extra.append(note)
    srcs = "<br>".join(_a(d["url"], d["cite"]) for d in e["documents"]) or "\u2014"
    return ('<tr class="removed">'
            f'<td>{escape(e["name"])}</td><td>{escape(e["listed"])}</td><td>{escape(e["removed"])}</td>'
            f'<td>{why}' + "".join(f'<br><span class="note">{escape(x)}</span>' for x in extra) + "</td>"
            f"<td>{srcs}</td></tr>")


def build(meta: dict, rows: list[dict], register: list[dict], documents: list[dict],
          history: dict | None = None) -> str:
    """`meta`: label, gloss, authority, as_of, official_url, official_label, repo_url (optional).
    `history` (optional): {"listed": historycheck.first_listed(...), "removals":
    historycheck.removals(...)}. With it the page shows when each company was first listed and
    every removal since the first list; without it, the notice each row comes from and the
    removal register."""
    tops = {r["name"] for r in rows if not r.get("parent")}
    # "Listed in": the date of the notice each row comes from. The date a company was first
    # designated needs the earlier annual lists, which this page does not read yet.
    listed_in = {d["document_number"]: d.get("publication_date", "") for d in documents}
    if history:
        from .historycheck import listed_on
        def first(r):
            return listed_on(history["listed"], r)
    body_rows = []
    for r in sorted(rows, key=lambda r: (r.get("parent") or r["name"]).lower() + "\x00" + ("" if not r.get("parent") else r["name"].lower())):
        under = r.get("parent", "")
        body_rows.append(
            "<tr>"
            f'<td{" class=sub" if under else ""}>{escape(r["name"])}</td>'
            f'<td>{escape("; ".join(r.get("aka", [])))}</td>'
            f"<td>{escape(under)}</td>"
            f'<td data-v="{int(r.get("source_page") or 0):08d}">{_a(r.get("source_url", ""), r.get("source_cite", "") or "source")}</td>'
            f'<td>{escape(first(r) if history else listed_in.get(r.get("source_doc", ""), ""))}</td>'
            "</tr>")
    hist_rows = [_removal_row(e) for e in history["removals"]] if history else []
    reg_rows = [
        '<tr class="removed">'
        f'<td>{escape(e["name"])}</td><td>{escape(e.get("removed_on", ""))}</td>'
        f'<td>{escape(e.get("reason", ""))}</td>'
        f'<td>{_a(e.get("source_url", ""), e.get("cite", "") or "notice")}</td></tr>'
        for e in sorted(register, key=lambda e: (e.get("removed_on", ""), e["name"]), reverse=True)]
    doc_items = [
        f'<li>{_a(d.get("html_url", ""), d.get("citation", "") or d["document_number"])} — '
        f'{escape(d.get("title", ""))} ({escape(d.get("publication_date", ""))}). '
        f'Saved text SHA-256 <code>{escape(d.get("sha256", "")[:16])}…</code></li>'
        for d in sorted(documents, key=lambda d: d.get("publication_date", ""))]
    repo = meta.get("repo_url", "")
    repo_line = (f'<p class="note">Code, saved sources and data: <a href="{escape(repo)}" rel="noopener">'
                 f"{escape(repo)}</a>.</p>") if repo.startswith("https://github.com/") else ""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(meta["label"])}</title><style>{_CSS}</style></head>
<body><main>
<h1>{escape(meta["label"])}</h1>
<p class="lede">{escape(meta.get("gloss", ""))}</p>
<div class="facts"><span>As of <b>{escape(meta.get("as_of", ""))}</b></span><span><b id="n">{len(rows)}</b> of {len(rows)} companies</span>
<span>{len(tops)} listed directly, {len(rows) - len(tops)} under a parent</span><span>{f"{len(hist_rows)} removed since 2021" if history else f"{len(register)} removed"}</span>
<span>Authority: {escape(meta.get("authority", ""))}</span><span>Official list: {_a(meta.get("official_url", ""), meta.get("official_label", "DoW PDF"))}</span></div>
<label for="q" class="note">Filter</label><br><input id="q" type="search" placeholder="Company, alias or parent" autocomplete="off">
<div class="wrap"><table id="list"><thead><tr><th><button>Company</button></th><th><button>Also known as</button></th>
<th><button>Listed under</button></th><th><button>Source (page)</button></th><th><button>{"Listed" if history else "Listed in"}</button></th></tr></thead>
<tbody>
{chr(10).join(body_rows)}
</tbody></table></div>
{_HISTORY.format(rows=chr(10).join(hist_rows)) if history else _REGISTER.format(rows=chr(10).join(reg_rows))}
<h2>How this page was made</h2>
<ol>
<li>A scheduled script asks the Federal Register for new notices about this list.</li>
<li>Each notice is saved, with its SHA-256, before anything reads it.</li>
<li>Fixed rules (no AI) turn the saved text into rows, each with its page.</li>
<li>One AI step exists, only for a notice the rules cannot read; code checks its answer.</li>
<li>An editor checks every change against the source links and approves it.</li>
<li>This page is rebuilt from the approved data.</li>
</ol>
<p class="note">Sources this page rests on:</p><ul>
{chr(10).join(doc_items)}
</ul>
{repo_line}
<p class="note">Not legal advice. The official list and notices control; check them before relying on this page.</p>
</main><script>{_JS}</script></body></html>
"""
    assert_offline(html)
    return html


def assert_offline(html: str) -> None:
    m = _FORBIDDEN.search(html)
    if m:
        raise ValueError(f"page would load an outside resource: {m.group(0)!r}")
