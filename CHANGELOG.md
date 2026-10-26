# Changelog

## 0.2.0 (alpha)

A guided run, a report that needs no on-screen score, singles, several games in one video.

* **`tools/analyze.py`**: asks what the match is, singles or doubles, which hand you hit with, whether there is a live score, when each game starts and ends and each game's final score; opens the court page and the player page; then
  tracks, finds the plays, measures positions, movement and posture, writes the words and builds the PDF. Flags for every answer, `--dry-run`, and a re-run with the same `--work` folder carries on.
* **`tools/pick_players.py`**: click yourself only. Partner and opponents are found by court half; the cue that tells you from your partner (shirt colour, shade, light or dark shorts) is tried on about 12 seconds of tracked video. Hand and singles mode are chosen here.
* **No score on screen**: `s06f_play_windows.py` (plays from shuttle sound and movement), `s07f_free_stats.py` (zones, formation, partner gap, work rate, pace), `s14a_free_words.py` (rule-based coaching and scouting words), `s14_free_report.py` (the PDF),
  `tools/check_tracking.py` (label check sheet). `s08_pose.py --windows`.
* **Singles** in the route above (tested on synthetic data only).
* **Tracker**: finds the starting end and a mid-game end change from the clothes; the person-size window follows a wide-angle lens; slots stay empty rather than take someone whose clothes say otherwise; an unbroken track keeps its label.
* **Safety checks**: shorts are not read from boxes that are wide or cut off at the edge of the picture; the cue's direction comes from the moments nearest your click; after tracking the guided run stops if the YOU track is not where you clicked.
* **Hand**: the hand you declare is used; the pose model's own left/right (mirrored for people seen from behind) is no longer printed as your hand.
* Also new since 0.1.0: PDF report (`s13`), opponent scouting (`s07b`), YouTube fetch (`tools/fetch_video.py`), several games in the scoreboard reader, title-card handling, shade-based teammate separation.
* 188 tests.

## 0.1.0 (alpha)

First public version: doubles, one game, an on-screen scoreboard, a reference example.
