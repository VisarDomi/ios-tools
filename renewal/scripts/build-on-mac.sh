#!/bin/bash
set -eu
reader_root="$(cd "$(dirname "$0")/.." && pwd)"
# Run in the GUI session for Keychain signing. The target+SDK invocation works
# on the existing Hackintosh where scheme destination discovery does not.
exec /usr/bin/xcodebuild \
  -project "$reader_root/apple/Gallery Reader Extension.xcodeproj" \
  -target 'Gallery Reader Extension (iOS)' -sdk iphoneos -configuration Debug \
  SYMROOT="$reader_root/build" DEVELOPMENT_TEAM="${SIGNING_TEAM:?Set SIGNING_TEAM}" \
  IPHONEOS_DEPLOYMENT_TARGET=18.0 \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration build
