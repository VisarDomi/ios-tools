#!/bin/bash
# Syncs NativeKit to the Mac mirror (~/Developer/ios-tools/native/Kit) and runs its macOS
# tests there (KitCore, KitNet, KitHTML). Extra arguments go to `swift test`.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
rsync -az --delete --exclude=.build --exclude=.swiftpm "$here/Kit/" mac:/Users/visar/Developer/ios-tools/native/Kit/
ssh mac "cd ~/Developer/ios-tools/native/Kit && xcrun swift test $*"
# The iOS build of every module (the UI modules only compile for iOS).
ssh mac 'cd ~/Developer/ios-tools/native/Kit && xcodebuild -scheme NativeKit-Package -destination "generic/platform=iOS" -derivedDataPath /tmp/nativekit-dd build -quiet > /tmp/nativekit-ios.log 2>&1; code=$?; grep -E "error|warning: " /tmp/nativekit-ios.log | grep -v appintents | head -40; echo "iOS build exit $code"; exit $code'
