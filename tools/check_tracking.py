#!/usr/bin/env python3
"""Tracking check sheet - look at who got which label.

Stage 3 draws six small pictures. This makes a bigger sheet for the one check no program can do for you: does every label sit on the right
person? It shows twelve moments of one game, cropped to the court area: six spread evenly over the game and, in doubles, six where you
and your partner stood closest together (the moments where labels are most likely to swap).

    YELLOW box  YOU         RED box  YOUR PARTNER         BLUE / GREEN boxes  the opponents

Run:
    python tools/check_tracking.py --proxy work/proxy.mp4 --players work/g1/players.npz --out work/g1/qa_check.jpg
Then open the picture. If a label sits on the wrong person in any of the pictures, the numbers for that player are not to be trusted:
pick another picture in tools/pick_players.py or give the tracker a more distinctive cue.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np

SLOTS = {"A_you": ("YOU", (0, 255, 255)), "A_partner": ("PARTNER", (0, 0, 255)), "B_opp1": ("opp 1", (255, 0, 0)), "B_opp2": ("opp 2", (0, 200, 0))}


def pick_moments(z, n_even=6, n_close=6, min_gap_s=20.0, shift=0.0):
    """sample indices: evenly spread ones and (doubles) those where you and your partner are closest"""
    t = np.asarray(z["t"], float)
    present = [k for k in SLOTS if f"{k}_flag" in z and np.asarray(z[f"{k}_flag"]).astype(bool).any()]
    ok = np.zeros(len(t), bool)
    for k in present:
        ok |= (np.asarray(z[f"{k}_flag"]) == 1) & ~np.isnan(np.asarray(z[f"{k}_box"])[:, 0])
    span = (t[-1] - t[0] - 10) / n_even
    even = [int(np.argmin(np.abs(t - x))) for x in t[0] + 5 + span * (np.arange(n_even) + shift)]
    close = []
    if "A_partner" in present and "A_you" in present:
        a, b = np.asarray(z["A_you_xy"], float), np.asarray(z["A_partner_xy"], float)
        d = np.hypot(*(a - b).T)
        for i in np.argsort(np.where(np.isnan(d) | ~ok, 99, d)):
            if np.isnan(d[i]) or d[i] > 1.2:
                break
            if all(abs(t[i] - t[j]) > min_gap_s for j in close):
                close.append(int(i))
            if len(close) == n_close:
                break
    return sorted(set(even + close)), present


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--players", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--shift", type=float, default=0.0, help="0 to 1: move the evenly spread moments along, to look at different ones (default 0)")
    args = ap.parse_args(argv)
    z = np.load(args.players, allow_pickle=True)
    idx, present = pick_moments(z, shift=args.shift)
    cap = cv2.VideoCapture(args.proxy)
    frames = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(z["frames"][i]))
        ok, img = cap.read()
        if ok:
            frames.append((i, img))
    cap.release()
    if not frames:
        raise SystemExit("could not read any frame of the video")
    boxes = np.concatenate([np.asarray(z[f"{k}_box"], float)[:, :4] for k in present if k in ("A_you", "A_partner") or True])
    boxes = boxes[~np.isnan(boxes[:, 0])]
    h, w = frames[0][1].shape[:2]
    x1, y1 = max(0, int(np.percentile(boxes[:, 0], 2)) - 40), max(0, int(np.percentile(boxes[:, 1], 2)) - 30)
    x2, y2 = min(w, int(np.percentile(boxes[:, 2], 98)) + 40), min(h, int(np.percentile(boxes[:, 3], 98)) + 30)
    tiles = []
    for i, img in frames:
        for k in present:
            if int(np.asarray(z[f"{k}_flag"])[i]) and not np.isnan(np.asarray(z[f"{k}_box"], float)[i][0]):
                b = np.asarray(z[f"{k}_box"], float)[i]
                name, col = SLOTS[k]
                cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), col, 3)
                cv2.putText(img, name, (int(b[0]), max(16, int(b[1]) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2, cv2.LINE_AA)
        crop = img[y1:y2, x1:x2].copy()
        cv2.putText(crop, f"t={z['t'][i]:.0f}s", (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(crop, (680, int(680 * crop.shape[0] / crop.shape[1]))))
    th = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, th - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    if len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + 2]) for i in range(0, len(tiles), 2)])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"wrote {args.out}: {len(frames)} moments. Check that every label sits on the right person.")


if __name__ == "__main__":
    main()
