#!/usr/bin/env python3
"""Stage 14a - COACHING AND SCOUTING WORDS FOR A VIDEO WITH NO SCORE (rule-based).

Stage 14 lays out tips.json and scouting.json. An AI assistant can write those from the numbers (CLAUDE.md), but the run should not need one, so this
stage writes a first version by rules: each tip is a sentence template that is only used when the numbers call for it, with the numbers filled in. Every
tip says what it rests on and how sure it is. It never talks about winning or losing a point (the video does not show who won), and it asks questions
about the video where a number can only raise one.

Existing tips.json / scouting.json are kept unless --force is given. words_source.json records "automatic" so the report can say so.

Run:
    python stages/s14a_free_words.py --work work_m1 [--force]
"""
import argparse
import json
from pathlib import Path

import numpy as np

import s14_free_report as rep


class V(list):
    """values taken from the games, remembering which game each came from"""
    titles = ()


def pct(x):
    return f"{100 * x:.0f}%"


def _per_game(xs, fmt):
    ts = getattr(xs, "titles", ())
    if len(xs) <= 1 or len(ts) != len(xs):
        return " and ".join(fmt(x) for x in xs)
    return " and ".join(f"{fmt(x)} ({t.lower()})" for x, t in zip(xs, ts))


def join_pct(xs):
    return _per_game(xs, pct)


def both(xs, f="{}"):
    return _per_game(xs, lambda x: f.format(x))


def vals(games, fn, only=None):
    out, titles = V(), []
    for g in games:
        if only and g["you_side"] != only:
            continue
        try:
            v = fn(g)
        except (KeyError, TypeError):
            v = None
        if v is not None:
            out.append(v)
            titles.append(g["title"])
    out.titles = tuple(titles)
    return out


