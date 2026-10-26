"""Checks of the stages for a video with no score on screen (6f, 7f, 14) and of the tracker options added for wide-angle videos.
Everything is built from small synthetic data, so no video is needed.
Run: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "stages"))
import s03_players as s03  # noqa: E402
import s06f_play_windows as pw  # noqa: E402
import s07f_free_stats as fs  # noqa: E402
import s14_free_report as rep  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from common import SLOTS, load_config  # noqa: E402


class Windows(unittest.TestCase):
    def test_otsu_splits_two_groups(self):
        rng = np.random.default_rng(1)
        v = np.r_[rng.normal(0, 0.3, 500), rng.normal(3, 0.3, 500)]
        self.assertTrue(1.0 < pw.otsu(v) < 2.0)

    def test_hits_are_found_in_noise(self):
        sr = 22050
        rng = np.random.default_rng(2)
        x = rng.normal(0, 0.01, sr * 20).astype(np.float32)
        at = [3.0, 3.8, 4.6, 11.0, 11.7]
        for a in at:
            i = int(a * sr)
            x[i:i + 200] += (rng.normal(0, 0.6, 200) * np.hanning(200)).astype(np.float32)
        found = pw.hit_times(x, sr)
        self.assertEqual(len(found), len(at))
        self.assertTrue(np.allclose(sorted(found), at, atol=0.05))

    def test_detects_alternating_play_and_rest(self):
        dt = 0.1
        t = np.arange(0, 120, dt)
        play = (t % 15) < 7                                    # 7 s of play every 15 s: eight plays
        act = np.where(play, 2.0, 0.1) + np.random.default_rng(3).normal(0, 0.05, len(t))
        hits = np.array([x for x in np.arange(0, 120, 0.1) if (x % 15) < 7 and int(x * 10) % 9 == 0])
        wins, info = pw.detect(t, act, hits, dt)
        self.assertEqual(len(wins), 8)
        self.assertTrue(info["audio_used"])
        for a, b in wins:
            self.assertTrue(5.5 < b - a < 8.5)

    def test_without_sound_movement_alone_is_used(self):
        dt = 0.1
        t = np.arange(0, 60, dt)
        act = np.where((t % 20) < 8, 2.0, 0.1) + np.random.default_rng(4).normal(0, 0.05, len(t))
        wins, info = pw.detect(t, act, None, dt)
        self.assertFalse(info["audio_used"])
        self.assertEqual(len(wins), 3)


class Stats(unittest.TestCase):
    def test_smooth_nan_skips_gaps(self):
        x = np.array([1.0, 1.0, np.nan, 1.0, 1.0, 1.0])
        self.assertTrue(np.allclose(fs.smooth_nan(x, 3)[[0, 1, 3, 4]], 1.0))

    def test_zones_add_up(self):
        u = np.array([0.5, 3.0, 5.5, 3.0])
        d = np.array([1.0, 3.0, 6.0, np.nan])
        z = fs.zone_shares(u, d)
        self.assertAlmostEqual(sum(z["depth"].values()), 1.0)
        self.assertAlmostEqual(sum(z["width"].values()), 1.0)
        self.assertAlmostEqual(z["depth"]["front"], 1 / 3)

    def test_formation_classes(self):
        n = 100
        play = np.ones(n, bool)
        same = np.full(n, 3.0)
        f = fs.formation(np.full(n, 1.0), same, np.full(n, 5.0), same + 0.5, play)
        self.assertEqual(f["side_by_side"], 1.0)
        f = fs.formation(np.full(n, 3.0), np.full(n, 5.5), np.full(n, 3.0), np.full(n, 1.5), play)
        self.assertEqual(f["front_back"], 1.0)
        self.assertEqual(f["first_at_back_when_front_back"], 1.0)

    def test_swaps_ignore_blips(self):
        seq = np.array([0] * 20 + [1] * 2 + [0] * 20 + [1] * 20)
        self.assertEqual(fs._held_swaps(seq, 5), 1)

    def test_distance_of_a_walker(self):
        dt = 0.1
        n = 600
        t = np.arange(n) * dt
        xy = np.stack([np.full(n, 3.0), 6.0 - t * 1.0], 1)       # walks towards the net at 1 m/s for a minute
        s = fs.player_stats(xy, np.ones(n, bool), dt, 10)
        self.assertAlmostEqual(s["distance_m"], 59.0, delta=2.0)
        self.assertAlmostEqual(s["speed_median_mps"], 1.0, delta=0.05)
        self.assertEqual(s["bursts_per_play_min"], 0.0)


def fake_game(n=1200, seed=0):
    """players.npz contents for 2 minutes at 10 samples a second: your pair near, one deep and one at the net."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) * 0.1 + 10
    z = {"frames": (t * 30).astype(int), "t": t, "fps": np.float64(30.0), "stride": np.int64(3), "tc": np.float64(1e9), "first_near": np.array("A")}
    base = {"A_you": (2.0, 3.0), "A_partner": (4.0, 3.2), "B_opp1": (2.5, 10.0), "B_opp2": (3.8, 10.2)}
    for k in SLOTS:
        x0, y0 = base[k]
        z[f"{k}_xy"] = np.c_[x0 + rng.normal(0, 0.4, n).cumsum() * 0.02 + 0.3 * np.sin(t / 3), y0 + 0.3 * np.cos(t / 4) + rng.normal(0, 0.05, n)]
        z[f"{k}_flag"] = np.ones(n, np.int8)
        z[f"{k}_box"] = np.full((n, 5), np.nan, np.float32)
    return z


