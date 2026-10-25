# How to film a match so the analysis works

Better footage improves results more than any code change. The reference video in this project was a small, low,
side-on, edited copy; most of its limits come from that.

## Do

* **Fixed camera on a tripod.** No panning, no zooming, no handheld. The court model is fitted once per camera position.
* **Behind one baseline, high up** (2.5 to 3 m if you can: a stand, a balcony, the umpire's chair position). A high, straight-on view puts every
  player at a similar scale and avoids players hiding behind each other.
* **The whole court in frame with a margin**, including both baselines and both sidelines. Anything outside the picture is not tracked.
* **1080p** (or 4K) at **30 or 60 fps**, landscape. A phone's standard video mode is fine.
* **Turn HDR video off.** iPhone: Settings, Camera, Record Video, HDR Video. (The program refuses HDR because the shirt colours go wrong.)
* **Players in clearly different shirt colours**, with at least one bright colour (red, blue, green, yellow, orange) in the group.
  Two teammates must not wear the same colour.
* **Record the whole game**, starting a little before the first serve, and keep the scoreboard or a score sheet.
* **Sound on.** Racket hits could later be used to find shots.

## Avoid

* Standing at the side of the court at net height (hard to see, players block each other, far court is tiny).
* Videos that have been edited, cut or recompressed to low resolution if you can get the original.
* Strong back-light or very dim halls (shirt colours get unreliable).
* Mixing several games in one file.

## Score

Winners come from the score shown before each rally. Easiest: record a scoreboard on screen, or keep a written list of
who won each rally. The program currently reads a particular on-screen style and otherwise needs the score entered by
hand in `overlay.json` (see [HOW_IT_WORKS.md](HOW_IT_WORKS.md), "Scores").
