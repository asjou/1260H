"""The proof, offline. Run: python3 -m unittest

- The saved notices still match their fingerprints (SHA-256).
- Re-reading them reproduces the published list, and every row links to its page.
- The classroom example fails until its two checks are decided, then passes; `decide` records them.
- Earlier years' lists are saved, read, and flag "Addisino" against 2025's "Addsino", without AI.
- The AI step stays off unless it is configured AND a person says yes, and code rejects a made-up name.
"""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run
from listwatch import LayoutError, ListwatchError, detect, history, replay, sources
from listwatch.lists import dow_1260h as R
from listwatch.names import key

HERE = Path(__file__).resolve().parent
LIVE = HERE / "data" / "dow-1260h"
EXAMPLE = HERE / "example" / "dow-1260h"
NOTICE = HERE / "example" / "unfamiliar-notice.txt"


@contextlib.contextmanager
def using(folder):
    old, run.DATA = run.DATA, folder
    try:
        yield
    finally:
        run.DATA = old


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = fn(*a)
    return code, out.getvalue()


class LiveList(unittest.TestCase):
    def test_saved_sources_match_their_hashes(self):
        for n in sources.saved(LIVE / "sources"):
            sources.load(LIVE / "sources", n)          # raises on a changed file

    def test_replay_reproduces_the_published_list(self):
        with using(LIVE):
            rep = replay.check(R, LIVE, run._all_docs(), run._store()["entities"], require_key=False)
        self.assertTrue(rep.ok, "\n".join(rep.lines()))

    def test_every_row_links_to_its_page(self):
        with using(LIVE):
            for r in run._store()["entities"]:
                self.assertTrue(r["source_url"].startswith("https://www.govinfo.gov/"), r["name"])
                self.assertTrue(r["source_page"])

    def test_nio_is_listed_and_wuxi_apptec_is_shown_as_removed(self):
        with using(LIVE):
            names = {key(r["name"]) for r in run._store()["entities"]}
            self.assertIn(key("NIO, Inc."), names)
            wuxi = next(e for e in run._register() if key(e["name"]) == key("WuXi AppTec Co., Ltd."))
        self.assertEqual(wuxi["cite"], "91 FR 72536")


