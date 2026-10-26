"""Checks of the guided run (tools/analyze.py): reading the answers, the plan of commands, and the first-game-side rule.
No video is needed: the run is checked with --dry-run, which prints the commands and runs nothing.
Run: python -m unittest discover -s tests"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "stages"))
import analyze as an  # noqa: E402
import common  # noqa: E402


class Reading(unittest.TestCase):
    def test_times(self):
        self.assertEqual(an.parse_time("0:08"), 8.0)
        self.assertEqual(an.parse_time("10:25"), 625.0)
        self.assertEqual(an.parse_time("1:02:03"), 3723.0)
        self.assertEqual(an.parse_time("65.5"), 65.5)
        for bad in ("", "abc", "1:2:3:4", "-5", "1::2"):
            with self.subTest(bad), self.assertRaises(ValueError):
                an.parse_time(bad)

    def test_games(self):
        self.assertEqual(an.parse_games("0:08-10:25, 10:34-19:04", 1200), [(8.0, 625.0), (634.0, 1144.0)])
        self.assertEqual(an.parse_games("", 900), [(0.0, 900)])
        self.assertEqual(an.parse_games("0:10-5:00,6:00-", 900), [(10.0, 300.0), (360.0, 900)])
        for bad in ("0:08", "5:00-4:00", "0:10-0:20", "0:00-5:00,4:00-9:00", "a-b"):
            with self.subTest(bad), self.assertRaises(ValueError):
                an.parse_games(bad, 1200)

    def test_cards(self):
        self.assertEqual(an.parse_cards("21-19, 21-13", 2), ["21-19", "21-13"])
        self.assertEqual(an.parse_cards("21 – 19", 1), ["21-19"])
        self.assertEqual(an.parse_cards("", 3), [None, None, None])
        for bad in ("21-19", "21-19,21-13,5", "x-y"):
            with self.subTest(bad), self.assertRaises(ValueError):
                an.parse_cards(bad, 2)

    def test_slug(self):
        self.assertEqual(an.slug("Saturday doubles!"), "saturday_doubles")
        self.assertEqual(an.slug("???"), "match")

    def test_teams_swap_ends_between_games(self):
        # you were on the near half in the picture of game 1
        self.assertEqual([an.first_near_for(i, 0, "near") for i in range(3)], ["A", "B", "A"])
        # you were on the far half in the picture
        self.assertEqual([an.first_near_for(i, 0, "far") for i in range(3)], ["B", "A", "B"])
        # the picture came from game 2
        self.assertEqual([an.first_near_for(i, 1, "near") for i in range(3)], ["B", "A", "B"])

    def test_which_game_a_second_belongs_to(self):
        games = [(8.0, 625.0), (634.0, 1144.0)]
        self.assertEqual([an.game_of(t, games) for t in (9, 624, 700, 5000)], [0, 0, 1, 0])


class Answers(unittest.TestCase):
    def args(self, *flags):
        return an.parse_args(list(flags))

    def test_missing_answers_without_a_keyboard_are_named(self):
        with self.assertRaises(SystemExit) as cm:
            an.gather(self.args("--video", "m.mp4"), {}, interactive=False)
        self.assertIn("--mode", str(cm.exception))
        self.assertIn("--hand", str(cm.exception))

    def test_flags_are_enough_and_score_defaults_to_no(self):
        ans = an.gather(self.args("--video", "/x/match one.mp4", "--mode", "singles", "--hand", "left"), {}, interactive=False)
        self.assertEqual((ans["mode"], ans["hand"], ans["score"], ans["label"]), ("singles", "left", False, "match one"))

    def test_saved_answers_are_reused_and_flags_win(self):
        saved = {"video": "a.mp4", "label": "Old", "mode": "doubles", "hand": "right", "score": False}
        ans = an.gather(self.args("--hand", "left"), saved, interactive=False)
        self.assertEqual((ans["label"], ans["hand"]), ("Old", "left"))


def dry(*flags):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        an.main(list(flags) + ["--dry-run"])
    return [ln for ln in buf.getvalue().splitlines() if ln.startswith("WOULD RUN")], buf.getvalue()


class Plan(unittest.TestCase):
    base = ("--video", "/tmp/some match.mp4", "--label", "Test", "--mode", "doubles", "--hand", "left", "--games", "0:08-10:25,10:34-19:04", "--cards", "21-19,21-13")

    def test_the_commands_run_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, _ = dry(*self.base, "--work", tmp)
        names = [re.search(r"([A-Za-z0-9_]+\.py)", ln).group(1) for ln in lines]
        self.assertEqual(names[:6], ["s00_proxy.py", "s01_detect.py", "pick_court_points.py", "s02_calibrate.py", "s03_features.py", "pick_players.py"])
        self.assertEqual(names[6:10], ["s03_players.py", "s06f_play_windows.py", "s07f_free_stats.py", "s08_pose.py"])
        self.assertEqual(names.count("s03_players.py"), 2)

    def test_each_game_gets_its_own_window_side_and_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, _ = dry(*self.base, "--work", tmp)
        tracks = [ln for ln in lines if "s03_players.py" in ln]
        self.assertIn("--start 8.0 --end 625.0", tracks[0])
        self.assertIn("--first-near A", tracks[0])
        self.assertIn("--start 634.0 --end 1144.0", tracks[1])
        self.assertIn("--first-near B", tracks[1])
        for ln in tracks:
            self.assertIn("--end-change auto", ln)
        plays = [ln for ln in lines if "s06f_play_windows.py" in ln]
        self.assertIn("--expect 40", plays[0])
        self.assertIn("--expect 34", plays[1])
        self.assertIn("--audio-from /tmp/some match.mp4", plays[0])

    def test_the_picker_is_told_the_mode_and_hand(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, _ = dry(*self.base, "--work", tmp)
        pick = [ln for ln in lines if "pick_players.py" in ln][0]
        self.assertIn("--mode doubles --hand left", pick)
        self.assertIn("--start 8.0", pick)

    def test_no_pose_skips_that_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, _ = dry(*self.base, "--work", tmp, "--no-pose")
        self.assertFalse([ln for ln in lines if "s08_pose.py" in ln])

    def test_a_live_score_in_doubles_uses_the_scoreboard_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, _ = dry("--video", "/tmp/m.mp4", "--mode", "doubles", "--hand", "right", "--score", "yes", "--work", tmp)
        self.assertEqual(len(lines), 1)
        self.assertIn("run_all.sh", lines[0])

    def test_singles_with_a_live_score_falls_back_to_the_free_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines, out = dry("--video", "/tmp/m.mp4", "--mode", "singles", "--hand", "right", "--score", "yes", "--work", tmp)
        self.assertIn("only built for doubles", out)
        self.assertTrue([ln for ln in lines if "s03_players.py" in ln])

    def test_a_missing_file_stops_a_real_run_early(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit) as cm:
            an.main(["--video", str(Path(tmp) / "nope.mp4"), "--mode", "doubles", "--hand", "left", "--work", str(Path(tmp) / "w")])
        self.assertIn("cannot find the video", str(cm.exception))

    def test_answers_are_saved_for_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            dry(*self.base, "--work", tmp)
            saved = json.loads((Path(tmp) / "match.json").read_text())
        self.assertEqual((saved["mode"], saved["hand"], saved["cards"]), ("doubles", "left", "21-19,21-13"))


class Resuming(unittest.TestCase):
    def test_waiting_for_a_step_that_was_skipped_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            R = an.Runner(Path(tmp))
            R.wait("finding the people", None)
            R.wait("finding the people", 0)

    def test_a_failed_step_stops_with_the_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            R = an.Runner(Path(tmp))
            R.logs.mkdir()
            (R.logs / "some_step.log").write_text("line 1\nthe real problem\n")
            with self.assertRaises(SystemExit) as cm:
                R.fail("Some step", 3)
        self.assertIn("the real problem", str(cm.exception))
        self.assertIn("run the same command again", str(cm.exception))


class Identity(unittest.TestCase):
    """After tracking, the track labelled YOU must be where the person clicked themselves."""

    def npz(self, tmp, you_x, partner_x):
        import numpy as np
        t = np.arange(0, 100, 0.1)
        z = {"t": t, "A_you_xy": np.c_[np.full(len(t), you_x), np.full(len(t), 3.0)], "A_partner_xy": np.c_[np.full(len(t), partner_x), np.full(len(t), 3.0)]}
        p = Path(tmp) / "players.npz"
        np.savez(p, **z)
        return p

    seen = {"t": 40.0, "you_half": "near", "you_xy": [1.5, 3.0], "partner_xy": [4.0, 3.0]}

    def test_a_correct_track_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(an.verify_identity(self.npz(tmp, 1.5, 4.0), self.seen, 8.0, 600.0))

    def test_inverted_labels_are_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            msg = an.verify_identity(self.npz(tmp, 4.0, 1.5), self.seen, 8.0, 600.0)
        self.assertIn("inverted", msg)

    def test_a_track_somewhere_else_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            msg = an.verify_identity(self.npz(tmp, 5.9, 5.0), self.seen, 8.0, 600.0)
        self.assertIn("m from where you clicked", msg)

    def test_a_picture_from_another_game_is_not_checked_here(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(an.verify_identity(self.npz(tmp, 4.0, 1.5), self.seen, 700.0, 1100.0))
            self.assertIsNone(an.verify_identity(self.npz(tmp, 4.0, 1.5), {}, 8.0, 600.0))


class GamesJson(unittest.TestCase):
    def test_games_json_for_doubles_and_singles(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / "g1").mkdir()
            (work / "g1" / "players.json").write_text(json.dumps({"coverage": {"A_you": 0.97}}))
            cfg = {"_match": {"mode": "doubles", "hand": "left", "opponents_indistinct": True}, "A_you": {"describe": "dark top, light shorts"},
                   "A_partner": {"describe": "dark top, dark shorts"}, "B_opp1": {"describe": "x"}, "B_opp2": {"describe": "y"}}
            doc = an.write_games_json(work, {"label": "L", "cards": "21-19"}, [(0, 600)], cfg, None)
            self.assertEqual((doc["mode"], doc["racket_hand"], doc["games"][0]["card"]), ("doubles", "left", "21-19"))
            self.assertIn("look alike", doc["opponents"])
            self.assertTrue(any(c["what"] == "Which opponent is which" and c["level"] == "weak" for c in doc["checks"]))
            self.assertIn("97%", [c for c in doc["checks"] if c["what"] == "Who is who"][0]["how"])
            cfg = {"_match": {"mode": "singles", "hand": "right"}, "A_you": {"describe": "a"}, "B_opp1": {"describe": "b"}}
            doc = an.write_games_json(work, {"label": "L", "cards": ""}, [(0, 600)], cfg, None)
            self.assertEqual(doc["mode"], "singles")
            self.assertNotIn("partner", doc)
            self.assertNotIn("card", doc["games"][0])


class ReferenceStillLoads(unittest.TestCase):
    def test_the_published_reference_config_is_unchanged_in_meaning(self):
        cfg = common.load_config(ROOT / "examples" / "reference-match" / "players_config.json")
        self.assertEqual(common.match_mode(cfg), "doubles")
        self.assertEqual(common.active_slots(cfg), common.SLOTS)
        self.assertFalse(cfg["_match"]["opponents_indistinct"])


if __name__ == "__main__":
    unittest.main()
