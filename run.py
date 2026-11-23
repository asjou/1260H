"""Keep the Section 1260H list current from the Federal Register. Python 3.10+, standard library
only; nothing to install.

    python3 run.py replay       re-read the saved notices offline and compare with the list (no network)
    python3 run.py decide       walk through each difference replay found and record your decision
    python3 run.py review       the same, as a clickable page in your browser (this computer only)
    python3 run.py spelling     compare the newest list's names with earlier years' lists (no network)
    python3 run.py history add DOC   save an earlier annual list from the Federal Register, for spelling
    python3 run.py completeness check that every company that left the list since 2021 has a document
                                or a recorded decision (no network)
    python3 run.py removals     every removal since 2021, quoting the documents (no network)
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

from listwatch import LayoutError, ListwatchError, detect, history, page, proposal as P, replay, sources
from listwatch import completeness, historycheck
from listwatch.names import key as _key
from listwatch.fetch import _OPENER as _NO_REDIRECT, fetch
from listwatch.lists import dow_1260h as RULES

HERE = Path(__file__).resolve().parent
LIVE = HERE / "data" / "dow-1260h"
DATA = LIVE
PROMPT = HERE / "prompts" / "listwatch.md"
SECOND = HERE / "prompts" / "second-opinion.md"


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


def _flag():
    """' --data <folder>' when working on anything but the live list, for commands we print."""
    return "" if DATA == LIVE else f" --data {_rel(DATA)}"


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


def _llm(interactive=None):
    """(url, model, key) when the AI step is configured, safe, and a person is at the keyboard; else None."""
    env = _settings()
    url, model, key = env.get("LISTWATCH_LLM_URL", ""), env.get("LISTWATCH_LLM_MODEL", ""), env.get("LISTWATCH_LLM_KEY", "")
    if interactive is None:
        interactive = sys.stdin.isatty()
    if not (url and model and interactive):
        return None
    if not _safe_endpoint(url):
        print(f"AI step off: {url} is not https (plain http is allowed only to this computer)")
        return None
    return url, model, key


def _chat(llm, prompt):
    """The one place a request goes to an AI model. Callers ask the person first."""
    url, model, key = llm
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url.rstrip("/") + "/chat/completions", data=body, headers=headers)
    with _NO_REDIRECT.open(req, timeout=300) as r:      # never follow a redirect with the key
        content = json.loads(r.read())["choices"][0]["message"]["content"]
    m = re.search(r"[\[{].*[\]}]", content, re.S)
    if not m:
        raise ValueError("the model did not answer in JSON")
    return json.loads(m.group(0))


def _reader(ask=input, interactive=None):
    """Reads a notice the rules cannot. None (no AI) unless LISTWATCH_LLM_URL and LISTWATCH_LLM_MODEL
    are set and a person is at the keyboard to say yes. Any OpenAI-compatible endpoint works: a
    local model, OpenRouter, or a paid provider. Swap it by changing the URL."""
    llm = _llm(interactive)
    if llm is None:
        return None
    url, model, _key_ = llm

    def read(text, doc):
        name = doc.get("document_number") or "this notice"
        if ask(f"The rules cannot read {name}. Send its text to {model} at {url}? [y/N] ").strip().lower() != "y":
            raise RuntimeError("you said no; the notice is left for a person to read")
        prompt = (PROMPT.read_text().replace("{title}", doc.get("title", "")).replace("{text}", text[:60000])
                  + '\n\nAnswer with one JSON object only: {"kind": "addition" | "removal" | "none", "names": [...]}')
        ans = _chat(llm, prompt)
        if not isinstance(ans, dict):
            raise ValueError("the model did not answer with one JSON object")
        return ans
    return read


GUESSES = ("typo", "rename", "different companies", "unsure")


def _second_opinion(pairs, ask=input, interactive=None):
    """One optional AI call for all the spelling pairs at once. Returns {pair number: (guess, why)},
    or {} when the AI step is off or the person says no. It only advises: the person decides."""
    llm = _llm(interactive)
    if llm is None or not pairs:
        return {}
    url, model, _k = llm
    q = (f"Ask {model} at {url} for a second opinion on {len(pairs)} spelling pair(s)? It sends only the "
         "company names and what earlier lists printed. [y/N] ")
    if ask(q).strip().lower() != "y":
        return {}
    lines = []
    for i, p in enumerate(pairs, 1):
        before = "; ".join(f"{e['date']} list printed {e['spelling']!r}" for e in p["earlier"]) or "no earlier list prints a close name"
        lines.append(f"{i}. notice prints {p['parsed']!r}; the list has {p['store']!r}; {before}")
    prompt = (SECOND.read_text().replace("{pairs}", "\n".join(lines))
              + '\n\nAnswer with one JSON array only: [{"n": 1, "guess": "' + '" | "'.join(GUESSES) + '", "why": "..."}]')
    try:
        ans = _chat(llm, prompt)
    except Exception as e:                  # any failure: no advice, the person decides alone
        print(f"no second opinion ({e})")
        return {}
    out = {}
    for a in ans if isinstance(ans, list) else []:
        if isinstance(a, dict) and a.get("guess") in GUESSES and a.get("n") in range(1, len(pairs) + 1):
            out[a["n"]] = (a["guess"], str(a.get("why", ""))[:240])
    return out


# ---- commands ----

def _earlier():
    """Earlier annual lists for the spelling comparison: this folder's history/, or the live list's."""
    for folder in (DATA / "history", LIVE / "history"):
        if folder.exists():
            return history.load(RULES, folder)
    return []


def _pdfs():
    """DoW PDFs saved by hand, {file name: path}: this folder's dow-pdf/, then the live list's."""
    out = {}
    for d in (DATA / "dow-pdf", LIVE / "dow-pdf"):
        if d.exists():
            for p in sorted(d.glob("*.pdf")):
                out.setdefault(p.name, p)
    return out


def _kind(d):
    return "pair" if d.get("parsed") and d.get("store") else "missing" if d.get("parsed") else "extra"


def _facts(d, earlier):
    """What to open and what earlier lists say, for one difference. Plain facts, no AI."""
    names = []
    for side in ("store", "parsed"):
        n = d.get(side)
        if not n or not earlier:
            continue
        seen = history.printed_before(n, earlier)
        close = [] if seen else history.earlier_spellings(n, earlier)
        names.append({"name": n, "side": side,
                      "printed_in": [{"year": h["date"][:4], "cite": h["cite"], "url": h["url"]} for h in seen],
                      "close": [{"year": e["date"][:4], "spelling": e["spelling"], "cite": e["cite"]} for e in close],
                      "new": not seen and not close and _kind(d) == "missing"})
    return {"fr": d.get("url", ""), "dow": _read("page-meta.json", {}).get("official_url", ""),
            "pdfs": list(_pdfs()), "names": names}


def _evidence(d, earlier):
    """The facts as lines for the terminal."""
    f = _facts(d, earlier)
    out = []
    if f["fr"]:
        out.append(f"      Federal Register: {f['fr']}")
    if f["dow"]:
        out.append(f"      DoW list (open in a browser, search for the name): {f['dow']}")
    out += [f"      your saved DoW PDF: {_rel(p)}" for p in _pdfs().values()]
    for n in f["names"]:
        if n["printed_in"]:
            out.append(f"      earlier lists print {n['name']!r}: " + ", ".join(f"{h['year']} ({h['cite']})" for h in n["printed_in"]))
        else:
            out.append(f"      no earlier list prints {n['name']!r}" + (
                "; close: " + ", ".join(f"{e['year']} printed {e['spelling']!r}" for e in n["close"]) if n["close"] else
                ": new in this notice" if n["new"] else ""))
    return out


def cmd_replay():
    rep = replay.check(RULES, DATA, _all_docs(), _store()["entities"], require_key=False)
    print("\n".join(rep.lines()))
    if rep.differences:
        earlier = _earlier()
        print("\nWhat to compare for each difference:")
        for i, d in enumerate(rep.differences, 1):
            print(f"  {i}. {d.get('parsed') or d.get('store')}")
            print("\n".join(_evidence(d, earlier)))
        print(f"\nThen record your decisions: python3 run.py decide{_flag()}")
    return 0 if rep.ok else 1


def cmd_spelling():
    """Names in the newest annual list that no earlier list prints, but that are close to a name an
    earlier list does print. Each may be a typo, a rename, or a different company."""
    earlier = _earlier()
    if not earlier:
        print("no earlier lists saved: add one with `python3 run.py history add DOC`")
        return 2
    newest = replay._annual_rows(RULES, DATA, _all_docs())
    hits = history.near_misses([r["name"] for r in newest], earlier)
    print(f"compared {len(newest)} names with {len(earlier)} earlier list(s): "
          + ", ".join(f"{h['date']} ({h['cite']}, {len(h['names'])} names)" for h in earlier))
    for h in hits:
        print(f"  {h['name']!r}")
        for e in h["earlier"]:
            print(f"      {e['date'][:4]} printed {e['spelling']!r}  ({e['cite']}, {e['url']})")
    print(f"{len(hits)} name(s) to look at. Each could be a typo, a rename or a different company: check the DoW PDF."
          if hits else "no new spellings close to earlier ones")
    return 0


DISCLAIMER = ("Not legal advice and not an official source. The Federal Register notices and the Department's "
              "own lists control; check each citation before you rely on it. Leaving this list is not a finding "
              "about a company's status under any other list or restriction.")


def _as_of():
    store = _store()
    return store, store.get("currency_date", "")


def cmd_completeness():
    """Walk every list since 2021: each company that left must have a document that removes it, or
    an approved decision in history-decisions.json. This shows that every departure is accounted for;
    it does not show that a decision is right, or that the saved files match the live government
    copies. Fixed rules, no AI, no network."""
    store, as_of = _as_of()
    try:
        rep = historycheck.report(RULES, LIVE, store["entities"], as_of, replay.equivalents(LIVE))
    except ListwatchError as e:
        print(f"cannot run the check: {e}")
        return 2
    print(f"Section 1260H list history, 2021 to the list as of {as_of}\n")
    print("\n".join(rep.lines()))
    print(f"\n{DISCLAIMER}")
    return 0 if rep.ok else 1


def cmd_removals():
    """Every removal since 2021, with what the documents say, quoted word for word. Labels such as
    "notice text" and the "No specific reason stated" marker are this repo's; notes marked
    "editor's note" are a person's, drawn from the documents cited."""
    store, as_of = _as_of()
    try:
        lists, statements = historycheck.inputs(RULES, LIVE, store["entities"], as_of)
    except ListwatchError as e:
        print(f"cannot read the history: {e}")
        return 2
    decisions = historycheck.read_decisions(LIVE)
    rep = completeness.check(lists, statements, decisions, replay.equivalents(LIVE))
    snaps = {x["id"]: x for x in lists}
    notes = {d["name"]: d for d in decisions}
    print(f"Section 1260H removals, 2021 to the list as of {as_of}")
    print("Quotes are copied from the saved documents (line breaks joined). A group heading gives one ground "
          "for the names under it; the documents give no facts for each company.")
    shown = ("removed", "not printed, no notice", "listed elsewhere")
    for it in rep.items:
        if it["outcome"] not in shown:
            continue
        a, b = it["transition"].split("→")
        row = next(r for r in snaps[a]["names"] if r["name"] == it["name"])
        mine = [s for s in statements if snaps[a]["date"] < s["published"] <= snaps[b]["date"]
                and completeness.keys(s) & completeness.keys(row)]
        print(f"\n{it['name']}  ({it['outcome']}, {it['transition']})")
        for s in mine:
            when = (f"PDF posted {s['published']} (date in its web address)" if s["source_kind"] == "dow_pdf"
                    else f"published {s['published']}" + (f", signed {s['dated']}" if s.get("dated") else ""))
            print(f"  {s['event']:8} {s['cite']}  ({when})")
            for x in s["statements"]:
                role = "stated ground" if x["role"] == "reason" else "notice text"
                where = x["scope"] + (f" over {x['over']} names" if x["over"] > 1 else "")
                print(f"      {role} ({where}): \"{x['quote']}\"")
        removals = [s for s in mine if s["event"] == "removal"]
        if not any(x["role"] == "reason" for s in removals for x in s["statements"]):
            cites = sorted({s["cite"] for s in removals})
            print("  No specific reason stated in " + ", ".join(cites) + "." if cites
                  else "  No removal notice; no reason stated.")
        if it["name"] in notes and notes[it["name"]].get("reader_note"):
            print(f"  editor's note: {notes[it['name']]['reader_note']}")
    n_rm = sum(1 for i in rep.items if i["outcome"] == "removed")
    n_np = sum(1 for i in rep.items if i["outcome"] == "not printed, no notice")
    print(f"\n{n_rm} removed by a document and not re-listed; {n_np} no longer printed, with no notice; "
          + ("every departure accounted for" if rep.ok else "the check FAILS: run `python3 run.py completeness`"))
    print(f"\n{DISCLAIMER}")
    return 0 if rep.ok else 1


