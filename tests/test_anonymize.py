"""Tests for tools/anonymize.py, on synthetic data only.

Run:
    python -m unittest tests.test_anonymize        (from the repository root)
    python tests/test_anonymize.py
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import anonymize as an  # noqa: E402

# Synthetic top-down "camera": 20 px per metre, court origin at pixel (60, 40).
# With the 1 m margin the court area is x 40..202, y 20..328 in a 260 x 400 image.
H_FLAT = np.array([[20, 0, 60], [0, 20, 40], [0, 0, 1]], float)


def noise(h=400, w=260, seed=1):
    return np.random.default_rng(seed).integers(0, 256, (h, w, 3), dtype=np.uint8)


def changed(a, b):
    """Per-pixel bool: any channel differs."""
    return (a != b).any(axis=2)


def mean_diff(a, b, sl):
    return float(np.abs(a[sl].astype(int) - b[sl].astype(int)).mean())


class PrivacyCore(unittest.TestCase):
    def test_court_polygon_is_court_plus_margin(self):
        poly = an.court_polygon(H_FLAT)
        np.testing.assert_array_equal(poly, [[40, 20], [202, 20], [202, 328], [40, 328]])
        np.testing.assert_array_equal(an.court_polygon(H_FLAT, margin=0), [[60, 40], [182, 40], [182, 308], [60, 308]])

    def test_court_polygon_rejects_corner_behind_camera(self):
        H = np.array([[1, 0, 0], [0, 1, 0], [0, 0.5, 1]], float)   # w = 1 + 0.5 Y goes negative at Y = -3
        with self.assertRaises(ValueError):
            an.court_polygon(H, margin=4.0)

    def test_outside_changes_inside_stays_without_people(self):
        img = noise()
        out = an.anonymize_frame(img, H_FLAT, [])
        inside = (slice(24, 325), slice(44, 199))
        np.testing.assert_array_equal(out[inside], img[inside])
        for sl in ((slice(0, 400), slice(0, 36)), (slice(0, 400), slice(206, 260)),
                   (slice(0, 16), slice(0, 260)), (slice(332, 400), slice(0, 260))):
            self.assertGreater(mean_diff(out, img, sl), 20, sl)

    def test_head_changes_body_does_not(self):
        img = noise()
        box = (100, 120, 130, 220)                       # inside the court area, 30 x 100
        out = an.anonymize_frame(img, H_FLAT, [box])
        head = (slice(112, 148), slice(98, 132))
        self.assertGreater(mean_diff(out, img, head), 20)
        body = (slice(152, 220), slice(100, 130))        # below the head rectangle
        np.testing.assert_array_equal(out[body], img[body])
        sides = (slice(112, 220), slice(60, 90))         # beside the box, inside the court area
        np.testing.assert_array_equal(out[sides], img[sides])

    def test_head_is_pixelated_in_blocks(self):
        img = noise()
        out = an.anonymize_frame(img, H_FLAT, [(100, 120, 130, 220)])
        x1, y1, x2, y2, block = an.head_region((100, 120, 130, 220), 260, 400)
        self.assertEqual(block, round(100 / an.HEAD_BLOCKS))
        patch = out[y1:y1 + 10, x1:x1 + 10]               # inside the first block: one flat colour
        self.assertEqual(len(np.unique(patch.reshape(-1, 3), axis=0)), 1)
        self.assertGreater(len(np.unique(img[y1:y1 + 10, x1:x1 + 10].reshape(-1, 3), axis=0)), 50)

    def test_keep_box_body_survives_outside_blur_but_head_does_not(self):
        img = noise()
        keep = (180, 120, 230, 220)                      # straddles the right edge of the court area
        out = an.anonymize_frame(img, H_FLAT, [], keep_boxes=[keep])
        body_outside = (slice(160, 215), slice(212, 228))        # outside the polygon, inside the keep box, below the head
        np.testing.assert_array_equal(out[body_outside], img[body_outside])
        self.assertGreater(mean_diff(out, img, (slice(125, 145), slice(212, 228))), 15)   # head of a keep box is hidden
        self.assertGreater(mean_diff(out, img, (slice(160, 215), slice(236, 258))), 20)   # outside the keep box: blurred

    def test_all_changes_are_inside_the_mask(self):
        img = noise()
        boxes = [(100, 120, 130, 220), (60, 200, 90, 290), (230, 100, 255, 180)]
        out, mask = an.anonymize_frame(img, H_FLAT, boxes, keep_boxes=[(180, 120, 230, 220)], return_mask=True)
        self.assertEqual(mask.dtype, bool)
        self.assertFalse(changed(out, img)[~mask].any())
        self.assertGreater(changed(out, img)[mask].mean(), 0.95)

    def test_input_not_modified_and_bad_boxes_ignored(self):
        img = noise()
        before = img.copy()
        ref = an.anonymize_frame(img, H_FLAT, [])
        out = an.anonymize_frame(img, H_FLAT, [(np.nan, 1, 5, 9), (10, 10, 10, 30), (50, 50, 40, 90), (-50, -50, -10, -5)])
        np.testing.assert_array_equal(img, before)
        np.testing.assert_array_equal(out, ref)
        self.assertEqual(out.shape, img.shape)
        self.assertEqual(out.dtype, np.uint8)


class HeadRule(unittest.TestCase):
    def test_default_geometry(self):
        x1, y1, x2, y2, block = an.head_region((100, 120, 130, 220), 260, 400)
        self.assertEqual((x1, x2), (95, 135))             # 15% of 30 px each side
        self.assertEqual((y1, y2), (110, 150))            # 10% above, 30% down
        self.assertEqual(block, 14)                       # 100 / 7

    def test_clipped_to_image(self):
        x1, y1, x2, y2, _ = an.head_region((-20, -10, 30, 90), 260, 400)
        self.assertEqual((x1, y1), (0, 0))
        self.assertIsNone(an.head_region((300, 10, 340, 90), 260, 400))

    def test_cut_off_box_is_hidden_completely(self):
        _, y1, _, y2, _ = an.head_region((40, 292, 508, 713), 1280, 720)   # touches the bottom edge
        self.assertEqual(y2, 713)

    def test_wide_box_is_hidden_to_40_percent_of_width(self):
        _, _, _, y2, _ = an.head_region((50, 100, 150, 140), 260, 400)     # lying person, 100 x 40
        self.assertEqual(y2, 140)
        _, _, _, y2, _ = an.head_region((0, 100, 100, 200), 260, 400)       # 100 x 100: 40 px deep beats 30 px
        self.assertAlmostEqual(y2, 140, delta=1)
        _, _, _, y2, _ = an.head_region((0, 100, 100, 300), 260, 400)       # 100 x 200: 40 px is less than 30% (60 px)
        self.assertAlmostEqual(y2, 160, delta=1)

    def test_tall_box_uses_standing_height(self):
        _, _, _, y2, _ = an.head_region((100, 100, 130, 300), 260, 400, stand_h=100)   # twice a standing person
        self.assertAlmostEqual(y2, 245, delta=1)
        _, _, _, y2, _ = an.head_region((100, 100, 130, 300), 260, 400, stand_h=190)   # normal height: 30% rule
        self.assertAlmostEqual(y2, 160, delta=1)
        _, _, _, y2, _ = an.head_region((100, 100, 130, 300), 260, 400, stand_h=-20)   # above the horizon: model not used
        self.assertAlmostEqual(y2, 160, delta=1)

    def test_standing_height_from_horizon(self):
        # camera looking along the court: horizon is a horizontal line in the image
        H = np.array([[100, 0, 400], [0, 30, 300], [0, 0.002, 1]], float)
        stand = an.standing_height(H)
        a, b, c = np.linalg.inv(H)[2]
        horizon = -c / b
        self.assertAlmostEqual(stand((380, 100, 420, 500)), 500 - horizon, places=3)
        self.assertIsNone(an.standing_height(H_FLAT)((0, 0, 10, 10)))        # no horizon in a top-down view


class Artifacts(unittest.TestCase):
    def test_player_ids_are_discovered_not_hard_coded(self):
        with tempfile.TemporaryDirectory() as d:
            np.savez(Path(d) / "p.npz", frames=np.arange(3), t=np.arange(3) / 30., fps=30.0,
                     Zed_box=np.zeros((3, 5)), Zed_xy=np.zeros((3, 2)), Zed_flag=np.ones(3, np.int8),
                     amy_white_box=np.zeros((3, 5)), amy_white_xy=np.zeros((3, 2)), amy_white_flag=np.ones(3, np.int8))
            z = np.load(Path(d) / "p.npz")
            self.assertEqual(sorted(an.player_ids(z)), ["Zed", "amy_white"])

    def test_default_pose_who(self):
        self.assertEqual(an.default_pose_who(["A_red", "A_White", "B_x"]), "A_White")
        self.assertEqual(an.default_pose_who(["p1", "p2"]), "p1")

    def test_colours_cycle(self):
        c = an.colours_for([f"id{i}" for i in range(10)])
        self.assertEqual(len(c), 10)
        self.assertEqual(c["id0"], c["id8"])

    def test_dets_nearest_sample_and_confidence(self):
        with tempfile.TemporaryDirectory() as d:
            frames = [{"f": 0, "b": [[1, 1, 5, 9, 0.9]]}, {"f": 3, "b": [[2, 2, 6, 9, 0.2], [3, 3, 7, 9, 0.04]]},
                      {"f": 6, "b": [[4, 4, 8, 9, 0.5]]}, {"f": 9, "b": [[5, 5, 9, 9, 0.5]]},
                      {"f": 12, "b": [[6, 6, 9, 9, 0.5]]}]
            (Path(d) / "dets.json").write_text(json.dumps({"frames": frames}))
            dets = an.Dets(Path(d) / "dets.json")
            got = sorted(int(b[0]) for b in dets.boxes(4))            # nearest sample f=3, plus f=0 and f=6
            self.assertEqual(got, [1, 2, 4])                          # the 0.04 box is dropped
            self.assertEqual(sorted(int(b[0]) for b in dets.boxes(4, conf_min=0.0)), [1, 2, 3, 4])
            self.assertEqual(sorted(int(b[0]) for b in dets.boxes(4, spread=0)), [2])
            self.assertEqual(sorted(int(b[0]) for b in dets.boxes(100, spread=0)), [6])

    def test_dets_static_boxes(self):
        with tempfile.TemporaryDirectory() as d:
            frames = [{"f": 3 * i, "b": [[100, 100, 140, 200, 0.9], [10 * i, 300, 10 * i + 40, 380, 0.9]]} for i in range(20)]
            (Path(d) / "dets.json").write_text(json.dumps({"frames": frames}))
            st = an.Dets(Path(d) / "dets.json").static_boxes()
            self.assertEqual(len(st), 1)
            np.testing.assert_allclose(st[0][:4], [100, 100, 140, 200])

    def _players(self, d):
        frames = np.arange(0, 30, 3)
        n = len(frames)
        box = np.full((n, 5), np.nan, np.float32)
        box[:5] = (100, 100, 130, 220, 0.9)               # detected at frames 0..12
        flag = np.zeros(n, np.int8)
        flag[:5] = 1
        flag[5] = 2                                       # frame 15: interpolated, no box
        np.savez(Path(d) / "p.npz", frames=frames, t=frames / 30., fps=30.0, tc=5.0,
                 P1_box=box, P1_flag=flag, P1_xy=np.full((n, 2), 3.0, np.float32))
        return an.Players(Path(d) / "p.npz")

    def test_players_shown_and_privacy_boxes(self):
        with tempfile.TemporaryDirectory() as d:
            pl = self._players(d)
            self.assertEqual(pl.ids, ["P1"])
            self.assertIn("P1", pl.shown(12))                        # detected sample
            self.assertIn("P1", pl.shown(14))                        # 2 frames old, still shown
            self.assertNotIn("P1", pl.shown(16))                     # interpolated sample: not drawn
            self.assertNotIn("P1", pl.shown(35))                     # missing sample: not drawn
            self.assertEqual(pl.shown(-5), {})                       # before the first sample
            self.assertEqual(len(pl.privacy_boxes(9)), 2)            # the samples either side of the frame
            self.assertEqual(len(pl.privacy_boxes(12)), 1)           # the next sample has no box
            self.assertEqual(len(pl.privacy_boxes(-5)), 1)           # only the following one exists

    def test_blur_crop_head_covers_top_28_percent_only(self):
        crop = noise(100, 40, seed=3)
        out, rows = an.blur_crop_head(crop)
        self.assertIn(rows, (28, 29))                                 # 28% of 100 rows, rounded up
        self.assertGreater(mean_diff(out, crop, (slice(0, 28), slice(0, 40))), 20)
        np.testing.assert_array_equal(out[rows:], crop[rows:])

    def test_skeleton_drawn_only_for_confident_joints(self):
        c = np.zeros((100, 100, 3), np.uint8)
        kp = np.zeros((17, 3), np.float32)
        kp[5] = (20, 20, 0.9)
        kp[7] = (20, 60, 0.9)
        kp[9] = (80, 80, 0.2)
        an.draw_skeleton(c, kp)
        self.assertTrue(c[40, 20].any())                              # shoulder-elbow bone
        self.assertFalse(c[80, 80].any())                             # low confidence joint skipped

    def test_pose_crop_box_matches_stage_8(self):
        self.assertEqual(an.pose_crop_box((100, 200, 150, 300), (720, 1280)), (90, 188, 160, 308))

    def test_rally_at(self):
        P = [{"rally": 1, "start": 10, "end": 20}, {"rally": 2, "start": 30, "end": 40}]
        self.assertEqual(an.rally_at(P, 8)["rally"], 1)               # pre-serve window
        self.assertIsNone(an.rally_at(P, 2))
        self.assertEqual(an.rally_at(P, 99)["rally"], 2)
        self.assertIsNone(an.rally_at([], 5))

    def test_tint_marks_only_the_mask(self):
        img = np.full((20, 20, 3), 100, np.uint8)
        mask = np.zeros((20, 20), bool)
        mask[5:10, 5:10] = True
        t = an.tint(img, mask)
        self.assertTrue((t[mask] != 100).any())
        np.testing.assert_array_equal(t[~mask], img[~mask])


class EndToEnd(unittest.TestCase):
    """Whole CLI on a synthetic work folder with made-up player ids."""

    def build_work(self, d):
        W, Hh, n = 1280, 720, 30
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [6.1, 0], [6.1, 13.4], [0, 13.4]]),
                                        np.float32([[250, 700], [1050, 700], [850, 300], [450, 300]]))
        rng = np.random.default_rng(0)
        cv2.imwrite(str(d / "bg_median.png"), rng.integers(0, 256, (Hh, W, 3), dtype=np.uint8))
        (d / "calib.json").write_text(json.dumps({"H_court2img": H.tolist(),
                                                  "points": [{"name": "p", "px": [250, 700], "court": [0, 0]}]}))
        vw = cv2.VideoWriter(str(d / "proxy.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 30, (W, Hh))
        if not vw.isOpened():
            return False
        grad = np.tile(np.linspace(0, 255, W, dtype=np.uint8)[None, :, None], (Hh, 1, 3))
        for i in range(n):
            vw.write(np.roll(grad, i * 5, axis=1))
        vw.release()
        frames = np.arange(0, n, 3)
        k = len(frames)
        arrays = {}
        for j, pid in enumerate(("Rex_blue", "Sam_white")):
            box = np.tile(np.float32([560 + 90 * j, 380, 610 + 90 * j, 520, 0.9]), (k, 1))
            arrays.update({f"{pid}_box": box, f"{pid}_flag": np.ones(k, np.int8),
                           f"{pid}_xy": np.tile(np.float32([2.0 + 2 * j, 4.0]), (k, 1))})
        np.savez(d / "players.npz", frames=frames, t=frames / 30., fps=30.0, stride=3, tc=0.5, **arrays)
        dets = [{"f": int(f), "b": [[560, 380, 610, 520, 0.9], [650, 380, 700, 520, 0.8], [900, 200, 930, 280, 0.3]]}
                for f in frames]
        (d / "dets.json").write_text(json.dumps({"frames": dets}))
        kp = rng.uniform(5, 40, (8, 17, 3)).astype(np.float32)
        kp[:, :, 2] = 0.9
        np.savez(d / "pose_samples.npz", who=np.array(["Sam_white"] * 8), rally=np.ones(8, int),
                 t=frames[:8] / 30., near=np.ones(8, bool), kp=kp)
        (d / "points.json").write_text(json.dumps({"rallies": [{"rally": 1, "start": 0.2, "end": 0.9, "A_after": 1, "B_after": 0}]}))
        return True

    def test_cli_makes_four_images_and_debug_copies(self):
        with tempfile.TemporaryDirectory() as td:
            work, out = Path(td) / "work", Path(td) / "out"
            work.mkdir()
            if not self.build_work(work):
                self.skipTest("this OpenCV build cannot write mp4")
            argv = ["anonymize.py", "--work", str(work), "--out", str(out), "--montage-times", "0.1,0.3,0.5,0.8"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as log:
                an.main()
            self.assertIn("Rex_blue", log.getvalue())                  # ids come from the data
            sizes = {"court_overlay.jpg": (720, 1280), "tracking_sheet.jpg": (720, 1920),
                     "skeleton_strip.jpg": None, "video_montage.jpg": (900, 1600)}
            for name, shape in sizes.items():
                for p in (out / name, out / "debug" / name):
                    img = cv2.imread(str(p))
                    self.assertIsNotNone(img, p)
                    if shape:
                        self.assertEqual(img.shape[:2], shape, p)
            strip = cv2.imread(str(out / "skeleton_strip.jpg"))
            self.assertEqual(strip.shape[1], 8 * 200)

    def test_unknown_pose_id_is_an_error(self):
        with tempfile.TemporaryDirectory() as td:
            work, out = Path(td) / "work", Path(td) / "out"
            work.mkdir()
            if not self.build_work(work):
                self.skipTest("this OpenCV build cannot write mp4")
            argv = ["anonymize.py", "--work", str(work), "--out", str(out), "--pose-who", "nobody"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    an.main()


if __name__ == "__main__":
    unittest.main()