class EndToEnd(unittest.TestCase):
    def test_stats_and_pdf_from_synthetic_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            W = Path(tmp)
            for g in ("g1", "g2"):
                (W / g).mkdir()
                z = fake_game(seed=1 if g == "g1" else 2)
                np.savez(W / g / "players.npz", **z)
                windows = [{"start": 12 + 15 * i, "end": 19 + 15 * i, "dur": 7.0} for i in range(7)]
                (W / g / "play_windows.json").write_text(json.dumps({"windows": windows}))
                st = fs.analyse(np.load(W / g / "players.npz", allow_pickle=True), windows)
                (W / g / "free_stats.json").write_text(json.dumps(st))
                self.assertEqual(st["plays"]["n"], 7)
                self.assertEqual(st["slots"]["A_you"]["side"], "near")
                self.assertEqual(st["slots"]["B_opp1"]["side"], "far")
            (W / "games.json").write_text(json.dumps({"label": "Test match", "racket_hand": "left", "games": [
                {"dir": "g1", "title": "Game 1", "card": "21-19"}, {"dir": "g2", "title": "Game 2"}]}))
            (W / "tips.json").write_text(json.dumps([{"title": "A tip", "body": "Some words.", "kind": "improve"}]))
            (W / "scouting.json").write_text(json.dumps({"strengths": [], "weaknesses": [{"title": "W", "body": "x"}], "plan": []}))
            out = W / "report.pdf"
            cfg = rep.build(W, out, "A4", "1 January 2030")
            self.assertTrue(out.stat().st_size > 20000)
            self.assertEqual(cfg["games"][0]["card_n"], 40)
            self.assertIsNone(cfg["games"][1]["card_n"])
            for name in ("01_heatmaps.png", "02_formation.png", "03_movement.png", "04_pace.png"):
                self.assertTrue((W / "images_free" / name).exists(), name)

    def test_missing_stats_stop_with_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            W = Path(tmp)
            (W / "games.json").write_text(json.dumps({"label": "x", "games": [{"dir": "g1", "title": "Game 1"}]}))
            with self.assertRaises(SystemExit):
                rep.load(W)