def tips_doubles(cfg):
    G, hand, out = cfg["games"], cfg.get("racket_hand"), []
    team = lambda g: g["S"]["teams"].get("A")
    fb = vals(G, lambda g: team(g)["front_back"])
    sbs = vals(G, lambda g: team(g)["side_by_side"])
    front = vals(G, lambda g: g["S"]["slots"]["A_you"]["zones"]["depth"]["front"])
    if fb and np.mean(fb) <= 0.2:
        out.append({"kind": "improve", "title": "Try going front and back more often",
                    "body": f"Your pair stood front-and-back (one of you at least 2.5 m deeper than the other) for only {join_pct(fb)} of play, and the front court (the first 2.2 m from the net) "
                            f"held you for {join_pct(front)} of the time. Most of the time you were side by side in the middle of your half ({join_pct(sbs)}). The video cannot show whether "
                            "you were attacking or defending at those moments, so this is a question, not a verdict.",
                    "try": "In a practice game, agree that after an attacking shot (a smash or a steep drop) one of you steps in to the net and the other holds the back, then compare "
                           "how those rallies go with your usual side-by-side ones.",
                    "watch": "Watch the longest plays listed at the end of this report and notice who is where when you hit downwards.",
                    "sure": "Where you stood: solid when you were near the camera, a little rougher in depth when far. Why you stood there: not measured."})
    elif fb and np.mean(fb) >= 0.35:
        out.append({"kind": "strength", "title": "You use the front-and-back formation",
                    "body": f"Your pair stood front and back for {join_pct(fb)} of play, which is a lot: it is the formation that suits attacking play.",
                    "sure": "Solid for positions; the video cannot show how the rallies ended."})
    wid = vals(G, lambda g: team(g)["gap_width_median"])
    close = vals(G, lambda g: team(g)["close_together"])
    oclose = vals(G, lambda g: g["S"]["teams"]["B"]["close_together"])
    if wid and np.mean(wid) < 2.0 and np.mean(close) >= 0.4:
        extra = f" The opponents did the same ({join_pct(oclose)} of the time within 1.5 m), so it may be normal at this level, but it is also a gap that a wide cross-court shot can find." if oclose else ""
        out.append({"kind": "improve", "title": "Spread out a little when defending",
                    "body": f"You and your partner were usually only {both(wid, '{:.1f} m')} apart across the court and within 1.5 m of each other for "
                            f"{join_pct(close)} of play. Splitting the width of the court in half would put you about 3 m apart. A narrow pair leaves wide gaps at both sidelines." + extra,
                    "try": "When you defend side by side, aim to stand about half the court width apart and each own your half, with the middle shared by whoever has the forehand.",
                    "sure": "Solid when you were near the camera; approximate when far."})
    rear = vals(G, lambda g: 1 - team(g)["first_at_back_when_front_back"] if team(g)["front_back"] * team(g)["n"] >= 80 else None)
    if len(rear) >= 1 and (min(rear) >= 0.6 or max(rear) <= 0.4):
        who, shares = ("your partner", rear) if min(rear) >= 0.6 else ("you", [1 - r for r in rear])
        swaps = vals(G, lambda g: team(g)["rear_swaps"])
        out.append({"kind": "check", "title": "Who plays the back court, and is it on purpose?",
                    "body": f"When you did go front and back, {who} {'was' if who == 'you' else 'was'} the one at the back in {join_pct(shares)} of those moments"
                            f": "
                            f"{'you were mostly the front or middle player' if who == 'your partner' else 'your partner was mostly the front or middle player'}. The back-court job swapped between you "
                            f"{both(swaps)} times. That is a consistent split, which is good if you chose it. It is worth checking that the swaps happen cleanly "
                            "and that you are not both left in the mid-court when the shuttle goes to the back.",
                    "watch": "Look for rallies in the longest plays where both of you are in the middle of the court at the same time.",
                    "sure": "Approximate: it rests on the share of play when you were front and back."})
    left = vals(G, lambda g: team(g)["first_on_left_when_side_by_side"])
    if left and (max(left) - min(left) >= 0.2 or min(left) <= 0.35 or max(left) >= 0.65):
        mine = join_pct(left)
        ht = {"left": " As a left-hander you may prefer the right-hand side of the pair, so it is worth deciding on purpose who takes which side and the middle, instead of letting it drift.",
              "right": " It is worth deciding on purpose who takes which side and the middle, instead of letting it drift."}.get(hand, " It is worth deciding on purpose who takes which side and the middle.")
        out.append({"kind": "check", "title": "Which side each of you stands on" if max(left) - min(left) < 0.2 else "The left and right split changed between the games",
                    "body": f"When you stood side by side you were on the pair's left for {mine} of the time{'' if len(left) == 1 else ' (game by game)'}." + ht,
                    "watch": "Pick one rally from each game and see which of you takes the shuttle that comes down the middle.",
                    "sure": "Good when you were near the camera; left and right stay reliable when far."})
    near_pose = [(g["POSE"].get("A_you"), g["POSE"].get("A_partner")) for g in G if g["you_side"] == "near" and g["POSE"].get("A_you", {}).get("samples", 0) >= 200]
    if near_pose:
        you, mate = near_pose[0]
        n = you["samples"]
        if you["bent_lt150"] < 0.2:
            out.append({"kind": "check", "title": "Stand a little lower in your ready position",
                        "body": f"Your knees were bent below 150 degrees in only {pct(you['bent_lt150'])} of the body-point samples" + (f" (your partner {pct(mate['bent_lt150'])})" if mate else "") +
                                f"; the rest of the time you were standing upright or walking. Your feet were about {you['stance_median']:.1f} shoulder widths apart. A lower, wider base helps you push off quickly in any direction.",
                        "try": "Between shots, sink a little at the knees with the weight on the balls of your feet, so the first step comes from a loaded position.",
                        "sure": f"Approximate. It uses a body-point model on frames where you were close to the camera (about {n:,} samples); the view from behind makes knee angles less exact."})
        up = you.get("racket_up_share")
        if up is not None and up >= 0.75:
            hand_txt = f" That is the hand you told us you use ({hand})." if hand else ""
            out.append({"kind": "strength", "title": "Your racket hand is up and ready",
                        "body": f"Your racket hand was held up (wrist above your hip) in {pct(up)} of the body-point samples" + (f", and your partner's in {pct(mate['racket_up_share'])}" if mate and mate.get("racket_up_share") is not None else "") +
                                f". That is a good habit in doubles, where the shuttle comes back fast.{hand_txt}",
                        "sure": f"Approximate, from about {n:,} samples of you."})
    blocks = vals(G, lambda g: [b["per_play_min"] for b in g["S"]["blocks"]["A_you"] if b["per_play_min"] is not None], only="near") or \
        vals(G, lambda g: [b["per_play_min"] for b in g["S"]["blocks"]["A_you"] if b["per_play_min"] is not None])
    if blocks and all(len(b) >= 3 for b in blocks):
        lo, hi = min(min(b) for b in blocks), max(max(b) for b in blocks)
        fade = any(np.mean(b[-2:]) < 0.7 * np.mean(b[:2]) for b in blocks)
        mates = vals(G, lambda g: g["S"]["slots"]["A_partner"]["distance_per_play_min"])
        yours = vals(G, lambda g: g["S"]["slots"]["A_you"]["distance_per_play_min"])
        if fade:
            out.append({"kind": "check", "title": "Your work rate drops late in a game",
                        "body": f"Over 2-minute blocks you moved between {lo:.0f} and {hi:.0f} metres per minute of play, and in at least one game the last blocks were well below the first.",
                        "watch": "Compare how you move in the first and last minutes of that game on the video.",
                        "sure": "Approximate: each block holds about a minute of play."})
        else:
            out.append({"kind": "strength", "title": "You keep your work rate steady",
                        "body": f"You moved {lo:.0f} to {hi:.0f} metres per minute of play across all the 2-minute blocks, with no steady fade. Over a whole game you averaged {both(yours, '{:.0f}')} metres per play-minute, "
                                f"your partner {both(mates, '{:.0f}')}.",
                        "sure": "Approximate: each block holds about a minute of play. Numbers for a game where you are on the far half read a little high."})
    short = vals(G, lambda g: g["S"]["plays"]["short_share"])
    if short and np.mean(short) >= 0.35:
        out.append({"kind": "check", "title": "Many plays end within five seconds",
                    "body": f"{join_pct(short)} of the plays lasted under 5 s. Short plays are usually a serve, a return or a quick finish, so they are worth a look: who is hitting first and where.",
                    "watch": "Find a handful of short plays on the video (the plays list gives the long ones; short ones are the gaps between them).",
                    "sure": "Approximate: plays come from movement and shuttle sound, and a very short one can be a false start."})
    return out


