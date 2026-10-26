#!/usr/bin/env python3
"""Analyse a match from start to PDF: a few questions, two clicks, then everything runs.

    .venv/bin/python tools/analyze.py

It asks, in this order (anything you pass as a flag is not asked):
  1. Where is the video? (a file, or a YouTube link to a match you filmed) and what would you like to call this match?
  2. Singles or doubles?
  3. Which hand do you hit with?
  4. Does the video show a live score on screen? (Usually not: then you get the position-and-movement report.)
  5. How many games are in the video, and when does each start and end? (Enter for one game, the whole video.)
  6. The final score of each game, if you know it (optional; used to check the number of plays found).
Then it makes a small copy of the video, finds the people in it in the background, and opens two pages in your browser:
  - the court photo: click where the painted lines cross (the page guides you);
  - a few pictures of the game with everyone boxed: click yourself. Your partner and the opponents are found for you.
After that nothing more is asked: tracking, plays, positions, movement, posture, the coaching and scouting notes and the PDF are made.
Everything stays on this computer (a YouTube link is downloaded first).

Non-interactive (for scripts, or an AI assistant that has already asked the questions):
    python tools/analyze.py --video match.mp4 --label "Saturday doubles" --mode doubles --hand left --score no --games "0:08-10:25,10:34-19:04" --cards "21-19,21-13"
Run it again with the same --work folder to carry on where it stopped; finished steps are skipped.
With a live score on screen (doubles only) the scoreboard route of run_all.sh is used instead; see docs/HOW_IT_WORKS.md.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGES = ROOT / "stages"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(STAGES))
import numpy as np  # noqa: E402
import common  # noqa: E402

# Exit code 1 is a verdict, not a crash, for these stages (tracking: "look at the sheet"; posture: "too few usable samples" when you were far from the camera
# for the whole game). The output files are still written, so the run goes on; tracking is judged separately below.
OK_EXIT = {"s03_players.py": (0, 1), "s08_pose.py": (0, 1), "check_tracking.py": (0, 1)}
MODES = common.MODES
HANDS = common.HANDS


# ---------------------------------------------------------------------------------------------
# reading answers
# ---------------------------------------------------------------------------------------------
def parse_time(text):
    """'1:05' -> 65.0, '1:02:03' -> 3723.0, '65' or '65.5' -> seconds. Raises ValueError."""
    parts = str(text).strip().split(":")
    if not 1 <= len(parts) <= 3 or not all(re.fullmatch(r"\d+(\.\d+)?", p) for p in parts):
        raise ValueError(f"cannot read the time {text!r}: write minutes:seconds, for example 10:25")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


def parse_games(text, video_seconds=None):
    """'0:08-10:25, 10:34-19:04' -> [(8.0, 625.0), (634.0, 1144.0)]. Empty means one game over the whole video. The last end may be left out ('10:34-')."""
    text = (text or "").strip()
    if not text:
        return [(0.0, video_seconds)] if video_seconds else [(0.0, None)]
    games = []
    for piece in re.split(r"[,;]\s*", text):
        m = re.fullmatch(r"\s*([\d:.]+)\s*[-–]\s*([\d:.]*)\s*", piece)
        if not m:
            raise ValueError(f"cannot read {piece!r}: write each game as start-end, for example 0:08-10:25, separated by commas")
        a = parse_time(m.group(1))
        b = parse_time(m.group(2)) if m.group(2) else video_seconds
        if b is not None and b <= a + 30:
            raise ValueError(f"the game {piece!r} ends less than 30 seconds after it starts")
        games.append((a, b))
    for (a1, b1), (a2, b2) in zip(games, games[1:]):
        if b1 is None or a2 < b1:
            raise ValueError("the games must be in order and must not overlap")
    return games


def parse_cards(text, n_games):
    """'21-19, 21-13' -> ['21-19', '21-13'] (your score first). Empty means unknown."""
    text = (text or "").strip()
    if not text:
        return [None] * n_games
    cards = [c.strip() for c in re.split(r"[,;]\s*", text)]
    if len(cards) != n_games or not all(re.fullmatch(r"\d{1,2}\s*[-–]\s*\d{1,2}", c) for c in cards):
        raise ValueError(f"give one score per game, yours first, for example 21-19, 21-13 ({n_games} game{'s' if n_games != 1 else ''})")
    return [re.sub(r"\s*[–]\s*|\s*-\s*", "-", c) for c in cards]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "match"


def first_near_for(game_index, seen_game_index, you_half):
    """Which team is on the near half at the start of a game. Teams swap ends between games, so the side alternates from the picture's game on."""
    you_near_then = you_half == "near"
    same_side = (game_index - seen_game_index) % 2 == 0
    return "A" if you_near_then == same_side else "B"


