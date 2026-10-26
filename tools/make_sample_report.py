#!/usr/bin/env python3
"""Makes the SAMPLE report for the route without a score on screen, from invented data.

Nobody played this match. Two games of doubles are simulated (players who drift between a base position and a target, walk to the service spots
between plays, sometimes stand front and back), then the same stages that run on a real match turn them into statistics, rule-based words and a PDF.
Every page says it is a sample. The point is to show what the report looks like without publishing anybody's real weaknesses.

Run:
    python tools/make_sample_report.py [--out examples/sample-no-score-report] [--seed 7]
Writes <out>/match_report.pdf, <out>/README.md and the data it was built from (<out>/data/).
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "stages"))
import s07f_free_stats as fs  # noqa: E402
import s14_free_report as rep  # noqa: E402
import s14a_free_words as words  # noqa: E402
from common import NET_Y, SLOTS, TEAM_WIDTH  # noqa: E402

FPS, STRIDE = 30.0, 3
DT = STRIDE / FPS


def simulate_game(rng, n_plays, you_near, front_back_share, partner_back_share, work_rate, depth_back=0.0, spread=(0.5, 1.0)):
    """positions (court metres) of the four players for one game of n_plays plays. Returns a players.npz-like dict and the play windows."""
    windows, cur = [], 5.0
    for _ in range(n_plays):
        dur = float(np.clip(rng.lognormal(np.log(7.0), 0.5), 3.0, 28.0))
        windows.append({"start": round(cur, 2), "end": round(cur + dur, 2), "dur": round(dur, 2)})
        cur += dur + float(np.clip(rng.normal(6.5, 1.5), 3.5, 11.0))
    n = int((cur + 6.0) / DT)
    t = np.arange(n) * DT
    play = np.zeros(n, bool)
    for w in windows:
        play |= (t >= w["start"]) & (t <= w["end"])

    def team(team_is_near, who_back, fb):
        """(u, d) of a pair in its own half: a base formation that changes every few seconds, plus a pull towards a moving target while the shuttle is in play"""
        u = np.zeros((2, n))
        d = np.zeros((2, n))
        pos = np.array([[1.8, 3.2], [4.3, 3.4]])            # side by side in the middle to start with
        vel = np.zeros((2, 2))
        base_until, base = 0.0, pos.copy()
        for i in range(n):
            if t[i] >= base_until:
                base_until = t[i] + rng.uniform(3, 9)
                if rng.random() < fb:                       # front and back: one at the net, one deep
                    back = 0 if rng.random() < who_back else 1
                    base = np.array([[rng.uniform(1.5, 4.5), 1.3 + depth_back], [rng.uniform(1.5, 4.5), 4.9 + depth_back]])
                    if back:
                        base = base[::-1]
                else:                                       # side by side
                    cx = rng.uniform(2.4, 3.7)
                    base = np.array([[cx - rng.uniform(*spread), rng.uniform(2.7, 4.2) + depth_back], [cx + rng.uniform(*spread), rng.uniform(2.7, 4.2) + depth_back]])
                    if rng.random() < 0.4:                  # who stands on which side is not fixed
                        base = base[::-1]
            target = base + (rng.normal(0, 0.9, (2, 2)) if play[i] else 0)
            pull = 3.2 if play[i] else 1.0
            vel = 0.82 * vel + pull * (target - pos) * DT + rng.normal(0, 0.05 * work_rate, (2, 2))
            speed = np.hypot(vel[:, 0], vel[:, 1]) / DT
            vel *= np.where(speed > 4.2, 4.2 / np.maximum(speed, 1e-6), 1.0)[:, None]
            pos = np.clip(pos + vel, [0.2, 0.3], [TEAM_WIDTH - 0.2, NET_Y - 0.2])
            u[:, i], d[:, i] = pos[:, 0], pos[:, 1]
        return u, d

    z = {"frames": (t * FPS).astype(int), "t": t, "fps": np.float64(FPS), "stride": np.int64(STRIDE), "tc": np.float64(1e9),
         "first_near": np.array("A" if you_near else "B")}
    for tm, slots, near, who_back, fb in (("A", ("A_you", "A_partner"), you_near, partner_back_share, front_back_share),
                                          ("B", ("B_opp1", "B_opp2"), not you_near, 0.5, front_back_share * 0.8)):
        u, d = team(near, who_back, fb)
        for j, k in enumerate(slots):
            X = u[j] if near else TEAM_WIDTH - u[j]
            Y = NET_Y - d[j] if near else NET_Y + d[j]
            z[f"{k}_xy"] = np.c_[X, Y].astype(np.float32)
            z[f"{k}_flag"] = np.ones(n, np.int8)
            z[f"{k}_box"] = np.full((n, 5), np.nan, np.float32)
    return z, windows


def pose_stats(rng, you_bent, partner_bent):
    def one(bent, up):
        return {"samples": int(rng.integers(700, 1300)), "bent_lt150": bent, "deep_lt130": 0.02, "stance_median": round(float(rng.uniform(1.2, 1.5)), 2),
                "racket_up_share": up, "racket_arm": "R"}
    return {"stage": 8, "stats": {"A_you": one(you_bent, 0.82), "A_partner": one(partner_bent, 0.88)}}


def build(out, seed=7):
    rng = np.random.default_rng(seed)
    out = Path(out)
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        W = Path(tmp)
        specs = [("g1", "Game 1", True, 0.10, 0.65, 1.0, 0.0, "21-17"), ("g2", "Game 2", False, 0.12, 0.55, 1.1, 0.4, "19-21")]
        games = []
        for gdir, title, you_near, fb, back, work, depth, card in specs:
            (W / gdir).mkdir()
            n_plays = sum(int(x) for x in card.split("-"))            # as many plays as the invented score implies
            z, windows = simulate_game(rng, n_plays, you_near, fb, back, work, depth)
            np.savez(W / gdir / "players.npz", **z)
            (W / gdir / "play_windows.json").write_text(json.dumps({"windows": windows}))
            stats = fs.analyse(np.load(W / gdir / "players.npz", allow_pickle=True), windows)
            (W / gdir / "free_stats.json").write_text(json.dumps(stats))
            (W / gdir / "pose_stats.json").write_text(json.dumps(pose_stats(rng, 0.19, 0.12)))
            games.append({"dir": gdir, "title": title, "card": card})
        sample = ("SAMPLE REPORT. Nobody played this match: two games of doubles were simulated and every number, chart and sentence below comes from invented data, "
                  "made only to show what the report looks like. The scores are invented too.")
        (W / "games.json").write_text(json.dumps({
            "label": "Sample match (invented data)", "mode": "doubles", "racket_hand": "right", "you": "navy top, white shorts", "partner": "black top, black shorts",
            "opponents": "two players in blue and red tops", "games": games, "sample": True, "sample_note": sample,
            "card_note": "Invented scores, yours first: 21-17 and 19-21. There is no score on screen in a real video of this kind.",
            "checks": [{"what": "Everything in this report", "how": "Invented. It describes no real match, so none of it can be checked against a video.", "level": "none"},
                       {"what": "Plays", "how": "In a real run these come from the shuttle sound and the players' movement.", "level": "approximate"}]}, indent=1))
        cfg = rep.load(W)
        tips, scout = words.build_words(cfg)
        (W / "tips.json").write_text(json.dumps(tips, indent=1))
        (W / "scouting.json").write_text(json.dumps(scout, indent=1))
        (W / "words_source.json").write_text(json.dumps({"source": "automatic", "files": ["tips.json", "scouting.json"]}))
        rep.build(W, out / "match_report.pdf", "A4", "a sample")
        for name in ("games.json", "tips.json", "scouting.json"):
            (data / name).write_text((W / name).read_text())
        for g in games:
            (data / f"{g['dir']}_free_stats.json").write_text((W / g["dir"] / "free_stats.json").read_text())
    (out / "README.md").write_text(
        "# Sample report (invented data)\n\n"
        "`match_report.pdf` is what the route **without a score on screen** produces. **Nobody played this match**: two games of doubles were simulated by "
        "`tools/make_sample_report.py` and run through the same statistics, rule-based words and PDF stages as a real video. Every number, chart and sentence is invented; "
        "the first page and the header of every page say so. It exists so you can see the report without anyone's real weaknesses being published.\n\n"
        "Rebuild it with `python tools/make_sample_report.py` (seeded, so the result is the same each time). `data/` holds what it was made from.\n\n"
        "The scoreboard route has its own example in [`../reference-match/`](../reference-match/) (a real game, anonymised).\n")
    return out / "match_report.pdf"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="examples/sample-no-score-report")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    pdf = build(args.out, args.seed)
    print(f"wrote {pdf} ({pdf.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
