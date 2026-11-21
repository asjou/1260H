"""Keep the Section 1260H list current from the Federal Register. Python 3.10+, standard library
only; nothing to install.

    python3 run.py replay       re-read the saved notices offline and compare with the list (no network)
    python3 run.py page         rebuild the web page from the list (no network)
    python3 run.py check        ask the Federal Register for new 1260H notices; save them; write proposals
    python3 run.py show         list open proposals and what each would change
    python3 run.py approve ID   apply one proposal, after you have checked it against its source links
    python3 run.py stale        exit 1 if the Federal Register has a 1260H notice not handled here
    python3 run.py read FILE    try the rules on a notice saved as a text file; offer the AI step if they fail
    python3 run.py prepare      (used by the weekly GitHub job) apply proposals with no holds; print a summary

Add --data example/dow-1260h to any command to work on the classroom example instead of the live list.

Nothing here calls an AI model unless it asks you first and you approve. See "The AI step" in README.md.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from listwatch import LayoutError, ListwatchError, detect, page, proposal as P, replay, sources
from listwatch.fetch import _OPENER as _NO_REDIRECT, fetch
from listwatch.lists import dow_1260h as RULES

HERE = Path(__file__).resolve().parent
LIVE = HERE / "data" / "dow-1260h"
DATA = LIVE
PROMPT = HERE / "prompts" / "listwatch.md"


# ---- files ----

def _read(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def _write(name, data):
    (DATA / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _store():
    return _read("entities.json", {"entities": []})


def _register():
    return _read("removed.json", {"entries": []})["entries"]


def _proposals():
    return P.load_all(DATA / "proposals")


def _approved_docs():
    seen, docs = set(), []
    for p in _proposals():
        if p["status"] == "approved":
            for d in p["documents"]:
                if d["document_number"] not in seen:
                    seen.add(d["document_number"])
                    docs.append(d)
    return docs


def _all_docs():
    """What replay re-reads: the notices of approved proposals, plus an open starting proposal
    (the example's draft list is checked against it before it is approved). Oldest first."""
    seen, docs = set(), []
    for p in sorted(_proposals(), key=lambda p: p["publication_date"]):
        if not (p["status"] == "approved" or (p["status"] == "open" and p["kind"] == "start")):
            continue
        for d in p["documents"]:
            if d["document_number"] not in seen:
                seen.add(d["document_number"])
                docs.append(d)
    return docs


def _rel(p):
    try:
        return str(p.relative_to(HERE))
    except ValueError:
        return str(p)


def _page_path():
    return HERE / "docs" / "index.html" if DATA == LIVE else DATA.parent / "index.html"


# ---- the AI step (off unless configured, and it asks first) ----

def _settings():
    """LISTWATCH_LLM_* from the environment, or from a local .env file (never committed)."""
    env = {k: v for k, v in os.environ.items() if k.startswith("LISTWATCH_LLM_")}
    f = HERE / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            m = re.match(r"\s*(LISTWATCH_LLM_[A-Z_]+)\s*=\s*(.*?)\s*$", line)
            if m and m.group(1) not in env:
                env[m.group(1)] = re.sub(r"\s+#.*$", "", m.group(2)).strip().strip("'\"")
    return env


def _safe_endpoint(url: str) -> bool:
    """https anywhere, or plain http only to this computer (a local model)."""
    u = urllib.parse.urlsplit(url)
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("127.0.0.1", "localhost", "::1"))


