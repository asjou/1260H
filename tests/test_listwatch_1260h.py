"""The § 1260H rules against the real Federal Register notices saved in tests/fixtures/listwatch
(plan 2026-11-20-001, U2). No network."""
import json
import tempfile
import unittest
from pathlib import Path

from listwatch import LayoutError, replay, sources
from listwatch.detect import classify
from listwatch.lists import dow_1260h as R
from listwatch.names import key, parse_entry, split_companies

FIX = Path(__file__).parent / "fixtures" / "listwatch"
DOCS = {d["document_number"]: d for d in json.loads((FIX / "fr-search-1260h.json").read_text())["results"]}


def text(n):
    return sources.clean((FIX / "notices" / f"{n}.txt").read_bytes())


def annual():
    return R.parse("annual", text("2026-11571"), DOCS["2026-11571"], [])


class Names(unittest.TestCase):
    def test_split_keeps_corporate_suffixes_and_parentheses(self):
        self.assertEqual(
            split_companies("A Co., Ltd., B Co., Ltd. (Bee), C (Group) Co., Ltd., and D Inc."),
            ["A Co., Ltd.", "B Co., Ltd. (Bee)", "C (Group) Co., Ltd.", "D Inc."])

    def test_two_single_words_are_one_name(self):
        self.assertEqual(split_companies("Better Way Limited, SMIC, Americas"), ["Better Way Limited", "SMIC, Americas"])

    def test_entry_reads_short_names_and_formerly(self):
        self.assertEqual(parse_entry("AVIC Chengdu Aircraft Co., Ltd. (formerly Zhonghang Co. (ZEMIC))"),
                         ("AVIC Chengdu Aircraft Co., Ltd.", ["Zhonghang Co. (ZEMIC)"]))
        self.assertEqual(parse_entry("China Communications Construction Group (Limited) (CCCG)"),
                         ("China Communications Construction Group (Limited)", ["CCCG"]))


class Classify(unittest.TestCase):
    def test_the_four_title_forms(self):
        self.assertEqual(classify(DOCS["2026-11571"], R), "annual")
        self.assertEqual(classify(DOCS["2026-22840"], R), "removal")
        self.assertEqual(classify(DOCS["2024-24723"], R), "addition")
        self.assertEqual(classify(DOCS["2024-25167"], R), "mixed")

    def test_rule_is_no_change_and_unknown_notice_is_unreadable(self):
        self.assertEqual(classify({"type": "Rule", "title": "DFARS: Section 1260H companies"}, R), "no_change")
        self.assertEqual(classify({"type": "Notice", "title": "Defense Federal Acquisition Regulation Supplement"}, R),
                         "no_change")
        self.assertEqual(classify({"type": "Notice", "title": "Update to the 1260H list"}, R), "unreadable")


