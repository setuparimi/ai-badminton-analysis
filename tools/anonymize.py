#!/usr/bin/env python3
"""Anonymised evidence images for publishing.

Regenerates four example images from the analysis artifacts in a work folder, with privacy
protection applied to every photographic frame BEFORE anything (boxes, labels, skeletons) is
drawn on it:
    court_overlay.jpg   clean median background + court model (stage 2)
    tracking_sheet.jpg  6 frames, tracked players boxed and labelled (stage 3)
    skeleton_strip.jpg  8 pose crops of one player, head blurred (stage 8)
    video_montage.jpg   4 frames with player boxes, top bar and mini-map (stage 11)
A tinted copy of each image is written to <out>/debug/ so a human can see what was covered.

What is protected (region based, no face recognition is used on purpose):
    1. Everything OUTSIDE the court area is Gaussian blurred (sigma 12) and then pixelated
       in 16 px blocks. The court area is the court rectangle grown by 1.0 m on every side,
       projected to the image with H_court2img. This removes the crowd, the bench, the
       umpire and the umpire chair.
    2. Every person box in the frame gets its head pixelated: the top 30% of the box (plus
       10% of the box height above it), widened by 15% of the box width on each side, with
       blocks of about box_height / 7 pixels. The rectangle grows when the box cannot be
       trusted to start at the head: a box cut off by the bottom edge of the frame is a
       close-up person and is hidden completely; a wide box (lying, diving, lunging) is
       hidden to a depth of 40% of its width; a box much taller than a standing person at that
       spot (raised racket, two people merged) is hidden down to where a standing head
       would be. Boxes come from dets.json (confidence >= 0.05, the sample nearest to the
       frame plus one sample either side) and from the tracked players, so players,
       partners, the umpire and anyone near the court are covered.
    3. Tracked player boxes are exempt from rule 1 (their bodies stay visible so clothing
       based labelling can be shown) but never from rule 2.
    4. Pose crops get a second, heavy blur over the top 28% of the crop before the skeleton
       is drawn, on top of rules 1 and 2 applied to the full frame the crop is cut from.

What is NOT protected:
    - Faces that no person box covers: a person the detector missed AND who stands inside
      the court area (for example someone walking across the court).
    - Heads that sit below the head rectangle, for example a player bent over with an arm
      or racket held up so that the box top is far above the head. At that distance a face
      is about 10 px tall.
    - Reflections and glare on the polished floor (a faint mirror image of a player).
    - Everything that is not a face: clothing, body shape, skin tone, hair colour below
      the head rectangle, shoes, rackets, and any text or graphics burned into the video
      that lie inside the court area or inside a tracked player box.
    Players in the far half of the court have their upper body above the projected floor
    area, so they stay visible only because rule 3 exempts their box; outside it is blurred.

HUMAN REVIEW IS REQUIRED. Look at every output image at full size (and at the red tinted
copy in debug/) before publishing. The tool is conservative but no automatic blur is
guaranteed to hide every face. The debug/ copies are for review only: do not publish them.

Run:
    python tools/anonymize.py --work work --out docs/img
    python tools/anonymize.py --work work --out docs/img --pose-who PLAYER_ID --montage-times 62,215,420,560

Inputs from --work: bg_median.png, calib.json, proxy.mp4 (or --proxy), players.npz, dets.json,
pose_samples.npz (skeleton strip only) and points.json (score bar only, optional).
Outputs: the four jpg files in --out and debug/<name>.jpg tinted copies.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

STAGES = Path(__file__).resolve().parents[1] / "stages"
sys.path.insert(0, str(STAGES))
from s02_calibrate import LINES, NET, W_D, L, project  # noqa: E402  court model shared with stage 2

MARGIN = 1.0           # metres added around the court before everything outside is blurred
BG_SIGMA = 12.0        # Gaussian sigma for the outside-court blur
BG_BLOCK = 16          # pixelation block size outside the court (px)
HEAD_FRAC = 0.30       # head rectangle: top share of a person box
HEAD_SIDE = 0.15       # ... widened by this share of the box width on each side
HEAD_UP = 0.10         # ... and extended above the box by this share of the box height
HEAD_BLOCKS = 7        # pixelation block = box height / HEAD_BLOCKS
HEAD_WIDE = 0.4        # head rectangle is at least this share of the box WIDTH tall (lying, lunging, close-up)
HEAD_TRUNC = 1.0       # box cut off by the bottom edge of the frame: a close-up person, hide the whole box
TALL_BOX = 1.2         # box this much taller than a standing person at that spot: raised racket or two people
MIN_CONF = 0.05        # person boxes below this detector confidence are ignored
NEIGHBOURS = 1         # extra sampled frames used on each side of the nearest one
POSE_HEAD_FRAC = 0.28  # top share of a pose crop that is blurred again
PALETTE = [(0, 0, 255), (0, 255, 255), (255, 0, 0), (0, 200, 0), (255, 0, 255), (255, 128, 0),
           (0, 128, 255), (200, 200, 0)]
SK = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]
JPG = [cv2.IMWRITE_JPEG_QUALITY, 92]


# ---------------------------------------------------------------- privacy core

def court_polygon(H, margin=MARGIN):
    """Court rectangle grown by margin metres on every side, projected to pixels (4 x 2 int32)."""
    H = np.asarray(H, np.float64)
    corners = [(-margin, -margin), (W_D + margin, -margin), (W_D + margin, L + margin), (-margin, L + margin)]
    w = H @ np.array([[x, y, 1.0] for x, y in corners]).T
    if (w[2] <= 1e-6).any():
        raise ValueError("a court corner lies on or behind the camera plane; cannot build the court mask")
    return np.round(project(H, corners)).astype(np.int32)


def pixelate(img, block):
    h, w = img.shape[:2]
    block = max(2, int(block))
    small = cv2.resize(img, (max(1, -(-w // block)), max(1, -(-h // block))), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def obscure(img, sigma, block):
    """Gaussian blur, then pixelate: the heavy treatment."""
    return pixelate(cv2.GaussianBlur(img, (0, 0), sigma), block)


def head_region(box, w, h, stand_h=None):
    """Pixels to hide for one person box: (x1, y1, x2, y2, block) clipped to a w x h image, or None.

    Normally the top 30% of the box, 15% wider each side, a little above. The share grows when the
    box cannot be trusted to start at the head: cut off by the bottom edge (close-up person), wide
    (lying or lunging), or taller than a standing person at that spot (stand_h, in pixels).
    """
    x1, y1, x2, y2 = (float(v) for v in box[:4])
    if not np.isfinite([x1, y1, x2, y2]).all() or x2 <= x1 or y2 <= y1:
        return None
    bw, bh = x2 - x1, y2 - y1
    frac = max(HEAD_FRAC, HEAD_WIDE * bw / bh)
    if y2 >= 0.98 * h:                       # detector boxes stop a few px short of the edge
        frac = max(frac, HEAD_TRUNC)
    if stand_h is not None and stand_h > 1 and bh > TALL_BOX * stand_h:
        frac = max(frac, 1 - 0.55 * stand_h / bh)
    frac = min(frac, 1.0)
    rx1, rx2 = int(np.floor(max(0, x1 - HEAD_SIDE * bw))), int(np.ceil(min(w, x2 + HEAD_SIDE * bw)))
    ry1, ry2 = int(np.floor(max(0, y1 - HEAD_UP * bh))), int(np.ceil(min(h, y1 + frac * bh)))
    if rx2 <= rx1 or ry2 <= ry1:
        return None
    return rx1, ry1, rx2, ry2, max(2, int(round(bh / HEAD_BLOCKS)))


def standing_height(H):
    """Return f(box) = pixel height of a person standing at the box's feet, from the horizon of H.

    The horizon is where the court plane goes to infinity (third row of the inverse homography);
    a person's height in pixels is about the distance from his feet up to the horizon. f returns
    None when the calibration has no usable horizon.
    """
    a, b, c = np.linalg.inv(np.asarray(H, np.float64))[2]
    if abs(b) < 1e-9:
        return lambda box: None
    return lambda box: box[3] - (-(a * (box[0] + box[2]) / 2 + c) / b)


def anonymize_frame(img, calib_H_court2img, person_boxes, keep_boxes=(), return_mask=False):
    """Hide faces in a BGR frame. Returns the new image (and a bool mask of altered pixels).

    1. Blur + pixelate everything outside the court rectangle grown by MARGIN metres,
       except inside keep_boxes (tracked players: their bodies stay visible).
    2. Pixelate the head rectangle of every box in person_boxes and keep_boxes.
    Boxes are (x1, y1, x2, y2[, conf]) in pixels; NaN boxes are ignored.
    """
    h, w = img.shape[:2]
    inside = np.zeros((h, w), np.uint8)
    cv2.fillPoly(inside, [court_polygon(calib_H_court2img)], 255)
    outside = inside == 0
    for b in keep_boxes:
        if np.isfinite(np.asarray(b[:4], float)).all():
            x1, y1, x2, y2 = (int(round(v)) for v in b[:4])
            outside[max(0, y1):max(0, y2), max(0, x1):max(0, x2)] = False
    out = img.copy()
    heavy = obscure(img, BG_SIGMA, BG_BLOCK)
    out[outside] = heavy[outside]
    mask = outside.copy()
    stand = standing_height(calib_H_court2img)
    for b in list(person_boxes) + list(keep_boxes):
        r = head_region(b, w, h, stand(b))
        if r is None:
            continue
        x1, y1, x2, y2, block = r
        out[y1:y2, x1:x2] = pixelate(out[y1:y2, x1:x2], block)
        mask[y1:y2, x1:x2] = True
    return (out, mask) if return_mask else out


def tint(img, mask, H=None):
    """Debug copy: covered pixels tinted red, court area outlined in cyan."""
    out = img.copy()
    out[mask] = (0.55 * out[mask] + 0.45 * np.array([0, 0, 255], np.float32)).astype(np.uint8)
    if H is not None:
        cv2.polylines(out, [court_polygon(H)], True, (255, 255, 0), 2, cv2.LINE_AA)
    return out


# ---------------------------------------------------------------- artifact access

def player_ids(z):
    """Player ids = every key ending in _box in players.npz, in file order."""
    return [k[:-4] for k in z.files if k.endswith("_box")]


def default_pose_who(ids):
    return next((k for k in ids if "white" in k.lower()), ids[0])


def colours_for(ids):
    return {k: PALETTE[i % len(PALETTE)] for i, k in enumerate(ids)}


class Dets:
    """Person boxes from dets.json, sampled every few frames."""

    def __init__(self, path):
        d = json.loads(Path(path).read_text())
        self.f = np.array([r["f"] for r in d["frames"]], int)
        self.b = [np.array(r["b"], np.float32).reshape(-1, 5) for r in d["frames"]]

    def boxes(self, f, conf_min=MIN_CONF, spread=NEIGHBOURS):
        """All boxes at the sampled frame nearest to f and at `spread` samples either side."""
        k = int(np.argmin(np.abs(self.f - f)))
        out = []
        for j in range(max(0, k - spread), min(len(self.f), k + spread + 1)):
            out.extend(b for b in self.b[j] if b[4] >= conf_min)
        return out

    def static_boxes(self, min_share=0.2, cell=24):
        """Boxes that sit in the same place in a large share of the samples (spectators, umpire)."""
        acc = {}
        for bs in self.b:
            seen = set()
            for b in bs:
                key = (int(round((b[0] + b[2]) / 2 / cell)), int(round(b[3] / cell)))
                if key not in seen:
                    seen.add(key)
                    acc.setdefault(key, []).append(b)
        need = min_share * len(self.b)
        return [np.mean(v, axis=0) for v in acc.values() if len(v) >= need]


class Players:
    """Tracked players from players.npz."""

    def __init__(self, path):
        z = np.load(path)
        self.frames, self.t, self.fps = z["frames"], z["t"], float(z["fps"])
        self.ids = player_ids(z)
        self.box = {k: z[f"{k}_box"] for k in self.ids}
        self.flag = {k: z[f"{k}_flag"] for k in self.ids}
        self.xy = {k: z[f"{k}_xy"] for k in self.ids}

    def index_at(self, f):
        return int(np.searchsorted(self.frames, f, side="right") - 1)

    def shown(self, f, max_age=3):
        """id -> box for players drawn at frame f (detected, not older than max_age frames)."""
        j = self.index_at(f)
        out = {}
        for k in self.ids:
            b = self.box[k][j] if j >= 0 else None
            if b is not None and not np.isnan(b[0]) and self.flag[k][j] == 1 and f - self.frames[j] <= max_age:
                out[k] = b[:4]
        return out

    def privacy_boxes(self, f):
        """Every tracked box (any flag) at the samples either side of f."""
        j = self.index_at(f)
        out = []
        for k in self.ids:
            for i in (j, j + 1):
                if 0 <= i < len(self.frames) and not np.isnan(self.box[k][i][0]):
                    out.append(self.box[k][i][:4])
        return out


def read_frame(cap, f):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
    ok, img = cap.read()
    if not ok:
        raise RuntimeError(f"cannot read frame {f} from the proxy video")
    return img


def protected_frame(img, f, H, players, dets):
    """Anonymise frame f using detections and tracks. Returns (image, mask, shown boxes)."""
    shown = players.shown(f)
    persons = dets.boxes(f) + players.privacy_boxes(f)
    out, mask = anonymize_frame(img, H, persons, list(shown.values()), return_mask=True)
    return out, mask, shown


def write_pair(out_dir, name, img, dbg):
    (out_dir / "debug").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / name), img, JPG)
    cv2.imwrite(str(out_dir / "debug" / name), dbg, JPG)


# ---------------------------------------------------------------- the four images

def draw_boxes(img, shown, colours, thick=3):
    for k, b in shown.items():
        x1, y1, x2, y2 = (int(v) for v in b[:4])
        cv2.rectangle(img, (x1, y1), (x2, y2), colours[k], thick)
        cv2.putText(img, k, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, colours[k], 2, cv2.LINE_AA)


def court_overlay(work, dets, H, calib):
    bg = cv2.imread(str(work / "bg_median.png"))
    if bg is None:
        raise FileNotFoundError(work / "bg_median.png")
    # a median has no per-frame detections: use the boxes that sit still in most frames
    out, mask = anonymize_frame(bg, H, dets.static_boxes(), return_mask=True)
    dbg = tint(out, mask, H)
    for im in (out, dbg):
        for a, b in LINES:
            p = project(H, [a, b]).astype(int)
            cv2.line(im, tuple(p[0]), tuple(p[1]), (0, 0, 255), 1, cv2.LINE_AA)
        p = project(H, list(NET)).astype(int)
        cv2.line(im, tuple(p[0]), tuple(p[1]), (255, 0, 255), 2, cv2.LINE_AA)
        for q in calib["points"]:
            cv2.circle(im, (int(q["px"][0]), int(q["px"][1])), 5, (0, 255, 0), 2)
    return out, dbg, mask


def tracking_sheet(cap, H, players, dets):
    colours = colours_for(players.ids)
    picks = np.linspace(len(players.frames) * 0.05, len(players.frames) * 0.95, 6).astype(int)
    tiles, dtiles, covered = [], [], []
    for r in picks:
        f = int(players.frames[r])
        out, mask, shown = protected_frame(read_frame(cap, f), f, H, players, dets)
        dbg = tint(out, mask, H)
        for im in (out, dbg):
            draw_boxes(im, shown, colours)
            cv2.putText(im, f"t={players.t[r]:.1f}s", (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(cv2.resize(out, (640, 360), interpolation=cv2.INTER_AREA))
        dtiles.append(cv2.resize(dbg, (640, 360), interpolation=cv2.INTER_AREA))
        covered.append(mask.mean())
    grid = lambda t: np.vstack([np.hstack(t[:3]), np.hstack(t[3:])])
    return grid(tiles), grid(dtiles), float(np.mean(covered))


def pose_crop_box(box, shape):
    """Same crop as stages/s08_pose.py: padded 0.2 w sideways, 0.12 h above, 0.08 h below."""
    w, h = box[2] - box[0], box[3] - box[1]
    x1, y1 = max(0, int(box[0] - 0.2 * w)), max(0, int(box[1] - 0.12 * h))
    x2, y2 = min(shape[1], int(box[2] + 0.2 * w)), min(shape[0], int(box[3] + 0.08 * h))
    return x1, y1, x2, y2


def blur_crop_head(crop):
    """Second, heavy blur over the top POSE_HEAD_FRAC of a pose crop (done before drawing)."""
    out = crop.copy()
    n = max(2, int(np.ceil(POSE_HEAD_FRAC * crop.shape[0])))
    out[:n] = obscure(crop[:n], max(3.0, crop.shape[0] / 25), max(4, crop.shape[0] // 6))
    return out, n


def draw_skeleton(c, kp):
    for a, b in SK:
        if kp[a, 2] > 0.4 and kp[b, 2] > 0.4:
            cv2.line(c, tuple(kp[a, :2].astype(int)), tuple(kp[b, :2].astype(int)), (0, 255, 0), 2)
    for q in range(17):
        if kp[q, 2] > 0.4:
            cv2.circle(c, tuple(kp[q, :2].astype(int)), 3, (0, 0, 255), -1)


def skeleton_strip(cap, H, players, dets, pose_path, who, n=8):
    z = np.load(pose_path)
    if who not in players.ids:
        raise SystemExit(f"--pose-who {who!r} is not a tracked id; choose one of {players.ids}")
    sel = np.where(z["who"] == who)[0]
    good = sel[(z["kp"][sel, :, 2] >= 0.4).sum(1) >= 10]       # skeletons with most joints found
    sel = good if len(good) >= n else sel
    if len(sel) == 0:
        raise SystemExit(f"no pose samples for {who!r} in {pose_path}")
    order = sel[np.linspace(0, len(sel) - 1, min(n, len(sel))).astype(int)]
    tiles, dtiles = [], []
    for s in order:
        i = int(np.argmin(np.abs(players.t - z["t"][s])))      # the player's box nearest in time
        box = players.box[who][i]
        if np.isnan(box[0]):
            continue
        f = int(players.frames[i])
        out, mask, _ = protected_frame(read_frame(cap, f), f, H, players, dets)
        x1, y1, x2, y2 = pose_crop_box(box, out.shape)
        crop, rows = blur_crop_head(out[y1:y2, x1:x2])
        cm = mask[y1:y2, x1:x2].copy()
        cm[:rows] = True
        dcrop = tint(crop, cm)
        for im in (crop, dcrop):
            draw_skeleton(im, z["kp"][s])
        for im, dst in ((crop, tiles), (dcrop, dtiles)):
            dst.append(cv2.resize(im, (200, int(200 * im.shape[0] / max(1, im.shape[1])))))
    if not tiles:
        raise SystemExit("no usable pose crops")
    hmax = max(x.shape[0] for x in tiles)
    pad = lambda ts: np.hstack([cv2.copyMakeBorder(x, 0, hmax - x.shape[0], 0, 0, cv2.BORDER_CONSTANT) for x in ts])
    return pad(tiles), pad(dtiles)


def rally_at(P, t):
    """Rally whose window (3 s before the serve to the end) contains t, as in stages/s11_video.py."""
    for p in P:
        if p["start"] - 3.0 <= t < p["end"]:
            return p
    return P[-1] if P and t >= P[-1]["start"] else None


def top_bar(img, t, P):
    """Simplified stage 11 bar: rally number, score before the rally, clock."""
    W = img.shape[1]
    bar = img[0:46, 0:W].copy()
    cv2.rectangle(img, (0, 0), (W, 46), (20, 20, 20), -1)
    cv2.addWeighted(bar, 0.25, img[0:46, 0:W], 0.75, 0, img[0:46, 0:W])
    p = rally_at(P, t)
    if p:
        i = P.index(p)
        a, b = (P[i - 1].get("A_after") or 0, P[i - 1].get("B_after") or 0) if i > 0 else (0, 0)
        cv2.putText(img, f"Rally {p['rally']}/{len(P)}   A {a} - {b} B", (10, 31),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.78, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(img, f"{int(t // 60)}:{int(t % 60):02d}", (W - 85, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)


def video_montage(cap, H, players, dets, times, rallies):
    import s11_video                                           # draw_minimap lives in stage 11
    colours = colours_for(players.ids)
    s11_video.COL.update(colours)                              # minimap colours = box colours
    tiles, dtiles, covered = [], [], []
    for t in times:
        f = int(round(t * players.fps))
        out, mask, shown = protected_frame(read_frame(cap, f), f, H, players, dets)
        dbg = tint(out, mask, H)
        j = players.index_at(f)
        pos = {k: (None if j < 0 or np.isnan(players.xy[k][j][0]) else players.xy[k][j]) for k in players.ids}
        mm = s11_video.draw_minimap(pos)
        for im in (out, dbg):
            draw_boxes(im, shown, colours)
            top_bar(im, f / players.fps, rallies)
            y0 = im.shape[0] - mm.shape[0] - 10
            im[y0:y0 + mm.shape[0], im.shape[1] - mm.shape[1] - 10:im.shape[1] - 10] = mm
        tiles.append(cv2.resize(out, (800, 450), interpolation=cv2.INTER_AREA))
        dtiles.append(cv2.resize(dbg, (800, 450), interpolation=cv2.INTER_AREA))
        covered.append(mask.mean())
    while len(tiles) % 2:
        tiles.append(np.zeros_like(tiles[0]))
        dtiles.append(np.zeros_like(dtiles[0]))
    grid = lambda ts: np.vstack([np.hstack(ts[i:i + 2]) for i in range(0, len(ts), 2)])
    return grid(tiles), grid(dtiles), float(np.mean(covered))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True, help="folder with the analysis artifacts")
    ap.add_argument("--out", required=True, help="folder for the four jpg files (and debug/)")
    ap.add_argument("--proxy", help="proxy video (default <work>/proxy.mp4)")
    ap.add_argument("--pose-who", help="player id for the skeleton strip (default: first id containing 'white', else the first)")
    ap.add_argument("--montage-times", default="62,215,420,560", help="comma separated seconds for the montage")
    args = ap.parse_args()

    work, out_dir = Path(args.work), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    calib = json.loads((work / "calib.json").read_text())
    H = np.array(calib["H_court2img"], np.float64)
    players, dets = Players(work / "players.npz"), Dets(work / "dets.json")
    cap = cv2.VideoCapture(str(args.proxy or work / "proxy.mp4"))
    if not cap.isOpened():
        sys.exit("cannot open the proxy video")
    print(f"players: {players.ids} | court area = court + {MARGIN} m")

    img, dbg, mask = court_overlay(work, dets, H, calib)
    write_pair(out_dir, "court_overlay.jpg", img, dbg)
    print(f"court_overlay.jpg   {100 * mask.mean():.0f}% of pixels covered")

    img, dbg, cov = tracking_sheet(cap, H, players, dets)
    write_pair(out_dir, "tracking_sheet.jpg", img, dbg)
    print(f"tracking_sheet.jpg  {100 * cov:.0f}% of pixels covered (mean over tiles)")

    pose = work / "pose_samples.npz"
    if pose.exists():
        who = args.pose_who or default_pose_who(players.ids)
        img, dbg = skeleton_strip(cap, H, players, dets, pose, who)
        write_pair(out_dir, "skeleton_strip.jpg", img, dbg)
        print(f"skeleton_strip.jpg  player {who}, head region blurred before the skeleton was drawn")
    else:
        print("skeleton_strip.jpg  skipped (no pose_samples.npz)")

    pts = work / "points.json"
    rallies = json.loads(pts.read_text())["rallies"] if pts.exists() else []
    times = [float(x) for x in args.montage_times.split(",") if x.strip()]
    img, dbg, cov = video_montage(cap, H, players, dets, times, rallies)
    write_pair(out_dir, "video_montage.jpg", img, dbg)
    print(f"video_montage.jpg   {100 * cov:.0f}% of pixels covered (mean over tiles)")
    cap.release()
    print(f"\nimages: {out_dir}\ndebug : {out_dir / 'debug'}  <- red = covered; LOOK at every image before publishing")


if __name__ == "__main__":
    main()