class ClassroomExample(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "example" / "dow-1260h"
        shutil.copytree(EXAMPLE, self.data)
        # Test the example as shipped, even after a student has worked through it on this computer.
        props = list((self.data / "proposals").glob("*.json"))
        if any(json.loads(p.read_text())["status"] != "open" for p in props):
            self.skipTest("the example has been approved here; run `git checkout example/` to reset it")
        f = self.data / "replay-exceptions.json"
        exc = json.loads(f.read_text())
        for d in exc["differences"]:
            d.update(resolution=None, note="")
            d.pop("alias", None)
        f.write_text(json.dumps(exc))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_example_fails_on_exactly_the_two_differences(self):
        with using(self.data):
            code, out = quiet(run.cmd_replay)
        self.assertEqual(code, 1)
        unresolved = [l for l in out.splitlines() if "UNRESOLVED" in l]
        self.assertEqual(len(unresolved), 2, out)
        self.assertTrue(any("NIO, Inc." in l and "#page=" in l for l in unresolved), out)
        self.assertTrue(any("Addisino" in l and "Addsino" in l for l in unresolved), out)

    def test_after_the_checks_it_passes_and_approval_adds_nio(self):
        f = self.data / "replay-exceptions.json"
        exc = json.loads(f.read_text())
        for d in exc["differences"]:
            if d["parsed"] and d["parsed"].startswith("NIO"):
                d.update(resolution="add", note="checked the PDF page")
            else:
                d.update(resolution="same entity", alias=False, note="Federal Register typo")
        f.write_text(json.dumps(exc))
        with using(self.data):
            self.assertEqual(quiet(run.cmd_replay)[0], 0)
            pid = next(p["id"] for p in run._proposals() if p["status"] == "open")
            self.assertEqual(quiet(run.cmd_approve, pid)[0], 0)
            names = {r["name"] for r in run._store()["entities"]}
            self.assertIn("NIO, Inc.", names)
            self.assertIn("Addsino Co., Ltd.", names)
            self.assertNotIn("Addisino Co., Ltd", names)
            self.assertTrue(run._register())                  # the removals are recorded

    def test_the_daily_job_is_told_to_hold_while_a_check_is_undecided(self):
        with using(self.data), mock.patch.object(run, "_page_path", return_value=Path(self.tmp.name) / "p.html"):
            code, out = quiet(run.cmd_prepare)
        self.assertEqual(code, 10)
        self.assertIn("do not merge", out)

    def test_approval_is_refused_while_a_check_is_undecided(self):
        with using(self.data):
            pid = next(p["id"] for p in run._proposals() if p["status"] == "open")
            code, out = quiet(run.cmd_approve, pid)
        self.assertEqual(code, 2)
        self.assertIn("replay", out)
        self.assertIn(f"decide --data {self.data}", out)      # the command to type names this folder

    def test_replay_shows_what_to_compare(self):
        with using(self.data):
            _code, out = quiet(run.cmd_replay)
        self.assertIn("DoW list", out)
        self.assertIn("earlier lists print 'Addsino Co., Ltd.': 2025 (90 FR 1105)", out)
        self.assertIn("no earlier list prints 'NIO, Inc.': new in this notice", out)
        self.assertIn("run.py decide --data", out)

    def answers(self, *a):
        it = iter(a)
        return lambda q: next(it)

    def test_decide_records_both_answers_and_the_replay_passes(self):
        ask = self.answers("y", "", "DoW PDF and 2025 list print Addsino.", "a", "Printed at 91 FR 35193.")
        with using(self.data):
            code, out = quiet(run.cmd_decide, ask, False)
        self.assertEqual(code, 0, out)
        self.assertIn("replay: PASS", out)
        exc = {d["parsed"]: d for d in json.loads((self.data / "replay-exceptions.json").read_text())["differences"]}
        self.assertEqual((exc["Addisino Co., Ltd"]["resolution"], exc["Addisino Co., Ltd"]["alias"]), ("same entity", False))
        self.assertEqual(exc["NIO, Inc."]["resolution"], "add")
        self.assertEqual(exc["NIO, Inc."]["note"], "Printed at 91 FR 35193.")

    def test_decide_shows_the_ai_guess_as_a_guess(self):
        ask = self.answers("s", "s")
        with using(self.data), mock.patch.object(run, "_second_opinion", return_value={1: ("typo", "one extra i")}):
            _code, out = quiet(run.cmd_decide, ask, True)
        self.assertIn("AI's guess (a guess, not a source; check it): typo. one extra i", out)

    def test_decide_asks_again_for_an_empty_reason(self):
        ask = self.answers("y", "", "", "   ", "the DoW PDF prints Addsino", "s")
        with using(self.data):
            code, out = quiet(run.cmd_decide, ask, False)
        self.assertEqual(code, 1)
        self.assertIn("A reason is needed", out)

    def test_decide_no_or_skip_leaves_it_undecided(self):
        with using(self.data):
            code, out = quiet(run.cmd_decide, self.answers("n", "s"), False)
        self.assertEqual(code, 1)
        self.assertIn("two different companies", out)
        self.assertEqual(out.count("UNRESOLVED"), 2)


class ReviewPage(unittest.TestCase):
    """The clickable page: same rules as `decide`, this computer only, a secret code per run."""

    def setUp(self):
        import threading
        import review
        ClassroomExample.setUp(self)
        self.pdf = Path(self.tmp.name) / "2026-06-08.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 test")
        self.ctx = using(self.data)
        self.ctx.__enter__()
        self.srv = review.make_server(state=run._state, decide=run._page_decide, advice=run._page_advice,
                                      pdfs=lambda: {"2026-06-08.pdf": self.pdf}, port=0)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.ctx.__exit__(None, None, None)
        self.tmp.cleanup()

    def req(self, path, body=None, token=None, host=None):
        import urllib.error
        import urllib.request
        h = {"Content-Type": "application/json"}
        if token:
            h["X-Review-Token"] = token
        if host:
            h["Host"] = host
        r = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers=h)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_the_page_carries_the_code_and_a_strict_policy(self):
        code, body = self.req("/")
        self.assertEqual(code, 200)
        self.assertIn(self.srv.token.encode(), body)
        self.assertNotIn(b"__TOKEN__", body)

    def test_state_lists_the_two_differences_with_what_to_compare(self):
        s = json.loads(self.req("/state")[1])
        self.assertFalse(s["ok"])
        pair = next(d for d in s["differences"] if d["kind"] == "pair")
        self.assertEqual(pair["store"], "Addsino Co., Ltd.")
        self.assertIn("2026-11571.pdf#page=2", pair["facts"]["fr"])
        self.assertTrue(pair["facts"]["dow"].startswith("https://media.defense.gov/"))

    def test_an_answer_without_the_code_or_from_another_host_is_refused(self):
        body = {"parsed": "NIO, Inc.", "store": None, "choice": "add", "why": "on the DoW PDF"}
        self.assertEqual(self.req("/decide", body)[0], 403)
        self.assertEqual(self.req("/decide", body, token="wrong")[0], 403)
        self.assertEqual(self.req("/decide", body, token=self.srv.token, host="evil.example:80")[0], 403)
        self.assertEqual(self.req("/", host="evil.example")[0], 403)
        self.assertFalse(json.loads(self.req("/state")[1])["ok"])

    def test_same_rules_as_decide_a_reason_and_a_fitting_choice(self):
        t = self.srv.token
        self.assertEqual(self.req("/decide", {"parsed": "NIO, Inc.", "store": None, "choice": "add", "why": "  "}, t)[0], 400)
        self.assertEqual(self.req("/decide", {"parsed": "NIO, Inc.", "store": None, "choice": "keep", "why": "x"}, t)[0], 400)
        self.assertEqual(self.req("/decide", {"parsed": "Invented Ltd.", "store": None, "choice": "add", "why": "x"}, t)[0], 400)

    def test_two_answers_and_the_replay_passes(self):
        t = self.srv.token
        code, _ = self.req("/decide", {"parsed": "Addisino Co., Ltd", "store": "Addsino Co., Ltd.",
                                       "choice": "same entity", "typo": True, "why": "DoW PDF prints Addsino"}, t)
        self.assertEqual(code, 200)
        code, body = self.req("/decide", {"parsed": "NIO, Inc.", "store": None, "choice": "add", "why": "91 FR 35193"}, t)
        self.assertTrue(json.loads(body)["ok"])
        exc = {d["parsed"]: d for d in json.loads((self.data / "replay-exceptions.json").read_text())["differences"]}
        self.assertEqual((exc["Addisino Co., Ltd"]["resolution"], exc["Addisino Co., Ltd"]["alias"]), ("same entity", False))
        with using(self.data):
            self.assertEqual(quiet(run.cmd_replay)[0], 0)

    def test_only_a_listed_pdf_is_served(self):
        code, body = self.req("/pdf/2026-06-08.pdf")
        self.assertEqual((code, body[:5]), (200, b"%PDF-"))
        self.assertEqual(self.req("/pdf/..%2F..%2Freplay-exceptions.json")[0], 404)
        self.assertEqual(self.req("/pdf/../run.py")[0], 404)