def cmd_history_add(doc):
    """Save one earlier annual list from the Federal Register into history/ (network)."""
    meta = json.loads(fetch(f"https://www.federalregister.gov/api/v1/documents/{doc}.json"))
    d = {"document_number": doc, **detect._meta(meta)}
    if detect.classify(d, RULES) not in ("annual", "addition"):      # the 2021 list is titled as a designation
        print(f"{doc} is not a 1260H list ({meta.get('title', '')!r})")
        return 2
    body = fetch(sources.check_url(d["raw_text_url"]))
    try:                                   # read it before saving: only a whole list belongs in history/
        n = len(RULES.earlier_names(sources.clean(body), d))
    except LayoutError as e:
        print(f"{doc} does not read as a whole list ({e}); not saved")
        return 2
    folder = DATA / "history"
    rec = sources.save(folder, doc, d["raw_text_url"], body, detect._now())
    rec.update({k: d[k] for k in ("title", "publication_date", "citation", "start_page", "html_url")})
    (folder / f"{doc}.json").write_text(json.dumps(rec, indent=2) + "\n")
    print(f"saved {_rel(folder / (doc + '.txt'))}: {d['publication_date']} ({d['citation']}), {n} names")
    return 0


def _save_decision(d, **fields):
    f = DATA / "replay-exceptions.json"
    exc = _read("replay-exceptions.json", {"differences": []})
    same = lambda e: _key(e.get("parsed") or "") == _key(d.get("parsed") or "") and \
        _key(e.get("store") or "") == _key(d.get("store") or "")
    hit = next((e for e in exc["differences"] if same(e)), None)
    if hit is None:
        hit = {"parsed": d.get("parsed"), "store": d.get("store")}
        exc["differences"].append(hit)
    hit.update(fields)
    f.write_text(json.dumps(exc, ensure_ascii=False, indent=2) + "\n")