def game_of(t, games):
    for i, (a, b) in enumerate(games):
        if a <= t and (b is None or t < b):
            return i
    return 0


def ask(prompt, default=None, choices=None, check=None):
    """One question in the terminal. choices: accepted answers (case-insensitive); check: function that raises ValueError for a bad answer."""
    while True:
        tail = f" [{default}]" if default not in (None, "") else ""
        if choices:
            tail = f" ({'/'.join(choices)})" + tail
        raw = input(f"{prompt}{tail}: ").strip()
        if not raw and default is not None:
            raw = str(default)
        if choices and raw.lower() not in choices:
            print(f"  Please answer with one of: {', '.join(choices)}")
            continue
        if check:
            try:
                check(raw)
            except ValueError as e:
                print(f"  {e}")
                continue
        return raw.lower() if choices else raw


def gather(args, saved, interactive):
    """The answers: flags first, then what was saved by an earlier run, then questions (only when a person is at the keyboard)."""
    ans = dict(saved)
    for k in ("video", "label", "mode", "hand", "score", "games", "cards", "start"):
        v = getattr(args, k, None)
        if v is not None:
            ans[k] = v
    if not interactive:
        ans.setdefault("score", "no")
        if "video" in ans:
            ans.setdefault("label", Path(ans["video"]).stem if not str(ans["video"]).startswith("http") else "My match")
    need = [k for k in ("video", "label", "mode", "hand", "score") if k not in ans]
    if need and not interactive:
        raise SystemExit("These answers are missing and there is no keyboard to ask: " + ", ".join("--" + k for k in need)
                         + ". Run the script in a terminal to be asked, or pass them as flags (see --help).")
    if "video" not in ans:
        print("\nLet's analyse a match.\n")
        ans["video"] = ask("1. Where is the video? Give the path to a file, or a YouTube link to a match you filmed")
    if "label" not in ans:
        default = Path(ans["video"]).stem if not ans["video"].startswith("http") else "My match"
        ans["label"] = ask("   What would you like to call this match? (shown on the report)", default)
    if "mode" not in ans:
        ans["mode"] = ask("2. Is it singles or doubles?", "doubles", MODES)
    if "hand" not in ans:
        ans["hand"] = ask("3. Which hand do you hit with?", None, HANDS)
    if "score" not in ans:
        ans["score"] = ask("4. Does the video show a live score on screen that changes every rally?", "no", ("yes", "no"))
    if ans["mode"] not in MODES or ans["hand"] not in HANDS or str(ans["score"]).lower() not in ("yes", "no", "true", "false"):
        raise SystemExit("--mode must be singles or doubles, --hand left or right, --score yes or no")
    ans["score"] = str(ans["score"]).lower() in ("yes", "true")
    if "games" not in ans:
        if interactive:
            ans["games"] = ask("5. How many games are in the video? Say when each starts and ends, like 0:08-10:25, 10:34-19:04 (Enter = one game, the whole video)", "",
                               check=lambda t: parse_games(t, 1e9))
        else:
            ans["games"] = ""
    if "cards" not in ans:
        n = len(parse_games(ans["games"], 1e9))
        ans["cards"] = ask("6. Do you know each game's final score, yours first, like 21-19, 21-13? (Enter to skip)", "", check=lambda t: parse_cards(t, n)) if interactive else ""
    ans.setdefault("start", None)
    return ans