class EarlierLists(unittest.TestCase):
    HIST = LIVE / "history"

    def test_saved_earlier_lists_match_their_hashes_and_read_whole(self):
        counts = {h["doc"]: len(h["names"]) for h in history.load(R, self.HIST)}
        self.assertEqual(counts, {"2025-00070": 133, "2024-06895": 77, "2021-13753": 47})

    def test_the_2025_list_prints_addsino_and_its_misprinted_bracket_is_read(self):
        h = next(h for h in history.load(R, self.HIST) if h["doc"] == "2025-00070")
        names = {r["name"] for r in h["names"]}
        self.assertIn("Addsino Co., Ltd.", names)
        self.assertIn("Semiconductor Manufacturing International (Tianjin) Corporation", names)
        self.assertNotIn("ShenZhen Consys Science & Technology Co., Ltd.", names)   # in its removals, not its list

    def test_addisino_is_flagged_against_2025_and_exact_names_are_not(self):
        earlier = history.load(R, self.HIST)
        hit = history.earlier_spellings("Addisino Co., Ltd", earlier)
        self.assertEqual([(e["spelling"], e["date"]) for e in hit], [("Addsino Co., Ltd.", "2025-01-07")])
        self.assertEqual(history.earlier_spellings("Addsino Co., Ltd.", earlier), [])
        self.assertEqual(history.earlier_spellings("NIO, Inc.", earlier), [])

    def test_a_one_company_notice_is_not_a_list(self):
        text = sources.clean((HERE / "tests" / "fixtures" / "listwatch" / "notices" / "2024-24723.txt").read_bytes())
        with self.assertRaises(LayoutError):
            R.earlier_names(text, {"document_number": "2024-24723"})

    def test_the_spelling_command_names_addisino(self):
        with using(LIVE):
            code, out = quiet(run.cmd_spelling)
        self.assertEqual(code, 0)
        self.assertIn("'Addisino Co., Ltd.'", out)
        self.assertIn("2025 printed 'Addsino Co., Ltd.'", out)