class TrackerOptions(unittest.TestCase):
    def cand(self, tmp, heights):
        cols = ["f", "x1", "y1", "x2", "y2", "conf", "X", "Y", "h_per_ppm", "tL"]
        rows = [[3 * i, 100, 100, 160, 300, 0.9, 3.0, 3.0, h, 20.0] for i, h in enumerate(heights)]
        p = Path(tmp) / "cand.npz"
        np.savez(p, data=np.array(rows, float), cols=np.array(cols), fps=30.0, stride=3)
        return p

    def test_height_window_is_adjustable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self.cand(tmp, [2.0, 3.0, 3.6])
            c, _, _ = s03.load_candidates(p, 0, 0.25)
            self.assertEqual(len(c["f"]), 1)                                  # default window 1.25 to 2.5
            c, _, _ = s03.load_candidates(p, 0, 0.25, height_ratio=(1.4, 3.8))
            self.assertEqual(len(c["f"]), 3)

    def test_clothes_gate_leaves_the_slot_empty(self):
        cfg = {"A_you": {"shirt": "any", "shorts": "white"}, "A_partner": {"shirt": "any", "shorts": "dark"},
               "B_opp1": {"shirt": "blue"}, "B_opp2": {"shirt": "black"}}
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "c.json"
            f.write_text(json.dumps(cfg))
            cfg = load_config(f)
        n = 10
        c = {k: np.zeros(n) for k in ("x1", "y1", "x2", "y2", "conf", "X", "Y", "tL", "t_red", "t_blue", "t_green", "t_yellow", "t_orange", "lL", "l_white", "l_dark", "sL")}
        c["f"] = np.arange(n) * 3.0
        c["conf"][:] = 0.9
        c["X"][:] = 3.0
        c["Y"][:] = 3.0
        c["x1"][:], c["x2"][:], c["y1"][:], c["y2"][:] = 100, 160, 100, 300      # a whole person in the middle of the picture
        c["sL"][:] = 90.0                     # bright shorts: this is "you", never the partner
        c["lL"][:] = 150.0
        frames, pos, _ = s03.track(c, 30.0, 3, 1e9, "A", 0.0, cfg, min_appearance=0.1)
        self.assertTrue(np.isnan(pos["A_partner"]).all())
        self.assertFalse(np.isnan(pos["A_you"]).all())


def write_cfg(tmp, doc):
    f = Path(tmp) / "players_config.json"
    f.write_text(json.dumps(doc))
    return f


DOUBLES_SHORTS = {"_match": {"mode": "doubles", "hand": "left"},
                  "A_you": {"shirt": "any", "shorts": "white", "describe": "dark top, light shorts"},
                  "A_partner": {"shirt": "any", "shorts": "dark", "describe": "dark top, dark shorts"},
                  "B_opp1": {"shirt": "blue", "describe": "blue top"}, "B_opp2": {"shirt": "black", "describe": "dark top"}}