# ---------------------------------------------------------------------------------------------
# running the stages
# ---------------------------------------------------------------------------------------------
class Runner:
    def __init__(self, work, dry=False, verbose=False):
        self.work, self.dry, self.verbose = work, dry, verbose
        self.logs = work / "logs"
        self.step_no = 0
        self.t0 = time.time()
        self.commands = []

    def say(self, text):
        print(f"[{time.time() - self.t0:5.0f}s] {text}", flush=True)

    def _cmd(self, script, args):
        path = script if os.path.isabs(str(script)) else (STAGES / script if (STAGES / script).exists() else TOOLS / script)
        return [sys.executable, str(path), *map(str, args)]

    def run(self, label, script, args, *, ok_codes=(0,), background=False):
        """Run one stage script. Returns the exit code (or the Popen for a background run). The output goes to logs/<label>.log."""
        cmd = self._cmd(script, args)
        self.commands.append((label, cmd))
        if self.dry:
            print("WOULD RUN:", " ".join(cmd))
            return 0
        self.logs.mkdir(parents=True, exist_ok=True)
        log = open(self.logs / f"{slug(label)}.log", "w")
        self.say(label + " ...")
        if background:
            return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT).returncode
        log.close()
        if rc not in ok_codes:
            self.fail(label, rc)
        return rc

    def interactive(self, label, script, args):
        """A stage that talks to the person (opens a page and waits)."""
        cmd = self._cmd(script, args)
        self.commands.append((label, cmd))
        if self.dry:
            print("WOULD RUN:", " ".join(cmd))
            return 0
        self.say(label)
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc != 0:
            self.fail(label, rc)
        return rc

    def wait(self, label, proc):
        if self.dry or proc in (None, 0):          # nothing was started (a finished step is skipped on a re-run)
            return
        self.say(f"waiting for: {label}")
        rc = proc.wait()
        if rc != 0:
            self.fail(label, rc)

    def fail(self, label, rc):
        log = self.logs / f"{slug(label)}.log"
        tail = ""
        if log.exists():
            tail = "\n".join(log.read_text(errors="replace").strip().splitlines()[-14:])
        raise SystemExit(f"\nStopped: '{label}' failed (exit code {rc}).\n{tail}\n\nFull output: {log}\nFix the problem and run the same command again: finished steps are skipped.")


def verify_identity(players_npz, seen, game_start, game_end):
    """After tracking: at the moment of the picture, your track must be where you clicked. Returns None when it is, otherwise a message.
    A track that sits where your partner stood means the labels are inverted: every number about you would really be your partner's."""
    import numpy as np
    if not seen or "you_xy" not in seen or not (game_start <= seen.get("t", -1) < game_end):
        return None
    z = np.load(players_npz, allow_pickle=True)
    r = int(np.argmin(np.abs(np.asarray(z["t"], float) - seen["t"])))
    if abs(float(z["t"][r]) - seen["t"]) > 1.0:
        return None
    def dist(slot, xy):
        p = np.asarray(z[f"{slot}_xy"], float)[max(0, r - 3):r + 4]
        p = p[~np.isnan(p[:, 0])]
        return float(np.min(np.hypot(p[:, 0] - xy[0], p[:, 1] - xy[1]))) if len(p) else None
    you = dist("A_you", seen["you_xy"])
    if you is not None and you <= 1.0:
        return None
    mate = dist("A_partner", seen["you_xy"]) if "partner_xy" in seen else None
    if mate is not None and mate <= 1.0:
        return (f"At {seen['t']:.0f} s you clicked yourself at a spot where the tracker put your PARTNER label: the two labels are inverted. "
                "Nothing after this point would be about you.")
    return (f"At {seen['t']:.0f} s the track labelled YOU is {you:.1f} m from where you clicked yourself" if you is not None else
            f"At {seen['t']:.0f} s the track labelled YOU has no position near where you clicked yourself") + ". Look at the label check sheet before trusting anything."


def have(*paths):
    return all(Path(p).exists() for p in paths)


def video_seconds(work):
    info = work / "proxy_info.json"
    if info.exists():
        d = json.loads(info.read_text())
        if isinstance(d.get("duration"), (int, float)):
            return float(d["duration"])
    import cv2
    cap = cv2.VideoCapture(str(work / "proxy.mp4"))
    n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()
    return float(n / fps)


