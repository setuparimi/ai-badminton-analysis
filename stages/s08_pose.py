#!/usr/bin/env python3
"""Stage 8 - POSE.

Body landmarks on a crop around a player, then three coaching numbers:
    crouch      knee angle (180 = straight leg). bent < 150 deg, deep < 130 deg
    stance      ankle gap divided by shoulder width
    racket arm  which wrist goes overhead more often (= the racket hand), and how often that
                wrist is held up (above the hip) versus hanging down during rallies
Pose needs a big enough person, so only samples where the box is at least --min-height px
tall are used; on this camera that means the near half of the court only.

Run:
    python stages/s08_pose.py --proxy work/proxy.mp4 --players work/players.npz \
        --points work/points.json --out work/pose_stats.json
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from common import near_team_at

SK = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]


def angle(a, b, c):
    v1, v2 = a - b, c - b
    n = np.linalg.norm(v1) * np.linalg.norm(v2)
    return float(np.degrees(np.arccos(np.clip(np.dot(v1, v2) / n, -1, 1)))) if n > 1e-6 else np.nan


def iou(a, b):
    ix1, iy1, ix2, iy2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0


def sample_metrics(kp, cf, thr=0.4):
    """kp (17,2) px, cf (17,) -> dict of per-sample numbers (nan if unreliable)"""
    g = lambda i: kp[i] if cf[i] >= thr else None
    out = {}
    knees = []
    for hip, kn, an in ((11, 13, 15), (12, 14, 16)):
        if g(hip) is not None and g(kn) is not None and g(an) is not None:
            knees.append(angle(g(hip), g(kn), g(an)))
    out["knee"] = float(np.mean(knees)) if knees else np.nan
    sh = [g(5), g(6)]
    an = [g(15), g(16)]
    out["stance"] = float(np.linalg.norm(an[0] - an[1]) / np.linalg.norm(sh[0] - sh[1])) \
        if all(x is not None for x in sh + an) and np.linalg.norm(sh[0] - sh[1]) > 5 else np.nan
    nose, hips = g(0), [g(11), g(12)]
    hip_y = np.mean([h[1] for h in hips if h is not None]) if any(h is not None for h in hips) else np.nan
    for side, w, s in (("L", 9, 5), ("R", 10, 6)):
        wr, sh_ = g(w), g(s)
        out[f"{side}_overhead"] = float(wr is not None and nose is not None and wr[1] < nose[1])
        out[f"{side}_up"] = float(wr is not None and not np.isnan(hip_y) and wr[1] < hip_y)
        out[f"{side}_seen"] = float(wr is not None)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--proxy", required=True)
    ap.add_argument("--players", required=True)
    ap.add_argument("--points", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="yolo11m-pose.pt")
    ap.add_argument("--weights-dir", default="models")
    ap.add_argument("--min-height", type=float, default=150)
    ap.add_argument("--who", default="A_you,A_partner")
    args = ap.parse_args()

    import os
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    import torch
    from ultralytics import YOLO
    from ultralytics.utils.downloads import attempt_download_asset
    wp = Path(args.weights_dir) / args.model
    if not wp.exists():
        wp.parent.mkdir(parents=True, exist_ok=True)
        attempt_download_asset(str(wp))
    model = YOLO(str(wp))
    device = "mps" if torch.backends.mps.is_available() else "cpu"

    z = np.load(args.players)
    frames, t = z["frames"], z["t"]
    R = json.loads(Path(args.points).read_text())["rallies"][:-1]
    who = args.who.split(",")

    # samples: detected boxes (flag 1) tall enough, inside a rally window
    jobs = {}
    for k in who:
        B, fl = z[f"{k}_box"], z[f"{k}_flag"]
        for i in range(len(frames)):
            if fl[i] != 1 or np.isnan(B[i][0]):
                continue
            h = B[i][3] - B[i][1]
            if h < args.min_height:
                continue
            tt = t[i]
            ral = next((r for r in R if r["start"] + 0.3 <= tt < r["end"] - 0.3), None)
            if ral is None:
                continue
            jobs.setdefault(int(frames[i]), []).append((k, i, B[i][:4].copy(), ral["rally"]))
    print(f"pose samples queued: {sum(len(v) for v in jobs.values())} in {len(jobs)} frames (box height >= {args.min_height:.0f} px)")

    cap = cv2.VideoCapture(args.proxy)
    idx, results, keep_vis, kps = 0, [], [], []
    pending = []

    def flush():
        crops = [c for c, _ in pending]
        res = model.predict(crops, imgsz=384, device=device, verbose=False)
        for (crop, meta), r in zip(pending, res):
            k, i, box, rally, off = meta
            if r.boxes is None or len(r.boxes) == 0:
                continue
            tb = [box[0] - off[0], box[1] - off[1], box[2] - off[0], box[3] - off[1]]
            best = max(range(len(r.boxes)), key=lambda j: iou(r.boxes.xyxy[j].cpu().numpy(), tb))
            if iou(r.boxes.xyxy[best].cpu().numpy(), tb) < 0.3:
                continue
            kp, cf = r.keypoints.xy[best].cpu().numpy(), r.keypoints.conf[best].cpu().numpy()
            m = sample_metrics(kp, cf)
            tc_, first_near = float(z["tc"]), str(z["first_near"])
            m.update({"who": k, "rally": rally, "t": float(t[i]), "i": int(i), "n_kp": int((cf >= 0.4).sum()),
                      "near": bool(near_team_at(float(t[i]), tc_, first_near) == k[0])})
            results.append(m)
            kps.append(np.concatenate([kp, cf[:, None]], axis=1))
            if len(keep_vis) < 400 and k == "A_you":
                keep_vis.append((crop.copy(), kp, cf))
        pending.clear()

    while True:
        if not cap.grab():
            break
        if idx in jobs:
            ok, img = cap.retrieve()
            for k, i, box, rally in jobs[idx]:
                w, h = box[2] - box[0], box[3] - box[1]
                x1, y1 = max(0, int(box[0] - 0.2 * w)), max(0, int(box[1] - 0.12 * h))
                x2, y2 = min(img.shape[1], int(box[2] + 0.2 * w)), min(img.shape[0], int(box[3] + 0.08 * h))
                pending.append((img[y1:y2, x1:x2].copy(), (k, i, box, rally, (x1, y1))))
                if len(pending) >= 32:
                    flush()
        idx += 1
    flush()
    cap.release()
    print(f"usable pose samples: {len(results)}")

    stats = {}
    for k in who:
        S = [r for r in results if r["who"] == k]
        if not S:
            continue
        knee = np.array([r["knee"] for r in S])
        stance = np.array([r["stance"] for r in S])
        k_ok = knee[~np.isnan(knee)]
        Sn = [r for r in S if r["near"]]                      # handedness is only read from near-side frames
        Sh = Sn if sum(r["L_overhead"] + r["R_overhead"] for r in Sn) >= 6 else S
        L_over, R_over = sum(r["L_overhead"] for r in Sh), sum(r["R_overhead"] for r in Sh)
        dom = "R" if R_over > L_over else "L" if L_over > R_over else \
            ("R" if sum(r["R_up"] for r in Sh) >= sum(r["L_up"] for r in Sh) else "L")
        up = np.array([r[f"{dom}_up"] for r in S if r[f"{dom}_seen"]])
        stats[k] = {"samples": len(S), "rallies": len({r["rally"] for r in S}),
                    "knee_median": float(np.median(k_ok)), "bent_lt150": float((k_ok < 150).mean()), "deep_lt130": float((k_ok < 130).mean()),
                    "stance_median": float(np.nanmedian(stance)),
                    "overhead_left": int(L_over), "overhead_right": int(R_over), "racket_arm": dom,
                    "racket_up_share": float(up.mean()) if len(up) else None,
                    "racket_down_share": float(1 - up.mean()) if len(up) else None}
        # won vs lost for this player
        won = [r for r in S if next(p for p in R if p["rally"] == r["rally"])["user_team_won"] is True]
        lost = [r for r in S if next(p for p in R if p["rally"] == r["rally"])["user_team_won"] is False]
        def agg(rs, key):
            v = np.array([r[key] for r in rs], float)
            return float(np.nanmean(v)) if len(v) else None
        stats[k]["won_vs_lost"] = {"n_samples_won": len(won), "n_samples_lost": len(lost),
                                   "knee_won": agg(won, "knee"), "knee_lost": agg(lost, "knee"),
                                   "stance_won": agg(won, "stance"), "stance_lost": agg(lost, "stance"),
                                   "racket_up_won": agg([r for r in won if r[f"{dom}_seen"]], f"{dom}_up"),
                                   "racket_up_lost": agg([r for r in lost if r[f"{dom}_seen"]], f"{dom}_up")}
    for k in who:
        if k not in stats:
            continue
        dom = stats[k]["racket_arm"]
        stats[k]["by_side"] = {}
        for side_name, side in (("near", True), ("far", False)):
            S = [r for r in results if r["who"] == k and r["near"] == side]
            if len(S) < 30:
                continue
            kn = np.array([r["knee"] for r in S], float); kn = kn[~np.isnan(kn)]
            seen = [r for r in S if r[f"{dom}_seen"]]
            d = {"samples": len(S), "rallies": len({r["rally"] for r in S}), "knee_median": float(np.median(kn)),
                 "bent_lt150": float((kn < 150).mean()), "stance_median": float(np.nanmedian([r["stance"] for r in S])),
                 "racket_up_share": float(np.mean([r[f"{dom}_up"] for r in seen])) if seen else None}
            for label, flag in (("won", True), ("lost", False)):
                RS = [r for r in S if next(p for p in R if p["rally"] == r["rally"])["user_team_won"] is flag]
                kk = np.array([r["knee"] for r in RS], float); kk = kk[~np.isnan(kk)]
                sn = [r for r in RS if r[f"{dom}_seen"]]
                d[label] = {"samples": len(RS), "rallies": len({r["rally"] for r in RS}),
                            "knee_median": float(np.median(kk)) if len(kk) else None,
                            "bent_lt150": float((kk < 150).mean()) if len(kk) else None,
                            "racket_up_share": float(np.mean([r[f"{dom}_up"] for r in sn])) if sn else None}
            stats[k]["by_side"][side_name] = d
    Path(args.out).write_text(json.dumps({"stage": 8, "min_height": args.min_height, "stats": stats}, indent=1))
    np.savez_compressed(Path(args.out).with_name("pose_samples.npz"),
                        who=np.array([r["who"] for r in results]), rally=np.array([r["rally"] for r in results]),
                        t=np.array([r["t"] for r in results]), knee=np.array([r["knee"] for r in results]),
                        stance=np.array([r["stance"] for r in results]), near=np.array([r["near"] for r in results]),
                        kp=np.array(kps, np.float32))

    # skeleton check sheet (evenly spaced samples of the user)
    tiles = []
    if keep_vis:
        for crop, kp, cf in [keep_vis[j] for j in np.linspace(0, len(keep_vis) - 1, min(8, len(keep_vis))).astype(int)]:
            c = crop.copy()
            for a, b in SK:
                if cf[a] > 0.4 and cf[b] > 0.4:
                    cv2.line(c, tuple(kp[a].astype(int)), tuple(kp[b].astype(int)), (0, 255, 0), 2)
            for q in range(17):
                if cf[q] > 0.4:
                    cv2.circle(c, tuple(kp[q].astype(int)), 3, (0, 0, 255), -1)
            tiles.append(cv2.resize(c, (200, int(200 * c.shape[0] / max(1, c.shape[1])))))
        hmax = max(x.shape[0] for x in tiles)
        tiles = [cv2.copyMakeBorder(x, 0, hmax - x.shape[0], 0, 0, cv2.BORDER_CONSTANT) for x in tiles]
        cv2.imwrite(str(Path(args.out).with_name("s08_check.jpg")), np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 92])

    for k, s in stats.items():
        print(f"\n{k}: {s['samples']} samples from {s['rallies']} rallies")
        print(f"  knee angle median {s['knee_median']:.0f} deg | bent (<150) {100 * s['bent_lt150']:.0f}% | deep (<130) {100 * s['deep_lt130']:.0f}% | stance/shoulder {s['stance_median']:.2f}")
        for sd, d in s.get("by_side", {}).items():
            w, l = d["won"], d["lost"]
            print(f"  [{sd:4s}] {d['samples']:4d} samples / {d['rallies']:2d} rallies | knee median {d['knee_median']:.0f} | bent {100*d['bent_lt150']:.0f}% | "
                  f"racket up {100*(d['racket_up_share'] or 0):.0f}% || won: bent {100*(w['bent_lt150'] or 0):.0f}% up {100*(w['racket_up_share'] or 0):.0f}% ({w['rallies']} r) "
                  f"| lost: bent {100*(l['bent_lt150'] or 0):.0f}% up {100*(l['racket_up_share'] or 0):.0f}% ({l['rallies']} r)")
        print(f"  overhead wrist count L {s['overhead_left']} vs R {s['overhead_right']} -> racket arm {s['racket_arm']} | racket up {100 * (s['racket_up_share'] or 0):.0f}% of samples")
    ok = bool(stats.get("A_you")) and stats["A_you"]["samples"] >= 300
    print(f"\nstats: {args.out}\nsheet: {Path(args.out).with_name('s08_check.jpg')}  <- skeletons must sit on the body")
    print("STAGE 8 " + ("PASSED (automatic checks); now do the visual check." if ok else "FAILED: too few usable samples."))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
