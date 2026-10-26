"""Checks of the PDF report (stage 13) and the coaching section of report.md, built from the published reference match.
Run: python -m unittest discover -s tests"""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stages"))
import s10_build_report as br  # noqa: E402
import s13_pdf_report as pdf  # noqa: E402

EXAMPLE = ROOT / "examples" / "reference-match"


def make_work(tmp):
    """The reference match's published files, laid out the way the stages leave them in work/."""
    work = Path(tmp) / "work"
    work.mkdir()
    for f in (EXAMPLE / "data").glob("*.json"):
        shutil.copy(f, work / f.name)
    for name in ("players_config.json", "tips.json", "scouting.json"):
        shutil.copy(EXAMPLE / name, work / name)
    shutil.copytree(EXAMPLE / "images", work / "images")
    return work


def pages(path):
    return len(re.findall(rb"/Type\s*/Page[^s]", Path(path).read_bytes()))


class Build(unittest.TestCase):
    def build(self, work, **kw):
        out = work / "report.pdf"
        pdf.build(work, out, kw.get("label", "Test match"), kw.get("page", "A4"), kw.get("photos", False), "1 January 2030")
        return out

    def test_full_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.build(make_work(tmp))
            data = out.read_bytes()
            self.assertTrue(data.startswith(b"%PDF-"))
            self.assertTrue(b"Test match" in data, "the label should be in the PDF title")
            self.assertTrue(8 <= pages(out) <= 18, f"{pages(out)} pages")
            self.assertTrue(b"FontFile2" in data, "fonts should be embedded, not left to the viewer")

    def test_us_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            letter = self.build(work, page="letter").read_bytes()
            a4 = self.build(work, page="A4").read_bytes()
        box = lambda data: re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)", data)
        self.assertTrue(box(letter) is not None and abs(float(box(letter).group(1)) - 612) < 0.5, "letter should be 612 pt wide")
        self.assertTrue(box(a4) is not None and abs(float(box(a4).group(1)) - 595.3) < 0.5, "A4 should be 595 pt wide")

    def test_photos_option_adds_the_pictures(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            plain = self.build(work).stat().st_size
            with_photos = self.build(work, photos=True).stat().st_size
            self.assertGreater(with_photos, plain)

    def test_builds_without_the_assistants_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            (work / "tips.json").unlink()
            (work / "scouting.json").unlink()
            out = self.build(work)
            self.assertTrue(8 <= pages(out) <= 18)

    def test_accents_in_a_name_do_not_break_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            cfg = json.loads((work / "players_config.json").read_text())
            cfg["A_you"]["name"] = "Zoë Łukasz"
            (work / "players_config.json").write_text(json.dumps(cfg))
            self.assertTrue(self.build(work).exists())

    def test_missing_images_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            (work / "images" / "12_opponents.png").unlink()
            with self.assertRaises(SystemExit) as cm:
                self.build(work)
            self.assertIn("12_opponents.png", str(cm.exception))
            self.assertIn("stage 12", str(cm.exception))


class Notes(unittest.TestCase):
    def write(self, tmp, obj):
        p = Path(tmp) / "x.json"
        p.write_text(json.dumps(obj))
        return p

    def test_defaults_and_cleaning(self):
        with tempfile.TemporaryDirectory() as tmp:
            items = pdf.load_items(self.write(tmp, [{"title": " A ", "body": "b", "kind": "strength", "try": "  "}, {"title": "C", "body": "d", "kind": "nonsense"}]), "tips")
        self.assertEqual(items[0], {"title": "A", "body": "b", "kind": "strength"})        # blank 'try' is dropped
        self.assertEqual(items[1]["kind"], "improve")                                       # unknown kind falls back

    def test_bad_notes_stop_with_a_message_that_names_the_field(self):
        bad = {"not a list": {"title": "x"}, "item not an object": ["x"], "no body": [{"title": "x"}], "empty title": [{"title": " ", "body": "b"}],
               "try not text": [{"title": "x", "body": "b", "try": 3}]}
        with tempfile.TemporaryDirectory() as tmp:
            for label, obj in bad.items():
                with self.subTest(label), self.assertRaises(SystemExit) as cm:
                    pdf.load_items(self.write(tmp, obj), "tips")
                self.assertTrue(str(cm.exception))
            with self.assertRaises(SystemExit) as cm:
                pdf.load_items(self.write(tmp, [{"title": "x"}]), "tips")
            self.assertIn("body", str(cm.exception))

    def test_scouting_needs_an_object_and_tolerates_missing_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = pdf.load_scouting(self.write(tmp, {"plan": [{"title": "t", "body": "b"}]}))
            self.assertEqual((len(s["plan"]), s["strengths"], s["weaknesses"]), (1, [], []))
            with self.assertRaises(SystemExit):
                pdf.load_scouting(self.write(tmp, []))

    def test_symbols_arial_may_lack_are_written_out_but_accents_are_kept(self):
        self.assertEqual(pdf.safe("a → b c"), "a -> b c")
        self.assertEqual(pdf.safe("Zoë"), "Zoë")
        self.assertEqual(pdf.esc("<b> & </b>"), "&lt;b&gt; &amp; &lt;/b&gt;")             # nothing a person typed becomes markup


class ReportMarkdown(unittest.TestCase):
    def test_coaching_section_comes_from_the_two_notes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = make_work(tmp)
            md = br.notes_markdown(work)
            self.assertIn("### What to work on", md)
            self.assertIn("### Questions to check on the video", md)
            self.assertIn("### What is working", md)
            self.assertIn("### Game plan to try", md)
            self.assertLess(md.index("What to work on"), md.index("What is working"))
            (work / "tips.json").unlink()
            (work / "scouting.json").unlink()
            self.assertIsNone(br.notes_markdown(work))


if __name__ == "__main__":
    unittest.main()
