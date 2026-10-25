#!/usr/bin/env bash
# Runs the whole pipeline on one video.
#   Usage: bash run_all.sh path/to/video.mp4 [work_folder]
#
# Three small files in the work folder describe YOUR video. The script stops and tells you if one is missing:
#   court_points.json    python tools/pick_court_points.py --video work/proxy.mp4 --out work/court_points.json
#   players_config.json  copy examples/reference-match/players_config.json and set the four shirt colours
#   game_start.json      suggested by the script; open start_check.jpg, then set "confirmed": true
# Scoreboard: stages 4-6 need work/overlay.json (the score before every rally). If your video has the same kind of
# yellow on-screen scoreboard as the reference video, run with SCOREBOARD=yes to read it; otherwise see docs/HOW_IT_WORKS.md.
# Coaching text is not made here: ask your AI assistant to write work/coaching.md and work/tips.json (see CLAUDE.md).
set -euo pipefail
cd "$(dirname "$0")"
VIDEO="${1:?usage: bash run_all.sh path/to/video.mp4 [work_folder]}"
WORK="${2:-work}"
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "No .venv yet. Run: bash setup.sh"; exit 1; }
mkdir -p "$WORK"

$PY stages/s00_proxy.py --src "$VIDEO" --out-dir "$WORK"
$PY stages/s01_detect.py --proxy "$WORK/proxy.mp4" --out "$WORK/dets.json"

[ -f "$WORK/court_points.json" ] || { echo; echo "STOP: $WORK/court_points.json is missing."; echo "Run: $PY tools/pick_court_points.py --video $WORK/proxy.mp4 --out $WORK/court_points.json"; echo "then run this script again."; exit 2; }
[ -f "$WORK/players_config.json" ] || { echo; echo "STOP: $WORK/players_config.json is missing."; echo "Copy examples/reference-match/players_config.json to $WORK/ and set the four shirt colours, then run again."; exit 2; }

$PY stages/s02_calibrate.py --proxy "$WORK/proxy.mp4" --points "$WORK/court_points.json" --out "$WORK/calib.json"
$PY stages/s03_features.py --proxy "$WORK/proxy.mp4" --dets "$WORK/dets.json" --calib "$WORK/calib.json" --out "$WORK/cand.npz"

if [ ! -f "$WORK/game_start.json" ]; then
  $PY stages/s03_find_start.py --proxy "$WORK/proxy.mp4" --cand "$WORK/cand.npz" --calib "$WORK/calib.json" --out "$WORK/game_start.json"
fi
CONFIRMED=$($PY -c "import json,sys; print(json.load(open('$WORK/game_start.json')).get('confirmed', False))")
if [ "$CONFIRMED" != "True" ]; then
  echo; echo "STOP: look at $WORK/start_check.jpg. If the game really starts at the suggested time, set \"confirmed\": true in $WORK/game_start.json"
  echo "(edit \"start\" and \"first_window_on\"/\"first_window_off\" there if the suggestion is wrong), then run this script again."; exit 2
fi
START=$($PY -c "import json; print(json.load(open('$WORK/game_start.json'))['start'])")
$PY stages/s03_players.py --proxy "$WORK/proxy.mp4" --cand "$WORK/cand.npz" --start "$START" --out "$WORK/players.npz"

if [ ! -f "$WORK/overlay.json" ]; then
  if [ "${SCOREBOARD:-no}" = "yes" ]; then
    $PY stages/s04a_overlay.py --proxy "$WORK/proxy.mp4" --out "$WORK/overlay.json"
  else
    echo; echo "STOP after stage 3: no $WORK/overlay.json (the score before every rally), so rallies and winners cannot be worked out."
    echo "Players are tracked: $WORK/players.npz and $WORK/s03_check.jpg. For scoring see docs/HOW_IT_WORKS.md, section 'Scores'."; exit 0
  fi
fi

$PY stages/s04_serves.py --players "$WORK/players.npz" --overlay "$WORK/overlay.json" --game-start "$WORK/game_start.json" --out "$WORK/serves.json"
$PY stages/s05_score.py --serves "$WORK/serves.json" --out "$WORK/score.json"
$PY stages/s06_rallies.py --proxy "$WORK/proxy.mp4" --serves "$WORK/serves.json" --score "$WORK/score.json" --players "$WORK/players.npz" --out "$WORK/points.json"
$PY stages/s07_movement.py --players "$WORK/players.npz" --points "$WORK/points.json" --out "$WORK/motion.json"
$PY stages/s08_pose.py --proxy "$WORK/proxy.mp4" --players "$WORK/players.npz" --points "$WORK/points.json" --out "$WORK/pose_stats.json"
$PY stages/s09_pickups.py --players "$WORK/players.npz" --serves "$WORK/serves.json" --points "$WORK/points.json" --out "$WORK/pickups.json" || echo "(pickups not usable on this video: that is a result, not an error)"
$PY stages/s10_report.py --work "$WORK"
$PY stages/s10_build_report.py --work "$WORK" --label "$(basename "$VIDEO")"
$PY stages/s12_images.py --work "$WORK" --label "$(basename "$VIDEO")"
if [ "${MAKE_VIDEO:-no}" = "yes" ]; then
  $PY stages/s11_video.py --proxy "$WORK/proxy.mp4" --players "$WORK/players.npz" --points "$WORK/points.json" --start "$START" --out "$WORK/analysis_video.mp4"
fi
echo; echo "Done. Open $WORK/report.md and $WORK/images/. Ask your AI assistant to write $WORK/coaching.md and $WORK/tips.json, then run s10_build_report.py and s12_images.py again."
