#!/usr/bin/env python3
"""Stage 4a - SCOREBOARD OVERLAY (only for videos that have a burned-in score).

Finds every time the yellow score overlay is on screen and reads its two numbers with
macOS's built-in text recognition (Vision framework: free, local, macOS only).
For the test video this is the server-first scoreboard shown while players set up to
serve, so each run gives (a) the serve window and (b) the server's score and the
receiver's score before that rally.

Run:
    python stages/s04a_overlay.py --proxy work/proxy.mp4 --out work/overlay.json

Output overlay.json: {"corner", "n_games", "games": [{"game", "first_window", "runs", "problems"}], "runs", "problems"}; "runs" and "problems" repeat
game 1 so a one-game video works as before. A video that shows 0-0 before the first rally of every game is split into games, and for more than one
game the stage also writes overlay_game1.json, overlay_game2.json, ... and game_start_game1.json, ... (the stage 4 to 6 inputs for each game).
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

# y0, y1, x0, x1 in the 1280x720 proxy. The reference video shows its score top right; --corner auto also looks top left.
CORNERS = {"right": (0, 130, 780, 1280), "left": (0, 140, 0, 520)}
ROI = CORNERS["right"]


def yellow_fraction(img, roi=None):
    y0, y1, x0, x1 = roi or ROI
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


def digits_only_text(text):
    """OCR often reads a bold 0 as the letter O (or D, Q). The crop holds only the yellow score, so when the text is nothing but digits, dashes
    and those letters, read the letters as zeros."""
    letters = re.sub(r"[\d\s\-\u2013\u2014:.,]", "", text)
    if letters and set(letters) <= set("OoDQ"):
        return re.sub(r"[OoDQ]", "0", text)
    return text


def read_scores(ocr, frame, roi=None):
    """Two OCR attempts (thin and thick strokes) on one frame -> list of (first, second)."""
    _, m0 = yellow_fraction(frame, roi)
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
        nums = re.findall(r"\d+", digits_only_text(ocr(img)))
        if len(nums) == 2:
            out.append((int(nums[0]), int(nums[1])))
    return out


def decode_game(results, first_index=1):
    """Viterbi over legal score steps for the runs of ONE game (each run shows the score after one more point).
    Overlay j steps from the previous (s, r) to (s+1, r) [server won again] or (r+1, s) [receiver won, so the serve changes]."""
    problems, states, history = [], {(0, 0): (0.0, None)}, []
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
    st = min(states, key=lambda k: states[k][0]) if states else None
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
    return problems


def majority(run):
    cnt = Counter(map(tuple, run["votes"]))
    return cnt.most_common(1)[0][0] if cnt else None


def split_games(results, cutaways=()):
    """Some videos show 0-0 before the first rally of every game (and a game can be one of several sets). Returns a list of
    (first window or None, runs of that game). A run starts a game when it reads 0-0, or when it cannot be read and begins right after a
    title card (stage 1 lists them as cutaways; a set card, for example). Without such runs there is one game and no first window
    (the reference video's banner)."""
    near_card = lambda r: any(c[1] - 1.0 <= r["t_on"] <= c[1] + 4.0 for c in cutaways)
    is_start = lambda r: majority(r) == (0, 0) or (majority(r) is None and near_card(r))
    zero = [k for k, r in enumerate(results) if is_start(r) and (k == 0 or not is_start(results[k - 1]))]
    if not zero or zero[0] != 0:
        return [(None, results)]
    games = []
    for n, k in enumerate(zero):
        end = zero[n + 1] if n + 1 < len(zero) else len(results)
        runs = [dict(r, j=i) for i, r in enumerate(results[k + 1:end], 1)]
        games.append(({"t_on": results[k]["t_on"], "t_off": results[k]["t_off"]}, runs))
    return games


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--thr", type=float, default=0.02, help="yellow pixel fraction that counts as 'overlay on'")
    ap.add_argument("--corner", choices=["auto", "right", "left"], default="auto", help="where the score is shown (auto: the corner with more yellow runs)")
    ap.add_argument("--dets", help="dets.json from stage 1, for the title cards (default: next to the proxy)")
    args = ap.parse_args()
    dets_path = Path(args.dets) if args.dets else Path(args.proxy).with_name("dets.json")
    cutaways = json.loads(dets_path.read_text()).get("cutaways", []) if dets_path.exists() else []

    cap = cv2.VideoCapture(args.proxy)
    fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = 5
    frac = {c: np.zeros(total) for c in CORNERS}
    i = 0
    while cap.grab():                              # one sequential pass, 6 samples per second, both corners
        if i % step == 0 and i < total:
            ok, f = cap.retrieve()
            if ok:
                for c, roi in CORNERS.items():
                    frac[c][i] = yellow_fraction(f, roi)[0]
        i += 1

    def find_runs(on):
        runs, start = [], None
        for k in range(0, total, step):
            if on[k] and start is None:
                start = k
            if not on[k] and start is not None:
                runs.append([start, k - step]); start = None
        if start is not None:
            runs.append([start, total - 1])
        merged = []                                # glue runs separated by < 0.6 s
        for r in runs:
            if merged and r[0] - merged[-1][1] < 0.6 * fps:
                merged[-1][1] = r[1]
            else:
                merged.append(r)
        return merged

    if args.corner == "auto":
        corner = max(CORNERS, key=lambda c: len(find_runs(frac[c] > args.thr)))
    else:
        corner = args.corner
    roi = CORNERS[corner]
    merged = find_runs(frac[corner] > args.thr)
    print(f"score overlay corner: {corner} ({len(merged)} yellow runs; " + ", ".join(f"{c} {len(find_runs(frac[c] > args.thr))}" for c in CORNERS) + ")")

    def refine(lo, hi, want):                     # exact first/last frame where overlay state == want
        for k in range(max(0, lo), min(total - 1, hi) + 1):
            cap.set(cv2.CAP_PROP_POS_FRAMES, k)
            ok, f = cap.read()
            if ok and (yellow_fraction(f, roi)[0] > args.thr) == want:
                return k
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
                votes += read_scores(ocr, f, roi)
        results.append({"j": j, "t_on": round(first / fps, 3), "t_off": round((last + 1) / fps, 3),
                        "first": None, "second": None, "votes": [list(v) for v in votes]})
    cap.release()

    # Decode every game on its own with the scoring rule, so a run that could not be read is settled by its neighbours
    # instead of stopping everything, and a new game (score back to 0-0) starts a fresh decode.
    games = []
    for g, (window, runs) in enumerate(split_games(results, cutaways), 1):
        problems = decode_game(runs)
        games.append({"game": g, "first_window": window, "runs": runs, "problems": problems})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    first = games[0]
    doc = {"stage": "4a", "fps": fps, "corner": corner, "n_games": len(games), "games": games, "runs": first["runs"], "problems": first["problems"]}
    Path(args.out).write_text(json.dumps(doc, indent=1))
    if len(games) > 1:                             # one pair of files per game, ready for stages 4 to 6
        stem = Path(args.out)
        for g in games:
            n = g["game"]
            w = g["first_window"]
            stem.with_name(f"{stem.stem}_game{n}.json").write_text(json.dumps(
                {"stage": "4a", "fps": fps, "game": n, "runs": g["runs"], "problems": g["problems"]}, indent=1))
            stem.with_name(f"game_start_game{n}.json").write_text(json.dumps(
                {"confirmed": False, "start": round(max(0.0, w["t_on"] - 1.0), 2), "first_window_on": w["t_on"],
                 "first_window_off": round(min(w["t_off"], w["t_on"] + 3.5), 2),
                 "method": "the 0-0 score overlay before the first rally of this game"}, indent=1))

    print(f"overlay runs found: {len(results)} in {len(games)} game(s)")
    for g in games:
        w = g["first_window"]
        print(f"  game {g['game']}: " + (f"first window {w['t_on']:.1f}-{w['t_off']:.1f}s, " if w else "") + f"{len(g['runs'])} runs, {len(g['problems'])} corrected by the scoring rule")
        for r in g["runs"][:3]:
            print(f"    run {r['j']:2d}  {r['t_on']:6.2f}-{r['t_off']:6.2f}s  {r['first']}-{r['second']}")
        print("    ...")
        for r in g["runs"][-2:]:
            print(f"    run {r['j']:2d}  {r['t_on']:6.2f}-{r['t_off']:6.2f}s  {r['first']}-{r['second']}")
        for p in g["problems"][:15]:
            print("    -", p)
    ok = len(results) > 0 and all(len(g["runs"]) >= 3 for g in games)
    print("\nOVERLAY " + ("PASSED: every run decoded to a legal score step (check the notes above by eye)." if ok else "FAILED: no overlay runs found, or a game with fewer than 3."))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
