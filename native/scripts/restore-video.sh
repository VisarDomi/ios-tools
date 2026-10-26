#!/bin/bash
# The slow, visual restore test (restore-check is the fast, coded one). On the Mac:
#   restore-video.sh <bundle> <outdir> [seconds]
# shoots the settled screen, sends the app to the background, kills it and records the
# relaunch as video; then, on this PC, restore-frames.py <outdir copied back> [fps] lists how
# much of each frame differs from the screen as it was left.
set -euo pipefail
: "${SIM:?Select the exact UUID of an active guarded simulator session}"
"$(dirname "$0")/mac-workload" assert-simulator --device "$SIM"
APPLE_TOOL="$(dirname "$0")/apple-tool"
B=${1:?bundle}; OUT=${2:?output directory}; S=${3:-5}
mkdir -p "$OUT"
if [ -n "$(ls -A "$OUT")" ]; then echo 'Use an empty output directory; existing captures are preserved.' >&2; exit 1; fi
"$APPLE_TOOL" simctl io "$SIM" screenshot "$OUT"/before.png >/dev/null 2>&1
"$APPLE_TOOL" simctl launch "$SIM" com.apple.Preferences >/dev/null; sleep 2
"$APPLE_TOOL" simctl terminate "$SIM" "$B"; sleep 1
"$APPLE_TOOL" simctl io "$SIM" recordVideo --codec h264 --force "$OUT"/launch.mp4 >/dev/null 2>&1 &
rec=$!
trap 'kill -INT "$rec" 2>/dev/null || true' EXIT
sleep 1.5
"$APPLE_TOOL" simctl launch "$SIM" "$B" >/dev/null
sleep "$S"
kill -INT "$rec"; wait "$rec" 2>/dev/null || true