def tips_singles(cfg):
    G, hand, out = cfg["games"], cfg.get("racket_hand"), []
    z = vals(G, lambda g: g["S"]["slots"]["A_you"]["zones"])
    if z:
        back = [x["depth"]["back"] for x in z]
        front = [x["depth"]["front"] for x in z]
        mid = [x["depth"]["middle"] for x in z]
        if np.mean(back) >= 0.3:
            out.append({"kind": "check", "title": "A lot of your time is in the back court",
                        "body": f"You spent {join_pct(back)} of play in the back court (the last 2.2 m before the baseline), {join_pct(mid)} in the middle and {join_pct(front)} at the front. "
                                "In singles, being pushed back is often a sign of defending: the video cannot say whether you chose to stand there.",
                        "watch": "On the longest plays, look at where you stand between shots: do you come back to the middle of your half?", "sure": "Solid when you were near the camera."})
        else:
            out.append({"kind": "check", "title": "Where you stand between shots",
                        "body": f"You spent {join_pct(front)} of play at the front, {join_pct(mid)} in the middle and {join_pct(back)} at the back of your half.",
                        "watch": "On the longest plays, look at whether you return to the middle of your half after each shot.", "sure": "Solid when you were near the camera."})
    near_pose = [g["POSE"].get("A_you") for g in G if g["you_side"] == "near" and g["POSE"].get("A_you", {}).get("samples", 0) >= 200]
    if near_pose:
        you = near_pose[0]
        if you["bent_lt150"] < 0.2:
            out.append({"kind": "check", "title": "Stand a little lower in your ready position",
                        "body": f"Your knees were bent below 150 degrees in only {pct(you['bent_lt150'])} of the body-point samples. A lower, wider base helps you push off quickly, and singles is mostly about the first step.",
                        "try": "Between shots, sink a little at the knees with the weight on the balls of your feet.", "sure": "Approximate: the view from behind makes knee angles less exact."})
        up = you.get("racket_up_share")
        if up is not None and up >= 0.75:
            out.append({"kind": "strength", "title": "Your racket hand is up and ready",
                        "body": f"Your racket hand was held up (wrist above your hip) in {pct(up)} of the body-point samples" + (f" ({hand}-handed, as you told us)" if hand else "") + ".",
                        "sure": "Approximate, from the frames where you were close to the camera."})
    blocks = vals(G, lambda g: [b["per_play_min"] for b in g["S"]["blocks"]["A_you"] if b["per_play_min"] is not None])
    if blocks and all(len(b) >= 3 for b in blocks):
        lo, hi = min(min(b) for b in blocks), max(max(b) for b in blocks)
        fade = any(np.mean(b[-2:]) < 0.7 * np.mean(b[:2]) for b in blocks)
        out.append({"kind": "check" if fade else "strength", "title": "Your work rate drops late in a game" if fade else "You keep your work rate steady",
                    "body": f"Over 2-minute blocks you moved between {lo:.0f} and {hi:.0f} metres per minute of play" + (", and the last blocks of at least one game were well below the first." if fade else ", with no steady fade."),
                    "sure": "Approximate: each block holds about a minute of play."})
    short = vals(G, lambda g: g["S"]["plays"]["short_share"])
    if short and np.mean(short) >= 0.35:
        out.append({"kind": "check", "title": "Many plays end within five seconds",
                    "body": f"{join_pct(short)} of the plays lasted under 5 s: usually a serve, a return or a quick finish.",
                    "sure": "Approximate: plays come from movement and shuttle sound."})
    return out


