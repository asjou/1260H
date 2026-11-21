"""The proof, offline. Run: python -m unittest

- The saved notices still match their fingerprints (SHA-256).
- Re-reading them reproduces the published list, and every row links to its page.
- The classroom example fails until its two checks are decided, then passes.
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
from listwatch import ListwatchError, detect, replay, sources
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

    def test_the_weekly_job_is_told_to_hold_while_a_check_is_undecided(self):
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
