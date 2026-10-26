#!/usr/bin/env bash
# Runs the whole pipeline on one video.
#   Usage: bash run_all.sh path/to/video.mp4 [work_folder]
#          bash run_all.sh "https://www.youtube.com/watch?v=VIDEO_ID" [work_folder]    (one YouTube video you filmed or may use; see below)
#
# Three small files in the work folder describe YOUR video. The script stops and tells you if one is missing:
#   court_points.json    python tools/pick_court_points.py --video work/proxy.mp4 --out work/court_points.json
#   game_start.json      suggested by the script; open start_check.jpg, then set "confirmed": true
#   players_config.json  python tools/pick_players.py --video work/proxy.mp4 --cand work/cand.npz --start START --out work/players_config.json
#                        (a page opens: click the player to analyse, their partner and the two opponents)
# Scoreboard: stages 4-6 need work/overlay.json (the score before every rally). If your video has the same kind of
# yellow on-screen scoreboard as the reference video, run with SCOREBOARD=yes to read it; otherwise see docs/HOW_IT_WORKS.md.
# A YouTube link is downloaded first with tools/fetch_video.py (needs yt-dlp: .venv/bin/pip install -r requirements-youtube.txt). You are asked to
# confirm that you filmed the video or may use it; in a script, say so with CONFIRM_RIGHTS=yes. It is saved in <work>/download and reused on a re-run.
# The coaching and scouting words are not made here: your AI assistant writes work/tips.json and work/scouting.json from the numbers
# (see CLAUDE.md), then the last two steps (images and PDF) are run again. Options: LABEL="Saturday doubles" PAGE=letter
set -euo pipefail
cd "$(dirname "$0")"
VIDEO="${1:?usage: bash run_all.sh path/to/video.mp4|YouTube-link [work_folder]}"
WORK="${2:-work}"
PY=".venv/bin/python"
[ -x "$PY" ] || { echo "No .venv yet. Run: bash setup.sh"; exit 1; }
mkdir -p "$WORK"

if [[ "$VIDEO" == http://* || "$VIDEO" == https://* ]]; then
  if [ -f "$WORK/download/source.json" ]; then
    echo "Using the video already downloaded in $WORK/download (remove that folder to download again)."
  else
    CONF=""; [ "${CONFIRM_RIGHTS:-}" = "yes" ] && CONF="--confirm-rights"
    $PY tools/fetch_video.py "$VIDEO" --out-dir "$WORK/download" $CONF || exit $?
  fi
  VIDEO="$WORK/download/$($PY -c "import json,sys; print(json.load(open(sys.argv[1]))['file'])" "$WORK/download/source.json")"
  LABEL="${LABEL:-Match report}"
fi

$PY stages/s00_proxy.py --src "$VIDEO" --out-dir "$WORK"
$PY stages/s01_detect.py --proxy "$WORK/proxy.mp4" --out "$WORK/dets.json"

[ -f "$WORK/court_points.json" ] || { echo; echo "STOP: $WORK/court_points.json is missing."; echo "Run: $PY tools/pick_court_points.py --video $WORK/proxy.mp4 --out $WORK/court_points.json"; echo "then run this script again."; exit 2; }

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
if [ ! -f "$WORK/players_config.json" ]; then
  echo; echo "STOP: $WORK/players_config.json is missing (who is who). Run this, click the four players, then run this script again:"
  echo "  $PY tools/pick_players.py --video $WORK/proxy.mp4 --cand $WORK/cand.npz --start $START --out $WORK/players_config.json"; exit 2
fi
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
$PY stages/s07b_opponents.py --work "$WORK"
$PY stages/s10_report.py --work "$WORK"
LABEL="${LABEL:-$(basename "$VIDEO")}"
$PY stages/s10_build_report.py --work "$WORK" --label "$LABEL"
$PY stages/s12_images.py --work "$WORK" --label "$LABEL"
$PY stages/s13_pdf_report.py --work "$WORK" --label "$LABEL" --page "${PAGE:-A4}"
if [ "${MAKE_VIDEO:-no}" = "yes" ]; then
  $PY stages/s11_video.py --proxy "$WORK/proxy.mp4" --players "$WORK/players.npz" --points "$WORK/points.json" --start "$START" --out "$WORK/analysis_video.mp4"
fi
echo; echo "Done. The report is $WORK/match_report.pdf (charts only, no photographs); the pictures are in $WORK/images/."
if [ ! -f "$WORK/tips.json" ] || [ ! -f "$WORK/scouting.json" ]; then
  echo "It has no coaching or scouting words yet. Ask your AI assistant to write $WORK/tips.json and $WORK/scouting.json (see CLAUDE.md), then run:"
  echo "  $PY stages/s12_images.py --work $WORK --label \"$LABEL\" && $PY stages/s13_pdf_report.py --work $WORK --label \"$LABEL\""
fi
