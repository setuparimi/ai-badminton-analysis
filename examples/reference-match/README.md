# Reference match

What the pipeline produced on the one video it was built and checked on. **The video is not included.** This folder holds
numbers, a report and images with people's faces blurred.

## The match

* One doubles game, 53 rallies, about 11 minutes, filmed at 640x360 from a low side position, with an on-screen scoreboard.
  It is an edited game (a title card, a short highlights teaser, trimmed dead time).
* **Confirmed by the player:** their team won the game, and the opponents served first. (The last rally's winner is not shown
  in the video, so the final score is not in the data.)
* All numbers are estimates from video; read `report.md` for how sure each one is.

## What is here

| path | what |
|---|---|
| `match_report.pdf` | **the PDF report** (13 pages): cover, match, coaching plan, charts, opponent scouting, moments to check, how sure. Charts only, no photographs |
| `pdf_preview/` | three page images of the PDF, used in the main README |
| `report.md` | the same facts as text (numbers, limits, checks, coaching and scouting notes) |
| `images/` | the 14 images (01 to 11 about you and your team, 12 and 13 about the opponents); photographs in `07_posture.png` and `11_how_it_was_seen.png` are anonymised (faces and crowd blurred), the others are charts. `07_posture_charts.png` has no photographs. **Look at them for yourself before reusing them** |
| `data/` | every result file: `points.json` (rallies), `score.json`, `serves.json`, `motion.json`, `pose_stats.json`, `pickups.json`, `report_data.json`, `players.json`, `calib.json`, `overlay.json`, `opponents.json` (the scouting numbers) |
| `players_config.json` | the four shirt colours used to tell the players apart |
| `court_points.json` | the court landmarks clicked on this camera view (pixels and metres) |
| `game_start.json` | the confirmed start of the game and its first serve window |
| `tips.json`, `scouting.json` | the coaching plan and the opponent scouting notes, written by the AI assistant from the numbers under the rules in `CLAUDE.md` |

## Use it

* To see the format of each stage's output, open the JSON files in `data/`.
* To see what a finished report looks like, open `report.md`.
* To run the pipeline on your own video, follow the [README](../../README.md). Do not expect identical numbers: they depend on your video.

## What is not here, on purpose

The video, the resized copy, the raw detections, the tracks (`players.npz`), the overlay video and any unblurred frame. They show identifiable people.
