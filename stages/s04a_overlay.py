#!/usr/bin/env python3
"""Stage 4a - SCOREBOARD OVERLAY (only for videos that have a burned-in score).

Finds every time the yellow score overlay is on screen and reads its two numbers with
macOS's built-in text recognition (Vision framework: free, local, macOS only).
For the test video this is the server-first scoreboard shown while players set up to
serve, so each run gives (a) the serve window and (b) the server's score and the
receiver's score before that rally.

Run:
    python stages/s04a_overlay.py --proxy work/proxy.mp4 --out work/overlay.json

Output overlay.json: {"runs": [{"j", "t_on", "t_off", "first", "second", "votes"}], "problems": [...]}
"""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROI = (0, 130, 780, 1280)  # y0, y1, x0, x1 in the 1280x720 proxy: the top-right corner


def yellow_fraction(img):
    y0, y1, x0, x1 = ROI
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    m = (hsv[..., 0] >= 22) & (hsv[..., 0] <= 36) & (hsv[..., 1] >= 80) & (hsv[..., 2] >= 235)
    return float(m.mean()), m


def make_ocr():
    import Vision
    from Foundation import NSData

    def ocr(img):
        ok, buf = cv2.imencode(".png", img)
        data = NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
        req = Vision.VNRecognizeTextRequest.alloc().init()
        req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        req.setUsesLanguageCorrection_(False)
        handler.performRequests_error_([req], None)
        out = []
        for o in req.results() or []:
            c = o.topCandidates_(1)[0]
            out.append(c.string())
        return " ".join(out)
    return ocr


def read_scores(ocr, frame):
    """Two OCR attempts (thin and thick strokes) on one frame -> list of (first, second)."""
    _, m0 = yellow_fraction(frame)
    out = []
    for grow in (0, 1):
        m = m0.astype(np.uint8) * 255
        if grow:
            m = cv2.dilate(m, np.ones((3, 3), np.uint8))
        ys, xs = np.where(m > 0)
        if len(xs) == 0:
            continue
        crop = m[max(0, ys.min() - 10):ys.max() + 10, max(0, xs.min() - 14):xs.max() + 14]
        img = cv2.cvtColor(255 - cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC),
                           cv2.COLOR_GRAY2BGR)
        nums = re.findall(r"\d+", ocr(img))
        if len(nums) == 2:
            out.append((int(nums[0]), int(nums[1])))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--thr", type=float, default=0.02, help="yellow pixel fraction that counts as 'overlay on'")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.proxy)
    fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = 5
    on = np.zeros(total, bool)
    for i in range(0, total, step):               # coarse scan, 6 samples per second
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, f = cap.read()
        if ok:
            on[i] = yellow_fraction(f)[0] > args.thr
    runs, start = [], None
    for i in range(0, total, step):
        if on[i] and start is None:
            start = i
        if not on[i] and start is not None:
            runs.append([start, i - step]); start = None
    if start is not None:
        runs.append([start, total - 1])
    merged = []                                   # glue runs separated by < 0.6 s
    for r in runs:
        if merged and r[0] - merged[-1][1] < 0.6 * fps:
            merged[-1][1] = r[1]
        else:
            merged.append(r)

    def refine(lo, hi, want):                     # exact first/last frame where overlay state == want
        for i in range(max(0, lo), min(total - 1, hi) + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ok, f = cap.read()
            if ok and (yellow_fraction(f)[0] > args.thr) == want:
                return i
        return lo

    ocr = make_ocr()
    results = []
    for j, (a, b) in enumerate(merged, 1):
        first = refine(a - step, a, True)
        last_off = refine(b, b + step, False)
        last = last_off - 1 if last_off > b else b
        votes = []
        for q in np.linspace(0.1, 0.9, 9):         # 9 frames x 2 OCR variants per run
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(first + q * (last - first)))
            ok, f = cap.read()
            if ok:
                votes += read_scores(ocr, f)
        results.append({"j": j, "t_on": round(first / fps, 3), "t_off": round((last + 1) / fps, 3),
                        "first": None, "second": None, "votes": [list(v) for v in votes]})
    cap.release()

    # Decode all runs together with the scoring rule. Overlay j shows j total points and steps from the
    # previous (s, r) to (s+1, r) [server won again] or (r+1, s) [receiver won, so the serve changes].
    # Find the whole path of legal steps that agrees best with every OCR reading (Viterbi), so a run that
    # could not be read is settled by its neighbours instead of stopping everything.
    problems = []
    states = {(0, 0): (0.0, None)}          # state -> (cost so far, previous state)
    history = []
    for r in results:
        cnt = Counter(map(tuple, r["votes"]))
        total = sum(cnt.values())
        new_states = {}
        for st, (c0, _) in states.items():
            for nxt in {(st[0] + 1, st[1]), (st[1] + 1, st[0])}:
                cost = c0 - math.log((cnt.get(nxt, 0) + 0.1) / (total + 0.1))
                if nxt not in new_states or cost < new_states[nxt][0]:
                    new_states[nxt] = (cost, st)
        history.append(new_states)
        states = new_states
    path = []
    st = min(states, key=lambda k: states[k][0])
    for new_states in reversed(history):
        path.append(st)
        st = new_states[st][1]
    path.reverse()
    for r, pick in zip(results, path):
        r["first"], r["second"] = pick
        cnt = Counter(map(tuple, r["votes"]))
        where = f"run {r['j']} at {r['t_on']:.1f}s"
        if cnt and cnt.most_common(1)[0][0] != pick:
            problems.append(f"{where}: raw OCR majority {cnt.most_common(1)[0][0]} overruled by the scoring rule -> {pick}")
        elif not cnt:
            problems.append(f"{where}: nothing readable, {pick} inferred from the neighbouring runs")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"stage": "4a", "fps": fps, "runs": results, "problems": problems}, indent=1))

    print(f"overlay runs found: {len(results)}")
    for r in results[:6]:
        print(f"  run {r['j']:2d}  {r['t_on']:6.2f}-{r['t_off']:6.2f}s  {r['first']}-{r['second']}")
    print("  ...")
    for r in results[-3:]:
        print(f"  run {r['j']:2d}  {r['t_on']:6.2f}-{r['t_off']:6.2f}s  {r['first']}-{r['second']}")
    print(f"notes (OCR corrected by the scoring rule): {len(problems)}")
    for p in problems[:15]:
        print("  -", p)
    ok = len(results) > 0
    print("\nOVERLAY " + ("PASSED: every run decoded to a legal score step (check the notes above by eye)." if ok else "FAILED: no overlay runs found."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
