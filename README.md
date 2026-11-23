# The Section 1260H list, kept current from the Federal Register

The Department of Defense (now also styled the Department of War; "DoW" below) names "Chinese military
companies" under Section 1260H of the FY2021 NDAA. We know of no official, current,
machine-readable copy of that list. DoW publishes an annual list, then adds and removes companies
by separate Federal Register notices. For example, a notice published 10 November 2026 (91 FR 72536)
removed WuXi AppTec "in compliance with" a preliminary injunction issued on 7 August 2026. The notice
says the removal is "without prejudice to relisting the entity on additional or supplementary grounds".

This repo keeps the net list. Every row links to the page of the official notice it came from and
shows when the company was first listed. Every company removed since the first list (June 2021)
stays visible, with the dates it was listed and removed, the reason the documents give, and links
to them.

**The page:** <https://asjou.github.io/1260H/>

## How it works

```
 Federal Register API ──► save the notice ──► read it by rule ──► proposal ──► a person approves ──► page
  (daily, on GitHub)      (with its SHA-256)   (fixed Python)     (what would    (merges the pull
                                                                  change)        request)
```

1. **Detect.** Every night, at about 2 a.m. Eastern, a GitHub job asks the Federal Register API for notices that match
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
python3 run.py review    # decide each difference the replay found, on a page in your browser (this computer only)
python3 run.py spelling  # compare this year's names with earlier years' lists
python3 run.py completeness  # check every company that left since 2021 has a document or a recorded decision
python3 run.py removals  # every removal since 2021, quoting the documents
python3 run.py page      # rebuild docs/index.html (current list with first-listed dates, removals since 2021)
python3 run.py check     # look for new notices (network)
python3 run.py show      # what each open proposal would change
python3 run.py approve ID
```

## The classroom example: a practice copy with one mistake

`example/dow-1260h/` is a **practice copy** of the list, for teaching. Nothing you do there touches
the live list or the published page. It repeats one real problem: the two official copies of the
2026 list spell one company differently.

- The **Federal Register** notice prints **"Addisino Co., Ltd"** (91 FR 35190).
- The **DoW list** (the Department's own PDF) prints **"Addsino Co., Ltd."**, and so did the 2025
  list. No earlier list ever printed "Addisino".

Read against the earlier years, it is one company, Addsino, with a misprint in the Federal Register
copy, not a different company. The practice copy keeps the DoW spelling, and you record why. Check
it yourself: the replay links the Federal Register page, and the DoW PDF is
[here](https://media.defense.gov/2026/Jun/08/2003945537/-1/-1/1/ENTITIES-IDENTIFIED-AS-CHINESE-MILITARY-COMPANIES-OPERATING-IN-THE-UNITED-STATES-IN-ACCORDANCE-WITH-SECTION-1260H.PDF)
(open it in a browser; the site blocks scripts). Then search the web for "Addisino": the misprint
has been copied into other published lists.

**Step 1. Let the tool find it.** You don't hunt for typos; the replay does:

```
python3 run.py replay --data example/dow-1260h
```

It fails with one difference and shows what to compare: the Federal Register page, the DoW PDF,
and what earlier years' lists printed (2025 printed "Addsino"; no earlier list printed "Addisino").

**Step 2. Decide it on the review page.**

```
python3 run.py review --data example/dow-1260h
```

Your browser opens a page on your own computer (`http://127.0.0.1:8765`): one card for the
difference, with the Federal Register link, the saved DoW PDFs and what earlier years printed.
Click **"Same company, spelled two ways"**, leave **"'Addisino Co., Ltd' is a typo: keep it off the
page"** ticked, write your reason (for example "The DoW PDF and the 2025 list print Addsino.") and
click **Save decision**. Press Ctrl+C in the terminal to stop the page. In GitHub Codespaces, open
the forwarded port it offers.

The replay now passes. Your decision and your reason are saved in
`example/dow-1260h/replay-exceptions.json`: the record of what a person decided and why.

**Step 3. Approve and build the practice page.**

```
python3 run.py show --data example/dow-1260h
python3 run.py approve <id> --data example/dow-1260h
python3 run.py page --data example/dow-1260h        # writes example/index.html, on your computer only
git checkout example/                              # reset the practice copy to try again
```

Open `example/index.html`: Addsino is on the page and Addisino is not. This is a practice page; it
is not published anywhere. **On the live list, a change works differently:** the nightly GitHub
job finds the notice and opens a pull request showing what would change, each row with its source
link. You check it, and merging the pull request is what publishes the page at
<https://asjou.github.io/1260H/>. Closing it rejects the change.

## How to judge a difference

The tool finds a difference; a person decides it. Ask, in this order:

1. **What does the issuing agency's own document say?** The DoW PDF is DoW's list. The Federal
   Register copy is a reprint, typed again, and reprints carry typos. When the two disagree on a
   letter, the DoW PDF wins unless something shows otherwise.
2. **What did earlier years print?** `replay` and the review page show it. A spelling that every earlier
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

