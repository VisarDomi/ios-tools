The coding agent owns this repository: any file may be changed, including this one, README.md and test.txt.

Use `native/scripts/ios-push APP` (installed as `ios-push APP`) for ordinary app updates.
Wait only for its Queued/source-captured acknowledgement, then continue other work;
check `ios-push status JOB` before claiming installed. It builds/signs/installs under
the shared guard without launching the app. Read [push/README.md](push/README.md).
Approved renewal roots may be per-app frozen checkpoints; do not overwrite them or
assume the old mutable Mac mirror is the approved source. Test before enqueueing.

The tool mirror (`mac-sync` / `ios-tools-mac-sync.timer`) publishes committed HEAD,
so unfinished edits cannot break a running queue. Commit tested tool changes before
deploying them. App-source snapshots still include the caller's working edits.

Start here: [README.md](README.md), then [native/README.md](native/README.md) for anything about the iPhone apps (NativeKit, the rules every app follows, measuring on the phone, the simulator, deploying, renewal inputs). Mac and phone access: [mac-access.md](../../environment/mac-access.md).

Before Xcode builds or virtual-iPhone work, read [native/MAC-WORKLOADS.md](native/MAC-WORKLOADS.md) and use `native/scripts/mac-workload`. The Intel Mac has a captured SimMetalHost/AppleIntelKBLGraphics kernel panic; simulator use is subject to its recorded graphics-repair policy. Build with guests shut down, use explicit guest UUIDs, and never overlap compilation and simulator tests. A blocked simulator is not permission to automate the physical phone.

All setups must be power-off/reboot robust by default. The Mac already has persistent sleep prevention configured; do not use `caffeinate`, wake/keep-awake wrappers or extra startup jobs for it, or change power settings unless explicitly requested. Required behavior that depends on an agent session or a temporary helper after reboot is a bug, not a completed setup.

Mac-specific work is backed up to the private `private-backup` remote (`VisarDomi/ios-tools-private`). The public `VisarDomi/ios-tools` repository is upstream: do not publish local incident records or private Mac changes there. This checkout names that public remote `origin` and defaults pushes to `private-backup`; a restored private clone may name its private remote `origin`. Check URLs and visibility, not just remote names.