def game_commands(work, proxy, video, cfg_path, i, start, end, first_near, card, args):
    """Every stage command for one game, in order: [(label, script, args, the file it makes)]."""
    d = work / f"g{i + 1}"
    n = i + 1
    expect = ["--expect", sum(int(x) for x in re.findall(r"\d+", card))] if card else []
    out = [(f"Tracking the players, game {n}", "s03_players.py",
            ["--proxy", proxy, "--cand", work / "cand.npz", "--start", f"{start:.1f}", *(["--end", f"{end:.1f}"] if end else []), "--out", d / "players.npz",
             "--config", cfg_path, "--end-change", "auto", "--first-near", first_near, "--margin", "1.0"], d / "players.npz"),
           (f"Finding the plays, game {n}", "s06f_play_windows.py",
            ["--players", d / "players.npz", "--audio-from", video, "--out", d / "play_windows.json", *expect], d / "play_windows.json"),
           (f"Positions and movement, game {n}", "s07f_free_stats.py",
            ["--players", d / "players.npz", "--windows", d / "play_windows.json", "--config", cfg_path, "--out", d / "free_stats.json"], d / "free_stats.json")]
    if not args.no_pose:
        out.append((f"Posture, game {n}", "s08_pose.py",
                    ["--proxy", proxy, "--players", d / "players.npz", "--windows", d / "play_windows.json", "--config", cfg_path, "--out", d / "pose_stats.json",
                     "--weights-dir", ROOT / "models"], d / "pose_stats.json"))
    return out


def cue_disagreement(players_npz, cand_npz):
    """How often the label disagrees with the shorts, over the samples where the shorts can be read: (share of YOU labels on a dark reading, share of
    PARTNER labels on a light one, samples read for each). An upper bound on wrong labels (some readings are noise); None without a candidate file."""
    import numpy as np
    if not Path(cand_npz).exists():
        return None
    c = np.load(cand_npz)
    cols = [str(x) for x in c["cols"]]
    ix = {k: i for i, k in enumerate(cols)}
    if "sL" not in ix:
        return None
    D = c["data"]
    H = float(c["frame_h"]) if "frame_h" in c.files else 720.0
    by = {}
    for i, f in enumerate(D[:, ix["f"]].astype(int)):
        by.setdefault(f, []).append(i)
    z = np.load(players_npz, allow_pickle=True)

    def readings(slot):
        out = np.full(len(z["frames"]), np.nan)
        boxes, flags = z[f"{slot}_box"], z[f"{slot}_flag"]
        for r in range(len(out)):
            if flags[r] != 1 or np.isnan(boxes[r][0]):
                continue
            for i in by.get(int(z["frames"][r]), []):
                if abs(D[i, ix["x1"]] - boxes[r][0]) < 1.5 and abs(D[i, ix["y2"]] - boxes[r][3]) < 1.5:
                    if not common.shorts_unreliable(D[i, ix["x1"]], D[i, ix["y1"]], D[i, ix["x2"]], D[i, ix["y2"]], H):
                        out[r] = D[i, ix["sL"]]
                    break
        return out

    you, mate = readings("A_you"), readings("A_partner")
    ny, nm = int((~np.isnan(you)).sum()), int((~np.isnan(mate)).sum())
    if ny < 100 or nm < 100:
        return None
    return float(((you < 38) & ~np.isnan(you)).sum() / ny), float(((mate > 45) & ~np.isnan(mate)).sum() / nm), ny, nm


