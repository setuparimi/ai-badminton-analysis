"""Shared definitions for the stage scripts.

* The player slots: team A is "your team", team B the opponents. Doubles has four, singles two (A_you and B_opp1).
* players_config.json: which shirt colour each slot wears, so stage 3 can tell people apart.
* Clothing-colour scores: how well a detected person matches a named shirt colour.
* Which team is on the near half of the court at a given time (teams swap ends at most once).

Stage scripts import this as `import common` (they are run as `python stages/sNN_x.py`).
"""
import json
from pathlib import Path

import numpy as np

# slot order is kept from the first version (red/white, dark/grey) so results are comparable
SLOTS = ["A_partner", "A_you", "B_opp1", "B_opp2"]
TEAMS = {"A": ("A_partner", "A_you"), "B": ("B_opp1", "B_opp2")}
ROLE = {"A_you": "you", "A_partner": "your partner", "B_opp1": "opponent 1", "B_opp2": "opponent 2"}
SHORT = {"A_you": "YOU", "A_partner": "PARTNER", "B_opp1": "OPP", "B_opp2": "OPP"}

MODES = ("doubles", "singles")
HANDS = ("left", "right")
SINGLES_SLOTS = ["A_you", "B_opp1"]

COLOURS = ("red", "white", "black", "grey", "blue", "green", "yellow", "orange")
SHORTS = ("white", "dark")                                    # optional extra cue: shorts or skirt, read from the legs
CHROMATIC = ("red", "blue", "green", "yellow", "orange")   # colours that are easy to find by hue
NO_CHANGE = 1.0e9                                           # "tc" value when the teams never swap ends


