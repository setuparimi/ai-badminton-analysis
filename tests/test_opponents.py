"""Checks of the opponent scouting numbers (stage 7b) on small made-up games. Run: python -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stages"))
import s07b_opponents as o  # noqa: E402


def rally(n, start, dur, winner, server_team="A", server_player="A_you"):
    return {"rally": n, "start": start, "end": start + dur, "duration": dur, "winner": winner, "server_team": server_team, "server_player": server_player}


def move_row(n, a_near, winner, d1=5.0, d2=2.0, pair=None):
    p = lambda depth: {"distance_m": 7.0, "mean_speed": 0.8, "peak_speed": 2.0, "front": 0.1, "mid": 0.3, "back": 0.6, "mean_depth": depth,
                       "mean_lateral_from_centre": 0.5}
    return {"rally": n, "start": 10.0 * n, "end": 10.0 * n + 8, "A_is_near": a_near, "winner": winner,
            "players": {"B_opp1": p(d1), "B_opp2": p(d2)}, "pair_B": pair or {k: 0.3 for k in o.PAIR_KEYS}}


class Results(unittest.TestCase):
    def setUp(self):
        self.points = [rally(1, 0, 4, "B", "B", "B_opp1"), rally(2, 10, 5, "A", "B", "B_opp2"), rally(3, 20, 8, "B", "A", "A_you"),
                       rally(4, 30, 12, "B", "B", "B_opp2"), rally(5, 40, 9, "A", "A", "A_partner"), rally(6, 50, 20, None, "A", None)]

    def test_counts_exclude_the_undecided_last_rally(self):
        r = o.results(self.points)
        self.assertEqual(r["decided"], 5)
        self.assertEqual(r["serving"], [2, 3])        # rallies 1, 2, 4 served by B: won 1 and 4
        self.assertEqual(r["receiving"], [1, 2])      # rallies 3 and 5 served by A: B won rally 3
        self.assertEqual(r["by_server"]["B_opp2"], [1, 2])
        self.assertEqual(r["by_server"]["B_opp1"], [1, 1])

    def test_length_buckets_and_short_versus_long(self):
        r = o.results(self.points)
        self.assertEqual([(b["n"], b["won"]) for b in r["by_length"]], [(2, 1), (2, 1), (1, 1)])
        self.assertEqual(r["short_vs_long"]["short"], [1, 2])
        self.assertEqual(r["short_vs_long"]["longer"], [2, 3])

    def test_longest_run(self):
        pts = [rally(i, 10 * i, 5, w) for i, w in enumerate("BAABBBAB", 1)]
        run = o.streak(pts, "B")
        self.assertEqual((run["length"], run["rally"]), (3, 4))

    def test_unknown_server_is_counted_not_guessed(self):
        pts = [rally(1, 0, 5, "B", "B", None), rally(2, 10, 5, "A", "A", "A_you")]
        r = o.results(pts)
        self.assertEqual(r["server_unknown"], 1)
        self.assertEqual(r["by_server"]["B_opp1"], [0, 0])


class Players(unittest.TestCase):
    def test_depth_numbers_use_the_near_half_when_there_is_enough(self):
        rows = [move_row(i, a_near=(i % 2 == 0), winner="B") for i in range(1, 25)]       # 12 rallies with the opponents near
        used, which = o.pick_rows(rows, 10)
        self.assertEqual((which, len(used)), ("near", 12))
        used, which = o.pick_rows(rows, 13)
        self.assertEqual((which, len(used)), ("all", 24))

    def test_who_plays_the_net_side(self):
        rows = [move_row(i, False, "B", d1=5.0, d2=2.0) for i in range(1, 6)] + [move_row(6, False, "B", d1=1.5, d2=3.0)]
        block, extra = o.players_block(rows, rows, None)
        self.assertEqual(extra["rallies_with_both"], 6)
        self.assertAlmostEqual(block["B_opp2"]["net_side_share"], 5 / 6)
        self.assertAlmostEqual(block["B_opp1"]["net_side_share"], 1 / 6)

    def test_racket_hand_is_clear_only_with_enough_frames(self):
        rows = [move_row(i, False, "B") for i in range(1, 4)]
        pose = {k: {"overhead_left": l, "overhead_right": r, "racket_arm": "R" if r > l else "L", "samples": 100, "knee_median": 168.0, "bent_lt150": 0.1,
                    "racket_up_share": 0.8, "by_side": {}} for k, l, r in (("B_opp1", 2, 9), ("B_opp2", 8, 6))}
        block, _ = o.players_block(rows, rows, pose)
        self.assertTrue(block["B_opp1"]["pose"]["racket_arm_clear"])
        self.assertFalse(block["B_opp2"]["pose"]["racket_arm_clear"])


class Pair(unittest.TestCase):
    def test_won_versus_lost_means_and_p(self):
        rows = []
        for i in range(1, 13):
            won = i % 2 == 0
            rows.append(move_row(i, False, "B" if won else "A", pair={**{k: 0.3 for k in o.PAIR_KEYS}, "side_by_side": 0.05 if won else 0.2 + 0.001 * i}))
        out = o.pair_block(rows, rows)
        v = out["won_vs_lost"]["side_by_side"]
        self.assertAlmostEqual(v["won"], 0.05)
        self.assertGreater(v["lost"], 0.2)
        self.assertLess(v["p"], 0.01)
        self.assertGreater(out["won_vs_lost"]["crowded"]["p"], 0.5)      # identical groups
        self.assertEqual(out["n_comparisons"], len(o.PAIR_KEYS))

    def test_too_few_rallies_give_no_p(self):
        rows = [move_row(1, False, "B"), move_row(2, False, "A")]
        self.assertIsNone(o.pair_block(rows, rows)["won_vs_lost"]["crowded"]["p"])


class Zones(unittest.TestCase):
    def test_coverage_of_a_pair_standing_in_the_middle_lane(self):
        n = 40
        t = np.arange(n) * 0.1
        z = {"t": t, "B_opp1_xy": np.tile([3.05, 1.7], (n, 1)),     # near half: 5.0 m from the net, middle lane
             "B_opp2_xy": np.tile([3.05, 4.2], (n, 1))}             # 2.5 m from the net, middle lane
        rows = [{"start": 0.0, "end": 4.0, "A_is_near": False, "players": {"B_opp1": {}, "B_opp2": {}}}]
        out = o.zone_block(z, rows)
        cov = out["coverage"]
        self.assertEqual(cov["back centre"], 1.0)
        self.assertEqual(cov["front centre"], 1.0)
        self.assertEqual(cov["front left"], 0.0)
        self.assertEqual(cov["back right"], 0.0)
        self.assertEqual({x["zone"] for x in out["least_covered"]} <= {k for k, v in cov.items() if v == 0.0}, True)
        self.assertAlmostEqual(sum(out["occupancy"]["B_opp1"].values()), 1.0)
        self.assertEqual(out["occupancy"]["B_opp1"]["back centre"], 1.0)

    def test_far_half_is_mirrored_into_the_teams_own_view(self):
        n = 40
        z = {"t": np.arange(n) * 0.1, "B_opp1_xy": np.tile([1.0, 11.7], (n, 1)), "B_opp2_xy": np.tile([1.0, 11.7], (n, 1))}   # far half, X=1.0
        rows = [{"start": 0.0, "end": 4.0, "A_is_near": True, "players": {"B_opp1": {}, "B_opp2": {}}}]                     # opponents are far
        out = o.zone_block(z, rows)
        # seen from behind the far team, X=1.0 is on their RIGHT
        self.assertEqual(out["occupancy"]["B_opp1"]["back right"], 1.0)


if __name__ == "__main__":
    unittest.main()
