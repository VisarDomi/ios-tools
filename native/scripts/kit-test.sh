#!/bin/bash
# NativeKit's checks. The tests (KitCore, KitNet, KitHTML, KitLifecycle, KitBackup) run on this PC
# with Swift 6.2.4 for Linux (README: "Logic tests on the PC"); the Mac, a build station, only
# compiles every module for iOS (the UI modules compile to nothing elsewhere).
#   kit-test.sh            PC tests, then the Mac's iOS build
#   kit-test.sh --pc       PC tests only (seconds)
#   kit-test.sh --mac      also the macOS `swift test` on the Mac (Darwin-only paths: os.Logger,
#                          Security pinning, background URLSession configuration)
# Extra arguments go to `swift test`.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
pc_only=0; mac_tests=0; args=()
for arg in "$@"; do
  case $arg in --pc) pc_only=1 ;; --mac) mac_tests=1 ;; *) args+=("$arg") ;; esac
done
swift=$(command -v swift || echo "$HOME/.local/share/swiftly/bin/swift")
xml_include=/usr/include/libxml2; [[ -d $xml_include ]] || xml_include=$HOME/.local/opt/libxml2-dev/usr/include/libxml2
link=(); [[ -e /usr/lib/x86_64-linux-gnu/libxml2.so ]] || link=(-Xlinker "-L$HOME/.local/opt/libxml2-dev/lib")
(cd "$here/Kit" && "$swift" test -j "$(nproc)" -Xcc "-I$xml_include" ${link[@]+"${link[@]}"} ${args[@]+"${args[@]}"})
bash "$here/Kit/Linux/Shims/check.sh"
(( pc_only )) && exit 0
rsync -az --delete --exclude=.build --exclude=.swiftpm "$here/Kit/" mac:/Users/visar/Developer/ios-tools/native/Kit/
guard='sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 /Users/visar/Developer/ios-tools/native/scripts/mac-workload build --timeout 900 --'
if (( mac_tests )); then
  ssh mac "cd ~/Developer/ios-tools/native/Kit && $guard /usr/bin/xcrun swift test"
fi
ssh mac "cd ~/Developer/ios-tools/native/Kit && $guard /usr/bin/xcodebuild -scheme NativeKit-Package -destination generic/platform=iOS -derivedDataPath /tmp/nativekit-dd build -quiet > /tmp/nativekit-ios.log 2>&1; code=\$?; grep -E 'error|warning: ' /tmp/nativekit-ios.log | grep -v appintents | head -40; echo \"iOS build exit \$code\"; exit \$code"