CHOICES = {"pair": "same entity", "missing": "add", "extra": "keep"}


def record(d, choice, why, typo=True):
    """Record one decision: the only way `decide` and `review` save an answer. Raises ValueError
    for a choice that does not fit the difference, or a missing reason."""
    want = CHOICES[_kind(d)]
    if choice != want:
        raise ValueError(f"for this difference the answer is {want!r} or skip")
    why = " ".join((why or "").split())
    if not why:
        raise ValueError("a reason is needed: the next person reads it")
    fields = {"resolution": choice, "note": why}
    if choice == "same entity":
        fields["alias"] = not typo          # a typo stays off the page
    _save_decision(d, **fields)


def _differences():
    rep = replay.check(RULES, DATA, _all_docs(), _store()["entities"], require_key=False)
    earlier = _earlier()
    pairs = [{**d, "earlier": history.earlier_spellings(d["parsed"], earlier)}
             for d in rep.differences if _kind(d) == "pair"]
    return rep, earlier, pairs


def _why(ask):
    while True:
        w = ask("    Why? One line: what the sources show. > ").strip()
        if w:
            return w
        print("    A reason is needed: the next person reads it.")


def cmd_decide(ask=input, interactive=None):
    """Walk through each difference the replay found. Show what to compare, ask, and record the
    answer in replay-exceptions.json. Nothing is published: approving the proposal comes after."""
    rep, earlier, pairs = _differences()
    if not rep.differences:
        print("nothing to decide: the replay passes" if rep.ok else "\n".join(rep.lines()))
        return 0 if rep.ok else 1
    advice = _second_opinion(pairs, ask, interactive)
    print(f"{len(rep.differences)} difference(s) to decide. Open the links, compare, then answer.")
    for i, d in enumerate(rep.differences, 1):
        print()
        kind = _kind(d)
        if kind == "pair":
            print(f"{i}. Two spellings. The Federal Register notice prints {d['parsed']!r}; the list has {d['store']!r}.")
            print("\n".join(_evidence(d, earlier)))
            n = next(j for j, p in enumerate(pairs, 1) if p["parsed"] == d["parsed"])
            if n in advice:
                print(f"      AI's guess (a guess, not a source; check it): {advice[n][0]}. {advice[n][1]}")
            a = ask("    Same company, spelled two ways? [y]es / [n]o / [s]kip > ").strip().lower()
            if a.startswith("y"):
                typo = ask(f"    Is the notice's spelling {d['parsed']!r} a mistake (keep it off the page)? [Y/n] > ").strip().lower()
                record(d, "same entity", _why(ask), typo=typo.startswith("y") or typo == "")
                print(f"    Saved: same company; the list keeps {d['store']!r}.")
            elif a.startswith("n"):
                print("    Then they are two different companies: one is missing from the list, and the other is in no"
                      " notice. That needs a closer look at both; left undecided.")
            else:
                print("    Skipped; still undecided.")
        elif kind == "missing":
            print(f"{i}. In the notice, not on the list: {d['parsed']!r}.")
            print("\n".join(_evidence(d, earlier)))
            a = ask("    Does the DoW list include it, so the list should too? [a]dd / [s]kip > ").strip().lower()
            if a.startswith("a"):
                record(d, "add", _why(ask))
                print("    Saved: add it.")
            else:
                print("    Skipped; still undecided.")
        else:
            print(f"{i}. On the list, but in no notice: {d['store']!r}.")
            print("\n".join(_evidence(d, earlier)))
            a = ask("    Keep it on the list anyway? [k]eep / [s]kip > ").strip().lower()
            if a.startswith("k"):
                record(d, "keep", _why(ask))
                print("    Saved: keep it.")
            else:
                print("    Skipped; still undecided.")
    print()
    return cmd_replay()


