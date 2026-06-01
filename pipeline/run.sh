#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Purplle Store Intelligence — Detection Pipeline Runner
# Usage: bash run.sh <clip_dir> <store_id> [--demo] [--frame-skip N]
# ─────────────────────────────────────────────────────────────────────────────
set -e

CLIP_DIR="${1:-./cctv_footage/CCTV Footage}"
STORE_ID="${2:-STORE_BLR_002}"
API_URL="${API_URL:-http://localhost:8000}"
FRAME_SKIP="${FRAME_SKIP:-3}"
DEMO_FLAG=""

# Check for --demo flag
for arg in "$@"; do
  if [ "$arg" = "--demo" ]; then
    DEMO_FLAG="--demo"
    echo "[INFO] Running in DEMO mode (no YOLO required)"
  fi
done

echo "========================================="
echo " Purplle Store Intelligence Pipeline"
echo " Store  : $STORE_ID"
echo " Clips  : $CLIP_DIR"
echo " API    : $API_URL"
echo " Skip   : every ${FRAME_SKIP} frames"
echo "========================================="

# Load POS data first
POS_CSV="./data/Brigade_Bangalore_10_April_26.csv"
if [ -f "$POS_CSV" ]; then
  echo "[INFO] Loading POS transactions from $POS_CSV"
  python -c "
import asyncio, sys
sys.path.insert(0, '.')
from pipeline.pos_loader import load_pos_to_db
import os
asyncio.run(load_pos_to_db('$POS_CSV', os.environ.get('DB_PATH', '/data/store_intelligence.db')))
print('[INFO] POS data loaded successfully')
"
fi

# Process each camera
CAMERAS=("CAM 1" "CAM 2" "CAM 3" "CAM 4" "CAM 5")
CAM_IDS=("CAM1" "CAM2" "CAM3" "CAM4" "CAM5")

for i in "${!CAMERAS[@]}"; do
  CAM_NAME="${CAMERAS[$i]}"
  CAM_ID="${CAM_IDS[$i]}"
  VIDEO_PATH="${CLIP_DIR}/${CAM_NAME}.mp4"

  if [ -f "$VIDEO_PATH" ]; then
    echo "[$(date +%H:%M:%S)] Processing $CAM_ID: $VIDEO_PATH"
    python pipeline/detect.py \
      --camera "$CAM_ID" \
      --video "$VIDEO_PATH" \
      --store "$STORE_ID" \
      --frame-skip "$FRAME_SKIP" \
      --api-url "$API_URL" \
      $DEMO_FLAG &
  else
    echo "[SKIP] $VIDEO_PATH not found"
    if [ -n "$DEMO_FLAG" ]; then
      echo "[DEMO] Generating demo events for $CAM_ID"
      python pipeline/detect.py \
        --camera "$CAM_ID" \
        --video "" \
        --store "$STORE_ID" \
        --api-url "$API_URL" \
        --demo &
    fi
  fi
done

echo "[$(date +%H:%M:%S)] All cameras dispatched. Waiting for completion..."
wait
echo "[$(date +%H:%M:%S)] Pipeline complete!"
echo "[INFO] Dashboard: $API_URL/dashboard"
echo "[INFO] API Docs:  $API_URL/docs"