def _reader(ask=input, interactive=None):
    """The one place an AI model can be called. None (no AI) unless LISTWATCH_LLM_URL and
    LISTWATCH_LLM_MODEL are set and a person is at the keyboard to say yes. Any OpenAI-compatible
    endpoint works: a local model, OpenRouter, or a paid provider. Swap it by changing the URL."""
    env = _settings()
    url, model, key = env.get("LISTWATCH_LLM_URL", ""), env.get("LISTWATCH_LLM_MODEL", ""), env.get("LISTWATCH_LLM_KEY", "")
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not (url and model and interactive):
        return None
    if not _safe_endpoint(url):
        print(f"AI step off: {url} is not https (plain http is allowed only to this computer)")
        return None

    def read(text, doc):
        name = doc.get("document_number") or "this notice"
        if ask(f"The rules cannot read {name}. Send its text to {model} at {url}? [y/N] ").strip().lower() != "y":
            raise RuntimeError("you said no; the notice is left for a person to read")
        prompt = (PROMPT.read_text().replace("{title}", doc.get("title", "")).replace("{text}", text[:60000])
                  + '\n\nAnswer with one JSON object only: {"kind": "addition" | "removal" | "none", "names": [...]}')
        body = json.dumps({"model": model, "temperature": 0,
                           "messages": [{"role": "user", "content": prompt}]}).encode()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=body, headers=headers)
        with _NO_REDIRECT.open(req, timeout=300) as r:      # never follow a redirect with the key
            content = json.loads(r.read())["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise ValueError("the model did not answer in JSON")
        return json.loads(m.group(0))
    return read


# ---- commands ----

def cmd_replay():
    rep = replay.check(RULES, DATA, _all_docs(), _store()["entities"], require_key=False)
    print("\n".join(rep.lines()))
    return 0 if rep.ok else 1


def _build_page():
    meta = _read("page-meta.json", {"label": "Section 1260H list"})
    store = _store()
    meta["as_of"] = store.get("currency_date", meta.get("as_of", ""))
    html = page.build(meta, store["entities"], _register(), _approved_docs())
    out = _page_path()
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    return out


def cmd_page():
    print(f"wrote {_rel(_build_page())}")
    return 0


def cmd_check():
    reader = _reader()
    print(detect.check(RULES, DATA, fetch, _store()["entities"], reader=reader, retry_reading=reader is not None))
    return 0


def _holds(prop, props):
    c = P.compare(prop, _store()["entities"], replay.equivalents(DATA))
    holds = P.holds(prop, c, earlier_open=P.earlier_open(props, prop))
    if prop["kind"] == "start":
        rep = replay.check(RULES, DATA, _all_docs(), _store()["entities"], require_key=False)
        if not rep.ok:
            holds.append("the replay check fails: run `python3 run.py replay` and resolve each difference")
    return c, holds


def cmd_show():
    props = _proposals()
    shown = 0
    for p in props:
        if p["status"] != "open":
            continue
        shown += 1
        c, holds = _holds(p, props)
        print(f"{p['id']} {p['kind']} {p['publication_date']}: +{len(c['added'])} -{len(c['removed'])}")
        for r in c["added"]:
            print(f"  + {r['name']}  {r.get('source_url', '')}")
        for r in c["removed"]:
            print(f"  - {r['name']}")
        for h in holds:
            print(f"  HOLD: {h}")
    if not shown:
        print("no open proposals")
    return 0


def _approve(prop):
    rows, reg = P.apply(prop, _store()["entities"], _register(),
                        equivalents=replay.equivalents(DATA), no_alias=replay.no_alias(DATA))
    store = _store()
    store.update(entities=rows, currency_date=P.currency_date(store.get("currency_date", ""), prop))
    _write("entities.json", store)
    _write("removed.json", {"schema": "listwatch/removed@1", "entries": reg})
    prop["status"] = "approved"
    P.save(DATA / "proposals", prop)


def cmd_approve(pid):
    props = _proposals()
    prop = next((p for p in props if p["id"] == pid), None)
    if not prop or prop["status"] != "open":
        print(f"no open proposal {pid}")
        return 2
    _c, holds = _holds(prop, props)
    if holds:
        print("cannot approve: " + " | ".join(holds))
        return 2
    _approve(prop)
    print(f"approved {pid}; run `python3 run.py page{'' if DATA == LIVE else ' --data ' + _rel(DATA)}` to rebuild the page")
    return 0


def cmd_stale():
    raw = fetch(detect.query_url(RULES.QUERY))
    missing = detect.notice_present(json.loads(raw)["results"], detect.load_log(DATA))
    if missing:
        print(f"new 1260H notice(s) not yet handled here: {', '.join(missing)}")
        return 1
    print("up to date with the Federal Register")
    return 0


def cmd_read(path):
    f = Path(path)
    text = sources.clean(f.read_bytes())
    side = f.with_suffix(".json")
    doc = json.loads(side.read_text()) if side.exists() else {
        "document_number": f.stem, "title": f.stem, "citation": "0 FR 0", "start_page": 0, "publication_date": ""}
    current = _store()["entities"]
    for kind in ("annual", "addition", "removal"):
        try:
            parsed = RULES.parse(kind, text, doc, current)
        except LayoutError:
            continue
        print(f"the rules read it as {kind}: +{len(parsed.adds or parsed.roster or [])} -{len(parsed.removes or [])}")
        return 0
    print(f"the rules do not recognise {f.name}")
    reader = _reader()
    if reader is None:
        print("needs human reading (no AI step configured, or no one at the keyboard to approve it)")
        return 1
    try:
        parsed, kind = detect.fallback(reader, text, doc, current, RULES)
    except (LayoutError, ListwatchError) as e:
        print(f"rejected by code: {e}")
        return 1
    names = [r["name"] for r in parsed.adds] or [r["name"] for r in parsed.removes]
    print(f"the model proposes this {kind}: {', '.join(names)}")
    print("every name was found word for word in the notice. Nothing was saved: a proposal comes only from a"
          " notice that `check` saved from the Federal Register, and you still approve it.")
    return 0


def cmd_prepare():
    """For the weekly GitHub job: apply each open proposal that has no holds (oldest first), rebuild
    the page, and print a summary for the pull request. Merging the pull request is the approval."""
    out = ["The weekly check found a new Section 1260H notice in the Federal Register.", ""]
    held = False
    for p in sorted(_proposals(), key=lambda p: p["publication_date"]):
        if p["status"] != "open":
            continue
        c, holds = _holds(p, _proposals())
        docs = ", ".join(f"[{d.get('citation') or d['document_number']}]({d.get('html_url', '')})" for d in p["documents"])
        out.append(f"### {p['kind']} — {p['publication_date']} — {docs}")
        out += [f"- add **{r['name']}** — [source page]({r.get('source_url', '')})" for r in c["added"]]
        out += [f"- remove **{r['name']}**" for r in c["removed"]]
        if holds:
            out += [f"- HOLD: {h}" for h in holds] + ["", "Not applied. Resolve the hold on your computer, then push."]
            held = True
            break
        _approve(p)
        out.append("")
    for n, e in sorted(detect.load_log(DATA)["documents"].items()):
        if isinstance(e, dict) and e.get("outcome") == "needs_reading" and not e.get("reviewed"):
            held = True
            out.append(f"- NEEDS HUMAN READING: {n} ({e.get('reason', '')}). Read it yourself, or run `python3 run.py check`"
                       " on your computer with the AI step set up: it asks before it sends anything.")
    _build_page()
    if held:
        out += ["", "**HOLD: do not merge yet.** Something above needs a person. Fix it on your computer and push to this branch."]
    else:
        out += ["", "**Check each change against its source link. Merging this pull request publishes the page. Close it to reject.**"]
    print("\n".join(out))
    return 10 if held else 0


def main(argv):
    global DATA
    if "--data" in argv:
        i = argv.index("--data")
        DATA = (HERE / argv[i + 1]).resolve()
        argv = argv[:i] + argv[i + 2:]
    cmds = {"replay": cmd_replay, "page": cmd_page, "check": cmd_check, "show": cmd_show,
            "stale": cmd_stale, "prepare": cmd_prepare}
    if len(argv) == 2 and argv[0] == "approve":
        return cmd_approve(argv[1])
    if len(argv) == 2 and argv[0] == "read":
        return cmd_read(argv[1])
    if len(argv) != 1 or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
