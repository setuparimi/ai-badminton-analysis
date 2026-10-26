#!/usr/bin/env python3
"""Stage 10 - REPORT (numbers).

Collects every earlier stage into one table-ready data file, adds the match-level
statistics (serve vs receive, rally length, streaks, momentum), a sensitivity check that
drops the rallies whose serving team is least certain, and a list of timestamps to check
by eye. The coaching text is written separately and merged by stages/s10_build_report.py.

Run:
    python stages/s10_report.py --work work
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


def mmss(s):
    return f"{int(s // 60)}:{int(s % 60):02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True)
    args = ap.parse_args()
    W = Path(args.work)
    P = json.loads((W / "points.json").read_text())["rallies"]
    S = json.loads((W / "serves.json").read_text())
    M = json.loads((W / "motion.json").read_text())
    PO = json.loads((W / "pose_stats.json").read_text())["stats"]
    PK = json.loads((W / "pickups.json").read_text())
    PL = json.loads((W / "players.json").read_text())
    chains = S["chains"]
    D = [p for p in P if p["winner"]]                 # rallies with a known winner (all but the last)

    def conf(r):
        return next(c["confidence"] for c in chains if c["rallies"][0] <= r <= c["rallies"][1])

    out = {"n_rallies": len(P), "n_decided": len(D)}
    # ---- score story
    A_pts = sum(p["winner"] == "A" for p in D)
    out["score_after_52"] = [A_pts, len(D) - A_pts]
    out["last_scoreboard"] = {"server_team": P[-1]["server_team"], "score": P[-1]["score_before"]}
    lead_changes, prev = 0, 0
    for p in D:
        d = p["A_after"] - p["B_after"]
        if prev and d and (d > 0) != (prev > 0):
            lead_changes += 1
        if d:
            prev = d
    out["lead_changes"] = lead_changes
    ties = sum(1 for p in D if p["A_after"] == p["B_after"])
    out["ties"] = ties
    # streaks
    def streaks(team):
        best, cur, start, bs = 0, 0, None, None
        for p in D:
            if p["winner"] == team:
                cur += 1
                start = p if cur == 1 else start
                if cur > best:
                    best, bs = cur, start
            else:
                cur = 0
        return best, (bs["rally"], bs["start"]) if bs else None
    out["streak_A"], out["streak_B"] = streaks("A"), streaks("B")
    # momentum by quarters of the game
    q = np.array_split(np.arange(len(D)), 4)
    out["quarters"] = [{"rallies": f"{D[i[0]]['rally']}-{D[i[-1]]['rally']}", "A": sum(D[j]['winner'] == 'A' for j in i), "n": len(i)} for i in q]

    # ---- serve vs receive
    def winpct(rows):
        return (sum(r["winner"] == "A" for r in rows), len(rows))
    A_srv = [p for p in D if p["server_team"] == "A"]
    A_rcv = [p for p in D if p["server_team"] == "B"]
    out["A_when_serving"], out["A_when_receiving"] = winpct(A_srv), winpct(A_rcv)
    out["A_when_serving_you"] = winpct([p for p in A_srv if p["server_player"] == "A_you"])
    out["A_when_serving_partner"] = winpct([p for p in A_srv if p["server_player"] == "A_partner"])
    out["serves_by_player"] = {k: sum(1 for p in P if p["server_player"] == k) for k in ("A_partner", "A_you", "B_opp1", "B_opp2")}
    p_sr = stats.fisher_exact([[out["A_when_serving"][0], out["A_when_serving"][1] - out["A_when_serving"][0]],
                               [out["A_when_receiving"][0], out["A_when_receiving"][1] - out["A_when_receiving"][0]]])[1]
    out["serve_vs_receive_p"] = float(p_sr)
    # ---- rally length
    buckets = [("under 6 s", 0, 6), ("6 to 10 s", 6, 10), ("over 10 s", 10, 99)]
    out["by_length"] = []
    for name, lo, hi in buckets:
        rows = [p for p in D if lo <= p["duration"] < hi]
        out["by_length"].append({"bucket": name, "n": len(rows), "A_won": sum(p["winner"] == "A" for p in rows)})
    dw = [p["duration"] for p in D if p["winner"] == "A"]
    dl = [p["duration"] for p in D if p["winner"] == "B"]
    out["duration_won_lost"] = [float(np.mean(dw)), float(np.mean(dl)), float(stats.mannwhitneyu(dw, dl).pvalue)]

    # ---- sensitivity: drop rallies in chains with confidence < 0.6
    keep = {p["rally"] for p in D if conf(p["rally"]) >= 0.6}
    rows = [r for r in M["rallies"] if r["rally"] in keep and r["user_team_won"] is not None]
    sens = {}
    for key, getter in (("distance_m", lambda r: r["players"]["A_you"].get("distance_m")),
                        ("mean_speed", lambda r: r["players"]["A_you"].get("mean_speed")),
                        ("back", lambda r: r["players"]["A_you"].get("back")),
                        ("crowded", lambda r: (r["pair_A"] or {}).get("crowded")),
                        ("open_gap_mean", lambda r: (r["pair_A"] or {}).get("open_gap_mean"))):
        w = np.array([getter(r) for r in rows if r["user_team_won"] and getter(r) is not None], float)
        l = np.array([getter(r) for r in rows if not r["user_team_won"] and getter(r) is not None], float)
        sens[key] = {"won": float(w.mean()), "lost": float(l.mean()), "n_won": len(w), "n_lost": len(l),
                     "p": float(stats.mannwhitneyu(w, l).pvalue)}
    out["sensitivity_confident_chains_only"] = {"rallies": len(rows), "metrics": sens}

    # ---- moments to check by eye
    lost = [p for p in D if p["winner"] == "B"]
    won = [p for p in D if p["winner"] == "A"]
    out["check"] = {
        "longest_lost": [(p["rally"], mmss(p["start"]), round(p["duration"], 1)) for p in sorted(lost, key=lambda p: -p["duration"])[:4]],
        "longest_won": [(p["rally"], mmss(p["start"]), round(p["duration"], 1)) for p in sorted(won, key=lambda p: -p["duration"])[:3]],
    }
    mr = {r["rally"]: r for r in M["rallies"]}
    cand = [(mr[p["rally"]]["pair_A"]["open_gap_mean"], p["rally"], p["start"]) for p in lost if p["rally"] in mr and mr[p["rally"]]["pair_A"]]
    out["check"]["widest_open_gap_lost"] = [(rr, mmss(st), round(g, 1)) for g, rr, st in sorted(cand, reverse=True)[:4]]
    cand = [(mr[p["rally"]]["pair_A"]["stacked"], p["rally"], p["start"]) for p in lost if p["rally"] in mr and mr[p["rally"]]["pair_A"]]
    out["check"]["most_stacked_lost"] = [(rr, mmss(st), round(g, 2)) for g, rr, st in sorted(cand, reverse=True)[:4]]
    if D:
        out["check"]["end_change"] = mmss(PL["tc"]) if PL["tc"] < 1e8 else None

    out["motion_summary"], out["motion_totals"] = M["summary"], M["totals"]
    out["pose"] = {k: {kk: v for kk, v in s.items() if kk in ("racket_arm", "racket_hand", "by_side", "knee_median", "stance_median")} for k, s in PO.items()}
    out["pickups"] = {"usable": PK["usable"], "single_team_rallies": PK["rallies_with_single_bending_team"],
                      "agree": PK["agree_with_loser"], "p": PK["p_value"]}
    out["tracking"] = PL["coverage"]
    (W / "report_data.json").write_text(json.dumps(out, indent=1, default=float))

    # ---- chart: score timeline
    fig, ax = plt.subplots(2, 1, figsize=(9, 5.5), gridspec_kw={"height_ratios": [3, 1.3]}, sharex=True)
    xa = [0] + [p["rally"] for p in D]
    ax[0].step(xa, [0] + [p["A_after"] for p in D], where="post", color="#d62728", lw=2, label="Your team (red + white)")
    ax[0].step(xa, [0] + [p["B_after"] for p in D], where="post", color="#1f77b4", lw=2, label="Opponents (dark + grey)")
    swap = next((p["rally"] for p in P if p["start"] > PL["tc"]), None)
    if swap:
        ax[0].axvline(swap - 0.5, color="grey", ls="--", lw=1)
        ax[0].text(swap + 0.2, 2, "ends swapped", fontsize=8, color="grey")
    ax[0].set_ylabel("points"); ax[0].legend(loc="upper left", fontsize=8); ax[0].set_title("Score after each rally")
    cols = ["#d62728" if p["winner"] == "A" else "#1f77b4" for p in D]
    ax[1].bar([p["rally"] for p in D], [p["duration"] for p in D], color=cols)
    ax[1].set_ylabel("rally length (s)"); ax[1].set_xlabel("rally number (bar colour = who won it)")
    fig.tight_layout(); fig.savefig(W / "s10_score_timeline.png", dpi=110)

    print(json.dumps({k: out[k] for k in ("score_after_52", "last_scoreboard", "lead_changes", "ties", "streak_A", "streak_B", "quarters",
                                          "A_when_serving", "A_when_receiving", "A_when_serving_you", "A_when_serving_partner", "serves_by_player",
                                          "serve_vs_receive_p", "by_length", "duration_won_lost")}, indent=1, default=float))
    print("sensitivity (confident chains only):", json.dumps(out["sensitivity_confident_chains_only"], default=float))
    print("check:", json.dumps(out["check"], default=float))


if __name__ == "__main__":
    main()