def scouting_doubles(cfg):
    G = cfg["games"]
    st, wk, plan = [], [], []
    B = vals(G, lambda g: g["S"]["teams"]["B"])
    if B:
        sbs, fb = [b["side_by_side"] for b in B], [b["front_back"] for b in B]
        close = [b["close_together"] for b in B]
        st.append({"title": "How they set up as a pair",
                   "body": f"The two opponents stood side by side for {join_pct(sbs)} of play and front-and-back for {join_pct(fb)}; they were within 1.5 m of each other across the court for {join_pct(close)} of the time. "
                           + ("They defend as a tight pair around the middle." if np.mean(close) >= 0.5 else "They keep some width between them."),
                   "sure": "Pair numbers from positions only: no shot data. Solid when they were near the camera, rougher when far."})
        if np.mean(close) >= 0.5:
            wk.append({"title": "Wide sidelines", "body": "Because they bunch (within 1.5 m across for more than half the time), the outer 2 m or more on each side of their half is often unguarded.",
                       "sure": "Approximate; width is the more reliable direction of the tracking."})
    opp = [g for g in G if "B_opp1" in g["S"]["slots"] and "B_opp2" in g["S"]["slots"]]
    dist = [(g["S"]["slots"]["B_opp1"]["distance_per_play_min"], g["S"]["slots"]["B_opp2"]["distance_per_play_min"]) for g in opp]
    if dist and all(abs(a - b) / max(a, b) >= 0.2 for a, b in dist) and (all(a > b for a, b in dist) or all(a < b for a, b in dist)):
        more = "B_opp1" if dist[0][0] > dist[0][1] else "B_opp2"
        desc = cfg.get("opponent_descriptions", {}).get(more) or ("the first opponent" if more == "B_opp1" else "the second opponent")
        st.append({"title": f"One opponent does most of the running ({desc})",
                   "body": "In every game one opponent moved at least 20% more than the other: " + "; ".join(f"{max(a, b):.0f} against {min(a, b):.0f} metres per minute of play" for a, b in dist) + ".",
                   "sure": "A hint only. Telling the two opponents apart relies on clothes in a dim hall; check the 'How sure' page."})
    near = [g for g in G if g["you_side"] == "far" and "B_opp1" in g["S"]["slots"]]            # opponents near the camera: depth is reliable
    if near:
        g = near[0]
        f = [g["S"]["slots"][k]["zones"]["depth"]["front"] for k in ("B_opp1", "B_opp2")]
        d = g["S"]["teams"]["B"]["pair_depth_mean"] if g["S"]["teams"].get("B") else None
        mine = g["S"]["teams"]["A"]["pair_depth_mean"] if g["S"]["teams"].get("A") else None
        if max(f) <= 0.08:
            wk.append({"title": f"The front court was left empty in {g['title'].lower()}",
                       "body": f"In {g['title'].lower()} the opponents spent only {pct(min(f))} to {pct(max(f))} of play in the front court (the first 2.2 m from the net)" +
                               (f" and stood on average {d:.1f} m from the net" + (f" (your pair {mine:.1f} m)" if mine else "") if d else "") + ". If that is how they defend, short net shots and drops are the space they leave.",
                       "sure": "Position only: it does not show whether net shots won points against them."})
    if wk:
        plan.append({"title": "Test the space they leave", "body": "Mix soft shots to the net and wide cross-court shots into your usual exchanges, and watch the longest plays listed at the end to see how they respond.",
                     "try": "Pick two plays per game to rewatch and note where each opponent was when you hit the shuttle.",
                     "sure": "This is a hypothesis from positions only. The score is not in the video, so it cannot say which tactic won points."})
    return {"strengths": st, "weaknesses": wk, "plan": plan}