class Modes(unittest.TestCase):
    def test_singles_has_two_active_slots_and_two_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(write_cfg(tmp, {"_match": {"mode": "singles", "hand": "right"}, "A_you": {"shirt": "red"}, "B_opp1": {"shirt": "any"}}))
        import common
        self.assertEqual(common.active_slots(cfg), ["A_you", "B_opp1"])
        self.assertEqual(common.match_mode(cfg), "singles")
        self.assertEqual(common.slot_probs(cfg, {"tL": 100.0, "t_red": 0.5, "t_blue": 0, "t_green": 0, "t_yellow": 0, "t_orange": 0})["A_partner"], 0.0)

    def test_opponents_that_look_alike_are_allowed_but_teammates_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = dict(DOUBLES_SHORTS, B_opp1={"shirt": "any"}, B_opp2={"shirt": "any"})
            self.assertTrue(load_config(write_cfg(tmp, doc))["_match"]["opponents_indistinct"])
            doc = dict(DOUBLES_SHORTS, A_you={"shirt": "any", "shorts": "dark"})
            with self.assertRaises(SystemExit):
                load_config(write_cfg(tmp, doc))

    def test_the_hand_must_be_left_or_right(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                load_config(write_cfg(tmp, dict(DOUBLES_SHORTS, _match={"mode": "doubles", "hand": "both"})))
            with self.assertRaises(SystemExit):
                load_config(write_cfg(tmp, dict(DOUBLES_SHORTS, _match={"mode": "triples"})))


def cand_arrays(n=600, fps=30.0, you_near_first=True, swap_at=None):
    """candidates for 20 seconds: one person in light shorts (A_you's cue), one in dark, and two opponents in dark shorts"""
    rng = np.random.default_rng(5)
    cols = {k: [] for k in ("f", "x1", "y1", "x2", "y2", "conf", "X", "Y", "tL", "t_red", "t_blue", "t_green", "t_yellow", "t_orange", "lL", "l_white", "l_dark", "sL", "h_per_ppm")}
    for k in range(n):
        f = 3 * k
        t = f / fps
        you_near = you_near_first if swap_at is None or t < swap_at else not you_near_first
        spec = [(1.5, 80.0, True), (4.0, 10.0, True), (1.5, 12.0, False), (4.0, 14.0, False)]
        for X, sl, mine in spec:
            near = mine == you_near
            Y = 3.0 if near else 10.0
            for key, v in (("f", f), ("x1", 100), ("y1", 100), ("x2", 160), ("y2", 300), ("conf", 0.9), ("X", X + rng.normal(0, 0.02)), ("Y", Y), ("tL", 20.0),
                           ("t_red", 0.0), ("t_blue", 0.0), ("t_green", 0.0), ("t_yellow", 0.0), ("t_orange", 0.0), ("lL", 100.0), ("l_white", 0.0), ("l_dark", 0.0),
                           ("sL", sl + rng.normal(0, 3)), ("h_per_ppm", 1.8)):
                cols[key].append(v)
    return {k: np.array(v, float) for k, v in cols.items()}, fps


class TrackerCues(unittest.TestCase):
    def cfg(self):
        with tempfile.TemporaryDirectory() as tmp:                 # opponents alike, so the only distinctive clothes are yours
            return load_config(write_cfg(tmp, dict(DOUBLES_SHORTS, B_opp1={"shirt": "any"}, B_opp2={"shirt": "any"})))

    def test_the_clothes_say_which_end_you_start_at(self):
        c, fps = cand_arrays(you_near_first=False)
        team, mask = s03.signature_mask(c, self.cfg())
        self.assertEqual(team, "A")
        side, share = s03.early_side(c, fps, 0.0, team, mask)
        self.assertEqual(side, "B")                        # team A (you) is on the far half, so team B starts near
        self.assertGreater(share, 0.9)

    def test_a_swap_in_the_middle_is_found(self):
        c, fps = cand_arrays(n=1500, you_near_first=True, swap_at=75.0)
        team, mask = s03.signature_mask(c, self.cfg())
        tc, first_near, strength = s03.find_end_change(c, fps, 0.0, team, mask)
        self.assertAlmostEqual(tc, 75.0, delta=4.0)
        self.assertEqual(first_near, "A")
        self.assertGreater(strength, 0.5)

    def test_no_swap_is_reported_as_none(self):
        c, fps = cand_arrays(n=1500)
        team, mask = s03.signature_mask(c, self.cfg())
        tc, first_near, strength = s03.find_end_change(c, fps, 0.0, team, mask)
        self.assertEqual(tc, common_no_change())
        self.assertEqual(first_near, "A")

    def test_nothing_distinctive_means_no_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_config(write_cfg(tmp, {"_match": {"mode": "singles", "hand": "left"}, "A_you": {"shirt": "any"}, "B_opp1": {"shirt": "any"}}))
        c, _ = cand_arrays(n=50)
        self.assertEqual(s03.signature_mask(c, cfg), (None, None))

    def test_the_size_window_follows_the_lens(self):
        for ratio, expect in ((1.8, (1.25, 2.5)), (2.45, (1.35, 3.8))):
            rows = [[3 * i, 100, 100, 160, 300, 0.9, 3.0, 3.0, ratio] for i in range(400)]
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "c.npz"
                np.savez(p, data=np.array(rows, float), cols=np.array(["f", "x1", "y1", "x2", "y2", "conf", "X", "Y", "h_per_ppm"]), fps=30.0, stride=3)
                self.assertEqual(s03.estimate_height_window(p), expect)

    def test_an_unbroken_track_keeps_its_label_when_the_clothes_misread_for_a_moment(self):
        cfg = self.cfg()
        n = 12
        keys = ("x1", "y1", "x2", "y2", "conf", "X", "Y", "tL", "t_red", "t_blue", "t_green", "t_yellow", "t_orange", "lL", "l_white", "l_dark", "sL")
        c = {k: np.zeros(2 * n) for k in keys}
        c["f"] = np.repeat(np.arange(n) * 3.0, 2)
        c["conf"][:] = 0.9
        c["x1"][:], c["x2"][:], c["y1"][:], c["y2"][:] = 100, 160, 100, 300      # a whole person in the middle of the picture
        c["X"][0::2] = np.linspace(2.0, 2.3, n)                 # you, walking slowly
        c["X"][1::2] = 4.5                                      # your partner, standing still
        c["Y"][:] = 3.0
        c["sL"][0::2] = 80.0
        c["sL"][1::2] = 10.0
        c["sL"][10:16:2] = 12.0                # three samples in which your light shorts read dark
        frames, pos, _ = s03.track(c, 30.0, 3, 1e9, "A", 0.0, cfg, min_appearance=0.1)
        self.assertFalse(np.isnan(pos["A_you"]).any(), "the track of you has a hole")
        self.assertTrue((pos["A_partner"][~np.isnan(pos["A_partner"][:, 0]), 0] > 4.0).all(), "your track was given to your partner")


def common_no_change():
    import common
    return common.NO_CHANGE


class Singles(unittest.TestCase):
    def test_singles_stats_and_pdf(self):
        import common
        with tempfile.TemporaryDirectory() as tmp:
            W = Path(tmp)
            cfg = load_config(write_cfg(W, {"_match": {"mode": "singles", "hand": "right"}, "A_you": {"shirt": "red", "describe": "red top"},
                                            "B_opp1": {"shirt": "black", "describe": "dark top"}}))
            (W / "g1").mkdir()
            z = fake_game()
            for k in ("A_partner", "B_opp2"):
                z[f"{k}_xy"] = np.full_like(z[f"{k}_xy"], np.nan)
                z[f"{k}_flag"] = np.zeros_like(z[f"{k}_flag"])
            np.savez(W / "g1" / "players.npz", **z)
            windows = [{"start": 12 + 15 * i, "end": 19 + 15 * i, "dur": 7.0} for i in range(7)]
            (W / "g1" / "play_windows.json").write_text(json.dumps({"windows": windows}))
            st = fs.analyse(np.load(W / "g1" / "players.npz", allow_pickle=True), windows, cfg)
            (W / "g1" / "free_stats.json").write_text(json.dumps(st))
            self.assertEqual(st["mode"], "singles")
            self.assertEqual(set(st["slots"]), {"A_you", "B_opp1"})
            self.assertEqual(st["teams"], {})
            (W / "games.json").write_text(json.dumps({"label": "Singles test", "mode": "singles", "racket_hand": "right", "games": [{"dir": "g1", "title": "Game 1"}]}))
            from s14a_free_words import build_words
            c14 = rep.load(W)
            tips, scout = build_words(c14)
            self.assertIsInstance(tips, list)
            self.assertEqual(set(scout), {"strengths", "weaknesses", "plan"})
            out = W / "r.pdf"
            rep.build(W, out, "A4", "1 January 2030")
            self.assertTrue(out.stat().st_size > 20000)
            self.assertFalse((W / "images_free" / "02_formation.png").exists())


class Words(unittest.TestCase):
    def test_doubles_words_say_where_they_come_from_and_stay_off_winning(self):
        from s14a_free_words import build_words
        with tempfile.TemporaryDirectory() as tmp:
            W = Path(tmp)
            (W / "g1").mkdir()
            z = fake_game()
            np.savez(W / "g1" / "players.npz", **z)
            windows = [{"start": 12 + 15 * i, "end": 19 + 15 * i, "dur": 7.0} for i in range(7)]
            (W / "g1" / "play_windows.json").write_text(json.dumps({"windows": windows}))
            (W / "g1" / "free_stats.json").write_text(json.dumps(fs.analyse(np.load(W / "g1" / "players.npz", allow_pickle=True), windows)))
            (W / "games.json").write_text(json.dumps({"label": "T", "games": [{"dir": "g1", "title": "Game 1"}], "racket_hand": "left"}))
            tips, scout = build_words(rep.load(W))
        text = json.dumps([tips, scout]).lower()
        for banned in ("you won", "you lost", "won the point", "lost the point", "winner"):
            self.assertNotIn(banned, text)
        for t in tips:
            self.assertIn(t["kind"], ("improve", "check", "strength"))
            self.assertTrue(t.get("sure"), t["title"])


class CheckSheet(unittest.TestCase):
    def test_moments_are_spread_and_pairs_that_stand_close_are_found(self):
        import check_tracking as ct
        z = fake_game()
        z["A_partner_xy"] = z["A_you_xy"] + 0.4                       # always 0.4 m apart
        for k in SLOTS:
            z[f"{k}_box"] = np.tile(np.array([100, 100, 160, 300, 0.9], np.float32), (len(z["t"]), 1))
        idx, present = ct.pick_moments(z)
        self.assertEqual(set(present), set(SLOTS))
        self.assertGreaterEqual(len(idx), 6)
        self.assertTrue(all(0 <= i < len(z["t"]) for i in idx))


if __name__ == "__main__":
    unittest.main()
