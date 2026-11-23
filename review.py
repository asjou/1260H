"""`python3 run.py review`: the decisions `decide` asks for, as a clickable page in your browser.

Standard library only. The server listens on this computer only (127.0.0.1), so no one else on
the network can reach it. Every answer it receives must carry a secret code that changes each run
and is written only into the page, so another website open in your browser cannot send answers.
It saves through the same `record` function as `decide`: the same rules, the same file.
Nothing is published from here; approving the proposal comes after, as before.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY = 20_000


def _hosts(port: int) -> set[str]:
    out = {f"127.0.0.1:{port}", f"localhost:{port}"}
    cs, dom = os.environ.get("CODESPACE_NAME"), os.environ.get("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if cs and dom:                                   # GitHub Codespaces forwards the port to its own address
        out.add(f"{cs}-{port}.{dom}")
    return out


def make_server(*, state, decide, advice, pdfs, port: int = 8765) -> ThreadingHTTPServer:
    """Build the server (not yet running). Tries `port` and the next ten; port 0 picks any free one."""
    token = secrets.token_urlsafe(24)
    lock = threading.Lock()          # one request reads or writes the decisions at a time

    class Handler(BaseHTTPRequestHandler):
        timeout = 30                                 # a browser's spare, silent connection is dropped

        def log_message(self, *a):                   # keep the terminal quiet
            pass

        def _allowed_host(self) -> bool:
            return self.headers.get("Host", "") in _hosts(self.server.server_port)

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data):
            self._send(code, json.dumps(data).encode(), "application/json")

        def do_GET(self):
            if not self._allowed_host():
                return self._send(403, b"wrong host", "text/plain")
            path = self.path.split("?", 1)[0]
            if path == "/":
                nonce = secrets.token_urlsafe(12)
                body = PAGE.replace("__TOKEN__", token).replace("__NONCE__", nonce).encode()
                csp = (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; "
                       "connect-src 'self'; img-src 'self'; frame-ancestors 'none'; form-action 'none'")
                return self._send(200, body, "text/html; charset=utf-8", {"Content-Security-Policy": csp})
            if path == "/state":
                with lock:
                    data = state()
                return self._json(200, data)
            if path.startswith("/pdf/"):
                p = pdfs().get(path[5:])                 # only a file listed in dow-pdf/, by exact name
                if p is None:
                    return self._send(404, b"no such PDF", "text/plain")
                return self._send(200, p.read_bytes(), "application/pdf")
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self._allowed_host() or (origin and origin.split("://", 1)[-1] not in _hosts(self.server.server_port)):
                return self._json(403, {"error": "wrong host"})
            if not hmac.compare_digest(self.headers.get("X-Review-Token", ""), token):
                return self._json(403, {"error": "wrong or missing code: reload the page"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY or not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._json(400, {"error": "bad request"})
            try:
                data = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad request"})
            try:
                if self.path == "/advice":           # the AI call can be slow: it does not hold the lock
                    return self._json(200, {"advice": advice()})
                with lock:
                    return self._post(data)
            except ValueError as e:
                return self._json(400, {"error": str(e)})

        def _post(self, data):
            if self.path == "/decide":
                decide(data.get("parsed"), data.get("store"), data.get("choice"), data.get("why", ""),
                       typo=bool(data.get("typo", True)))
                return self._json(200, state())
            return self._json(404, {"error": "not found"})

    last = None
    for p in ([0] if port == 0 else range(port, port + 11)):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            srv.daemon_threads = True
            srv.token = token
            return srv
        except OSError as e:
            last = e
    raise OSError(f"no free port from {port} to {port + 10}: {last}")


def serve(*, state, decide, advice, pdfs, port: int = 8765, open_browser: bool = True) -> int:
    srv = make_server(state=state, decide=decide, advice=advice, pdfs=pdfs, port=port)
    url = f"http://127.0.0.1:{srv.server_port}/"
    print(f"Open {url} in your browser. Press Ctrl+C here to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        srv.server_close()
    return 0


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review the differences</title>
<style>
:root { --bg:#fbfaf7; --fg:#1d1d1f; --muted:#5f6368; --line:#dcd8cf; --card:#fff; --accent:#1f4e8c;
        --ok:#1e6b3a; --bad:#a3271f; --soft:#f1eee7; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181c; --fg:#ececec; --muted:#a3a7ad; --line:#33373e; --card:#1e2126; --accent:#8fb4ea;
          --ok:#6fcf8f; --bad:#ff8a80; --soft:#262a30; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:17px/1.55 Georgia, "Times New Roman", serif; }
main { max-width:780px; margin:0 auto; padding:32px 20px 80px; }
h1 { font-size:1.6rem; margin:0 0 4px; } .sub { color:var(--muted); margin:0 0 20px; }
.ui, button, textarea, label, .pill, .links a, .chip { font-family:system-ui, -apple-system, "Segoe UI", sans-serif; }
.status { display:flex; align-items:center; gap:12px; padding:14px 16px; border:1px solid var(--line);
          background:var(--card); border-radius:10px; margin-bottom:18px; }
.pill { font-weight:700; font-size:.85rem; letter-spacing:.04em; padding:3px 10px; border-radius:99px; color:#fff; }
.pill.ok { background:var(--ok); } .pill.bad { background:var(--bad); }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px 20px; margin:16px 0; }
.kind { font:600 .78rem system-ui, sans-serif; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
.names { margin:6px 0 12px; } .names b { font-size:1.08rem; }
.names div { margin:2px 0; } .src { color:var(--muted); font-size:.92rem; }
h3 { font:600 .9rem system-ui, sans-serif; margin:14px 0 6px; color:var(--muted); }
.links { display:flex; flex-wrap:wrap; gap:8px; }
.links a, .chip { display:inline-block; font-size:.88rem; padding:5px 10px; border:1px solid var(--line);
                  border-radius:7px; color:var(--accent); text-decoration:none; background:var(--soft); }
.links a:hover { border-color:var(--accent); }
ul.earlier { margin:4px 0 0; padding-left:20px; } ul.earlier li { margin:2px 0; }
.guess { margin-top:12px; padding:10px 12px; border-left:3px solid var(--accent); background:var(--soft);
         font-size:.95rem; }
.guess .tag { font:600 .75rem system-ui, sans-serif; text-transform:uppercase; color:var(--muted); display:block; }
form { margin-top:16px; border-top:1px solid var(--line); padding-top:14px; }
label { display:block; margin:6px 0; font-size:.95rem; cursor:pointer; }
label.sub2 { margin-left:26px; color:var(--muted); }
textarea { width:100%; min-height:62px; margin-top:8px; padding:8px 10px; font-size:.95rem; border-radius:8px;
           border:1px solid var(--line); background:var(--bg); color:var(--fg); }
.row { display:flex; gap:10px; align-items:center; margin-top:10px; flex-wrap:wrap; }
button { font-size:.95rem; padding:8px 16px; border-radius:8px; border:1px solid var(--accent); cursor:pointer;
         background:var(--accent); color:var(--bg); font-weight:600; }
button[disabled] { opacity:.4; cursor:not-allowed; }
button.plain { background:transparent; color:var(--accent); }
.msg { font:.9rem system-ui, sans-serif; } .msg.err { color:var(--bad); } .msg.note { color:var(--muted); }
details { margin:8px 0 18px; } summary { cursor:pointer; color:var(--accent); font:.95rem system-ui, sans-serif; }
details ol { margin:8px 0; }
.done { color:var(--muted); font-size:.95rem; } .done li { margin:6px 0; }
</style></head>
<body><main>
<h1>Review the differences</h1>
<p class="sub" id="label"></p>
<div class="status"><span class="pill" id="pill"></span><span class="ui" id="summary"></span></div>
<details><summary>How to judge a difference</summary><ol>
<li><b>What does the issuing agency's own document say?</b> The DoW PDF is DoW's list. The Federal Register copy
is a reprint, typed again, and reprints carry typos.</li>
<li><b>What did earlier years print?</b> A spelling every earlier list printed, changed only in this year's reprint,
is very likely a typo.</li>
<li><b>Is it a rename?</b> A different word, not a different letter, points to a rename or a different company.</li>
<li><b>Write the reason down.</b> Which sources you compared and what each printed.</li></ol>
<p>Earlier years' lists are evidence, not the answer: an old list can carry a typo too.</p></details>
<div id="ai"></div>
<div id="cards"></div>
<div id="resolved"></div>
</main>
<script nonce="__NONCE__">
const TOKEN = "__TOKEN__";
let advice = {};
const $ = (t, attrs = {}, ...kids) => { const e = document.createElement(t);
  for (const [k, v] of Object.entries(attrs)) { if (k === "text") e.textContent = v; else if (k === "cls") e.className = v; else e.setAttribute(k, v); }
  for (const k of kids) if (k) e.append(k); return e; };
const safe = u => /^https:\\/\\//.test(u || "") ? u : null;
const link = (href, text) => href ? $("a", {href, target:"_blank", rel:"noopener noreferrer", text}) : null;

async function post(path, body) {
  const r = await fetch(path, {method:"POST", headers:{"Content-Type":"application/json", "X-Review-Token":TOKEN},
                               body:JSON.stringify(body)});
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || "something went wrong");
  return data;
}

function earlierList(facts) {
  const ul = $("ul", {cls:"earlier"});
  for (const n of facts.names) {
    let t;
    if (n.printed_in.length) t = `“${n.name}” is printed in earlier lists: ` + n.printed_in.map(h => `${h.year} (${h.cite})`).join(", ");
    else if (n.close.length) t = `No earlier list prints “${n.name}”. Close: ` + n.close.map(e => `${e.year} printed “${e.spelling}”`).join("; ");
    else if (n.new) t = `No earlier list prints “${n.name}”: new in this notice.`;
    else t = `No earlier list prints “${n.name}”.`;
    ul.append($("li", {text:t}));
  }
  return facts.names.length ? ul : $("p", {cls:"src", text:"No earlier lists saved."});
}

function card(d) {
  const c = $("div", {cls:"card"});
  const kinds = {pair:"Two spellings", missing:"In the notice, not on the list", extra:"On the list, in no notice"};
  c.append($("div", {cls:"kind", text:kinds[d.kind]}));
  const names = $("div", {cls:"names"});
  if (d.parsed) names.append($("div", {}, $("span", {cls:"src", text:"The Federal Register notice prints  "}), $("b", {text:d.parsed})));
  if (d.store) names.append($("div", {}, $("span", {cls:"src", text:"The list has  "}), $("b", {text:d.store})));
  c.append(names);
  const f = d.facts;
  c.append($("h3", {text:"Compare"}));
  const links = $("div", {cls:"links"}, link(safe(f.fr), "Federal Register page ↗"),
                  link(safe(f.dow), "DoW PDF online ↗ (search for the name)"));
  for (const p of f.pdfs) links.append(link("/pdf/" + encodeURIComponent(p), "Saved PDF " + p.replace(/\\.pdf$/i, "")));
  c.append(links);
  c.append($("h3", {text:"What earlier years printed"}), earlierList(f));
  const g = d.parsed && advice[d.parsed];
  if (g) c.append($("div", {cls:"guess"}, $("span", {cls:"tag", text:"AI's guess: a guess, not a source. Check it."}),
                    document.createTextNode(`${g.guess}. ${g.why}`)));
  c.append(form(d));
  return c;
}

function form(d) {
  const fm = $("form"), msg = $("span", {cls:"msg"});
  const id = "d" + Math.random().toString(36).slice(2);
  const why = $("textarea", {placeholder:"Why? One line: which sources you compared and what each printed."});
  const save = $("button", {type:"submit", text:"Save decision"}); save.disabled = true;
  let choice = null, typo = null;
  const opt = (value, text) => { const r = $("input", {type:"radio", name:id, value});
    r.addEventListener("change", () => { choice = value; update(); }); return $("label", {}, r, document.createTextNode(" " + text)); };
  if (d.kind === "pair") {
    fm.append(opt("same entity", "Same company, spelled two ways"));
    typo = $("input", {type:"checkbox"}); typo.checked = true;
    fm.append($("label", {cls:"sub2"}, typo, document.createTextNode(` “${d.parsed}” is a typo: keep it off the page`)));
    fm.append(opt("different", "Different companies: needs a closer look"));
  } else if (d.kind === "missing") {
    fm.append(opt("add", "The DoW list includes it: add it to the list"));
  } else {
    fm.append(opt("keep", "Keep it on the list anyway"));
  }
  fm.append(why, $("div", {cls:"row"}, save, msg));
  function update() {
    msg.className = "msg"; msg.textContent = "";
    if (choice === "different") { save.disabled = true; msg.className = "msg note";
      msg.textContent = "Then one is missing from the list and the other is in no notice. Look at both; nothing is saved."; return; }
    save.disabled = !(choice && why.value.trim());
  }
  why.addEventListener("input", update);
  fm.addEventListener("submit", async e => {
    e.preventDefault(); save.disabled = true;
    try { render(await post("/decide", {parsed:d.parsed, store:d.store, choice, why:why.value, typo: typo ? typo.checked : true})); }
    catch (err) { msg.className = "msg err"; msg.textContent = err.message; save.disabled = false; }
  });
  return fm;
}

function render(s) {
  document.getElementById("label").textContent = s.label;
  const pill = document.getElementById("pill");
  pill.textContent = s.ok ? "PASS" : "FAIL"; pill.className = "pill " + (s.ok ? "ok" : "bad");
  document.getElementById("summary").textContent = s.ok ? "Every difference is decided. Next: approve the proposal (python3 run.py show, then approve)."
    : `${s.differences.length} difference(s) to decide. Open the links, compare, then answer.`;
  const ai = document.getElementById("ai"); ai.replaceChildren();
  const pairs = s.differences.filter(d => d.kind === "pair").length;
  if (s.ai && pairs && !Object.keys(advice).length) {
    const b = $("button", {cls:"plain", type:"button", text:`Ask ${s.ai} for a second opinion on ${pairs} spelling pair(s)`});
    const m = $("span", {cls:"msg note", text:" Sends only the company names and what earlier lists printed."});
    b.addEventListener("click", async () => { b.disabled = true; m.textContent = " Asking…";
      try { const r = await post("/advice", {}); for (const a of r.advice) advice[a.parsed] = a;
            m.textContent = r.advice.length ? "" : " No usable answer."; render(await (await fetch("/state")).json()); }
      catch (err) { m.className = "msg err"; m.textContent = " " + err.message; b.disabled = false; } });
    ai.append($("div", {cls:"row"}, b, m));
  }
  document.getElementById("cards").replaceChildren(...s.differences.map(card));
  const res = document.getElementById("resolved"); res.replaceChildren();
  if (s.resolved.length) {
    const ul = $("ul", {cls:"done"});
    for (const r of s.resolved) ul.append($("li", {}, $("b", {text:`${r.parsed || "—"} / ${r.store || "—"}: ${r.resolution}. `}),
                                          document.createTextNode(r.note || "")));
    res.append($("h3", {text:"Decided (saved in replay-exceptions.json)"}), ul);
  }
}
fetch("/state").then(r => r.json()).then(render);
</script></body></html>
"""
