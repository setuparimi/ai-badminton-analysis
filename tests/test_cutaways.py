"""Title cards (runs of frames with nobody in view) must be told apart from a detector that misses people. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stages"))
from common import cutaway_runs  # noqa: E402

FPS, STRIDE = 30.0, 3


def frames(n):
    return np.arange(0, n * STRIDE, STRIDE)


class Cutaways(unittest.TestCase):
    def test_a_title_card_is_a_cutaway_not_a_miss(self):
        counts = np.full(300, 12)
        counts[100:160] = 0                                  # 60 sampled frames = 6 s
        cut, stray = cutaway_runs(counts, frames(300), FPS)
        self.assertEqual(len(cut), 1)
        self.assertAlmostEqual(cut[0][0], 10.0)
        self.assertAlmostEqual(cut[0][1], 16.0, delta=0.11)
        self.assertEqual(stray, 0.0)

    def test_scattered_empty_frames_are_misses(self):
        counts = np.full(300, 12)
        counts[[10, 50, 51, 120, 200, 201, 202]] = 0         # none lasts 2 s
        cut, stray = cutaway_runs(counts, frames(300), FPS)
        self.assertEqual(cut, [])
        self.assertAlmostEqual(stray, 7 / 300)

    def test_a_card_and_stray_misses_are_counted_separately(self):
        counts = np.full(300, 12)
        counts[100:160] = 0
        counts[[5, 6, 250]] = 0
        cut, stray = cutaway_runs(counts, frames(300), FPS)
        self.assertEqual(len(cut), 1)
        self.assertAlmostEqual(stray, 3 / 300)

    def test_a_card_at_the_very_start_or_end_and_the_two_second_boundary(self):
        counts = np.full(300, 12)
        counts[:25] = 0                                      # 2.5 s at the start
        counts[-19:] = 0                                     # 1.9 s at the end: too short
        cut, stray = cutaway_runs(counts, frames(300), FPS)
        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0][0], 0.0)
        self.assertAlmostEqual(stray, 19 / 300)

    def test_nothing_empty_and_nothing_at_all(self):
        self.assertEqual(cutaway_runs(np.full(50, 4), frames(50), FPS), ([], 0.0))
        self.assertEqual(cutaway_runs([], [], FPS), ([], 0.0))


if __name__ == "__main__":
    unittest.main()