**The DoW PDFs:** defense.gov blocks scripts, so the five list PDFs in `data/dow-1260h/dow-pdf/`
were saved by hand from a browser, as `dow-<date on the web address>.pdf`. When saved, each had the
same SHA-256 as the Wayback Machine capture of its official address; download the capture to check.
Beside each is its text, made once with `pdftotext -layout`, and a record with the official address,
the Wayback capture's address, and the SHA-256 of the PDF and of its text. `replay` and the review page list
the PDFs next to each difference. The scripts use the PDFs' saved text (after checking both
fingerprints) for two things only: the 2022 list, and the removal sections. The 2022 PDF is a scan;
its text has scanner slips ("Chioa" for "China", "Dn" for "DJI"), corrected openly in
`SCAN_ERRATA` in the rules file. See `dow-pdf/README.md`.

## Removals since 2021

The current list says who is on it. It does not say who was taken off, or why. That is spread over
five annual lists (the 2022 list only as a PDF), seven amendment notices and the Department's own
PDFs, which do not always say the same thing: the January 2024 PDF lists three earlier-listed
companies under a heading, "The Following Entities Did Not Meet Some or All of the Requirements of
Section 1260H…", with a note beside each, and the Federal Register copy of the same list leaves that
section out.

```
python3 run.py completeness   # every company that left has a document or a recorded decision, or it fails
python3 run.py removals       # each removal, quoting what the documents say
```

Both are fixed rules over saved files: no network, no AI. `completeness` walks the lists in order
(2021, 2022, 2024, 2025, 2026, and the list as it stands) and, for each pair, requires every company
on the earlier list and not the later one to be explained:

- by a document that removes it in between (a Federal Register notice, or a removal section in the
  Department's PDF); or
- by an approved decision in `data/dow-1260h/history-decisions.json`, for the few that no document
  removes: a rename the list states, names printed differently under the same parent, a subsidiary
  no longer printed whose parent is still listed (CNOOC Limited), a company the 2025 list keeps only
  in a footnote, and one company no longer printed, with no notice. Each decision says its basis: a
  document, where the lists print the names, or a person's judgment.

It also requires every removal a document makes to match a company that really left, and every
quote a decision cites to appear word for word in the saved document. Delete a decision, or change
one word of a saved text, and it fails. That is the safeguard: a check that every company that left
has a cited document or a recorded decision. It does not test whether a decision is right, or the
saved files against the live government copies; the fingerprints are recorded in this same repo.

`removals` says, for each one, whether a document states a ground or only says the company is
removed ("No specific reason stated in …"), and whether a quote is printed once over a group of
names or beside one name. A heading over ten names gives one ground for the group; the documents
give no facts for each company. Labels and the "No specific reason" marker are this repo's; notes
marked "editor's note" are a person's, drawn from the documents cited. Leaving this list is not a
finding about a company's status under any other list or restriction.

The page shows the same history in two columns. **Listed** is the date the Department released the
first list that prints the company, followed through approved renames; a company removed and listed
again keeps its first date (`historycheck.first_listed`). **Removed** is the date of the Federal
Register notice that removed it, or of the Department's PDF where no notice did. The reason column
quotes the most specific statement word for word, cut with "…" when long; the full text is one
click away. A company the history cannot date shows no date rather than a guess.

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
The daily GitHub job never calls a model, because no one is there to say yes.

**A second opinion on spellings.** The review page can also ask a model, once, when you click its button, for its guess on all the
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
   approve pull requests". Without it the daily job cannot open its pull request.
3. **Settings → Pages:** deploy from the `main` branch, folder `/docs`.
4. **Settings → Branches:** protect `main` so that changes arrive only by pull request.
5. **Actions → daily-check → Run workflow** to try it once.

GitHub pauses scheduled jobs in a repo with no activity for 60 days. Re-enable it on the Actions
tab, or run `python3 run.py stale` yourself.

## Files

| Path | What it is |
|---|---|
| `listwatch/` | The pipeline: find, save, read by rule, propose. Standard library only. |
| `listwatch/lists/dow_1260h.py` | The 1260H rules, including the known slips in the notices' own text and the scan slips in the 2022 PDF. |
| `listwatch/historycheck.py`, `listwatch/completeness.py` | The removal history and the check that none is missing. |
| `data/dow-1260h/` | The live list, its saved notices, approved proposals, and `replay-exceptions.json` (each difference and how it was decided). |
| `data/dow-1260h/history/` | Earlier years' annual lists, and (in `notices/`) the 2024 removal and designation notices. |
| `data/dow-1260h/dow-pdf/` | The Department's list PDFs, each with its text and a record of where it came from. |
| `data/dow-1260h/history-decisions.json` | The decisions for companies no document removes, each with its evidence. |
| `example/` | The classroom example and a made-up unfamiliar notice. |
| `review.py` | The clickable review page: a small web server on your own computer, standard library only. |
| `prompts/` | The two prompts, used only by the AI step: reading an unfamiliar notice, and the spelling second opinion. |
| `tests/`, `test_replay.py` | The proof. The rules are tested against the real notices. |

## What this is not

Not legal advice, and not an official source. The official list and the Federal Register notices
control. Check the source link before you rely on a row.

## Licence

MIT (see `LICENSE`). The Federal Register notices are U.S. government works.