def scouting_singles(cfg):
    G = cfg["games"]
    st, wk, plan = [], [], []
    z = vals(G, lambda g: g["S"]["slots"]["B_opp1"]["zones"]["depth"])
    if z:
        back, front = [x["back"] for x in z], [x["front"] for x in z]
        dist = vals(G, lambda g: g["S"]["slots"]["B_opp1"]["distance_per_play_min"])
        st.append({"title": "Where your opponent stands", "body": f"They spent {join_pct(front)} of play at the front of their half and {join_pct(back)} at the back, and moved {both(dist, '{:.0f}')} metres per minute of play.",
                   "sure": "Position only; depth is rougher when they were on the far half."})
        if np.mean(front) <= 0.1:
            wk.append({"title": "The front court may be open", "body": f"They spent only {join_pct(front)} of play at the front of their half, so short shots to the net are worth testing.",
                       "sure": "Position only: it does not show whether net shots won points."})
            plan.append({"title": "Test the net", "body": "Mix a few short net shots into your usual exchanges and rewatch the longest plays to see how they respond.", "sure": "A hypothesis from positions only."})
    return {"strengths": st, "weaknesses": wk, "plan": plan}


def build_words(cfg):
    singles = cfg["mode"] == "singles"
    tips = (tips_singles if singles else tips_doubles)(cfg)
    scout = (scouting_singles if singles else scouting_doubles)(cfg)
    return tips, scout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--force", action="store_true", help="replace tips.json and scouting.json even if they exist")
    args = ap.parse_args()
    W = Path(args.work)
    cfg = rep.load(W)
    wrote = []
    tips, scout = build_words(cfg)
    for name, doc in (("tips.json", tips), ("scouting.json", scout)):
        if (W / name).exists() and not args.force:
            print(f"kept the existing {name}")
            continue
        (W / name).write_text(json.dumps(doc, indent=1) + "\n")
        wrote.append(name)
    if wrote:
        (W / "words_source.json").write_text(json.dumps({"source": "automatic", "files": wrote}) + "\n")
        print(f"wrote {', '.join(wrote)}: {len(tips)} tips, {sum(len(v) for v in scout.values())} scouting notes (automatic wording from the numbers)")


if __name__ == "__main__":
    main()