def _state():
    """Everything the review page shows, as plain data."""
    rep, earlier, _pairs = _differences()
    llm = _llm(interactive=True)
    return {"ok": rep.ok, "lines": rep.lines(), "label": _read("page-meta.json", {}).get("label", ""),
            "ai": f"{llm[1]} at {llm[0]}" if llm else "",
            "differences": [{"parsed": d.get("parsed"), "store": d.get("store"), "kind": _kind(d),
                             "facts": _facts(d, earlier)} for d in rep.differences],
            "resolved": [{"parsed": e.get("parsed"), "store": e.get("store"), "resolution": e.get("resolution"),
                          "note": e.get("note", "")} for e in rep.resolved]}


def _page_decide(parsed, store, choice, why, typo=True):
    """A decision from the review page. It must match a difference the replay reports right now."""
    rep, _e, _p = _differences()
    d = next((d for d in rep.differences if (d.get("parsed") or None) == (parsed or None)
              and (d.get("store") or None) == (store or None)), None)
    if d is None:
        raise ValueError("that difference is no longer open: reload the page")
    record(d, choice, why, typo=typo)


def _page_advice():
    """The one AI call, from the page's button (the click is the yes)."""
    _rep, _e, pairs = _differences()
    got = _second_opinion(pairs, ask=lambda q: "y", interactive=True)
    return [{"parsed": pairs[n - 1]["parsed"], "guess": g, "why": w} for n, (g, w) in sorted(got.items())]


