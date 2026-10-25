#!/usr/bin/env python3
"""Stage 5 - SCORE.

Replays the game with the doubles service rule using the serving team found in stage 4:
the rally winner serves next, an even server score serves from the right court, and the
SAME player keeps serving while their team keeps winning. Produces who won every rally and
both teams' running scores, then tests the replay against the video:

  independent check: while a team keeps winning on serve, the serving player must stay the
  same person. If stage 4 had picked the wrong team as server, the 'server' would really be
  the receiver, and the receiver changes every time the server's court flips.

Run:
    python stages/s05_score.py --serves work/serves.json --out work/score.json
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serves", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    S = json.loads(Path(args.serves).read_text())
    sv = S["serves"]
    n = len(sv)
    score = {"A": 0, "B": 0}
    rows, problems = [], []
    for k, s in enumerate(sv):
        team = s["server_team"]
        other = "A" if team == "B" else "B"
        if (score[team], score[other]) != (s["server_score"], s["receiver_score"]):
            problems.append(f"rally {k + 1}: replay says {team} {score[team]}-{score[other]} but scoreboard shows "
                            f"{s['server_score']}-{s['receiver_score']}")
        winner = sv[k + 1]["server_team"] if k + 1 < n else None
        if winner:
            score[winner] += 1
        rows.append({"rally": k + 1, "server_team": team, "server_player": s["server_player"],
                     "court": s["court"], "server_score": s["server_score"], "receiver_score": s["receiver_score"],
                     "winner": winner, "A_after": score["A"] if winner else None, "B_after": score["B"] if winner else None})

    # independent check on the serving team
    same_pairs = [(k, k + 1) for k in range(n - 1) if rows[k]["winner"] == rows[k]["server_team"]]
    both = [(a, b) for a, b in same_pairs if rows[a]["server_player"] and rows[b]["server_player"]]
    stay = [rows[a]["server_player"] == rows[b]["server_player"] for a, b in both]
    # same test if the OTHER team had been called the server (what would happen if the direction were wrong)
    def other_player(r, k):
        s = sv[k]
        team = "A" if s["server_team"] == "B" else "B"
        even = s["server_score"] % 2 == 0
        is_near = team == s["near_team"]
        c = []
        for idn in (("A_partner", "A_you") if team == "A" else ("B_opp1", "B_opp2")):
            p = s["positions"][idn]
            if p and ((p[0] > 3.05) == even if is_near else (p[0] < 3.05) == even):
                c.append((abs(p[1] - 6.7), idn))
        return min(c)[1] if c else None
    both_o = [(a, b) for a, b in same_pairs if other_player(rows[a], a) and other_player(rows[b], b)]
    stay_o = [other_player(rows[a], a) == other_player(rows[b], b) for a, b in both_o]

    decided = [r for r in rows if r["winner"]]
    won = {t: sum(1 for r in decided if r["winner"] == t) for t in "AB"}
    out = {"stage": 5, "rows": rows, "final_known": {"A": score["A"], "B": score["B"]},
           "last_scoreboard": {"server": sv[-1]["server_score"], "receiver": sv[-1]["receiver_score"],
                               "server_team": sv[-1]["server_team"]},
           "same_server_checks": {"pairs": len(both), "same_player": int(sum(stay)),
                                  "if_direction_were_wrong": {"pairs": len(both_o), "same_player": int(sum(stay_o))}},
           "problems": problems}
    Path(args.out).write_text(json.dumps(out, indent=1))

    print(f"replayed {n} rallies; winners known for {len(decided)} (the last rally's winner is not shown in the video)")
    print(f"score after rally {len(decided)}: A {score['A']} - B {score['B']}   | last scoreboard: server team {sv[-1]['server_team']} "
          f"{sv[-1]['server_score']}-{sv[-1]['receiver_score']} before the final rally")
    print(f"replay vs scoreboard      : {len(problems)} disagreements")
    for p in problems[:8]:
        print("   -", p)
    print(f"same player keeps serving : {sum(stay)} of {len(both)} consecutive same-team serves "
          f"({100 * sum(stay) / max(1, len(both)):.0f}%)")
    print(f"  ... if the direction were wrong: {sum(stay_o)} of {len(both_o)} "
          f"({100 * sum(stay_o) / max(1, len(both_o)):.0f}%)   <- the receiver rotates, so this should be low")
    ratio = sum(stay) / len(both) if both else 0.0
    ratio_wrong = sum(stay_o) / len(both_o) if both_o else 0.0
    supported = ratio > 0.7 and ratio > ratio_wrong + 0.25
    ok = not problems and len(both) >= 8 and supported
    few = not problems and len(both) < 8 and (not both or ratio > ratio_wrong)
    if ok:
        verdict = "PASSED (automatic checks)."
    elif few:
        verdict = (f"INCONCLUSIVE: only {len(both)} consecutive same-team serves, too few to confirm which team serves. "
                   "Treat who won each rally as unverified (ask the player who served first and who won).")
    else:
        verdict = "FAILED: see numbers above. If the 'wrong direction' line is the higher one, rerun stage 4 with --flip-cue."
    print("\nSTAGE 5 " + verdict)
    ok = ok or few                       # too little evidence is reported, not treated as a crash
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
