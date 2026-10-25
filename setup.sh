#!/usr/bin/env bash
# One-time setup: creates .venv and installs the packages in requirements.txt.
# Usage: bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

command -v ffmpeg >/dev/null || { echo "ffmpeg is missing. macOS: brew install ffmpeg   Linux: sudo apt install ffmpeg"; exit 1; }

PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$PYV" in
  3.10|3.11|3.12) ;;
  *) echo "python3 is $PYV; this project needs 3.10 to 3.12 (PyTorch wheels)."; exit 1 ;;
esac

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

python - <<'PY'
import cv2, torch, ultralytics
print("opencv     :", cv2.__version__)
print("torch      :", torch.__version__)
print("ultralytics:", ultralytics.__version__)
print("Apple GPU (MPS) available:", torch.backends.mps.is_available(), "| CUDA available:", torch.cuda.is_available())
PY
echo "Done. Next: read docs/USING_WITH_CLAUDE_CODE.md or run the steps in run_all.sh"
