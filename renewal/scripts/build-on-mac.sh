#!/bin/bash
set -eu
reader_root="$(cd "$(dirname "$0")/.." && pwd)"
# Run in the GUI session for Keychain signing. First-time device registration
# needs an actual scheme destination; generic builds can reuse enrolled profiles.
destination=(-target 'Gallery Reader Extension (iOS)' -sdk iphoneos)
if [[ -n "${SIGNING_DEVICE:-}" ]]; then
  destination=(-scheme 'Gallery Reader Extension (iOS)' -sdk iphoneos
    -destination "platform=iOS,id=$SIGNING_DEVICE" -destination-timeout 30)
fi
exec /usr/bin/xcodebuild \
  -project "$reader_root/apple/Gallery Reader Extension.xcodeproj" \
  "${destination[@]}" -configuration Debug \
  SYMROOT="$reader_root/build" DEVELOPMENT_TEAM="${SIGNING_TEAM:?Set SIGNING_TEAM}" \
  READER_HOST_BUNDLE_ID="${READER_HOST_BUNDLE_ID:-com.visar.galleryreader.extensiontest}" \
  IPHONEOS_DEPLOYMENT_TARGET=18.0 \
  -allowProvisioningUpdates -allowProvisioningDeviceRegistration build
