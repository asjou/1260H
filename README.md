# The Section 1260H list, kept current from the Federal Register

The Department of Defense (aka War; "DoW" below) names "Chinese military
companies" under Section 1260H of the FY2021 NDAA. We know of no official, current,
machine-readable copy of that list. DoW publishes an annual list, then adds and removes companies
by separate Federal Register notices. For example, DoW removed WuXi AppTec on 10 November 2026
(91 FR 72536) "in compliance with" a preliminary injunction issued on 7 August 2026. The case is
not over, and the company could be listed again.

This repo keeps the net list. Every row links to the page of the official notice it came from, and
removed companies stay visible, with the date, the reason and the notice.

**The page:** <https://asjou.github.io/1260H/>

## How it works

```
 Federal Register API ──► save the notice ──► read it by rule ──► proposal ──► a person approves ──► page
  (weekly, on GitHub)     (with its SHA-256)   (fixed Python)     (what would    (merges the pull
                                                                  change)        request)
```

1. **Detect.** Every Monday a GitHub job asks the Federal Register API for notices that match
   "1260H". The DoW website blocks scripts, so the Federal Register (federalregister.gov and
   govinfo.gov) is the source: it is the official journal where DoW publishes these notices.
2. **Save first.** Each new notice is saved with its SHA-256 fingerprint before anything reads it
   (`data/dow-1260h/sources/`). If a saved notice changes by one byte, the tests fail.
3. **Read by rule.** Fixed Python rules (`listwatch/lists/dow_1260h.py`) turn the text into rows:
   company, short names, the parent it is listed under, the Federal Register page, and a link.
   A layout the rules do not recognise is refused, not guessed.
4. **Propose.** The job opens a pull request that shows what would be added or removed, each with
   its source link.
5. **A person approves.** You check each change against its source link. **Merging the pull
   request is the approval.** Closing it rejects the change. Nothing publishes by itself. If the
   pull request title starts with **HOLD**, do not merge it: something needs a person first.
6. **Publish.** GitHub Pages serves the page in `docs/` from the main branch.

## The design rule

1. Write a script when the input has a pattern.
2. Save the source before you read it.
3. Test against an answer a person already checked.
4. Call an AI model only where the rules fail, only to propose, and only after you say yes. Code
   checks its answer.
5. Mark what a machine read.
6. A person approves what publishes.

## Run it

Python 3.10 or later (`python3`), standard library only. Nothing to install. No account, no key.

```
python3 -m unittest      # the proof: all tests, offline
python3 run.py replay    # re-read the saved notices and compare with the list
python3 run.py decide    # answer a question for each difference the replay found
python3 run.py spelling  # compare this year's names with earlier years' lists
python3 run.py page      # rebuild docs/index.html
python3 run.py check     # look for new notices (network)
python3 run.py show      # what each open proposal would change
python3 run.py approve ID
```

## The classroom example: find and fix two mistakes

`example/dow-1260h/` holds the list as a first parse of the DoW PDF left it. It is an example for
teaching, and it repeats two real problems:

