"""Shared definitions for the stage scripts.

* The four player slots (doubles only): team A is "your team", team B the opponents.
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

COLOURS = ("red", "white", "black", "grey", "blue", "green", "yellow", "orange")
CHROMATIC = ("red", "blue", "green", "yellow", "orange")   # colours that are easy to find by hue
NO_CHANGE = 1.0e9                                           # "tc" value when the teams never swap ends


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def other(team):
    return "A" if team == "B" else "B"


def near_team_at(t, tc, first_near):
    """team on the near half of the court at time t"""
    return first_near if t < tc else other(first_near)


# ---------------------------------------------------------------- config
def load_config(path):
    """players_config.json -> dict with one entry per slot: {"shirt": colour, "describe": text}"""
    cfg = json.loads(Path(path).read_text())
    for s in SLOTS:
        if s not in cfg or cfg[s].get("shirt") not in COLOURS:
            raise SystemExit(f"{path}: slot {s} needs a 'shirt' colour, one of {', '.join(COLOURS)}")
        cfg[s].setdefault("describe", f"{cfg[s]['shirt']} top")
    for team, (a, b) in TEAMS.items():
        if cfg[a]["shirt"] == cfg[b]["shirt"]:
            raise SystemExit(f"{path}: the two players of team {team} wear the same shirt colour "
                             f"({cfg[a]['shirt']}); they cannot be told apart by colour")
    return cfg


def signature(cfg):
    """(team, colour) used to find which half a team is on: the first chromatic shirt, team A first"""
    for team in ("A", "B"):
        for s in TEAMS[team]:
            if cfg[s]["shirt"] in CHROMATIC:
                return team, cfg[s]["shirt"]
    return None


def team_phrase(cfg):
    """wording for reports: (your team, the opponents)"""
    return (f"you in the {cfg['A_you']['describe']} and your partner in the {cfg['A_partner']['describe']}",
            f"the opponents in the {cfg['B_opp1']['describe']} and the {cfg['B_opp2']['describe']}")


# ---------------------------------------------------------------- colours
def colour_score(name, f):
    """0..1 how well a person matches a shirt colour. f holds the torso features of one detection:
    tL (Lab lightness 0-255) and the pixel fractions t_red, t_blue, t_green, t_yellow, t_orange."""
    tL = f["tL"]
    if name == "red":
        return sigmoid((f["t_red"] - 0.10) / 0.04)
    if name == "black":
        return sigmoid((90 - tL) / 12)
    if name == "white":
        return (1 - colour_score("red", f)) * (0.25 + 0.75 * sigmoid((tL - 135) / 10))
    if name == "grey":
        return (1 - colour_score("black", f)) * (0.25 + 0.75 * sigmoid((150 - tL) / 12))
    if name in ("blue", "green", "yellow", "orange"):
        return sigmoid((f["t_" + name] - 0.10) / 0.04)
    raise ValueError(name)


def slot_probs(cfg, f):
    return {s: colour_score(cfg[s]["shirt"], f) for s in SLOTS}


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
