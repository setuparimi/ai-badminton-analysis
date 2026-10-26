# How it works

For developers and curious players. Start with the [README](../README.md) for what the project does.

## Folder layout

```
stages/        one script per stage, run in order (s00 ... s14a) plus common.py (shared definitions)
tools/         analyze.py (the guided run: questions, clicks, PDF), make_sample_report.py (the sample report from invented data), pick_court_points.py (click the court), pick_players.py (click yourself), check_tracking.py (the label check sheet), fetch_video.py (optional: save one YouTube video you may use), anonymize.py (blur faces for examples), make_pipeline_diagram.py (draws docs/img/pipeline.png)
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
* **Player slots**: `A_you`, `A_partner` (your team) and `B_opp1`, `B_opp2` (opponents). In singles only `A_you` and `B_opp1` play; the other two are inactive placeholders.
  `players_config.json` has an optional `_match` entry, `{"mode": "doubles"|"singles", "hand": "left"|"right"}`.
* **Every stage** prints its checks and ends with `PASSED` or `FAILED`, writes JSON or `.npz` next to the other outputs, and
  writes a check image where a person should look.

## The stages

| stage | script | in | out | main idea and check |
|---|---|---|---|---|
| 0 | `s00_proxy.py` | video | `proxy.mp4`, `proxy_info.json` | ffmpeg to 1280x720, 30 fps, SDR. Refuses HDR (needs `zscale`). 7 automatic checks |
| 1 | `s01_detect.py` | proxy | `dets.json` | YOLO person boxes every 3rd frame. 5 checks and a sheet. Title cards (2 s or more with nobody in view) are listed as `cutaways` and not counted as misses; `--recheck` re-runs the checks without detecting again |
| 2 | `s02_calibrate.py` | proxy, `court_points.json` | `calib.json` | homography pixels to metres from clicked points. Fit error under 4 px, red court drawn over the photo |
| 3a | `s03_features.py` | proxy, dets, calib | `cand.npz` | each box projected to court metres, with shirt-colour features |
| 3b | `s03_find_start.py` | proxy, cand, calib | `game_start.json` | quiet serve-setup windows; a game is a run of 4+ less than 30 s apart. A suggestion: a person confirms |
| 3c | `s03_players.py` | cand, config, start | `players.npz` | one track per player (the config comes from `tools/pick_players.py`). Clothes scores plus continuity, Hungarian assignment, gap fill and despike. A person is never given a slot whose clothes clearly say someone else, unless the track has run on unbroken for the last 0.3 s. `--end-change auto` finds the starting end and one mid-game end change from the clothes; `--height-ratio auto` follows the lens (a wide-angle lens makes real players read taller); `--first-near A|B` says who starts near |
| 4a | `s04a_overlay.py` | proxy | `overlay.json` | reads the on-screen score (macOS Vision) and decodes with the scoring rule. Finds the score in the top-right or top-left corner by itself. A 0-0, or an unreadable run right after a title card, starts a new game, so a video with several games or sets is decoded game by game and the stage also writes `overlay_gameN.json` and `game_start_gameN.json` |
| 4 | `s04_serves.py` | players, overlay, start | `serves.json` | serve windows; which team serves (below) |
| 5 | `s05_score.py` | serves | `score.json` | replays the doubles rules; independent same-player test |
| 6 | `s06_rallies.py` | serves, score, players | `points.json` | rally start and end, winner, running score |
| 7 | `s07_movement.py` | players, points | `motion.json`, heatmaps | distance, speed, depth shares, pair cover; won vs lost with Mann-Whitney tests |
| 7b | `s07b_opponents.py` | points, motion, players, pose | `opponents.json` | the opponents from their side: results (serving, receiving, by rally length, by server), who plays the net side, pair shape (won vs lost), a 3 x 3 zone map. Depth and zone numbers use only the rallies when they were near the camera |
| 6f | `s06f_play_windows.py` | players, the video's sound | `play_windows.json` | no score on screen: the stretches of play, from shuttle-hit sound (1.8 to 9 kHz clicks) and how much the players move, each as a score, averaged, split by an automatic (Otsu) threshold |
| 7f | `s07f_free_stats.py` | players, windows, config | `free_stats.json` | per player: distance, speed, bursts, front/middle/back and left/middle/right shares, heat map; per pair: side by side or front and back, gap, who is at the back, swaps; load in 2-minute blocks; pace of play. Singles skips the pair |
| 8 | `s08_pose.py` | proxy, players, points or windows | `pose_stats.json` | YOLO pose on near-half crops: knee angle, racket hand, for all players (`--windows` instead of `--points` when there is no score). The model's own left/right is mirrored for people seen from behind, so the hand you declared is used |
| 9 | `s09_pickups.py` | players, serves, points | `pickups.json` | bends near the end of a rally vs the loser; reports NOT USABLE if it is chance |
| 10 | `s10_report.py`, `s10_build_report.py` | all | `report_data.json`, `report.md` | numbers, then `report.md`. Its coaching section is built from `tips.json` and `scouting.json` (or `coaching.md` if you wrote one) |
| 11 | `s11_video.py` | proxy, players, points | `analysis_video.mp4` | overlays, mini-map, optional spoken summary (macOS `say`) |
| 12 | `s12_images.py` | all, `tips.json` | `images/*.png` | the statistics as pictures: 01 to 11 about you, 12 and 13 about the opponents; `07_posture_charts.png` has no photographs |
| 13 | `s13_pdf_report.py` | all, `images/`, `tips.json`, `scouting.json` | `match_report.pdf` | the PDF: cover, match, coaching plan, charts, opponent scouting, moments to check, how sure, appendix. Embedded fonts; charts only unless `--photos` |
| 14a | `s14a_free_words.py` | `games.json`, game folders | `tips.json`, `scouting.json`, `words_source.json` | no score on screen: coaching and scouting words from sentence templates, used only when the numbers call for them, each with how sure. Never about winning or losing. Existing files are kept unless `--force` |
| 14 | `s14_free_report.py` | `games.json`, game folders, `calib.json`, `bg_median.png` | `images_free/`, `match_report.pdf` | the PDF without a score: court check picture, games at a glance, coaching plan, heat maps, pair formation, work rate, posture, opponents, pace, longest plays, how sure. Charts only |

## The route without a score on screen (`tools/analyze.py`)

Most matches somebody films themselves have no live score. `tools/analyze.py` asks a few questions, then runs: proxy (0), detection (1, in the background while the person clicks the court), court fit (2), clothing features (3a),
`tools/pick_players.py`, and for each game `s03_players` (3c), `s06f`, `s07f`, `s08_pose --windows`, `tools/check_tracking.py`; then it writes `games.json` (the questions' answers and a list of `checks` saying what was verified and how sure),
runs `s14a_free_words.py` and `s14_free_report.py`. Each stage keeps its own output, so a re-run with the same `--work` folder skips what is done.

How the pieces decide:

* **Who you are.** You click yourself. Doubles: your partner is the other box on your half, the opponents are the two on the other half (the picker uses the court fit to know which half). For each way two teammates could be told apart (shirt colour,
  light against dark shorts measured at hip to mid-thigh, two shades of one colour) the picker follows the two people by position for 6 seconds either side of the picture and keeps the cue that puts the right person in the right place at least 80% of the time.
  Opponents who look alike are tracked as a pair. The direction of the cue (who is the lighter one) comes from the moments right around your click; the rest of the followed video only tests whether it holds. The shorts are
  not read from a box that is wide (an arm out puts bright floor in the middle of it) or cut off at the top or bottom of the picture (the band lands on the shirt, so white shorts read dark): there the tracker leans on where
  the person was a moment ago. After tracking, `tools/analyze.py` checks that the track labelled YOU really is where you clicked yourself, and stops if the labels are inverted.
* **Which end you start at.** Teams swap ends between games, so the side alternates from the game of the picture on; the tracker also reads it from the clothes (which half your distinctive clothes are on) and prefers the clothes when they are clear. It looks for one mid-game swap (the decider) in the same way, and the positions of a team that changes ends are mirrored back from that moment on, so left and right stay the team's own. An unbroken track is trusted over the clothes for a momentary misreading, but not for more than 1.2 s of readable clothes that contradict it.
* **Plays.** The sound track is band-passed (1.8 to 9 kHz); peaks 3 times above the local median are shuttle hits. Hit density and mean player speed are z-scored, averaged, and a play is where the average is above the Otsu threshold (with hysteresis), at least 2.5 s, gaps under 2 s merged.
  Checked on one match with result cards: 37 and 32 found against 40 and 34 with the final code (an earlier tracker gave 39 and 33). Neighbouring courts add hits, so a count is an estimate.
* **What is left out.** Winners, serves, shots, errors: nothing in the video says them. The report says so on its first page.

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

## Getting the video from YouTube (optional)

`tools/fetch_video.py` is a thin wrapper around [yt-dlp](https://github.com/yt-dlp/yt-dlp), which is installed separately (`requirements-youtube.txt`) and not part of this project.
`--info` looks the video up and downloads nothing. A download needs `--confirm-rights` (or typing YES in a terminal): the person says they filmed the video or may use it.
Guards, all tested: only `youtube.com` / `youtu.be` links to one video (playlists, channels, other sites, links with a user name or odd port are refused); live streams, unknown or
over-long videos (`--max-minutes`, default 120) and over-large downloads (`--max-mb`, default 2500) are refused; no cookies and no login; one extractor only; at most 720 pixels of height
(the analysis uses a 1280x720 copy anyway); the file is named by the video id, never the title, in a new empty folder; the title and channel are cleaned before they are shown; the finished
file is checked with ffprobe (a video stream, and a length that matches the page). `source.json` next to it records the link, the checksum and that the right to use it was confirmed.
`run_all.sh` accepts a link in place of a file and reuses `work/download/` on a re-run. A test (`tests/test_fetch_video.py`) drives the real yt-dlp against a tiny web server on the same
computer, so no network is needed.

## Who is who

`tools/pick_players.py` serves a page (127.0.0.1 only) with a few pictures from the start of the game and a numbered box around every person on the court.
The person clicks the player to analyse (slot `A_you`, "you" in the report), their partner (`A_partner`) and the two opponents (`B_opp1`, `B_opp2`).
The tool reads each shirt colour from the clicked box (they can correct it in a list), refuses teammates in the same colour, and writes
`players_config.json`; an optional name goes into `A_you.name` and appears on the PDF cover only. To analyse the *other* team player, pick them as "you".

## The words in the report

Numbers come from the stages; the words come from an assistant. `tips.json` is a list of `{"kind": "improve" | "check" | "strength", "title", "body", "try", "watch", "sure"}`
and `scouting.json` is `{"strengths": [...], "weaknesses": [...], "plan": [...]}` with the same item fields. Stage 13 validates both and lays them out.
The writing rules (cite a number, give a time, say how sure, label general advice, never claim a cause) are in `CLAUDE.md`.

## Players and shirt colours

`players_config.json` names a shirt colour per slot. Two teammates in two shades of one colour (royal blue and teal, say) are allowed: the picker gives one `"tone": "dark"` and the other `"light"`, with a `tone_split` lightness between them, and the tracker multiplies the colour score by that. When shirts all look alike (a dim hall), a slot can use `"shirt": "any"` with `"shorts": "white"` or `"dark"`, read from the legs. `s03_players.py` also takes `--end SECONDS` (one game of several in a video) and `--margin` / `--margin-far` (how far outside the sidelines a person may stand and still count, so players on neighbouring courts are left out). `common.colour_score` turns a detection's torso features into a 0 to 1 score
for each colour (red, blue, green, yellow, orange by hue fraction; black and grey and white by lightness). Tracking assigns the
best detection to each slot by colour plus closeness to the last position. A bright colour, if present, is also used to find which
half each team is on and when they swap ends (once, at most).

## Extending

* **New metric**: compute it in `s07_movement.py` per rally (or `s07b_opponents.py` for the opponents), add it to the summary, and add a panel in `s12_images.py`. Keep every claim data-driven.
* **New colour**: add a hue fraction in `s03_features.py` and a score in `common.colour_score`.
* **New stage**: read and write JSON next to the others, end with `PASSED`/`FAILED`, and add a check image where a person must look.
* **Run the tests**: `python -m unittest discover -s tests`. Add a test for any logic that is not an image or a model.

## Known weak points

* Player identity relies on shirt colour; white versus grey and shaded white are the weakest pairs.
* The serve cue was found on one video. The same-player test is the safety net; it can fail on others.
* Start detection is a suggestion and can be wrong on warm-ups.
* Pose on far-half players is not reliable at low resolution and is not used for conclusions. Opponent racket hand and knee bend rest on a few dozen frames.
* Opponent scouting is about results and positions only: there is no shuttle tracking, so no shot types or landing spots. Far-half depth is squeezed towards the net, so role and zone numbers use near-camera rallies.
* Everything assumes one end change at most.
