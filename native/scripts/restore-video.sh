#!/bin/bash
# The slow, visual restore test (restore-check is the fast, coded one). On the Mac:
#   restore-video.sh <bundle> <outdir> [seconds]
# shoots the settled screen, sends the app to the background, kills it and records the
# relaunch as video; then, on this PC, restore-frames.py <outdir copied back> [fps] lists how
# much of each frame differs from the screen as it was left.
SIM=960E5E0A-15C3-423E-B196-1206C66B28E9; B=$1; OUT=$2; S=${3:-5}
rm -rf $OUT; mkdir -p $OUT
xcrun simctl io $SIM screenshot $OUT/before.png >/dev/null 2>&1
xcrun simctl launch $SIM com.apple.Preferences >/dev/null; sleep 2
xcrun simctl terminate $SIM $B; sleep 1
xcrun simctl io $SIM recordVideo --codec h264 --force $OUT/launch.mp4 >/dev/null 2>&1 &
rec=$!; sleep 1.5
xcrun simctl launch $SIM $B >/dev/null
sleep $S
kill -INT $rec; wait $rec 2>/dev/null