class TheAIStep(unittest.TestCase):
    ON = {"LISTWATCH_LLM_URL": "http://127.0.0.1:8082/v1", "LISTWATCH_LLM_MODEL": "local"}

    def test_env_file_comments_are_not_part_of_the_value(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "HERE", Path(d)), mock.patch.dict("os.environ", {}, clear=True):
            (Path(d) / ".env").write_text("LISTWATCH_LLM_URL=http://127.0.0.1:8080/v1   # local\nLISTWATCH_LLM_MODEL='m'\n")
            self.assertEqual(run._settings(), {"LISTWATCH_LLM_URL": "http://127.0.0.1:8080/v1", "LISTWATCH_LLM_MODEL": "m"})

    def test_off_without_settings(self):
        with mock.patch.object(run, "_settings", return_value={}):
            self.assertIsNone(run._reader(interactive=True))

    def test_off_when_no_one_is_at_the_keyboard(self):
        with mock.patch.object(run, "_settings", return_value=self.ON):
            self.assertIsNone(run._reader(interactive=False))

    def test_refuses_plain_http_to_another_computer(self):
        with mock.patch.object(run, "_settings", return_value={**self.ON, "LISTWATCH_LLM_URL": "http://example.com/v1"}):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(run._reader(interactive=True))

    def test_it_asks_first_and_no_means_nothing_is_sent(self):
        with mock.patch.object(run, "_settings", return_value=self.ON), \
             mock.patch("urllib.request.urlopen") as net:
            read = run._reader(ask=lambda q: "n", interactive=True)
            with self.assertRaises(RuntimeError):
                read("text", {"document_number": "x"})
            net.assert_not_called()

    PAIR = [{"parsed": "Addisino Co., Ltd", "store": "Addsino Co., Ltd.", "earlier": []}]

    def test_second_opinion_is_off_without_settings_or_a_person(self):
        with mock.patch.object(run, "_settings", return_value={}):
            self.assertEqual(run._second_opinion(self.PAIR, lambda q: "y", True), {})
        with mock.patch.object(run, "_settings", return_value=self.ON):
            self.assertEqual(run._second_opinion(self.PAIR, lambda q: "y", False), {})

    def test_second_opinion_asks_first_and_no_sends_nothing(self):
        with mock.patch.object(run, "_settings", return_value=self.ON), mock.patch.object(run, "_chat") as chat:
            self.assertEqual(run._second_opinion(self.PAIR, lambda q: "n", True), {})
            chat.assert_not_called()

    def test_second_opinion_is_one_call_and_bad_answers_are_dropped(self):
        reply = [{"n": 1, "guess": "typo", "why": "one extra letter"}, {"n": 7, "guess": "typo"}, {"n": 1, "guess": "made up"}]
        with mock.patch.object(run, "_settings", return_value=self.ON), \
             mock.patch.object(run, "_chat", return_value=reply) as chat:
            self.assertEqual(run._second_opinion(self.PAIR, lambda q: "y", True), {1: ("typo", "one extra letter")})
            self.assertEqual(chat.call_count, 1)

    def test_the_rules_do_not_read_the_unfamiliar_notice_so_it_goes_to_a_person(self):
        with mock.patch.object(run, "_settings", return_value={}):
            code, out = quiet(run.cmd_read, str(NOTICE))
        self.assertEqual(code, 1)
        self.assertIn("needs human reading", out)

    def test_code_rejects_a_made_up_name_and_accepts_a_real_one(self):
        text = sources.clean(NOTICE.read_bytes())
        doc = json.loads(NOTICE.with_suffix(".json").read_text())
        with self.assertRaises(ListwatchError):
            detect.fallback(lambda t, d: {"kind": "addition", "names": ["Invented Holdings Ltd."]}, text, doc, [], R)
        parsed, kind = detect.fallback(lambda t, d: {"kind": "addition", "names": ["Example Harbor Robotics Co., Ltd."]},
                                       text, doc, [], R)
        self.assertEqual((kind, parsed.adds[0]["name"]), ("addition", "Example Harbor Robotics Co., Ltd."))


if __name__ == "__main__":
    unittest.main()