def write_games_json(work, ans, games, cfg, you_describe_games):
    mode = common.match_mode(cfg)
    cards = parse_cards(ans.get("cards", ""), len(games))
    known = [c for c in cards if c]
    note = "The video shows no score during play." if not known else \
        ("Final scores you gave, yours first: " + ", ".join(c or "?" for c in cards) + ". The video shows no score during play.")
    checks = []
    calib = work / "calib.json"
    if calib.exists():
        c = json.loads(calib.read_text())
        n = len(c.get("points", []))
        checks.append({"what": "Court position", "how": f"Fitted to the {n} points you clicked on the court photo (fit error {c.get('rms_px', 0):.1f} px, which only says the points agree with each other). "
                                                    "Look at the court picture on page 2: if the lines do not sit on the paint, the numbers are wrong.", "level": "approximate"})
    cov = []
    for i in range(len(games)):
        pj = work / f"g{i + 1}" / "players.json"
        if pj.exists():
            cov.append(json.loads(pj.read_text()).get("coverage", {}))
    if mode == "doubles" and cfg["A_you"].get("shorts"):
        dis = []
        for i in range(len(games)):
            d = cue_disagreement(work / f"g{i + 1}" / "players.npz", work / "cand.npz")
            if d:
                dis.append(f"game {i + 1}: {100 * d[0]:.0f}% of your labels and {100 * d[1]:.0f}% of your partner's")
        if dis:
            checks.append({"what": "Labels against the shorts", "how": "Where the shorts could be read, the label disagrees with them in " + "; ".join(dis) +
                                                                      ". This is an upper bound on wrong labels (some readings are noise), and the wrong ones come in short runs, mostly when the two of you overlap or one of you is at the camera.",
                           "level": "approximate"})
    if cov:
        yours = ", ".join(f"{100 * c.get('A_you', 0):.0f}%" for c in cov)
        checks.append({"what": "Who is who", "how": f"You were found in {yours} of the play time (game by game). The labels still have to be checked by eye on the label check sheets (work folder, g1/qa_check.jpg and so on); "
                                                    "until that is done this stays approximate.", "level": "approximate"})
    if mode == "doubles" and cfg["_match"].get("opponents_indistinct"):
        checks.append({"what": "Which opponent is which", "how": "The two opponents looked alike, so they were tracked as a pair and single-opponent numbers should be ignored.", "level": "weak"})
    elif mode == "doubles":
        checks.append({"what": "Which opponent is which", "how": "Told apart by clothes only and not checked by eye; use the pair numbers for the opponents.", "level": "weak"})
    checks.append({"what": "Plays", "how": "Found from movement and shuttle sound. The sound also picks up other courts, so a play is where sound and movement agree.", "level": "approximate"})
    doc = {"label": ans["label"], "mode": mode, "racket_hand": cfg["_match"].get("hand"), "you": cfg["A_you"]["describe"],
           "games": [{"dir": f"g{i + 1}", "title": f"Game {i + 1}", **({"card": cards[i]} if cards[i] else {})} for i in range(len(games))],
           "card_note": note, "checks": checks}
    if mode == "doubles":
        doc["partner"] = cfg["A_partner"]["describe"]
        doc["opponents"] = f"{cfg['B_opp1']['describe']} and {cfg['B_opp2']['describe']}" if not cfg["_match"].get("opponents_indistinct") else "two opponents who look alike"
    else:
        doc["opponents"] = cfg["B_opp1"]["describe"]
    (work / "games.json").write_text(json.dumps(doc, indent=1) + "\n")
    return doc


