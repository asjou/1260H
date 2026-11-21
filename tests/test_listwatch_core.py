"""The list-independent core of listwatch: detection, sources, proposals, the fallback check,
the page, and the package boundary (plan 2026-11-20-001, U1, U3 core, U4 core, U8)."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

from listwatch import LayoutError, ListwatchError, SourceError, detect, page, proposal as P, sources
from listwatch.lists import dow_1260h as R
from listwatch.names import key
from listwatch.rules import Parsed

PKG = Path(__file__).resolve().parents[1] / "listwatch"
FIX = Path(__file__).parent / "fixtures" / "listwatch"
SEARCH = json.loads((FIX / "fr-search-1260h.json").read_text())
DOCS = {d["document_number"]: d for d in SEARCH["results"]}
STDLIB = {"__future__", "ast", "dataclasses", "datetime", "hashlib", "html", "json", "pathlib", "re",
          "urllib", "typing", "collections"}


def fake_fetch(extra_results=(), texts=None, calls=None):
    texts = texts or {}

    def fetch(url):
        if calls is not None:
            calls.append(url)
        if "documents.json" in url:
            return json.dumps({"results": [*extra_results, *SEARCH["results"]]}).encode()
        for n, body in texts.items():
            if n in url:
                return body
        for n in DOCS:
            if n in url:
                return (FIX / "notices" / f"{n}.txt").read_bytes()
        raise SourceError(f"unexpected url {url}")
    return fetch


def new_doc(n, title, typ="Notice", date="2026-12-01"):
    return {"document_number": n, "title": title, "type": typ, "publication_date": date, "citation": "91 FR 80000",
            "start_page": 80000, "html_url": f"https://www.federalregister.gov/d/{n}",
            "pdf_url": f"https://www.govinfo.gov/content/pkg/FR-x/pdf/{n}.pdf",
            "raw_text_url": f"https://www.federalregister.gov/documents/full_text/text/x/{n}.txt"}


class Boundary(unittest.TestCase):
    def test_package_imports_only_itself_and_the_standard_library(self):
        for f in PKG.rglob("*.py"):
            tree = ast.parse(f.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level:            # relative: inside the package
                        continue
                    self.assertIn(node.module.split(".")[0], STDLIB, f"{f.name}: from {node.module}")
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split(".")[0], STDLIB, f"{f.name}: import {a.name}")

    def test_core_holds_no_1260h_knowledge(self):
        for f in PKG.glob("*.py"):
            src = f.read_text()
            self.assertNotIn("Chinese military", src, f.name)
            self.assertNotIn("defense-department", src, f.name)


class Sources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_allowlist(self):
        self.assertEqual(sources.check_url("https://www.govinfo.gov/x"), "https://www.govinfo.gov/x")
        for bad in ("http://www.federalregister.gov/x", "https://evil.com/x", "https://gov.evil.com/x"):
            with self.subTest(bad), self.assertRaises(SourceError):
                sources.check_url(bad)

    def test_botwall_and_empty_refused(self):
        wall = b"<html>Request Access. Due to aggressive automated scraping ...</html>"
        with self.assertRaises(SourceError):
            sources.save(self.d, "2026-1", "https://www.federalregister.gov/a", wall, "t")
        with self.assertRaises(SourceError):
            sources.save(self.d, "2026-1", "https://www.federalregister.gov/a", b"", "t")

    def test_round_trip_and_hash(self):
        rec = sources.save(self.d, "2026-1", "https://www.federalregister.gov/a", b"<pre>A &amp; B</pre>", "t")
        text, rec2 = sources.load(self.d, "2026-1")
        self.assertEqual(text, "A & B")
        self.assertEqual(rec["sha256"], rec2["sha256"])


class Detect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        detect.check(R, self.d, fake_fetch(), [], log=lambda *_: None)        # baseline
        self.current = R.parse("annual", sources.clean((FIX / "notices/2026-11571.txt").read_bytes()),
                               DOCS["2026-11571"], []).roster

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_run_records_everything_silently(self):
        log = detect.load_log(self.d)
        self.assertEqual(len(log["documents"]), 11)
        self.assertEqual({e["outcome"] for e in log["documents"].values()}, {"baseline"})
        self.assertFalse((self.d / "proposals").exists())

    def test_no_new_notices(self):
        res = detect.check(R, self.d, fake_fetch(), self.current, log=lambda *_: None)
        self.assertEqual(str(res), "no new notices")

    def test_new_removal_becomes_a_saved_source_and_an_open_proposal(self):
        body = (FIX / "notices/2026-22840.txt").read_bytes().replace(b"2026-22840", b"2026-99999")
        doc = {**DOCS["2026-22840"], "document_number": "2026-99999", "publication_date": "2026-12-01",
               "raw_text_url": "https://www.federalregister.gov/documents/full_text/text/2026/12/01/2026-99999.txt"}
        res = detect.check(R, self.d, fake_fetch([doc], {"2026-99999": body}), self.current, log=lambda *_: None)
        self.assertEqual(res.proposals, ["2026-99999"])
        self.assertTrue((self.d / "sources" / "2026-99999.json").exists())
        prop = P.load_all(self.d / "proposals")[0]
        self.assertEqual((prop["kind"], prop["status"], prop["machine_read"]), ("removal", "open", False))
        self.assertEqual([r["name"] for r in prop["removes"]], ["WuXi AppTec Co., Ltd."])
        again = detect.check(R, self.d, fake_fetch([doc], {"2026-99999": body}), self.current, log=lambda *_: None)
        self.assertEqual(again.new, [])                                       # re-run is a no-op

    def test_rule_mentioning_1260h_is_logged_as_no_change(self):
        doc = new_doc("2026-88888", "Defense Federal Acquisition Regulation Supplement: Section 1260H", typ="Rule")
        calls = []
        res = detect.check(R, self.d, fake_fetch([doc], calls=calls), self.current, log=lambda *_: None)
        self.assertEqual(res.no_change, ["2026-88888"])
        self.assertFalse(any("2026-88888" in c for c in calls))
        detect.mark_reviewed(self.d, "2026-88888")
        self.assertEqual(detect.load_log(self.d)["documents"]["2026-88888"]["outcome"], "reviewed")

    def test_unknown_notice_is_saved_and_needs_human_reading_without_a_reader(self):
        doc = new_doc("2026-77777", "Update Regarding Section 1260H Entities")
        res = detect.check(R, self.d, fake_fetch([doc], {"2026-77777": b"<pre>Some notice text</pre>"}),
                           self.current, log=lambda *_: None)
        self.assertEqual(res.needs_reading, ["2026-77777"])
        self.assertTrue((self.d / "sources" / "2026-77777.json").exists())
        f = fake_fetch([doc], {"2026-77777": b"<pre>Some notice text</pre>"})
        quiet = detect.check(R, self.d, f, self.current, reader=lambda t, d: None, log=lambda *_: None)
        self.assertEqual(quiet.new, [])                     # a scheduled run does not retry it
        retry = detect.check(R, self.d, f, self.current, reader=lambda t, d: None, retry_reading=True,
                             log=lambda *_: None)
        self.assertEqual(retry.new, ["2026-77777"])         # a person with the AI step on is offered it again

    def test_fetch_error_is_retried_next_run(self):
        doc = new_doc("2026-66666", "Notice of Removal of Designated Chinese Military Company")

        def broken(url):
            if "documents.json" in url:
                return json.dumps({"results": [doc]}).encode()
            raise SourceError("HTTP 503")
        res = detect.check(R, self.d, broken, self.current, log=lambda *_: None)
        self.assertEqual(res.errors, ["2026-66666"])
        self.assertNotIn("2026-66666", detect.load_log(self.d)["documents"])

    def test_no_step_asks_media_defense_gov(self):
        calls = []
        doc = {**DOCS["2026-22840"], "document_number": "2026-99998", "publication_date": "2026-12-02"}
        detect.check(R, self.d, fake_fetch([doc], calls=calls), self.current, log=lambda *_: None)
        self.assertFalse(any("media.defense.gov" in c for c in calls))


class Fallback(unittest.TestCase):
    TEXT = "The following entity is delisted: WuXi AppTec Co., Ltd. effective today."
    DOC = new_doc("2026-55555", "Odd notice")
    CUR = [{"name": "WuXi AppTec Co., Ltd.", "aka": []}, {"name": "Other Co.", "aka": []}]

    def test_names_must_be_in_the_text_and_on_the_list(self):
        p, kind = detect.fallback(lambda t, d: {"kind": "removal", "names": ["WuXi AppTec Co., Ltd."]},
                                  self.TEXT, self.DOC, self.CUR, R)
        self.assertEqual((kind, [r["name"] for r in p.removes]), ("removal", ["WuXi AppTec Co., Ltd."]))
        with self.assertRaises(ListwatchError):
            detect.fallback(lambda t, d: {"kind": "removal", "names": ["Made Up Ltd."]}, self.TEXT, self.DOC, self.CUR, R)
        with self.assertRaises(ListwatchError):
            detect.fallback(lambda t, d: {"kind": "removal", "names": ["effective today"]}, self.TEXT, self.DOC, self.CUR, R)

    def test_machine_read_is_never_a_full_replacement_and_bad_answers_fail(self):
        with self.assertRaises(ListwatchError):
            detect.fallback(lambda t, d: {"kind": "annual", "names": ["WuXi AppTec Co., Ltd."]}, self.TEXT, self.DOC, self.CUR, R)
        for bad in (lambda t, d: "not json", lambda t, d: {"kind": "removal"}):
            with self.assertRaises(ListwatchError):
                detect.fallback(bad, self.TEXT, self.DOC, self.CUR, R)

        def boom(t, d):
            raise TimeoutError("slow")
        with self.assertRaises(ListwatchError):
            detect.fallback(boom, self.TEXT, self.DOC, self.CUR, R)

    def test_reader_only_called_when_rules_fail(self):
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)
        detect.check(R, d, fake_fetch(), [], log=lambda *_: None)

        def must_not_run(t, doc):
            raise AssertionError("reader called")
        doc = {**DOCS["2026-22840"], "document_number": "2026-99997", "publication_date": "2026-12-03"}
        res = detect.check(R, d, fake_fetch([doc]), self.CUR, reader=must_not_run, log=lambda *_: None)
        self.assertEqual(res.proposals, ["2026-99997"])
        odd = new_doc("2026-44444", "Odd notice about 1260H")
        res = detect.check(R, d, fake_fetch([odd], {"2026-44444": f"<pre>{self.TEXT}</pre>".encode()}), self.CUR,
                           reader=lambda t, doc: {"kind": "removal", "names": ["WuXi AppTec Co., Ltd."]},
                           log=lambda *_: None)
        self.assertEqual(res.proposals, ["2026-44444"])
        self.assertTrue(next(p for p in P.load_all(d / "proposals") if p["id"] == "2026-44444")["machine_read"])
        tmp.cleanup()


def row(name, **kw):
    return {"name": name, "aka": kw.pop("aka", []), "source_doc": "old", **kw}


class Proposals(unittest.TestCase):
    DOC = {"document_number": "2026-2", "publication_date": "2026-12-01", "citation": "91 FR 2",
           "html_url": "https://www.federalregister.gov/d/2026-2"}

    def test_compare_recomputes_and_apply_keeps_names_and_verified(self):
        cur = [row("BOE Technology Group Company Limited", aka=["BOE"], verified={"date": "2026-09-13"}),
               row("Gone Co."), row("Stay Co.")]
        roster = [row("BOE Technology Group Co., Ltd.", aka=["BOE"], source_page=3), row("Stay Co."), row("New Co.")]
        prop = P.build("x", "annual", [self.DOC], Parsed(roster=roster))
        cmp = P.compare(prop, cur)
        self.assertEqual([r["name"] for r in cmp["added"]], ["New Co."])
        self.assertEqual([r["name"] for r in cmp["removed"]], ["Gone Co."])
        self.assertEqual(cmp["renamed"], [{"from": "BOE Technology Group Company Limited", "to": "BOE Technology Group Co., Ltd."}])
        rows, reg = P.apply(prop, cur, [])
        boe = rows[0]
        self.assertEqual(boe["name"], "BOE Technology Group Company Limited")
        self.assertIn("BOE Technology Group Co., Ltd.", boe["aka"])
        self.assertEqual((boe["verified"], boe["source_page"]), ({"date": "2026-09-13"}, 3))
        self.assertEqual(rows[2]["date_added"], "2026-12-01")
        self.assertEqual([e["name"] for e in reg], ["Gone Co."])
        self.assertEqual(reg[0]["removed_on"], "2026-12-01")

    def test_a_new_row_takes_its_own_notice_date_and_a_start_proposal_invents_none(self):
        annual = {"document_number": "2026-11571", "publication_date": "2026-06-10", "citation": "91 FR 35189"}
        later = {"document_number": "2026-22840", "publication_date": "2026-11-10", "citation": "91 FR 72536"}
        nio = row("NIO, Inc.", source_doc="2026-11571")
        start = P.build("x", "start", [annual, later], Parsed(roster=[nio]))
        self.assertEqual(start["publication_date"], "2026-11-10")
        self.assertEqual(P.apply(start, [], [])[0][0]["date_added"], "")      # not the proposal's date
        add = P.build("x", "addition", [annual, later], Parsed(adds=[nio]))
        self.assertEqual(P.apply(add, [], [])[0][0]["date_added"], "2026-06-10")

    def test_removal_not_on_the_list_holds(self):
        prop = P.build("x", "removal", [self.DOC], Parsed(removes=[{"name": "Nobody Ltd.", "reason": "r"}]))
        self.assertTrue(P.holds(prop, P.compare(prop, [row("Stay Co.")])))

    def test_earlier_open_proposal_holds_and_dates_never_go_back(self):
        a = P.build("x", "removal", [{**self.DOC, "document_number": "A", "publication_date": "2026-01-01"}], Parsed())
        b = P.build("x", "removal", [{**self.DOC, "document_number": "B", "publication_date": "2026-02-01"}], Parsed())
        self.assertEqual(P.earlier_open([a, b], b), ["A"])
        self.assertEqual(P.earlier_open([a, b], a), [])
        self.assertEqual(P.currency_date("2026-11-10", a), "2026-11-10")
        self.assertEqual(P.currency_date("2025-11-10", a), "2026-01-01")

    def test_register_drops_a_company_back_on_the_list(self):
        reg = [{"name": "Back Co.", "removed_on": "2026-01-01", "aka": []}]
        prop = P.build("x", "addition", [self.DOC], Parsed(adds=[row("Back Co.")]))
        rows, new_reg = P.apply(prop, [row("Stay Co.")], reg)
        self.assertEqual(new_reg, [])
        self.assertIn("Back Co.", [r["name"] for r in rows])


class Page(unittest.TestCase):
    def test_self_contained_escaped_and_stable(self):
        rows = [{"name": "A </script><b>", "aka": ["x"], "parent": "", "source_page": 2, "source_cite": "91 FR 2",
                 "source_url": "https://www.govinfo.gov/p.pdf#page=2"},
                {"name": "B", "aka": [], "parent": "A", "source_page": 2, "source_cite": "91 FR 2",
                 "source_url": "javascript:alert(1)"}]
        reg = [{"name": "C", "removed_on": "2026-11-10", "reason": "court", "cite": "91 FR 72536",
                "source_url": "https://www.federalregister.gov/d/2026-22840"}]
        meta = {"label": "Test list", "as_of": "2026-11-10", "official_url": "https://media.defense.gov/x.pdf"}
        html = page.build(meta, rows, reg, [{"document_number": "1", "sha256": "ab" * 32}])
        self.assertEqual(html, page.build(meta, rows, reg, [{"document_number": "1", "sha256": "ab" * 32}]))
        self.assertNotIn("A </script>", html)
        self.assertNotIn('href="javascript', html)
        self.assertEqual(html.count("<tr"), 2 + 2 + 1)        # two header rows, two rows, one removal
        page.assert_offline(html)
        with self.assertRaises(ValueError):
            page.assert_offline('<img src="https://x">')

    def test_listed_in_is_the_date_of_the_row_s_own_notice(self):
        rows = [{"name": "N", "aka": [], "parent": "", "source_doc": "2026-11571", "date_added": "2026-11-10"}]
        docs = [{"document_number": "2026-11571", "publication_date": "2026-06-10"},
                {"document_number": "2026-22840", "publication_date": "2026-11-10"}]
        html = page.build({"label": "L"}, rows, [], docs)
        self.assertIn("<th><button>Listed in</button></th>", html)
        self.assertIn("<td>2026-06-10</td></tr>", html)


if __name__ == "__main__":
    unittest.main()


class Aliases(unittest.TestCase):
    def test_formerly_and_plain_alias_are_one(self):
        self.assertEqual(P._dedupe(["formerly Old Co. (OC)", "Old Co. (OC)", "Short"]), ["Old Co. (OC)", "Short"])


class NoAlias(unittest.TestCase):
    def test_same_entity_without_alias_keeps_the_list_spelling_only(self):
        doc = {"document_number": "1", "publication_date": "2026-06-10"}
        prop = P.build("x", "annual", [doc], Parsed(roster=[row("Addisino Co., Ltd.")]))
        eq = [("Addisino Co., Ltd.", "Addsino Co., Ltd.")]
        rows, _ = P.apply(prop, [row("Addsino Co., Ltd.")], [], equivalents=eq, no_alias={key("Addisino Co., Ltd.")})
        self.assertEqual((rows[0]["name"], rows[0]["aka"]), ("Addsino Co., Ltd.", []))
        rows, _ = P.apply(prop, [row("Addsino Co., Ltd.")], [], equivalents=eq)
        self.assertEqual(rows[0]["aka"], ["Addisino Co., Ltd."])
