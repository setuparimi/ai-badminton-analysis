"""Tests for tools/pick_court_points.py (no browser and no video needed).

Run:
    python -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pick_court_points as pcp  # noqa: E402

SIZE = (1280, 720)


def small_image():
    """A synthetic 1280x720 'photo' (a horizontal gradient)."""
    ramp = np.linspace(30, 220, SIZE[0], dtype=np.uint8)
    return np.repeat(np.repeat(ramp[None, :, None], SIZE[1], axis=0), 3, axis=2)


class Landmarks(unittest.TestCase):
    def test_count_and_uniqueness(self):
        lms = pcp.LANDMARKS
        self.assertEqual(len(lms), 32)  # 6 lines x 5 lines + 2 net posts
        self.assertEqual(len({m["name"] for m in lms}), 32)
        self.assertEqual(len({tuple(m["court"]) for m in lms}), 32)

    def test_every_landmark_is_on_a_painted_line_or_is_a_net_post(self):
        for m in pcp.LANDMARKS:
            x, y = m["court"]
            if y == pcp.s02.NET_Y:
                self.assertIn(x, (0, pcp.s02.W_D), m["name"])
                continue
            on_line = any(
                min(a[0], b[0]) - 1e-9 <= x <= max(a[0], b[0]) + 1e-9
                and min(a[1], b[1]) - 1e-9 <= y <= max(a[1], b[1]) + 1e-9
                and abs((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) < 1e-6
                for a, b in pcp.s02.LINES)
            self.assertTrue(on_line, m["name"])

    def test_names_follow_the_reference_points(self):
        names = {tuple(m["court"]): m["name"] for m in pcp.LANDMARKS}
        for p in pcp.SELFTEST_POINTS:
            self.assertEqual(names[tuple(p["court"])], p["name"])
        self.assertEqual(names[(0.46, 13.4)], "far baseline x left singles sideline")
        self.assertEqual(names[(0, 6.7)], "left net post base")

    def test_lines_in_page_come_from_stage_2(self):
        data = json.loads(re.search(r'id="data">(.*?)</script>', pcp.build_page(small_image()), re.S).group(1))
        self.assertEqual(len(data["lines"]), len(pcp.s02.LINES))
        self.assertEqual(data["net"], [list(p) for p in pcp.s02.NET])
        self.assertEqual((data["width"], data["height"]), SIZE)


class Validation(unittest.TestCase):
    def good(self):
        return json.loads(json.dumps(pcp.SELFTEST_POINTS))

    def test_accepts_the_reference_points(self):
        self.assertEqual(pcp.validate_points(self.good(), SIZE), pcp.SELFTEST_POINTS)

    def test_rejects_bad_input(self):
        def mutated(fn):
            pts = self.good()
            fn(pts)
            return pts
        cases = {
            "not a list": {"px": [1, 2]},
            "too few": self.good()[:3],
            "no name": mutated(lambda p: p[0].update(name="")),
            "px outside the image": mutated(lambda p: p[0].update(px=[1281, 5])),
            "px negative": mutated(lambda p: p[0].update(px=[-1, 5])),
            "px not finite": mutated(lambda p: p[0].update(px=[float("nan"), 5])),
            "px is a string": mutated(lambda p: p[0].update(px=["1", "2"])),
            "px wrong length": mutated(lambda p: p[0].update(px=[1, 2, 3])),
            "unknown court spot": mutated(lambda p: p[0].update(court=[1, 1])),
            "court is a bool": mutated(lambda p: p[0].update(court=[True, False])),
            "duplicate court spot": mutated(lambda p: p[1].update(court=p[0]["court"])),
            "item is not a dict": mutated(lambda p: p.__setitem__(0, "x")),
        }
        for label, payload in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    pcp.validate_points(payload, SIZE)


class Output(unittest.TestCase):
    def test_saved_file_is_what_stage_2_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "nested" / "court_points.json"
            pcp.save_points(out, pcp.SELFTEST_POINTS)
            pts = json.loads(out.read_text())  # same calls as s02_calibrate.main
            self.assertEqual(pts, pcp.SELFTEST_POINTS)
            px = np.array([p["px"] for p in pts], np.float64)
            co = np.array([p["court"] for p in pts], np.float64)
            self.assertEqual((px.shape, co.shape), ((9, 2), (9, 2)))
            self.assertEqual(out.read_text().count("\n"), len(pts) + 2)  # one point per line


class Page(unittest.TestCase):
    def test_page_is_self_contained(self):
        page = pcp.build_page(small_image())
        self.assertIn("data:image/jpeg;base64,", page)
        self.assertNotIn("__DATA__", page)
        self.assertNotIn("__IMAGE__", page)
        self.assertIsNone(pcp.EXTERNAL_RE.search(page))
        self.assertIsNotNone(pcp.EXTERNAL_RE.search('<script src="https://cdn.example/x.js">'))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_page_script_parses(self):
        page = pcp.build_page(small_image())
        js = re.findall(r"<script>\n(.*?)</script>", page, re.S)
        self.assertEqual(len(js), 1)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "page.js"
            f.write_text(js[0])
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


class Command(unittest.TestCase):
    def test_needs_a_source_unless_selftest(self):
        with contextlib.redirect_stderr(io.StringIO()):  # argparse prints its usage message
            with self.assertRaises(SystemExit):
                pcp.parse_args([])
            with self.assertRaises(SystemExit):
                pcp.parse_args(["--video", "a.mp4", "--image", "b.png"])
        self.assertTrue(pcp.parse_args(["--selftest"]).selftest)
        self.assertEqual(pcp.parse_args(["--image", "b.png"]).port, 8765)

    def test_selftest_serves_saves_and_shuts_down(self):
        messages = []
        ok = pcp.selftest(img=small_image(), log=messages.append)
        self.assertTrue(ok, "\n".join(messages))


if __name__ == "__main__":
    unittest.main()