def pipeline(ans, work, args):
    R = Runner(work, dry=args.dry_run)
    work.mkdir(parents=True, exist_ok=True)
    (work / "match.json").write_text(json.dumps(ans, indent=1) + "\n")
    video = ans["video"]
    if not R.dry and not re.match(r"https?://", video) and not Path(video).expanduser().exists():
        raise SystemExit(f"cannot find the video file: {video}")

    # 0. a link is downloaded first
    if re.match(r"https?://", video):
        if not have(work / "download" / "source.json"):
            R.interactive("Downloading the video", "fetch_video.py", [video, "--out-dir", work / "download", *(["--confirm-rights"] if args.yes else [])])
        src = work / "download" / (json.loads((work / "download" / "source.json").read_text())["file"] if not R.dry else "video.mp4")
        video = str(src)
    video = str(Path(video).expanduser().resolve()) if not R.dry else video
    proxy = work / "proxy.mp4"

    if ans["score"]:
        if ans["mode"] == "singles":
            print("Note: reading a live score is only built for doubles, so you get the position-and-movement report instead.")
            ans["score"] = False
        else:
            return scoreboard_route(R, ans, work, video, args)

    # 1. a small copy of the video, then find the people in it while you click the court
    if not have(proxy):
        R.run("Making a small copy of the video", "s00_proxy.py", ["--src", video, "--out-dir", work])
    det = None
    if not have(work / "dets.json"):
        det = R.run("Finding the people in the video", "s01_detect.py", ["--proxy", proxy, "--out", work / "dets.json"], background=True)
    if not have(work / "court_points.json"):
        R.interactive("Click the court", "pick_court_points.py", ["--video", proxy, "--out", work / "court_points.json", *(["--no-browser"] if args.no_browser else [])])
    R.wait("finding the people", det)
    if not have(work / "calib.json"):
        R.run("Fitting the court", "s02_calibrate.py", ["--proxy", proxy, "--points", work / "court_points.json", "--out", work / "calib.json"])
    if not have(work / "cand.npz"):
        R.run("Reading what the people wear", "s03_features.py", ["--proxy", proxy, "--dets", work / "dets.json", "--calib", work / "calib.json", "--out", work / "cand.npz"])

    # 2. the games
    secs = video_seconds(work) if not R.dry else 1200.0
    games = parse_games(ans.get("games", ""), secs)
    games = [(a, b if b is not None else secs) for a, b in games]
    first_start = float(ans["start"]) if ans.get("start") else games[0][0]
    games[0] = (first_start, games[0][1])
    print(f"Games: " + ", ".join(f"{i + 1}: {a:.0f}s to {b:.0f}s" for i, (a, b) in enumerate(games)))

    # 3. who are you
    cfg_path = work / "players_config.json"
    if not have(cfg_path):
        R.interactive("Click yourself", "pick_players.py", ["--video", proxy, "--cand", work / "cand.npz", "--start", f"{first_start:.1f}", "--mode", ans["mode"], "--hand", ans["hand"],
                                                           "--out", cfg_path, *(["--no-browser"] if args.no_browser else [])])
    cfg = common.load_config(cfg_path) if not R.dry else {"_match": {"mode": ans["mode"], "hand": ans["hand"], "seen": {"t": first_start + 60, "you_half": "near"}},
                                                           "A_you": {"describe": "you"}, "A_partner": {"describe": "your partner"}, "B_opp1": {"describe": "opp 1"}, "B_opp2": {"describe": "opp 2"}}
    seen = cfg["_match"].get("seen") or {}
    gp = game_of(seen.get("t", first_start), games)
    half = seen.get("you_half", "near")

    # 4. each game
    cards = parse_cards(ans.get("cards", ""), len(games))
    for i, (a, b) in enumerate(games):
        fn = first_near_for(i, gp, half)
        (work / f"g{i + 1}").mkdir(exist_ok=True)
        for label, script, sargs, made in game_commands(work, proxy, video, cfg_path, i, a, b, fn, cards[i], args):
            if have(made):
                continue
            if script == "s03_players.py":
                rc = R.run(label, script, sargs, ok_codes=(0, 1))
                if not R.dry and not made.exists():            # exit code 1 without a result file is a crash, not a failed check
                    R.fail(label, rc)
                problem = verify_identity(made, seen, a, b) if made.exists() else None
                if problem and not args.keep_going:
                    made.unlink()
                    raise SystemExit(f"\nStopped: {problem}\nPress 'Another picture' in the picker and click yourself again (delete {cfg_path} first), or run with --keep-going to look at it anyway.")
                if rc == 1 and not args.keep_going:
                    for f in (made, made.with_suffix(".json")):
                        if f.exists() and f.suffix == ".npz":
                            f.unlink()                      # a failed track is not kept, so a re-run does it again
                    raise SystemExit(f"\nStopped: the tracking check failed for game {i + 1} (see {made.with_suffix('.json')} and {made.with_name('s03_check.jpg')}).\n"
                                     "Usually someone is missing from many frames or the labels jump. Look at the sheet; if it is acceptable run again with --keep-going.")
            else:
                R.run(label, script, sargs, ok_codes=OK_EXIT.get(script, (0,)))
                if script == "s08_pose.py" and not R.dry and not made.exists():
                    raise SystemExit(f"\nStopped: '{label}' wrote no result ({made}). See {R.logs / (slug(label) + '.log')}.")
        qa = work / f"g{i + 1}" / "qa_check.jpg"
        if not have(qa):
            R.run(f"Making the label check sheet, game {i + 1}", "check_tracking.py", ["--proxy", proxy, "--players", work / f"g{i + 1}" / "players.npz", "--out", qa], ok_codes=(0, 1))

    # 5. the report
    if R.dry:
        print("WOULD WRITE games.json, then run s14a_free_words.py and s14_free_report.py")
        return R
    write_games_json(work, ans, games, cfg, None)
    R.run("Writing the coaching and scouting notes", "s14a_free_words.py", ["--work", work])
    R.run("Building the PDF report", "s14_free_report.py", ["--work", work, "--page", args.page])
    finish(work, games)
    return R