- the parse **missed NIO, Inc.**, which the 2026 list prints at 91 FR 35193;
- the Federal Register prints **"Addisino Co., Ltd"** (91 FR 35190), but the DoW list prints
  **"Addsino Co., Ltd."**. We treat the Federal Register spelling as a misprint and keep the DoW
  spelling. Check both yourself: the replay links the Federal Register page, and the DoW PDF is
  [here](https://media.defense.gov/2026/Jun/08/2003945537/-1/-1/1/ENTITIES-IDENTIFIED-AS-CHINESE-MILITARY-COMPANIES-OPERATING-IN-THE-UNITED-STATES-IN-ACCORDANCE-WITH-SECTION-1260H.PDF) (open it in a browser; the site blocks scripts). Then search the web for
  "Addisino": the misprint has been copied into other published lists.

**Step 1. Let the tool find them.** You don't hunt for typos; the replay does:

```
python3 run.py replay --data example/dow-1260h
```

It fails with two differences and, under each one, what to compare: the Federal Register page,
the DoW PDF, and what earlier years' lists printed. For Addisino it shows that the 2025 list
printed "Addsino" and no earlier list ever printed "Addisino".

**Step 2. Judge each one, and answer.** Open the links, compare, then:

```
python3 run.py decide --data example/dow-1260h
```

It asks one question at a time, in plain words, and records your answer and your reason:

```
1. Two spellings. The Federal Register notice prints 'Addisino Co., Ltd'; the list has 'Addsino Co., Ltd.'.
      Federal Register: https://www.govinfo.gov/...2026-11571.pdf#page=2
      DoW list (open in a browser, search for the name): https://media.defense.gov/...
      earlier lists print 'Addsino Co., Ltd.': 2025 (90 FR 1105)
      no earlier list prints 'Addisino Co., Ltd'; close: 2025 printed 'Addsino Co., Ltd.'
    Same company, spelled two ways? [y]es / [n]o / [s]kip > y
    Is the notice's spelling 'Addisino Co., Ltd' a mistake (keep it off the page)? [Y/n] > y
    Why? One line: what the sources show. > The DoW PDF and the 2025 list print Addsino.
```

When every difference is decided, the replay passes. Your answers are saved in
`example/dow-1260h/replay-exceptions.json`: the record of what a person decided and why.

**Step 3. Approve and publish (the example only).**

```
python3 run.py show --data example/dow-1260h
python3 run.py approve <id> --data example/dow-1260h
python3 run.py page --data example/dow-1260h        # writes example/index.html
git checkout example/                              # reset the example to try again
```

## How to judge a difference

The tool finds a difference; a person decides it. Ask, in this order:

1. **What does the issuing agency's own document say?** The DoW PDF is DoW's list. The Federal
   Register copy is a reprint, typed again, and reprints carry typos. When the two disagree on a
   letter, the DoW PDF wins unless something shows otherwise.
2. **What did earlier years print?** `replay` and `decide` show it. A spelling that every earlier
   list printed, and that only this year's reprint changes, is very likely a typo.
3. **Is it a rename?** Companies change names. The notices sometimes say so ("formerly ..."). A
   different word, not a different letter, points to a rename, or to a different company. Check
   the company's own filings before you treat two names as one.
4. **Write the reason down.** One line: which sources you compared and what each printed. The next
   person, or you next year, reads it.

Earlier years' lists are evidence, not the answer: an old list can carry a typo too.

## Earlier years' lists

`data/dow-1260h/history/` keeps the 2021, 2024 and 2025 annual lists as printed in the Federal
Register, saved with their fingerprints like every other source. They never build the list; they
are there to compare spellings.

```
python3 run.py spelling            # names this year that no earlier list prints, but that are close to one that does
python3 run.py history add DOC     # save another year's list by its Federal Register document number (network)
```

`spelling` is plain string comparison, no AI. On the 2026 list it finds "Addisino" (2025:
"Addsino"), and three more worth a look: "Phenix Optical" (2025: "Phoenix Optics"), "Chengdu
Mengsheng Electronic" (2025: "Chengdu M&S Electronics") and "China Communications Construction
(USA)" (2025: "Constructions USA, Inc."). Each could be a typo, a rename or a different company.

**The DoW PDFs:** defense.gov blocks scripts, so save them yourself, from your browser, into
`data/dow-1260h/dow-pdf/`, named by date (for example `2026-06-08.pdf`). `replay` and `decide` list
them next to each difference. The scripts never read them: they are for the person deciding.

## The AI step

**Nothing here calls an AI model unless it asks you first and you approve.**

The rules read the usual notices: the annual list, additions and removals (WuXi's removal is read by
rule). The AI step is for a notice the rules do not recognise, for example an off-cycle notice in a
new layout. Then `run.py` stops and asks:

```
The rules cannot read 2027-01234. Send its text to <model> at <url>? [y/N]
```

If you say yes, the model proposes the names. Code then rejects any name that is not printed word
for word in the notice, and any removal of a company not on the list. You still approve the result.
The weekly GitHub job never calls a model, because no one is there to say yes.

**A second opinion on spellings.** `decide` can also ask a model, once, for its guess on all the
spelling pairs together ("typo", "rename", "different companies" or "unsure", with one sentence
why). It asks you first, sends only the names and what earlier lists printed, and labels the answer
as a guess. You still decide, and you still write the reason.

Try it on the made-up example notice:

```
python3 run.py read example/unfamiliar-notice.txt   # the rules refuse it: "needs human reading"
```

**Any provider works, and you can swap it.** The step speaks the common OpenAI-compatible format,
so a model on your own computer, OpenRouter, or a paid provider are all one setting apart. If a
price goes up or a provider goes down, change the URL. Set three values in your shell, or in a file
named `.env` in this folder:

```
# a local model (no key needed), or for example https://openrouter.ai/api/v1
LISTWATCH_LLM_URL=http://127.0.0.1:8080/v1
LISTWATCH_LLM_MODEL=your-model-name
# only for a paid service
LISTWATCH_LLM_KEY=your-key
```

**Keep your key secret.** `.env` is listed in `.gitignore`, so git does not commit it. Never put a
key in a file that git tracks, in an issue, or in a GitHub Actions log. Plain `http` is allowed only
to your own computer. Any other address must use `https`.

## Set up your own copy

1. Fork or copy this repo.
2. **Settings → Actions → General → Workflow permissions:** tick "Allow GitHub Actions to create and
   approve pull requests". Without it the weekly job cannot open its pull request.
3. **Settings → Pages:** deploy from the `main` branch, folder `/docs`.
4. **Settings → Branches:** protect `main` so that changes arrive only by pull request.
5. **Actions → weekly-check → Run workflow** to try it once.

GitHub pauses scheduled jobs in a repo with no activity for 60 days. Re-enable it on the Actions
tab, or run `python3 run.py stale` yourself.

## Files

| Path | What it is |
|---|---|
| `listwatch/` | The pipeline: find, save, read by rule, propose. Standard library only. |
| `listwatch/lists/dow_1260h.py` | The 1260H rules, including the known slips in the notices' own text. |
| `data/dow-1260h/` | The live list, its saved notices, approved proposals, and `replay-exceptions.json` (each difference and how it was decided). |
| `data/dow-1260h/history/` | Earlier years' annual lists, kept to compare spellings. |
| `data/dow-1260h/dow-pdf/` | Where you save the DoW PDFs by hand. |
| `example/` | The classroom example and a made-up unfamiliar notice. |
| `prompts/` | The two prompts, used only by the AI step: reading an unfamiliar notice, and the spelling second opinion. |
| `tests/`, `test_replay.py` | The proof. The rules are tested against the real notices. |

## What this is not

Not legal advice, and not an official source. The official list and the Federal Register notices
control. Check the source link before you rely on a row.

## Licence

MIT (see `LICENSE`). The Federal Register notices are U.S. government works.