class Annual2026(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = annual()
        cls.by = {key(r["name"]): r for r in cls.p.roster}

    def test_counts(self):
        self.assertEqual(len(self.p.roster), 188)          # 187 + WuXi AppTec, before its removal
        self.assertEqual(len(self.p.register), 10)         # the "previously listed" removals

    def test_header_cut_by_a_page_marker_is_joined(self):
        avic = [r for r in self.p.roster if r.get("parent") == "Aviation Industry Corporation of China, Ltd."]
        self.assertIn("Shenyang Aircraft Design Institute", [r["name"] for r in avic])
        self.assertEqual(len(avic), 17)          # counted by hand in 91 FR 35189-90

    def test_reason_cut_by_a_page_marker_is_not_a_row(self):
        for r in self.p.roster:
            self.assertNotIn("1260H(", r["name"])
            self.assertFalse(r["name"].lower().startswith("it received"))

    def test_missing_blank_line_between_reason_and_next_company(self):
        for name in ("China COSCO SHIPPING Corporation Limited", "CETC Potevio Science & Technology Co., Ltd.",
                     "China United Network Communications Group Co., Ltd."):
            self.assertIn(key(name), self.by)

    def test_four_space_entry_is_listed_under_the_one_above(self):
        self.assertEqual(self.by[key("Autel Robotics Co., Ltd.")]["parent"], "Autel Intelligent Technology Corp., Ltd.")

    def test_full_stop_typed_for_a_comma_and_the_comac_erratum(self):
        self.assertIn(key("Kiekert USA Inc."), self.by)
        self.assertIn(key("COMAC America Corporation"), self.by)
        self.assertIn(key("Shanghai Aircraft Design and Research Institute"), self.by)

    def test_every_row_has_provenance_with_the_right_pdf_page(self):
        for r in self.p.roster:
            self.assertEqual(r["source_doc"], "2026-11571")
            self.assertTrue(35189 <= r["source_page"] <= 35194)
            self.assertTrue(r["source_url"].startswith("https://www.govinfo.gov/content/pkg/FR-2026-06-10/pdf/2026-11571.pdf#page="))
            self.assertEqual(r["source_url"].rsplit("=", 1)[1], str(r["source_page"] - 35189 + 1))
        nio = self.by[key("NIO, Inc.")]
        self.assertEqual((nio["source_page"], nio["source_cite"]), (35193, "91 FR 35193"))

    def test_register_reads_the_removals_section(self):
        names = {key(e["name"]) for e in self.p.register}
        self.assertIn(key("Taiji Computer Co., Ltd."), names)
        self.assertTrue(all(e["removed_on"] == "2026-06-10" for e in self.p.register))


class Amendments(unittest.TestCase):
    def test_wuxi_removal_with_reason(self):
        p = R.parse("removal", text("2026-22840"), DOCS["2026-22840"], annual().roster)
        self.assertEqual([r["name"] for r in p.removes], ["WuXi AppTec Co., Ltd."])
        self.assertIn("District Court", p.removes[0]["reason"])
        self.assertEqual(p.removes[0]["cite"], "91 FR 72536")
        self.assertEqual(p.leftover, "")

    def test_two_companies_on_one_comma_line(self):
        cur = [{"name": "IDG Capital Partners Co., Ltd.", "aka": []},
               {"name": "Advanced Micro-Fabrication Equipment Inc. China", "aka": ["AMEC"]},
               {"name": "Other Co.", "aka": []}]
        p = R.parse("removal", text("2024-30018"), DOCS["2024-30018"], cur)
        self.assertEqual(sorted(r["name"] for r in p.removes), sorted(n["name"] for n in cur[:2]))
        self.assertEqual(p.leftover, "")

    def test_removal_of_a_company_not_on_the_list_leaves_text_over(self):
        p = R.parse("removal", text("2024-30018"), DOCS["2024-30018"], [{"name": "IDG Capital Partners Co., Ltd.", "aka": []}])
        self.assertIn("Advanced Micro-Fabrication", p.leftover)

    def test_addition(self):
        p = R.parse("addition", text("2024-24723"), DOCS["2024-24723"], [])
        self.assertEqual([(r["name"], r["aka"]) for r in p.adds], [("Hesai Technology Co., Ltd.", ["Hesai"])])

    def test_correction_notice_goes_to_a_human(self):
        with self.assertRaises(LayoutError):
            R.parse("mixed", text("2024-25167"), DOCS["2024-25167"], [])


class OtherLayouts(unittest.TestCase):
    """The earlier annual notices use a flat list with no reasons. The rules refuse them loudly
    instead of guessing (structure check only; no rows are loaded)."""

    def test_2024_and_2025_annual_layouts_are_refused(self):
        for n in ("2024-06895", "2025-00070"):
            with self.subTest(n), self.assertRaises(LayoutError):
                R.parse("annual", text(n), DOCS[n], [])


class Replay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        for n in ("2026-11571", "2026-22840"):
            sources.save(self.folder / "sources", n, DOCS[n]["raw_text_url"],
                         (FIX / "notices" / f"{n}.txt").read_bytes(), "2026-11-20T00:00:00+00:00")
        self.docs = [DOCS["2026-11571"], DOCS["2026-22840"]]

    def tearDown(self):
        self.tmp.cleanup()

    def _checked_key(self, rows):
        k = replay.draft_answer_key(rows)
        for e in k["entries"]:
            e["checked"] = True
        (self.folder / "answer-key.json").write_text(json.dumps(k))

    def test_replay_matches_a_list_built_from_itself(self):
        rows, register, _ = replay.rebuild(R, self.folder, self.docs)
        self.assertEqual(len(rows), 187)
        self.assertIn(key("WuXi AppTec Co., Ltd."), {key(e["name"]) for e in register})
        self.assertTrue(replay.check(R, self.folder, self.docs, rows).key_missing)   # no key yet: fails
        self._checked_key(rows)
        self.assertTrue(replay.check(R, self.folder, self.docs, rows).ok)

    def test_unresolved_difference_fails_and_resolution_passes(self):
        rows, _, _ = replay.rebuild(R, self.folder, self.docs)
        current = [r for r in rows if key(r["name"]) != key("NIO, Inc.")]
        current = [dict(r, name="Addsino Co., Ltd.") if key(r["name"]) == key("Addisino Co., Ltd") else r for r in current]
        rep = replay.check(R, self.folder, self.docs, current)
        self.assertFalse(rep.ok)
        self.assertEqual(len(rep.differences), 3)
        self._checked_key(rows)
        (self.folder / "replay-exceptions.json").write_text(json.dumps({"differences": [
            {"parsed": "Addisino Co., Ltd", "store": "Addsino Co., Ltd.", "resolution": "same entity"},
            {"parsed": "NIO, Inc.", "store": None, "resolution": "add"}]}))
        self.assertTrue(replay.check(R, self.folder, self.docs, current).ok)

    def test_without_the_key_gate_an_undecided_pair_is_reported_once_with_its_page(self):
        rows, _, _ = replay.rebuild(R, self.folder, self.docs)
        current = [r for r in rows if key(r["name"]) != key("NIO, Inc.")]
        current = [dict(r, name="Addsino Co., Ltd.") if key(r["name"]) == key("Addisino Co., Ltd") else r for r in current]
        (self.folder / "replay-exceptions.json").write_text(json.dumps({"differences": [
            {"parsed": "Addisino Co., Ltd", "store": "Addsino Co., Ltd.", "resolution": None},
            {"parsed": "NIO, Inc.", "store": None, "resolution": None}]}))
        rep = replay.check(R, self.folder, self.docs, current, require_key=False)
        self.assertEqual(len(rep.differences), 2)                  # the pair is one difference
        lines = [l for l in rep.lines() if "UNRESOLVED" in l]
        self.assertTrue(all("#page=" in l for l in lines), lines)
        self.assertNotIn("ANSWER KEY", "\n".join(rep.lines()))
        self.assertTrue(replay.check(R, self.folder, self.docs, rows, require_key=False).ok)

    def test_answer_key_catches_a_wrong_parent_and_unchecked_entries_fail(self):
        rows, _, _ = replay.rebuild(R, self.folder, self.docs)
        k = replay.draft_answer_key(rows)
        self.assertGreater(len(k["entries"]), 20)
        (self.folder / "answer-key.json").write_text(json.dumps(k))
        self.assertFalse(replay.check(R, self.folder, self.docs, rows).ok)          # unchecked
        for e in k["entries"]:
            e["checked"] = True
        (self.folder / "answer-key.json").write_text(json.dumps(k))
        self.assertTrue(replay.check(R, self.folder, self.docs, rows).ok)
        group = next(e for e in k["entries"] if "subsidiaries" in e)
        group["subsidiaries"] = group["subsidiaries"][1:]
        (self.folder / "answer-key.json").write_text(json.dumps(k))
        rep = replay.check(R, self.folder, self.docs, rows)
        self.assertEqual(len(rep.key_mismatches), 1)

    def test_tampered_source_is_refused(self):
        p = self.folder / "sources" / "2026-22840.txt"
        p.write_bytes(p.read_bytes() + b" ")
        with self.assertRaises(sources.SourceError):
            replay.rebuild(R, self.folder, self.docs)


if __name__ == "__main__":
    unittest.main()