def mmss(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def pword(p):
    """a plain-words reading of a p-value (the chance of a gap this big if there were really none)"""
    return "probably real" if p < 0.01 else ("suggestive" if p < 0.05 else ("a hint only" if p < 0.2 else "no real gap"))


def cutaway_runs(counts, frame_ids, fps, min_seconds=2.0):
    """Title cards, logo cards and black frames: runs of consecutive sampled frames with nobody in them that last at least min_seconds.

    counts: people found per sampled frame; frame_ids: the frame numbers (ascending). Returns (runs as [start_s, end_s], share of ALL
    sampled frames that are empty but not inside such a run). A detector that misses people shows up in the second number."""
    counts = np.asarray(counts)
    ids = np.asarray(frame_ids, float)
    if len(counts) == 0:
        return [], 0.0
    dt = float(np.median(np.diff(ids))) / fps if len(ids) > 1 else 0.0
    empty = counts == 0
    runs, start = [], None
    for i, e in enumerate(list(empty) + [False]):
        if e and start is None:
            start = i
        elif not e and start is not None:
            if (ids[i - 1] - ids[start]) / fps + dt >= min_seconds:
                runs.append((start, i - 1))
            start = None
    in_run = np.zeros(len(counts), bool)
    for a, b in runs:
        in_run[a:b + 1] = True
    cut = [[round(float(ids[a] / fps), 2), round(float(ids[b] / fps + dt), 2)] for a, b in runs]
    return cut, float((empty & ~in_run).mean())


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def other(team):
    return "A" if team == "B" else "B"


def near_team_at(t, tc, first_near):
    """team on the near half of the court at time t"""
    return first_near if t < tc else other(first_near)


NET_Y = 6.7          # court metres: the net, along the length of the court
TEAM_WIDTH = 6.1     # court metres: doubles width


def own_half_coords(xy, team_is_near):
    """court (X, Y) rows -> (u, d) in a team's own half: u across (their left to right), d metres from the net.
    xy is an (n, 2) array (nan rows allowed); returns two arrays of length n."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    return (xy[:, 0] if team_is_near else TEAM_WIDTH - xy[:, 0]), np.abs(xy[:, 1] - NET_Y)


# ---------------------------------------------------------------- config
def load_config(path):
    """players_config.json -> dict with one entry per slot: {"shirt": colour or "any", "describe": text, optional "tone": "light"|"dark",
    "tone_split": Lab lightness, optional "shorts": "white"|"dark"}.
    "any" means the shirt is not a reliable cue (a dim hall makes every shirt look dark) and needs "shorts". Two teammates must differ in
    shirt colour, or in shade (one "light", one "dark"), or in shorts. The opponents may be left indistinct (both "any", no shorts): they are
    then tracked as a pair and told apart only by where they were a moment ago.
    An optional "_match" entry says {"mode": "doubles"|"singles", "hand": "left"|"right"}. In singles only A_you and B_opp1 are read; the
    other two slots come back as inactive placeholders (cfg[slot]["inactive"] is True) so that code looping over SLOTS keeps working."""
    cfg = json.loads(Path(path).read_text())
    match = cfg.get("_match") or {}
    if not isinstance(match, dict):
        raise SystemExit(f"{path}: '_match' must be an object")
    mode = match.get("mode", "doubles")
    if mode not in MODES:
        raise SystemExit(f"{path}: _match.mode must be one of {', '.join(MODES)}")
    if match.get("hand") not in (None,) + HANDS:
        raise SystemExit(f"{path}: _match.hand must be one of {', '.join(HANDS)}")
    cfg["_match"] = {"mode": mode, "hand": match.get("hand"), "opponents_indistinct": False, "seen": match.get("seen")}
    for s in SLOTS:
        if mode == "singles" and s not in SINGLES_SLOTS:
            cfg[s] = {"shirt": "any", "describe": "(not playing: singles)", "inactive": True}
            continue
        if s not in cfg or cfg[s].get("shirt") not in COLOURS + ("any",):
            raise SystemExit(f"{path}: slot {s} needs a 'shirt' colour, one of {', '.join(COLOURS)} (or 'any' together with 'shorts')")
        if cfg[s].get("tone") not in (None, "light", "dark"):
            raise SystemExit(f"{path}: slot {s} 'tone' must be 'light' or 'dark'")
        if cfg[s].get("shorts") not in (None,) + SHORTS:
            raise SystemExit(f"{path}: slot {s} 'shorts' must be one of {', '.join(SHORTS)}")
        if mode == "doubles" and cfg[s]["shirt"] == "any" and not cfg[s].get("shorts") and not (s.startswith("B_") and not cfg[s].get("tone")):
            raise SystemExit(f"{path}: slot {s} has shirt 'any', so it needs 'shorts' to be told apart")
        cfg[s].setdefault("describe", f"{cfg[s]['shirt']} top")
    if mode == "doubles":
        for team, (a, b) in TEAMS.items():
            A, B = cfg[a], cfg[b]
            differ = (A["shirt"] != B["shirt"] and "any" not in (A["shirt"], B["shirt"])) or (A.get("tone") and A.get("tone") != B.get("tone")) \
                or (A.get("shorts") and B.get("shorts") and A["shorts"] != B["shorts"])
            if differ:
                continue
            if team == "B" and A["shirt"] == B["shirt"] == "any" and not A.get("shorts") and not B.get("shorts"):
                cfg["_match"]["opponents_indistinct"] = True
                continue
            raise SystemExit(f"{path}: the two players of team {team} cannot be told apart ({A['shirt']} / {B['shirt']}); "
                             f"give them different shirt colours, a light and a dark shade, or white and dark shorts")
    return cfg


def match_mode(cfg):
    return cfg.get("_match", {}).get("mode", "doubles")


def active_slots(cfg):
    """the slots that are really on court: all four in doubles, A_you and B_opp1 in singles"""
    return [s for s in SLOTS if not cfg[s].get("inactive")]


def signature(cfg):
    """(team, colour) used to find which half a team is on: the first chromatic shirt, team A first"""
    for team in ("A", "B"):
        for s in TEAMS[team]:
            if not cfg[s].get("inactive") and cfg[s]["shirt"] in CHROMATIC:
                return team, cfg[s]["shirt"]
    return None


def team_phrase(cfg):
    """wording for reports: (your team, the opponents)"""
    if match_mode(cfg) == "singles":
        return f"you in the {cfg['A_you']['describe']}", f"your opponent in the {cfg['B_opp1']['describe']}"
    return (f"you in the {cfg['A_you']['describe']} and your partner in the {cfg['A_partner']['describe']}",
            f"the opponents in the {cfg['B_opp1']['describe']} and the {cfg['B_opp2']['describe']}")


# ---------------------------------------------------------------- colours
def colour_score(name, f, tone=None, tone_split=112.0):
    """0..1 how well a person matches a shirt colour. f holds the torso features of one detection:
    tL (Lab lightness 0-255) and the pixel fractions t_red, t_blue, t_green, t_yellow, t_orange.
    tone "light" or "dark" additionally asks for a torso lighter or darker than tone_split (two teammates in two shades of one colour)."""
    base = _colour_score(name, f)
    if tone == "light":
        return base * sigmoid((f["tL"] - tone_split) / 10)
    if tone == "dark":
        return base * sigmoid((tone_split - f["tL"]) / 10)
    return base


def _colour_score(name, f):
    tL = f["tL"]
    if name == "red":
        return sigmoid((f["t_red"] - 0.10) / 0.04)
    if name == "black":
        return sigmoid((90 - tL) / 12)
    if name == "white":
        return (1 - _colour_score("red", f)) * (0.25 + 0.75 * sigmoid((tL - 135) / 10))
    if name == "grey":
        return (1 - _colour_score("black", f)) * (0.25 + 0.75 * sigmoid((150 - tL) / 12))
    if name in ("blue", "green", "yellow", "orange"):
        return sigmoid((f["t_" + name] - 0.10) / 0.04)
    raise ValueError(name)


WIDE_BOX = 0.5       # width over height above which a box is mostly an outstretched arm or racket: the middle of it may be floor, not shorts


def shorts_unreliable(x1, y1, x2, y2, frame_h):
    """True where the shorts band of a box cannot be trusted: the box is wide (an arm out puts floor in the middle of it) or it touches the top or
    the bottom of the picture (a player right at the camera is cut off, so the band lands on the shirt and white shorts read dark)."""
    x1, y1, x2, y2 = (np.asarray(v, float) for v in (x1, y1, x2, y2))
    return ((x2 - x1) > WIDE_BOX * (y2 - y1)) | (y2 >= frame_h - 3) | (y1 <= 2)


def shorts_score(kind, f):
    """0..1 how well the shorts match "white" (light) or "dark". f["sL"] is the Lab lightness (0-255) at hip to mid-thigh; candidate files made
    before that column existed fall back to the legs (f["lL"], with l_white / l_dark). In a dim hall white shorts read about 60 to 140 and black
    ones 0 to 20, so the split sits near 40; in good light white reads far higher and the same split still works.
    f["wide"] (optional, True where shorts_unreliable says so) makes the reading uninformative (0.5): with an arm out the middle of the box can be
    bright floor and black shorts read 160; a player cut off at the bottom of the picture has the band on the shirt."""
    if "sL" in f:
        p = sigmoid((f["sL"] - 42) / 10) if kind == "white" else sigmoid((38 - f["sL"]) / 8)
        return np.where(np.asarray(f["wide"], bool), 0.5, p) if "wide" in f else p
    if kind == "white":
        return sigmoid((f["lL"] - 150) / 14) * (0.4 + 0.6 * sigmoid((f["l_white"] - 0.15) / 0.08))
    return sigmoid((95 - f["lL"]) / 14) * (0.4 + 0.6 * sigmoid((f["l_dark"] - 0.4) / 0.15))


def slot_probs(cfg, f):
    out = {}
    for s in SLOTS:
        c = cfg[s]
        if c.get("inactive"):
            out[s] = 0.0
            continue
        p = 1.0 if c["shirt"] == "any" else colour_score(c["shirt"], f, c.get("tone"), c.get("tone_split", 112.0))
        if c.get("shorts"):
            p *= shorts_score(c["shorts"], f)
        out[s] = p
    return out


# ---------------------------------------------------------------- how well backed up is each rally block
def chain_status(serves_doc, score_doc):
    """For each block of rallies between tied scores: how well is the serving team backed up?
    'confirmed' = at least two consecutive same-team serves where the same player served each time
    (an independent check), 'one pair' = one such pair, 'cue only' = only the position cue."""
    rows = score_doc["rows"]
    out = []
    for c in serves_doc["chains"]:
        a, b = c["rallies"]
        pairs = same = 0
        for k in range(a - 1, b - 1):
            if rows[k]["winner"] == rows[k]["server_team"] and rows[k]["server_player"] and rows[k + 1]["server_player"]:
                pairs += 1
                same += rows[k]["server_player"] == rows[k + 1]["server_player"]
        status = "confirmed" if pairs >= 2 and same == pairs else ("one pair" if pairs == 1 and same == 1 else "cue only")
        out.append({"rallies": [a, b], "n": c["n"], "pairs": pairs, "same": same, "status": status})
    return out
