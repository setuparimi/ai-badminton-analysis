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
| `report.md` | the full report this pipeline writes (numbers, limits, checks, coaching) |
| `images/` | the 11 images; photographs in them are anonymised (faces and crowd blurred). **Look at them for yourself before reusing them** |
| `data/` | every result file: `points.json` (rallies), `score.json`, `serves.json`, `motion.json`, `pose_stats.json`, `pickups.json`, `report_data.json`, `players.json`, `calib.json`, `overlay.json` |
| `players_config.json` | the four shirt colours used to tell the players apart |
| `court_points.json` | the court landmarks clicked on this camera view (pixels and metres) |
| `game_start.json` | the confirmed start of the game and its first serve window |
| `tips.json`, `coaching.md` | the coaching written by the AI assistant from the numbers, under the rules in `CLAUDE.md` |

## Use it

* To see the format of each stage's output, open the JSON files in `data/`.
* To see what a finished report looks like, open `report.md`.
* To run the pipeline on your own video, follow the [README](../../README.md). Do not expect identical numbers: they depend on your video.

## What is not here, on purpose

The video, the resized copy, the raw detections, the tracks (`players.npz`), the overlay video and any unblurred frame. They show identifiable people.
