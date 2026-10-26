"""Fast checks of the shared logic. Run: python -m unittest discover -s tests"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stages"))
import common  # noqa: E402
import s03_find_start as fs  # noqa: E402
import numpy as np  # noqa: E402

GOOD = {"A_you": {"shirt": "white"}, "A_partner": {"shirt": "red"}, "B_opp1": {"shirt": "black"}, "B_opp2": {"shirt": "grey"}}


def write(cfg):
    d = tempfile.mkdtemp()
    p = Path(d) / "players_config.json"
    p.write_text(json.dumps(cfg))
    return p


class Config(unittest.TestCase):
    def test_valid_config_loads_and_gets_descriptions(self):
        cfg = common.load_config(write(GOOD))
        self.assertEqual(cfg["A_you"]["describe"], "white top")

    def test_teammates_must_differ(self):
        bad = json.loads(json.dumps(GOOD))
        bad["A_you"]["shirt"] = "red"
        with self.assertRaises(SystemExit):
            common.load_config(write(bad))

    def test_unknown_colour_rejected(self):
        bad = json.loads(json.dumps(GOOD))
        bad["B_opp1"]["shirt"] = "purple"
        with self.assertRaises(SystemExit):
            common.load_config(write(bad))

    def test_signature_is_first_bright_colour(self):
        self.assertEqual(common.signature(common.load_config(write(GOOD))), ("A", "red"))
        neutral = {"A_you": {"shirt": "white"}, "A_partner": {"shirt": "black"}, "B_opp1": {"shirt": "grey"}, "B_opp2": {"shirt": "red"}}
        self.assertEqual(common.signature(common.load_config(write(neutral))), ("B", "red"))


class Teams(unittest.TestCase):
    def test_near_team_swaps_once(self):
        self.assertEqual(common.near_team_at(10, 100, "B"), "B")
        self.assertEqual(common.near_team_at(150, 100, "B"), "A")
        self.assertEqual(common.near_team_at(150, common.NO_CHANGE, "B"), "B")


class Colours(unittest.TestCase):
    def f(self, **kw):
        base = {"tL": np.float32(128), "t_red": np.float32(0), "t_blue": np.float32(0), "t_green": np.float32(0), "t_yellow": np.float32(0), "t_orange": np.float32(0)}
        base.update({k: np.float32(v) for k, v in kw.items()})
        return base

    def test_red_shirt_scores_red_not_black(self):
        f = self.f(t_red=0.4, tL=110)
        self.assertGreater(common.colour_score("red", f), 0.9)
        self.assertLess(common.colour_score("black", f), 0.5)

    def test_dark_shirt_scores_black(self):
        self.assertGreater(common.colour_score("black", self.f(tL=50)), 0.9)

    def test_bright_shirt_scores_white_over_grey(self):
        f = self.f(tL=200)
        self.assertGreater(common.colour_score("white", f), common.colour_score("grey", f))


class ChainStatus(unittest.TestCase):
    def test_confirmed_needs_two_same_player_pairs(self):
        rows = [{"winner": "A", "server_team": "A", "server_player": "A_you"} for _ in range(4)]
        out = common.chain_status({"chains": [{"rallies": [1, 4], "n": 4}]}, {"rows": rows})
        self.assertEqual(out[0]["status"], "confirmed")
        rows[2]["server_player"] = "A_partner"
        out = common.chain_status({"chains": [{"rallies": [1, 4], "n": 4}]}, {"rows": rows})
        self.assertNotEqual(out[0]["status"], "confirmed")


class FindStart(unittest.TestCase):
    def test_chain_ignores_a_lone_early_window(self):
        runs = [(18.0, 20.0), (49.0, 52.0), (56.0, 58.0), (70.0, 73.0), (82.0, 85.0), (107.0, 109.0)]
        self.assertEqual(fs.first_chain(runs, 4, 30.0), 1)

    def test_no_rhythm_returns_none(self):
        self.assertIsNone(fs.first_chain([(10.0, 12.0), (100.0, 102.0), (200.0, 202.0)], 4, 30.0))

    def test_quiet_windows_need_people_and_stillness(self):
        t = np.arange(0, 20, 0.1)
        energy = np.where((t > 5) & (t < 9), 0.2, 3.0)
        persons = np.full(len(t), 4.0)
        runs = fs.quiet_windows(t, energy, persons, 0.8, 1.5)
        self.assertEqual(len(runs), 1)
        self.assertLess(abs(runs[0][0] - 5.0), 0.6)
        self.assertEqual(fs.quiet_windows(t, energy, np.zeros(len(t)), 0.8, 1.5), [])


class Shades(unittest.TestCase):
    """Two teammates in the same colour but different shades (royal blue and teal, say) can be told apart."""
    ROYAL = {"tL": 85.0, "t_red": 0.0, "t_blue": 0.7, "t_green": 0.0, "t_yellow": 0.0, "t_orange": 0.0}
    TEAL = {"tL": 138.0, "t_red": 0.0, "t_blue": 0.7, "t_green": 0.0, "t_yellow": 0.0, "t_orange": 0.0}

    def test_without_a_shade_both_look_blue(self):
        self.assertGreater(common.colour_score("blue", self.ROYAL), 0.99)
        self.assertGreater(common.colour_score("blue", self.TEAL), 0.99)

    def test_a_shade_separates_them(self):
        split = 112.0
        self.assertGreater(common.colour_score("blue", self.ROYAL, "dark", split), 0.9)
        self.assertLess(common.colour_score("blue", self.ROYAL, "light", split), 0.1)
        self.assertGreater(common.colour_score("blue", self.TEAL, "light", split), 0.9)
        self.assertLess(common.colour_score("blue", self.TEAL, "dark", split), 0.1)

    def write(self, **slots):
        base = {"A_you": {"shirt": "blue"}, "A_partner": {"shirt": "blue"}, "B_opp1": {"shirt": "red"}, "B_opp2": {"shirt": "black"}}
        for k, v in slots.items():
            base[k] = {**base[k], **v}
        d = tempfile.mkdtemp()
        path = Path(d) / "c.json"
        path.write_text(json.dumps(base))
        return path

    def test_config_allows_same_colour_only_with_opposite_shades(self):
        common.load_config(self.write(A_you={"tone": "dark"}, A_partner={"tone": "light"}))
        for bad in (dict(), dict(A_you={"tone": "dark"}), dict(A_you={"tone": "dark"}, A_partner={"tone": "dark"})):
            with self.subTest(bad), self.assertRaises(SystemExit):
                common.load_config(self.write(**bad))
        with self.assertRaises(SystemExit):
            common.load_config(self.write(A_you={"tone": "medium"}, A_partner={"shirt": "green"}))

    def test_slot_probs_use_the_shade_and_ignore_it_when_absent(self):
        cfg = common.load_config(self.write(A_you={"tone": "dark", "tone_split": 112.0}, A_partner={"tone": "light", "tone_split": 112.0}))
        p = common.slot_probs(cfg, self.ROYAL)
        self.assertGreater(p["A_you"], 0.9)
        self.assertLess(p["A_partner"], 0.1)
        plain = common.load_config(self.write(A_partner={"shirt": "green"}))
        self.assertGreater(common.slot_probs(plain, self.TEAL)["A_you"], 0.99)


class ShortsAndAnyShirt(unittest.TestCase):
    """In a dim hall every shirt reads dark; shorts (read from the legs) can tell two teammates apart instead."""
    WHITE_LEGS = {"tL": 20.0, "t_red": 0, "t_blue": 0, "t_green": 0, "t_yellow": 0, "t_orange": 0, "lL": 200.0, "l_white": 0.5, "l_dark": 0.0}
    DARK_LEGS = {"tL": 20.0, "t_red": 0, "t_blue": 0, "t_green": 0, "t_yellow": 0, "t_orange": 0, "lL": 40.0, "l_white": 0.0, "l_dark": 0.8}

    def write(self, **slots):
        base = {"A_you": {"shirt": "any", "shorts": "white"}, "A_partner": {"shirt": "any", "shorts": "dark"},
                "B_opp1": {"shirt": "blue"}, "B_opp2": {"shirt": "black"}}
        for k, v in slots.items():
            base[k] = v
        path = Path(tempfile.mkdtemp()) / "c.json"
        path.write_text(json.dumps(base))
        return path

    def test_shorts_scores(self):
        self.assertGreater(common.shorts_score("white", self.WHITE_LEGS), 0.9)
        self.assertLess(common.shorts_score("white", self.DARK_LEGS), 0.05)
        self.assertGreater(common.shorts_score("dark", self.DARK_LEGS), 0.9)
        self.assertLess(common.shorts_score("dark", self.WHITE_LEGS), 0.05)

    def test_shorts_band_in_a_dim_hall(self):
        dim_white = dict(self.DARK_LEGS, sL=80.0)          # white shorts read about 60 to 140 here
        dim_black = dict(self.DARK_LEGS, sL=10.0)
        self.assertGreater(common.shorts_score("white", dim_white), 0.9)
        self.assertLess(common.shorts_score("white", dim_black), 0.05)
        self.assertGreater(common.shorts_score("dark", dim_black), 0.9)
        self.assertLess(common.shorts_score("dark", dim_white), 0.05)
        cfg = common.load_config(self.write())
        p = common.slot_probs(cfg, dim_white)
        self.assertGreater(p["A_you"], 0.9)
        self.assertLess(p["A_partner"], 0.05)

    def test_slot_probs_follow_the_legs_when_the_shirt_is_any(self):
        cfg = common.load_config(self.write())
        p = common.slot_probs(cfg, self.WHITE_LEGS)
        self.assertGreater(p["A_you"], 0.9)
        self.assertLess(p["A_partner"], 0.05)
        q = common.slot_probs(cfg, self.DARK_LEGS)
        self.assertGreater(q["A_partner"], 0.9)
        self.assertLess(q["A_you"], 0.05)

    def test_config_rules(self):
        with self.assertRaises(SystemExit):                       # "any" shirt with no shorts: nothing to tell the player by
            common.load_config(self.write(A_you={"shirt": "any"}))
        with self.assertRaises(SystemExit):                       # two teammates with the same shorts and no other difference
            common.load_config(self.write(A_partner={"shirt": "any", "shorts": "white"}))
        with self.assertRaises(SystemExit):
            common.load_config(self.write(A_you={"shirt": "any", "shorts": "plaid"}))
        with self.assertRaises(SystemExit):                       # "any" next to a plain red shirt, with no shorts to separate them: refused
            common.load_config(self.write(A_partner={"shirt": "red"}, A_you={"shirt": "any", "shorts": "white"}))
        common.load_config(self.write(A_partner={"shirt": "red", "shorts": "dark"}, A_you={"shirt": "any", "shorts": "white"}))


if __name__ == "__main__":
    unittest.main()
