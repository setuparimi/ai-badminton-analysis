#!/usr/bin/env python3
"""Stage 3a - CANDIDATES.

For every person box from stage 1 whose feet land on or near the court, project the foot
point into court metres with the stage 2 homography and measure the clothing colour of the
torso and the shorts. Saves everything to one .npz so stage 3b can work without touching
the video again.

Run:
    python stages/s03_features.py --proxy work/proxy.mp4 --dets work/dets.json \
        --calib work/calib.json --out work/cand.npz
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def region_stats(img_bgr, lab, hsv, x1, y1, x2, y2):
    """median Lab + pixel fractions of a box region: red, white, dark, then blue, green, yellow, orange"""
    H, W = img_bgr.shape[:2]
    x1, x2, y1, y2 = max(0, int(x1)), min(W, int(x2)), max(0, int(y1)), min(H, int(y2))
    if x2 - x1 < 3 or y2 - y1 < 3:
        return [np.nan] * 3 + [0.0] * 7
    l, h = lab[y1:y2, x1:x2].reshape(-1, 3), hsv[y1:y2, x1:x2].reshape(-1, 3)
    red = (((h[:, 0] <= 8) | (h[:, 0] >= 170)) & (h[:, 1] >= 110) & (h[:, 2] >= 90)).mean()
    white = ((h[:, 1] <= 45) & (h[:, 2] >= 170)).mean()
    dark = (h[:, 2] <= 70).mean()
    blue = ((h[:, 0] >= 100) & (h[:, 0] <= 130) & (h[:, 1] >= 90) & (h[:, 2] >= 60)).mean()
    green = ((h[:, 0] >= 40) & (h[:, 0] <= 85) & (h[:, 1] >= 80) & (h[:, 2] >= 60)).mean()
    yellow = ((h[:, 0] >= 20) & (h[:, 0] <= 35) & (h[:, 1] >= 110) & (h[:, 2] >= 150)).mean()
    orange = ((h[:, 0] > 8) & (h[:, 0] < 20) & (h[:, 1] >= 130) & (h[:, 2] >= 130)).mean()
    med = np.median(l, axis=0)
    return [med[0], med[1], med[2], red, white, dark, blue, green, yellow, orange]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--dets", required=True)
    ap.add_argument("--calib", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-conf", type=float, default=0.2)
    args = ap.parse_args()

    dets = json.loads(Path(args.dets).read_text())
    calib = json.loads(Path(args.calib).read_text())
    Hi2c = np.array(calib["H_img2court"], np.float64)
    Hc2i = np.array(calib["H_court2img"], np.float64)

    def to_court(pt):
        v = Hi2c @ np.array([pt[0], pt[1], 1.0])
        return v[:2] / v[2]

    def ppm_across(X, Y):  # pixels per metre across the court at a court location (local scale of H)
        a = Hc2i @ np.array([X, Y, 1.0])
        b = Hc2i @ np.array([X + 1.0, Y, 1.0])
        return float(np.linalg.norm(a[:2] / a[2] - b[:2] / b[2]))

    frames = {f["f"]: f["b"] for f in dets["frames"]}
    cap = cv2.VideoCapture(args.proxy)
    rows = []
    idx = 0
    stride = dets["stride"]
    while True:
        if not cap.grab():
            break
        if idx in frames:
            ok, img = cap.retrieve()
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            for x1, y1, x2, y2, conf in frames[idx]:
                if conf < args.min_conf:
                    continue
                X, Y = to_court(((x1 + x2) / 2, y2))
                if not (-2.5 <= X <= 8.6 and -5.0 <= Y <= 16.0):
                    continue
                h, w = y2 - y1, x2 - x1
                cx = (x1 + x2) / 2
                torso = region_stats(img, lab, hsv, cx - 0.22 * w, y1 + 0.18 * h, cx + 0.22 * w, y1 + 0.45 * h)
                legs = region_stats(img, lab, hsv, cx - 0.22 * w, y1 + 0.55 * h, cx + 0.22 * w, y1 + 0.75 * h)
                rows.append([idx, x1, y1, x2, y2, conf, X, Y, h / ppm_across(X, Y)] + torso + legs)
        idx += 1
    cap.release()
    cols = ["f", "x1", "y1", "x2", "y2", "conf", "X", "Y", "h_per_ppm",
            "tL", "ta", "tb", "t_red", "t_white", "t_dark", "t_blue", "t_green", "t_yellow", "t_orange",
            "lL", "la", "lb", "l_red", "l_white", "l_dark", "l_blue", "l_green", "l_yellow", "l_orange"]
    arr = np.array(rows, np.float32)
    np.savez_compressed(args.out, data=arr, cols=np.array(cols), fps=dets["fps"], stride=stride)
    print(f"{len(arr)} candidate boxes near the court from {len(frames)} sampled frames -> {args.out}")


if __name__ == "__main__":
    main()
