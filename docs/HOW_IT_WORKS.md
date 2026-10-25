# How it works

For developers and curious players. Start with the [README](../README.md) for what the project does.

## Folder layout

```
stages/        one script per stage, run in order (s00 ... s12) plus common.py (shared definitions)
tools/         pick_court_points.py (click the court), anonymize.py (blur faces for examples)
tests/         fast unit tests: python -m unittest discover -s tests
examples/      one reference match: anonymised numbers and blurred images only
docs/          guides and the project report
CLAUDE.md      the playbook an AI assistant follows
run_all.sh     all stages in order, stopping where a person must look
work/          YOUR outputs (git-ignored; never committed)
```

## Conventions

* **Time** is video time in seconds (the proxy copy keeps the original timeline).
* **Court coordinates** (metres): `X` across the court 0 to 6.1, `Y` along it 0 to 13.4. `Y = 0` is the baseline closest to the
  camera, the net is at `Y = 6.7`, `X = 0` is the left doubles sideline for a player on the near baseline facing the net.
* **Player slots**: `A_you`, `A_partner` (your team) and `B_opp1`, `B_opp2` (opponents). Doubles only.
* **Every stage** prints its checks and ends with `PASSED` or `FAILED`, writes JSON or `.npz` next to the other outputs, and
  writes a check image where a person should look.

## The stages

| stage | script | in | out | main idea and check |
|---|---|---|---|---|
| 0 | `s00_proxy.py` | video | `proxy.mp4`, `proxy_info.json` | ffmpeg to 1280x720, 30 fps, SDR. Refuses HDR (needs `zscale`). 7 automatic checks |
| 1 | `s01_detect.py` | proxy | `dets.json` | YOLO person boxes every 3rd frame. 5 checks and a sheet |
| 2 | `s02_calibrate.py` | proxy, `court_points.json` | `calib.json` | homography pixels to metres from clicked points. Fit error under 4 px, red court drawn over the photo |
| 3a | `s03_features.py` | proxy, dets, calib | `cand.npz` | each box projected to court metres, with shirt-colour features |
| 3b | `s03_find_start.py` | proxy, cand, calib | `game_start.json` | quiet serve-setup windows; a game is a run of 4+ less than 30 s apart. A suggestion: a person confirms |
| 3c | `s03_players.py` | cand, config, start | `players.npz` | four tracks. Colour scores plus continuity, Hungarian assignment, gap fill and despike |
| 4a | `s04a_overlay.py` | proxy | `overlay.json` | reads the on-screen score (macOS Vision) and decodes with the scoring rule |
| 4 | `s04_serves.py` | players, overlay, start | `serves.json` | serve windows; which team serves (below) |
| 5 | `s05_score.py` | serves | `score.json` | replays the doubles rules; independent same-player test |
| 6 | `s06_rallies.py` | serves, score, players | `points.json` | rally start and end, winner, running score |
| 7 | `s07_movement.py` | players, points | `motion.json`, heatmaps | distance, speed, depth shares, pair cover; won vs lost with Mann-Whitney tests |
| 8 | `s08_pose.py` | proxy, players, points | `pose_stats.json` | YOLO pose on near-half crops: knee angle, racket hand |
| 9 | `s09_pickups.py` | players, serves, points | `pickups.json` | bends near the end of a rally vs the loser; reports NOT USABLE if it is chance |
| 10 | `s10_report.py`, `s10_build_report.py` | all | `report_data.json`, `report.md` | numbers, then the document. The coaching text comes from `coaching.md` |
| 11 | `s11_video.py` | proxy, players, points | `analysis_video.mp4` | overlays, mini-map, optional spoken summary (macOS `say`) |
| 12 | `s12_images.py` | all, `tips.json` | `images/*.png` | the statistics as pictures |

## Scores (important)

Rallies and winners need, for every rally, the score *before* it, server first. Today that comes from an on-screen
scoreboard read by `s04a_overlay.py`. The reference video shows the score for 2 to 3 seconds while the players set up to serve.

If your video has no scoreboard, write `work/overlay.json` yourself:

```json
{"runs": [{"j": 1, "t_on": 70.3, "t_off": 72.9, "first": 1, "second": 0, "votes": []},
          {"j": 2, "t_on": 81.4, "t_off": 84.0, "first": 2, "second": 0, "votes": []}]}
```

`j` counts from 1; run `j` is the window before rally `j + 1`; `t_on` and `t_off` bracket the time the players stand
still before the serve; `first` is the **server's** score and `second` the receiver's. Rally 1 (0-0) uses the window in
`game_start.json` (`first_window_on`, `first_window_off`). Each run must be a legal step from the one before (the server wins
again: `(s+1, r)`; the receiver wins: `(r+1, s)`); the stage checks this. A helper that builds this file from a written
score list is the most useful missing piece (see CONTRIBUTING).

## Which team serves

The scoreboard gives the server's score but not the team. Between two non-tied scores the numbers say whether the same team
serves again, so the rallies fall into **chains** that break only at tied scores. In each chain the stage votes for which
team serves, using one cue measured in the pre-serve window: the team whose two players stand further apart *sideways* is
receiving (receivers keep their lanes, the server and partner swap courts); the compact team serves. A weaker second cue
is depth spread. Checks:

* Court parity: the server's score (even = right court) predicts which diagonal service quadrants are occupied. Correct parity should beat wrong parity clearly.
* **Same-player test** (stage 5): while a team keeps winning on serve, the same player must serve. If the cue pointed at the wrong team, the "server" would be the receiver, who changes every time. The stage prints the test for both directions. If the wrong one wins, rerun stage 4 with `--flip-cue`.
* `common.chain_status` marks each chain `confirmed` (two or more same-player pairs), `one pair` or `cue only`. The report and the "how sure" image show it.

## Players and shirt colours

`players_config.json` names a shirt colour per slot. `common.colour_score` turns a detection's torso features into a 0 to 1 score
for each colour (red, blue, green, yellow, orange by hue fraction; black and grey and white by lightness). Tracking assigns the
best detection to each slot by colour plus closeness to the last position. A bright colour, if present, is also used to find which
half each team is on and when they swap ends (once, at most).

## Extending

* **New metric**: compute it in `s07_movement.py` per rally, add it to the summary, and add a panel in `s12_images.py`. Keep every claim data-driven.
* **New colour**: add a hue fraction in `s03_features.py` and a score in `common.colour_score`.
* **New stage**: read and write JSON next to the others, end with `PASSED`/`FAILED`, and add a check image where a person must look.
* **Run the tests**: `python -m unittest discover -s tests`. Add a test for any logic that is not an image or a model.

## Known weak points

* Player identity relies on shirt colour; white versus grey and shaded white are the weakest pairs.
* The serve cue was found on one video. The same-player test is the safety net; it can fail on others.
* Start detection is a suggestion and can be wrong on warm-ups.
* Pose on far-half players is not reliable at low resolution and is not used for conclusions.
* Everything assumes one end change at most.
