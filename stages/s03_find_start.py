#!/usr/bin/env python3
"""Stage 3 (optional step 0) - FIND THE START OF THE GAME.

Title cards, highlight teasers and warm-ups all have players on court, so "players are
visible" is not enough. A real game has a rhythm: players stand almost still to set up a
serve, rally, stand still again. This script measures how much the court area moves at
10 fps, finds the quiet serve-setup windows, and proposes the first window that begins a
run of at least --min-chain such windows less than --max-gap seconds apart.

It is a SUGGESTION: it writes game_start.json (confirmed: false) and start_check.jpg, a sheet
of frames around the suggested start. Look at the sheet. If the game really starts there,
use "start" as --start for stage 3; if not, pick the right second yourself.

Run (needs stage 2 for the court area and stage 3a for the person counts):
    python stages/s03_find_start.py --proxy work/proxy.mp4 --cand work/cand.npz \
        --calib work/calib.json --out work/game_start.json

Output game_start.json: start, first_window_on, first_window_off, confirmed, windows (first 12)
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import median_filter

NET_Y = 6.7


def person_counts(cand_path):
    z = np.load(cand_path)
    D, cols = z["data"], list(z["cols"])
    c = {k: D[:, i] for i, k in enumerate(cols)}
    fps = float(z["fps"])
    X, Y = c["X"], c["Y"]
    far = Y >= NET_Y
    ok = (c["conf"] >= 0.3) & (c["h_per_ppm"] > 1.25) & (c["h_per_ppm"] < 2.5) & (Y > -2.5) & (Y < 13.8) \
        & np.where(far, (X > -0.3) & (X < 6.4), (X > -1.0) & (X < 7.0))
    frames = np.arange(0, int(c["f"].max()) + 1, int(z["stride"]))
    n = np.zeros(len(frames))
    index = {f: i for i, f in enumerate(frames)}
    for f in c["f"][ok].astype(int):
        n[index[f]] += 1
    return frames, n, fps


def court_energy(proxy, H, n_samples, stride):
    """mean absolute frame difference inside the court area (+1 m margin), 160x90 grey, per sampled frame"""
    corners = np.array([[-1, -1], [7.1, -1], [7.1, 14.4], [-1, 14.4]], np.float64).reshape(-1, 1, 2)
    cap = cv2.VideoCapture(str(proxy))
    W, Hh = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sx, sy = 160.0 / W, 90.0 / Hh
    poly = cv2.perspectiveTransform(corners, H).reshape(-1, 2) * [sx, sy]
    mask = np.zeros((90, 160), np.uint8)
    cv2.fillPoly(mask, [poly.astype(np.int32)], 1)
    energy, prev, i, k = np.zeros(n_samples), None, 0, 0
    while i < n_samples:
        if not cap.grab():
            break
        if k % stride == 0:
            ok, img = cap.retrieve()
            g = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32)
            if prev is not None:
                energy[i] = np.abs(g - prev)[mask > 0].mean()
            prev = g
            i += 1
        k += 1
    cap.release()
    return energy


def quiet_windows(t, energy, persons, thr, min_still):
    sm = median_filter(energy, size=5)                     # 0.5 s at 10 fps
    still = (sm < thr) & (median_filter(persons, size=5) >= 3)
    dt = float(np.median(np.diff(t)))
    runs, s = [], None
    for i, v in enumerate(list(still) + [False]):
        if v and s is None:
            s = i
        if not v and s is not None:
            if (i - s) * dt >= min_still:
                runs.append((float(t[s]), float(t[i - 1])))
            s = None
    return runs


def first_chain(runs, min_chain, max_gap):
    for i in range(len(runs)):
        n = 1
        while i + n < len(runs) and runs[i + n][0] - runs[i + n - 1][0] <= max_gap:
            n += 1
        if n >= min_chain:
            return i
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--cand", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--thr", type=float, default=0.8, help="court motion below this counts as 'still'")
    ap.add_argument("--min-still", type=float, default=1.5, help="seconds a quiet spell must last")
    ap.add_argument("--max-gap", type=float, default=30.0, help="max seconds between consecutive setup windows")
    ap.add_argument("--min-chain", type=int, default=4, help="setup windows in a row that make a game")
    args = ap.parse_args()

    H = np.array(json.loads(Path(args.calib).read_text())["H_court2img"])
    frames, persons, fps = person_counts(args.cand)
    stride = int(frames[1] - frames[0])
    print("measuring motion in the court area...")
    energy = court_energy(args.proxy, H, len(frames), stride)
    t = frames / fps
    runs = quiet_windows(t, energy, persons, args.thr, args.min_still)
    i0 = first_chain(runs, args.min_chain, args.max_gap)
    out = {"confirmed": False, "windows": [[round(a, 2), round(b, 2)] for a, b in runs[:12]],
           "method": f"first run of {args.min_chain}+ quiet serve-setup windows less than {args.max_gap:.0f} s apart"}
    if i0 is None:
        out.update({"start": None, "first_window_on": None, "first_window_off": None})
        Path(args.out).write_text(json.dumps(out, indent=1))
        raise SystemExit(f"No repeating serve-setup rhythm found ({len(runs)} quiet windows). Pick the start second by looking at the video.")
    on, off = runs[i0]
    out.update({"start": round(max(0.0, on - 1.0), 2), "first_window_on": round(on, 2),
                "first_window_off": round(min(off, on + 3.5), 2)})
    Path(args.out).write_text(json.dumps(out, indent=1))

    cap = cv2.VideoCapture(args.proxy)
    tiles = []
    for dt_ in (-12, -6, 0, 3, 8, 15):
        tm = max(0.0, on + dt_)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(tm * fps))
        ok, img = cap.read()
        if not ok:
            img = np.zeros((720, 1280, 3), np.uint8)
        cv2.putText(img, f"t={tm:.1f}s ({dt_:+d} s from the suggested start)", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 255, 255), 3, cv2.LINE_AA)
        tiles.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
    cap.release()
    sheet = Path(args.out).with_name("start_check.jpg")
    cv2.imwrite(str(sheet), np.vstack([np.hstack(tiles[:3]), np.hstack(tiles[3:])]), [cv2.IMWRITE_JPEG_QUALITY, 90])

    print(f"quiet windows found: {len(runs)} (first 8: {', '.join(f'{a:.1f}-{b:.1f}' for a, b in runs[:8])})")
    print(f"suggested start    : {out['start']} s   first serve window {out['first_window_on']}-{out['first_window_off']} s")
    print(f"written            : {args.out}\ncheck sheet        : {sheet}   <- does the game really start here? (the first tile is before it)")


if __name__ == "__main__":
    main()
