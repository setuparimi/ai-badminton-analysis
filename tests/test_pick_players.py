"""Checks of the player picker: choosing pictures, reading shirts, validating a choice, and the local server. Run: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pick_players as pp  # noqa: E402

sys.path.insert(0, str(ROOT / "stages"))
import common  # noqa: E402

COLS = ["f", "x1", "y1", "x2", "y2", "conf", "X", "Y", "h_per_ppm", "tL", "ta", "tb", "t_red", "t_white", "t_dark", "t_blue", "t_green", "t_yellow",
        "t_orange", "lL", "la", "lb", "l_red", "l_white", "l_dark", "l_blue", "l_green", "l_yellow", "l_orange"]
# (X, Y, x1, tL, t_red): white tee, red shirt, dark top, grey top
PEOPLE = [(1.0, 2.0, 100, 200, 0.0), (4.0, 2.5, 300, 120, 0.4), (1.5, 10.5, 500, 50, 0.0), (4.5, 11.0, 700, 120, 0.0)]


def write_cand(path, times=(50, 70, 90, 110, 130), people=PEOPLE, fps=30.0):
    rows = []
    for t in times:
        f = int(t * fps) // 3 * 3
        for X, Y, x1, tL, red in people:
            r = dict.fromkeys(COLS, 0.0)
            r.update(f=f, x1=x1, y1=100, x2=x1 + 60, y2=300, conf=0.9, X=X, Y=Y, h_per_ppm=1.8, tL=tL, ta=128, tb=128, t_red=red)
            rows.append([r[c] for c in COLS])
    np.savez_compressed(path, data=np.array(rows, np.float32), cols=np.array(COLS), fps=fps, stride=3)


class Shirts(unittest.TestCase):
    def test_best_shirt_for_each_clothing_type(self):
        feats = lambda tL, red: {"tL": tL, "t_red": red, "t_blue": 0.0, "t_green": 0.0, "t_yellow": 0.0, "t_orange": 0.0}
        self.assertEqual(pp.best_shirt(feats(200, 0.0))[0], "white")
        self.assertEqual(pp.best_shirt(feats(120, 0.4))[0], "red")
        self.assertEqual(pp.best_shirt(feats(50, 0.0))[0], "black")
        self.assertEqual(pp.best_shirt(feats(120, 0.0))[0], "grey")

    def test_swatch_is_an_rgb_triplet(self):
        rgb = pp.swatch_rgb(200, 128, 128)
        self.assertEqual(len(rgb), 3)
        self.assertTrue(all(0 <= v <= 255 for v in rgb))
        self.assertGreater(min(rgb), 150)          # light grey


class Frames(unittest.TestCase):
    def test_picks_spread_out_pictures_with_all_four_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "cand.npz"
            write_cand(cand)
            frames = pp.choose_frames(cand, start=40.0)
        self.assertGreaterEqual(len(frames), 3)
        ts = sorted(f["t"] for f in frames)
        self.assertTrue(all(b - a >= pp.MIN_GAP_S for a, b in zip(ts, ts[1:])))
        first = frames[0]
        self.assertEqual(len(first["boxes"]), 4)
        self.assertEqual([b["x1"] for b in first["boxes"]], sorted(b["x1"] for b in first["boxes"]))
        self.assertEqual([b["shirt"] for b in first["boxes"]], ["white", "red", "black", "grey"])
        self.assertEqual([b["id"] for b in first["boxes"]], [0, 1, 2, 3])

    def test_a_time_puts_the_nearest_picture_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "cand.npz"
            write_cand(cand)
            frames = pp.choose_frames(cand, start=40.0, at_time=112.0)
        self.assertAlmostEqual(frames[0]["t"], 110.0, delta=0.5)

    def test_nothing_found_when_fewer_than_four_people(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "cand.npz"
            write_cand(cand, people=PEOPLE[:3])
            self.assertEqual(pp.choose_frames(cand, start=40.0), [])


def box(i, half, shirt="white", score=0.9, tL=120.0, sL=None, X=1.0, Y=2.0, f=300):
    return {"id": i, "x1": 100.0 + 90 * i, "y1": 80.0, "x2": 160.0 + 90 * i, "y2": 300.0, "shirt": shirt, "score": score, "rgb": [1, 2, 3], "tL": tL, "sL": sL,
            "half": half, "X": X, "Y": Y}


def frame_of(boxes):
    return {"f": 300, "t": 10.0, "w": 640, "h": 360, "img": "data:,", "boxes": boxes}


class Cues(unittest.TestCase):
    def test_clearly_different_shirts_come_first(self):
        ca, cb, how = pp.team_cues(box(0, "near", "white", 0.9, 200, 80), box(1, "near", "red", 0.9, 90, 10))
        self.assertEqual((ca, cb), ({"shirt": "white"}, {"shirt": "red"}))
        self.assertIn("shirt colour", how)

    def test_shorts_when_the_shirts_look_alike(self):
        ca, cb, how = pp.team_cues(box(0, "near", "black", 0.95, 20, 85), box(1, "near", "black", 0.95, 22, 10))
        self.assertEqual((ca["shorts"], cb["shorts"]), ("white", "dark"))
        self.assertEqual((ca["shirt"], cb["shirt"]), ("any", "any"))
        self.assertIn("shorts", how)

    def test_shade_when_one_colour_and_no_shorts_signal(self):
        ca, cb, how = pp.team_cues(box(0, "near", "grey", 0.9, 150, None), box(1, "near", "grey", 0.9, 100, None))
        self.assertEqual((ca["tone"], cb["tone"]), ("light", "dark"))
        self.assertEqual(ca["tone_split"], 125.0)

    def test_nothing_when_they_look_the_same(self):
        self.assertIsNone(pp.team_cues(box(0, "near", "black", 0.9, 20, 12), box(1, "near", "black", 0.9, 22, 10)))

    def test_a_weak_colour_guess_is_used_last_and_says_so(self):
        ca, cb, how = pp.team_cues(box(0, "near", "blue", 0.6, 60, None), box(1, "near", "black", 0.6, 30, None))
        self.assertIn("only roughly", how)


class Roles(unittest.TestCase):
    four = frame_of([box(0, "far", X=1.0, Y=10.0), box(1, "far", X=4.0, Y=10.0), box(2, "near", X=1.0), box(3, "near", X=4.0)])

    def test_partner_and_opponents_follow_from_the_click(self):
        self.assertEqual(pp.auto_roles(self.four, 3), {"A_you": 3, "A_partner": 2, "B_opp1": 0, "B_opp2": 1})
        self.assertEqual(pp.auto_roles(self.four, 0), {"A_you": 0, "A_partner": 1, "B_opp1": 2, "B_opp2": 3})

    def test_a_third_person_on_one_half_is_refused_with_advice(self):
        fr = frame_of(self.four["boxes"] + [box(4, "near", X=5.0)])
        with self.assertRaisesRegex(ValueError, "Another picture"):
            pp.auto_roles(fr, 3)

    def test_singles_finds_the_one_opponent(self):
        fr = frame_of([box(0, "far", Y=10.0), box(1, "near")])
        self.assertEqual(pp.auto_roles(fr, 1, "singles"), {"A_you": 1, "B_opp1": 0})
        with self.assertRaises(ValueError):
            pp.auto_roles(self.four, 3, "singles")

    def test_unknown_box(self):
        with self.assertRaises(ValueError):
            pp.auto_roles(self.four, 9)


class Config(unittest.TestCase):
    fr = pp.synthetic_frames()[0]
    roles = {"A_you": 0, "A_partner": 1, "B_opp1": 2, "B_opp2": 3}

    def test_doubles_config_has_match_hand_and_cues(self):
        cfg, msg = pp.build_config(self.fr, self.roles, "doubles", "left", " Sam ")
        self.assertEqual(cfg["_match"], {"mode": "doubles", "hand": "left", "seen": {"t": 10.0, "you_half": "near", "you_xy": [1.0, 3.0], "partner_xy": [2.0, 3.0]}})
        self.assertEqual([cfg[s]["shirt"] for s in common.SLOTS], ["red", "white", "black", "blue"])
        self.assertEqual(cfg["A_you"]["name"], "Sam")
        self.assertIn("told apart", msg)

    def test_the_hand_is_required(self):
        for h in (None, "both", ""):
            with self.assertRaises(ValueError):
                pp.build_config(self.fr, self.roles, "doubles", h)

    def test_opponents_that_look_alike_become_a_pair(self):
        fr = pp.synthetic_frames()[0]
        for b in fr["boxes"][2:]:
            b.update(shirt="black", tL=30.0, sL=12.0)
        cfg, msg = pp.build_config(fr, self.roles, "doubles", "right")
        self.assertEqual((cfg["B_opp1"]["shirt"], cfg["B_opp2"]["shirt"]), ("any", "any"))
        self.assertIn("as a pair", msg)
        self.assertTrue(common.load_config(self._write(cfg))["_match"]["opponents_indistinct"])

    def test_opponents_in_black_and_grey_are_tracked_as_a_pair_but_a_bright_shirt_is_followed(self):
        fr = pp.synthetic_frames()[0]
        fr["boxes"][2].update(shirt="black", score=0.95, tL=30.0, sL=10.0)
        fr["boxes"][3].update(shirt="grey", score=0.95, tL=120.0, sL=12.0)
        cfg, msg = pp.build_config(fr, self.roles, "doubles", "right")
        self.assertEqual((cfg["B_opp1"]["shirt"], cfg["B_opp2"]["shirt"]), ("any", "any"))
        self.assertIn("as a pair", msg)
        fr["boxes"][3].update(shirt="blue", score=0.95)
        cfg, msg = pp.build_config(fr, self.roles, "doubles", "right")
        self.assertEqual((cfg["B_opp1"]["shirt"], cfg["B_opp2"]["shirt"]), ("black", "blue"))

    def test_teammates_that_look_alike_are_refused(self):
        fr = pp.synthetic_frames()[0]
        fr["boxes"][1].update(shirt="white", tL=200.0, sL=70.0)
        with self.assertRaisesRegex(ValueError, "cannot be told apart"):
            pp.build_config(fr, self.roles, "doubles", "right")

    def test_wrong_halves_are_refused(self):
        with self.assertRaises(ValueError):
            pp.build_config(self.fr, {"A_you": 0, "A_partner": 2, "B_opp1": 1, "B_opp2": 3}, "doubles", "right")

    def test_singles_config_loads_with_two_active_slots(self):
        fr = frame_of([box(0, "far", "black", 0.9, 30, 10, Y=10.0), box(1, "near", "white", 0.9, 200, 80)])
        cfg, _ = pp.build_config(fr, {"A_you": 1, "B_opp1": 0}, "singles", "left")
        self.assertEqual(set(cfg) - {"_match"}, {"A_you", "B_opp1"})
        loaded = common.load_config(self._write(cfg))
        self.assertEqual(common.active_slots(loaded), ["A_you", "B_opp1"])
        self.assertEqual(common.match_mode(loaded), "singles")
        self.assertTrue(loaded["A_partner"]["inactive"])

    def test_bad_input_is_refused(self):
        for roles in ([], {"A_you": 0}, dict(self.roles, B_opp2=0), dict(self.roles, B_opp2=9), dict(self.roles, B_opp2="3"), dict(self.roles, B_opp2=True)):
            with self.subTest(roles), self.assertRaises(ValueError):
                pp.build_config(self.fr, roles, "doubles", "left")

    def test_name_is_cleaned_and_limited(self):
        cfg, _ = pp.build_config(self.fr, self.roles, "doubles", "left", "  A\x00B\n" + "x" * 80)
        self.assertNotIn("\x00", cfg["A_you"]["name"])
        self.assertLessEqual(len(cfg["A_you"]["name"]), 40)
        self.assertNotIn("name", pp.build_config(self.fr, self.roles, "doubles", "left", "   ")[0]["A_you"])

    def _write(self, cfg):
        f = Path(tempfile.mkdtemp()) / "c.json"
        f.write_text(json.dumps(cfg))
        return f


class WideBoxes(unittest.TestCase):
    def test_a_wide_box_says_nothing_about_shorts(self):
        f = {"sL": 161.0, "tL": 20.0, "lL": 0.0, "l_white": 0.0, "l_dark": 0.0, "wide": True}
        self.assertEqual(float(common.shorts_score("dark", f)), 0.5)
        self.assertEqual(float(common.shorts_score("white", dict(f, wide=False))), float(common.shorts_score("white", {"sL": 161.0})))

    def test_boxes_at_the_edge_of_the_picture_or_arms_out_are_unreliable(self):
        self.assertTrue(bool(common.shorts_unreliable(100, 100, 220, 300, 720)))        # wide: 120 of 200
        self.assertTrue(bool(common.shorts_unreliable(100, 400, 160, 719, 720)))        # cut off at the bottom
        self.assertTrue(bool(common.shorts_unreliable(100, 0, 160, 300, 720)))          # cut off at the top
        self.assertFalse(bool(common.shorts_unreliable(100, 100, 160, 300, 720)))

    def test_no_shorts_cue_is_proposed_from_a_wide_box(self):
        a = box(0, "near", "black", 0.9, 20.0, 161.0)
        a["wide"] = True
        b = box(1, "near", "black", 0.9, 20.0, 10.0)
        self.assertEqual([k for k, *_ in pp.proposals(a, b)], [])
        a["wide"] = False
        self.assertIn("shorts", [k for k, *_ in pp.proposals(a, b)])

    def test_only_slim_moments_set_the_shorts_reading(self):
        feats = [{"tL": 20.0, "t_red": 0.0, "t_blue": 0.0, "t_green": 0.0, "t_yellow": 0.0, "t_orange": 0.0, "lL": 0.0, "l_white": 0.0, "l_dark": 0.0, "sL": v, "wide": w}
                 for v, w in ((10.0, False), (12.0, False), (11.0, False), (160.0, True), (170.0, True))]
        self.assertEqual(pp.smooth_box(box(0, "near", "black", 0.9, 20.0, 160.0), feats)["sL"], 11.0)


class Crossing(unittest.TestCase):
    """Two teammates walk past each other in the seconds around the picture, so the position-following can swap them. Who is who still follows the click."""

    def ctx(self, n=300):
        cols = ["f", "x1", "y1", "x2", "y2", "conf", "X", "Y", "tL", "t_red", "t_blue", "t_green", "t_yellow", "t_orange", "lL", "l_white", "l_dark", "sL", "h_per_ppm"]
        rows = []
        for k in range(n):
            for X, sl in ((1.0 + 0.015 * k, 85.0), (4.0 - 0.015 * k, 12.0)):
                rows.append(dict(f=3 * k, x1=(100 + 10 * k) if sl > 50 else (900 - 10 * k), y1=100, x2=((160 + 10 * k) if sl > 50 else (960 - 10 * k)), y2=300, conf=0.9, X=X, Y=3.0, tL=20.0, t_red=0.0, t_blue=0.0, t_green=0.0, t_yellow=0.0,
                                 t_orange=0.0, lL=100.0, l_white=0.0, l_dark=0.0, sL=sl, h_per_ppm=1.8))
        c = {k: np.array([r[k] for r in rows], float) for k in cols}
        by_f = {}
        for i in range(len(rows)):
            by_f.setdefault(int(c["f"][i]), []).append(i)
        return {"c": c, "fps": 30.0, "stride": 3, "by_f": by_f}

    def test_the_cue_points_the_way_you_clicked_whatever_the_followed_tracks_do(self):
        ctx = self.ctx()
        for k in (60, 80, 90, 120, 130, 150, 200):                # click moments before, around and after the crossing (at step 100)
            f0 = 3 * k
            a = box(0, "near", "black", 0.9, 20.0, 85.0, X=1.0 + 0.015 * k, Y=3.0, f=f0)      # you: the light-shorts person
            b = box(1, "near", "black", 0.9, 20.0, 12.0, X=4.0 - 0.015 * k, Y=3.0, f=f0)
            pairs = pp.seed_pairs(ctx, f0, a, b)
            self.assertTrue(all(len(p) == 3 for p in pairs))
            got = pp.team_cues(a, b, pairs)
            if got is None:
                continue                                         # a crossing right at the click may make the cue unusable; it must never be inverted
            self.assertEqual((got[0]["shorts"], got[1]["shorts"]), ("white", "dark"), f"click at step {k}")

    def test_pairs_carry_their_distance_from_the_click(self):
        ctx = self.ctx()
        a = box(0, "near", "black", 0.9, 20.0, 85.0, X=1.0 + 0.015 * 40, Y=3.0, f=120)
        b = box(1, "near", "black", 0.9, 20.0, 12.0, X=4.0 - 0.015 * 40, Y=3.0, f=120)
        steps = sorted({p[2] for p in pp.seed_pairs(ctx, 120, a, b)})
        self.assertEqual(steps[0], 1)
        self.assertLessEqual(steps[-1], 60)


class Seeds(unittest.TestCase):
    """Two teammates who walk about for twenty seconds; one wears light shorts, one dark. The picker follows them and checks the cue."""

    def make(self, tmp, alike=False):
        cols = COLS + ["sL"]
        rows = []
        for k in range(200):
            f = 1500 + 3 * k
            for X, Y, x1, tL, sL in ((1.0 + 0.01 * k, 2.0, 100, 30.0, 85.0), (4.0 - 0.01 * k, 2.5, 300, 30.0, 12.0 if not alike else 85.0),
                                     (1.5, 10.5, 500, 50.0, 14.0), (4.5, 11.0, 700, 120.0, 15.0)):
                r = dict.fromkeys(cols, 0.0)
                r.update(f=f, x1=x1, y1=100, x2=x1 + 60, y2=300, conf=0.9, X=X, Y=Y, h_per_ppm=1.8, tL=tL, ta=128, tb=128, sL=sL)
                rows.append([r[c] for c in cols])
        p = Path(tmp) / "cand.npz"
        np.savez_compressed(p, data=np.array(rows, np.float32), cols=np.array(cols), fps=30.0, stride=3)
        return p

    def test_follow_and_choose_shorts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = self.make(tmp)
            ctx = pp.build_ctx(cand, 40.0)
            frames = pp.choose_frames(cand, 40.0)
            fr = frames[0]
            near = sorted((b for b in fr["boxes"] if b["half"] == "near"), key=lambda b: b["x1"])
            pairs = pp.seed_pairs(ctx, fr["f"], near[0], near[1])
            self.assertGreater(len(pairs), 40)
            ca, cb, how = pp.team_cues(near[0], near[1], pairs)
            self.assertEqual((ca["shorts"], cb["shorts"]), ("white", "dark"))
            self.assertIn("100%", how)

    def test_the_cue_is_refused_when_the_two_look_alike_all_along(self):
        with tempfile.TemporaryDirectory() as tmp:
            cand = self.make(tmp, alike=True)
            ctx = pp.build_ctx(cand, 40.0)
            fr = pp.choose_frames(cand, 40.0)[0]
            near = sorted((b for b in fr["boxes"] if b["half"] == "near"), key=lambda b: b["x1"])
            self.assertIsNone(pp.team_cues(near[0], near[1], pp.seed_pairs(ctx, fr["f"], near[0], near[1])))


class Server(unittest.TestCase):
    def test_selftest_passes(self):
        lines = []
        self.assertTrue(pp.selftest(log=lines.append), "\n".join(lines))

    def test_page_is_self_contained_and_escapes_script_end(self):
        frames = pp.synthetic_frames()
        frames[0]["boxes"][0]["shirt"] = "</script><b>"
        page = pp.build_page(frames)
        self.assertNotIn("</script><b>", page)
        self.assertIsNone(pp.EXTERNAL_RE.search(page))


if __name__ == "__main__":
    unittest.main()


class Ranking(unittest.TestCase):
    def test_pictures_with_four_distinct_confident_colours_come_first(self):
        # two moments: at 50 s two people look alike (two whites), at 90 s all four colours differ
        with tempfile.TemporaryDirectory() as tmp:
            cand = Path(tmp) / "cand.npz"
            same = [(X, Y, x1, 200 if k < 2 else tL, red) for k, (X, Y, x1, tL, red) in enumerate(PEOPLE)]
            rows = []
            for t, people in ((50, same), (90, PEOPLE)):
                f = int(t * 30) // 3 * 3
                for X, Y, x1, tL, red in people:
                    r = dict.fromkeys(COLS, 0.0)
                    r.update(f=f, x1=x1, y1=100, x2=x1 + 60, y2=300, conf=0.9, X=X, Y=Y, h_per_ppm=1.8, tL=tL, ta=128, tb=128, t_red=0.0 if tL == 200 else red)
                    rows.append([r[c] for c in COLS])
            np.savez_compressed(cand, data=np.array(rows, np.float32), cols=np.array(COLS), fps=30.0, stride=3)
            frames = pp.choose_frames(cand, start=40.0)
        self.assertEqual(frames[0]["t"], 90.0)
        self.assertEqual([b["half"] for b in frames[0]["boxes"]], ["near", "near", "far", "far"])
