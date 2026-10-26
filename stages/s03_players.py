#!/usr/bin/env python3
"""Stage 3b - PLAYERS.

Turns the candidate boxes from stage 3a into four named player tracks in court metres.
Doubles, so two teams of two:
    team A = A_you + A_partner   <- the user's team
    team B = B_opp1 + B_opp2     <- the opponents
Shirt colours come from players_config.json (see examples/reference-match/players_config.json).
Which half of the court a team is on follows from where a bright "signature" shirt colour is
seen; the teams may swap ends once (found automatically). Inside a team, players are told apart
by shirt colour and by staying close to where they were a moment ago. Gaps up to 0.6 s are
filled and single-frame jumps removed.

Run:
    python stages/s03_players.py --proxy work/proxy.mp4 --cand work/cand.npz \
        --start 48.8 --out work/players.npz [--config work/players_config.json]
    --end-change none --first-near A|B     if no bright colour is available, say so by hand
    --end-change SECONDS --first-near A|B  if you already know when the teams swapped ends

Outputs next to --out: players.npz (tracks), players.json (summary), s03_check.jpg
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from common import NO_CHANGE, SLOTS as IDS, active_slots, load_config, match_mode, near_team_at, other, shorts_unreliable, signature, slot_probs

NET_Y = 6.7
COLOURS = {"A_partner": (0, 0, 255), "A_you": (0, 255, 255), "B_opp1": (255, 0, 0), "B_opp2": (0, 200, 0)}
FEATS = ("tL", "t_red", "t_blue", "t_green", "t_yellow", "t_orange", "lL", "l_white", "l_dark")


def load_candidates(path, start, min_conf, margin=1.0, margin_far=0.3, end=None, height_ratio=(1.25, 2.5)):
    z = np.load(path)
    D, cols = z["data"], list(z["cols"])
    c = {k: D[:, i] for i, k in enumerate(cols)}
    fps, stride = float(z["fps"]), int(z["stride"])
    t = c["f"] / fps
    X, Y = c["X"], c["Y"]
    far = Y >= NET_Y
    ok = (c["conf"] >= min_conf) & (c["h_per_ppm"] > height_ratio[0]) & (c["h_per_ppm"] < height_ratio[1]) & (t >= start) & (t < (end if end else 1e9)) \
        & (Y > -2.5) & (Y < 13.8) & np.where(far, (X > -margin_far) & (X < 6.1 + margin_far), (X > -margin) & (X < 6.1 + margin))
    out = {k: v[ok] for k, v in c.items()}
    out["_H"] = float(z["frame_h"]) if "frame_h" in z else 720.0            # the picture's height (older candidate files: the proxy is 720 high)
    return out, fps, stride


def estimate_height_window(path):
    """(low, high) for how tall a person's box may be, in metres by the court's own scale. A wide-angle lens makes real players read taller
    than a normal lens does, so the window follows the video: the median over confident near-half boxes decides. Normal videos (median up
    to 2.1) keep 1.25 to 2.5; wider ones get 0.55 to 1.55 times their median (2.45 gives 1.35 to 3.8)."""
    z = np.load(path)
    d = {k: z["data"][:, i] for i, k in enumerate(list(z["cols"]))}
    m = (d["conf"] > 0.6) & (d["Y"] > 0) & (d["Y"] < 6.2) & (d["X"] > -0.5) & (d["X"] < 6.6) & ((d["y2"] - d["y1"]) > 90)
    if m.sum() < 200:
        return 1.25, 2.5
    med = float(np.median(d["h_per_ppm"][m]))
    if med <= 2.1:
        return 1.25, 2.5
    return round(0.55 * med, 2), round(min(5.0, 1.55 * med), 2)


def dedupe(idxs, c):
    keep = []
    for i in sorted(idxs, key=lambda i: -c["conf"][i]):
        dup = False
        for j in keep:
            if np.hypot(c["X"][i] - c["X"][j], c["Y"][i] - c["Y"][j]) < 0.35:
                ix1, iy1 = max(c["x1"][i], c["x1"][j]), max(c["y1"][i], c["y1"][j])
                ix2, iy2 = min(c["x2"][i], c["x2"][j]), min(c["y2"][i], c["y2"][j])
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                a = (c["x2"][i] - c["x1"][i]) * (c["y2"][i] - c["y1"][i])
                if inter / a > 0.3:
                    dup = True
                    break
        if not dup:
            keep.append(i)
    return keep


def signature_mask(c, cfg):
    """(team, per-candidate mask) of detections that clearly belong to one named person, used to see which half that team is on.
    A chromatic shirt colour is the best cue. Without one, A_you's clothes are used where they are clearly not the partner's (in singles:
    not the opponent's), e.g. light shorts when the partner wears dark ones. Returns (None, None) if there is nothing to go on."""
    sig = signature(cfg)
    if sig is not None:
        return sig[0], c["t_" + sig[1]] > 0.12
    feats = {k: c[k] for k in FEATS + ("sL",) if k in c}
    feats["wide"] = shorts_unreliable(c["x1"], c["y1"], c["x2"], c["y2"], c.get("_H", 720.0))
    if "sL" in feats:
        bad = ~np.isfinite(feats["sL"])
        feats["wide"] = feats["wide"] | bad
        feats["sL"] = np.where(bad, 0.0, feats["sL"])
    p = slot_probs(cfg, feats)
    n = len(c["f"])
    P = {k: np.broadcast_to(np.asarray(v, float), (n,)) for k, v in p.items()}
    rival = "B_opp1" if match_mode(cfg) == "singles" else "A_partner"
    if cfg["A_you"]["shirt"] == "any" and not cfg["A_you"].get("shorts"):
        return None, None
    return "A", (P["A_you"] >= 0.85) & (P[rival] <= 0.2)


def find_end_change(c, fps, start, sig_team, sig_mask):
    """When do the teams swap ends? Looks at where the detections in sig_mask (worn by sig_team) are seen, far half or near half, over
    time. Returns (tc, first_near_team, strength); tc is NO_CHANGE if the teams never swap."""
    t = c["f"] / fps
    sig = np.asarray(sig_mask, bool)
    grid = np.arange(start + 3, t.max() - 3, 1.0)
    s = []
    for g in grid:
        m = (t >= g - 3) & (t < g + 3)
        nr = sig[m & (c["Y"] < NET_Y)].mean() if (m & (c["Y"] < NET_Y)).any() else 0
        fr = sig[m & (c["Y"] >= NET_Y)].mean() if (m & (c["Y"] >= NET_Y)).any() else 0
        s.append(fr - nr)               # > 0: the signature team is on the far half
    s = np.array(s)
    best, tc, sign = 0.0, None, 1
    for i in range(5, len(grid) - 5):   # single change point
        d = s[:i].mean() - s[i:].mean()
        if abs(d) > best:
            best, tc, sign = abs(d), float(grid[i]), (1 if d > 0 else -1)
    if best >= 0.35:
        return tc, (other(sig_team) if sign > 0 else sig_team), best
    return NO_CHANGE, (other(sig_team) if s.mean() > 0 else sig_team), best


def early_side(c, fps, start, sig_team, sig_mask, seconds=90.0):
    """(team on the near half at the start, share of the evidence that says so): the first `seconds` of the game."""
    t = c["f"] / fps
    m = (t >= start) & (t < start + seconds) & np.asarray(sig_mask, bool)
    if m.sum() < 15:
        return None, 0.0
    near = float((c["Y"][m] < NET_Y).mean())
    return (sig_team if near >= 0.5 else other(sig_team)), max(near, 1 - near)


PERSIST = 12         # samples (1.2 s) of readable clothes that contradict a label before an unbroken track stops being trusted over them


def team_prob(cand_i, c, cfg):
    """(probability of each slot from the clothes, True if the shorts could not be read for this box)"""
    f = {k: c[k][cand_i] for k in FEATS + ("sL",) if k in c}
    f["wide"] = bool(shorts_unreliable(c["x1"][cand_i], c["y1"][cand_i], c["x2"][cand_i], c["y2"][cand_i], c.get("_H", 720.0)))
    if "sL" in f and not np.isfinite(f["sL"]):             # an empty band (a box at the very edge): no reading, not a NaN that poisons the assignment
        f["sL"], f["wide"] = 0.0, True
    return slot_probs(cfg, f), f["wide"]


def track(c, fps, stride, tc, first_near, start, cfg, min_appearance=0.0):
    by_f = {}
    for i in range(len(c["f"])):
        by_f.setdefault(int(c["f"][i]), []).append(i)
    frames = np.arange(int(start * fps) // stride * stride, int(c["f"].max()) + 1, stride)
    n = len(frames)
    pos = {k: np.full((n, 2), np.nan, np.float32) for k in IDS}
    box = {k: np.full((n, 5), np.nan, np.float32) for k in IDS}
    last = {k: None for k in IDS}  # (frame_index_in_array, X, Y)
    bad = {k: 0 for k in IDS}      # consecutive samples in which readable clothes contradict the person this slot holds
    for r, f in enumerate(frames):
        t = f / fps
        cands = dedupe(by_f.get(int(f), []), c)
        if not cands:
            continue
        near_team = near_team_at(t, tc, first_near)
        cost = np.full((len(cands), 4), 1e6)
        info = {}
        for a, i in enumerate(cands):
            Y = c["Y"][i]
            p, unreadable = team_prob(i, c, cfg)
            info[a] = (p, unreadable)
            for b, k in enumerate(IDS):
                if cfg[k].get("inactive"):
                    continue
                team_is_near = (k[0] == near_team)
                if (Y < 6.2 and not team_is_near) or (Y > 7.2 and team_is_near):
                    continue
                move, tight = 0.0, False
                if last[k] is not None and r - last[k][0] <= 10:
                    d = np.hypot(c["X"][i] - last[k][1], c["Y"][i] - last[k][2])
                    move = 1.2 * min(d / 1.5, 3.0)
                    tight = d < 0.6 and r - last[k][0] <= 3 and bad[k] < PERSIST   # this slot was here a moment ago: the person is almost certainly the same
                if p[k] < min_appearance and not tight:               # clothes clearly say this is someone else (unless the track runs on unbroken)
                    continue
                cue = -np.log(p[k] + 0.03)
                cost[a, b] = (0.3 * cue if tight else cue) + move
        cost = np.nan_to_num(cost, nan=1e6, posinf=1e6, neginf=1e6)         # a feature that could not be read makes a pairing impossible, it must not stop the run
        ri, ci = linear_sum_assignment(cost)
        held = set()
        for a, b in zip(ri, ci):
            if cost[a, b] > 4.5:
                continue
            held.add(IDS[b])
            k, i = IDS[b], cands[a]
            p_k, unreadable = info[a]
            bad[k] = bad[k] + 1 if (min_appearance > 0 and not unreadable and p_k[k] < min_appearance) else 0
            pos[k][r] = (c["X"][i], c["Y"][i])
            box[k][r] = (c["x1"][i], c["y1"][i], c["x2"][i], c["y2"][i], c["conf"][i])
            last[k] = (r, c["X"][i], c["Y"][i])
        for k in IDS:
            if k not in held:
                bad[k] = 0
    return frames, pos, box


def clean(pos, max_gap=6, win=7, tol=1.2):
    """Hampel despike, linear gap fill (<= max_gap samples), then a 5-sample median."""
    out, flag = {}, {}
    for k, p in pos.items():
        p = p.copy()
        n = len(p)
        for ax in (0, 1):
            x = p[:, ax]
            for i in range(n):
                if np.isnan(x[i]):
                    continue
                lo, hi = max(0, i - win // 2), min(n, i + win // 2 + 1)
                nb = x[lo:hi][~np.isnan(x[lo:hi])]
                if len(nb) >= 3 and abs(x[i] - np.median(nb)) > tol:
                    p[i, :] = np.nan
        raw_valid = ~np.isnan(p[:, 0])
        f = np.zeros(n, np.int8)                 # 0 missing, 1 detected, 2 interpolated
        f[raw_valid] = 1
        idx = np.where(raw_valid)[0]
        for a, b in zip(idx[:-1], idx[1:]):
            if 1 < b - a <= max_gap + 1:
                for ax in (0, 1):
                    p[a + 1:b, ax] = np.linspace(p[a, ax], p[b, ax], b - a + 1)[1:-1]
                f[a + 1:b] = 2
        sm = p.copy()
        for ax in (0, 1):
            for i in range(n):
                lo, hi = max(0, i - 2), min(n, i + 3)
                v = p[lo:hi, ax][~np.isnan(p[lo:hi, ax])]
                if len(v) >= 3 and not np.isnan(p[i, ax]):
                    sm[i, ax] = np.median(v)
        out[k], flag[k] = sm, f
    return out, flag


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--cand", required=True)
    ap.add_argument("--start", type=float, required=True, help="second the real game starts (skip any teaser)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-conf", type=float, default=0.25)
    ap.add_argument("--end", type=float, help="second the game ends (default: the end of the video); use it for a video with several games")
    ap.add_argument("--margin", type=float, default=1.0, help="metres beyond the near sidelines where a person may still be a player (default %(default)s; smaller keeps neighbouring courts out)")
    ap.add_argument("--margin-far", type=float, default=0.3, help="the same for the far half (default %(default)s)")
    ap.add_argument("--height-ratio", default="auto", help="LOW,HIGH: how tall a person's box may be, in metres by the court's own scale "
                    "(default auto: 1.25,2.5 for a normal lens, wider when the video was filmed with a wide-angle lens, see estimate_height_window)")
    ap.add_argument("--min-appearance", default="auto", help="a person is never given a slot whose clothes match with less than this "
                    "probability (default auto: 0.1 when players are told apart by shorts or shade, otherwise off; 0.1 stops the tracker handing the "
                    "partner's label to you when the partner is out of view)")
    ap.add_argument("--config", help="players_config.json (default: next to --out)")
    ap.add_argument("--end-change", default="auto", help="auto, none, or the second the teams swapped ends")
    ap.add_argument("--first-near", choices=["A", "B"], help="team on the near half at the start (needed with --end-change none or a number)")
    args = ap.parse_args()

    cfg = load_config(args.config or Path(args.out).with_name("players_config.json"))
    if args.height_ratio == "auto":
        lo, hi = estimate_height_window(args.cand)
        print(f"person size window: {lo} to {hi} (from the video's lens)")
    else:
        lo, hi = (float(v) for v in args.height_ratio.split(","))
    c, fps, stride = load_candidates(args.cand, args.start, args.min_conf, args.margin, args.margin_far, args.end, (lo, hi))
    if args.min_appearance == "auto":
        cues = any(cfg[k].get("shorts") or cfg[k].get("tone") for k in active_slots(cfg))
        min_app = 0.1 if cues else 0.0
    else:
        min_app = float(args.min_appearance)
    sig_team, sig_mask = signature_mask(c, cfg)
    side, share = early_side(c, fps, args.start, sig_team, sig_mask) if sig_team is not None else (None, 0.0)
    if args.end_change == "auto":
        if sig_team is None:
            if not args.first_near:
                raise SystemExit("Nothing in players_config.json is distinctive enough to see which half a team is on (no bright shirt, no clear "
                                 "shorts). Pass --end-change none (or SECONDS) and --first-near A|B.")
            tc, first_near, strength = NO_CHANGE, args.first_near, float("nan")
            print(f"end change: not looked for (no distinctive clothes); team {first_near} starts on the near half as given")
        else:
            tc, first_near, strength = find_end_change(c, fps, args.start, sig_team, sig_mask)
            if tc == NO_CHANGE:
                if side is not None and share >= 0.85:
                    if args.first_near and side != args.first_near:
                        print(f"note: the clothes say team {side} starts on the near half ({100 * share:.0f}% of the first 90 s); using that instead of --first-near {args.first_near}")
                    first_near = side
                elif args.first_near:
                    first_near = args.first_near
            what = "never (teams stay on their halves)" if tc == NO_CHANGE else f"t = {tc:.0f} s"
            print(f"end change: {what}; team {first_near} starts on the near half (separation {strength:.2f})")
    else:
        first_near = args.first_near
        if not first_near:
            if side is None or share < 0.7:
                raise SystemExit("--first-near A|B is needed together with --end-change none or SECONDS (the clothes do not say which team starts on the near half)")
            first_near = side
            print(f"team {first_near} starts on the near half ({100 * share:.0f}% of the first 90 s of evidence)")
        elif side is not None and share >= 0.85 and side != first_near:
            print(f"WARNING: the clothes say team {side} is on the near half at the start ({100 * share:.0f}% of the evidence), "
                  f"but --first-near {first_near} was given. Check which end you were at.")
        strength = float("nan")
        tc = NO_CHANGE if args.end_change == "none" else float(args.end_change)
        print(f"end change given by hand: {args.end_change}; team {first_near} starts on the near half")
    frames, pos_raw, box = track(c, fps, stride, tc, first_near, args.start, cfg, min_app)
    pos, flag = clean(pos_raw)
    t = frames / fps

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    save = {"frames": frames, "t": t, "fps": fps, "stride": stride, "tc": tc, "first_near": np.array(first_near)}
    for k in IDS:
        save[f"{k}_xy"], save[f"{k}_flag"], save[f"{k}_box"] = pos[k], flag[k], box[k]
    np.savez_compressed(out, **save)

    act = active_slots(cfg)
    cov = {k: float((flag[k] > 0).mean()) for k in act}
    det = {k: float((flag[k] == 1).mean()) for k in act}
    speeds = {}
    for k in act:
        v = np.linalg.norm(np.diff(pos[k], axis=0), axis=1) / (stride / fps)
        v = v[~np.isnan(v)]
        speeds[k] = (float(np.median(v)), float(np.percentile(v, 99)), float((v > 9).mean())) if len(v) else (float("nan"),) * 3
    summ = {"tc": tc, "first_near": first_near, "start": args.start, "coverage": cov, "detected_only": det,
            "speed_median_p99_over9": speeds}
    out.with_suffix(".json").write_text(json.dumps(summ, indent=1))

    # annotated check frames: 6 moments spread over the game
    cap = cv2.VideoCapture(args.proxy)
    picks = np.linspace(len(frames) * 0.05, len(frames) * 0.95, 6).astype(int)
    tiles = []
    for r in picks:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frames[r]))
        ok, img = cap.read()
        for k in act:
            if flag[k][r] and not np.isnan(box[k][r][0]):
                x1, y1, x2, y2, _ = box[k][r]
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), COLOURS[k], 3)
                cv2.putText(img, k, (int(x1), max(18, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, COLOURS[k], 2, cv2.LINE_AA)
        cv2.putText(img, f"t={t[r]:.1f}s", (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
    cap.release()
    cv2.imwrite(str(out.with_name("s03_check.jpg")),
                np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:])]), [cv2.IMWRITE_JPEG_QUALITY, 92])

    print("\nper player: frames with a position (detected + filled) | detected only | median speed m/s | 99th pct | share > 9 m/s")
    for k in act:
        print(f"  {k:8s} {100 * cov[k]:5.1f}% | {100 * det[k]:5.1f}% | {speeds[k][0]:.2f} | {speeds[k][1]:.2f} | {100 * speeds[k][2]:.2f}%")
    print(f"\ntracks : {out}\nsummary: {out.with_suffix('.json')}\nsheet  : {out.with_name('s03_check.jpg')}  <- every label must sit on the right person")
    ok = all(cov[k] > 0.6 for k in act) and all(speeds[k][2] < 0.01 for k in act) and (tc == NO_CHANGE or strength >= 0.35 or args.end_change != "auto")
    print("\nSTAGE 3 " + ("PASSED (automatic checks); now do the visual check." if ok else "FAILED: see numbers above."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