def cmd_review(port=8765, open_browser=True):
    """A clickable page for the same decisions, on this computer only. Ctrl+C stops it."""
    import review
    return review.serve(state=_state, decide=_page_decide, advice=_page_advice, pdfs=_pdfs,
                        port=port, open_browser=open_browser)


def _page_history(store):
    """First-listed dates and every removal since 2021, when the data folder keeps the history
    (the classroom example does not). A history that cannot be read leaves the page as it was,
    and says so."""
    if not historycheck.has_history(RULES, DATA):
        return None
    eq, as_of = replay.equivalents(DATA), store.get("currency_date", "")
    try:
        return {"listed": historycheck.first_listed(RULES, DATA, store["entities"], as_of, eq),
                "removals": historycheck.removals(RULES, DATA, store["entities"], as_of, eq)}
    except ListwatchError as e:
        print(f"page: dates and removal history left out ({e})")
        return None


def _build_page():
    meta = _read("page-meta.json", {"label": "Section 1260H list"})
    store = _store()
    meta["as_of"] = store.get("currency_date", meta.get("as_of", ""))
    html = page.build(meta, store["entities"], _register(), _approved_docs(), _page_history(store))
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
            holds.append(f"the replay check fails: run `python3 run.py replay{_flag()}`, then `python3 run.py decide{_flag()}`")
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
    print(f"approved {pid}; run `python3 run.py page{_flag()}` to rebuild the page")
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
            "stale": cmd_stale, "prepare": cmd_prepare, "decide": cmd_decide, "spelling": cmd_spelling,
            "review": cmd_review, "completeness": cmd_completeness, "removals": cmd_removals}
    if len(argv) == 3 and argv[:2] == ["history", "add"]:
        return cmd_history_add(argv[2])
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