def scoreboard_route(R, ans, work, video, args):
    """Doubles with a live score on screen: the stage chain of run_all.sh. Its own checkpoints (game start, who is who) still apply."""
    env = dict(os.environ, SCOREBOARD="yes", LABEL=ans["label"], PAGE=args.page)
    cmd = ["bash", str(ROOT / "run_all.sh"), video, str(work)]
    R.commands.append(("scoreboard route", cmd))
    if R.dry:
        print("WOULD RUN:", " ".join(cmd))
        return R
    cfg_path = work / "players_config.json"
    if not have(work / "court_points.json") or not have(cfg_path):
        print("Note: this route stops at three checkpoints (court, game start, who is who). Do each one as asked and run this command again.")
    rc = subprocess.run(cmd, env=env, cwd=ROOT).returncode
    if rc == 2:
        print("\nThe script stopped at a checkpoint (see the message above). Do that step, then run the same command again.")
    return R


def finish(work, games):
    pdf = work / "match_report.pdf"
    tips = json.loads((work / "tips.json").read_text()) if (work / "tips.json").exists() else []
    print("\n" + "=" * 70)
    print(f"Done. Your report: {pdf}")
    if tips:
        print("What it found:")
        for t in tips[:3]:
            print(f"  - {t['title']}")
    print("\nBefore you trust it, look at:")
    for i in range(len(games)):
        print(f"  - {work / f'g{i + 1}' / 'qa_check.jpg'}  (every label must sit on the right person)")
    print(f"  - page 2 of the PDF (the court drawn on the photo must sit on the lines you played on)")
    print("Not measured: who won each rally, serves, shots, errors (the video has no score).")
    print("=" * 70)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", help="video file or YouTube link")
    ap.add_argument("--label", help="a name for the match (shown on the report)")
    ap.add_argument("--mode", choices=MODES, help="singles or doubles")
    ap.add_argument("--hand", choices=HANDS, help="the hand you hit with")
    ap.add_argument("--score", choices=("yes", "no"), help="does the video show a live score on screen")
    ap.add_argument("--games", help="when each game starts and ends, e.g. 0:08-10:25,10:34-19:04 (default: the whole video is one game)")
    ap.add_argument("--cards", help="final score of each game, yours first, e.g. 21-19,21-13 (optional)")
    ap.add_argument("--start", type=float, help="second the first game really starts (overrides the start in --games)")
    ap.add_argument("--work", help="folder for everything this run makes (default: work_<name of the match>)")
    ap.add_argument("--page", choices=("A4", "letter"), default="A4")
    ap.add_argument("--yes", action="store_true", help="for a YouTube link: confirm you filmed the video or may use it")
    ap.add_argument("--no-browser", action="store_true", help="print the page addresses instead of opening a browser")
    ap.add_argument("--no-pose", action="store_true", help="skip the posture stage (it is the slowest after detection)")
    ap.add_argument("--keep-going", action="store_true", help="carry on even if a tracking check fails")
    ap.add_argument("--dry-run", action="store_true", help="print what would run, run nothing")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    saved = {}
    if args.work and (Path(args.work) / "match.json").exists():
        saved = json.loads((Path(args.work) / "match.json").read_text())
    try:
        ans = gather(args, saved, interactive=sys.stdin.isatty() and not args.dry_run)
        parse_games(ans.get("games", ""), 1e9)
        parse_cards(ans.get("cards", ""), len(parse_games(ans.get("games", ""), 1e9)))
    except ValueError as e:
        raise SystemExit(str(e))
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("\nStopped.")
    work = Path(args.work or f"work_{slug(ans['label'])}").resolve()
    pipeline(ans, work, args)


if __name__ == "__main__":
    main()
