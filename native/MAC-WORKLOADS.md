# Builds and virtual iPhones on the shared Intel Mac

Read this before using Xcode or CoreSimulator. This Mac is a Dell Latitude 5480
Hackintosh: i5-7200U (two physical/four logical cores), HD 620, 8 GiB RAM.
The PC is canonical; access is `ssh mac`, using the pinned host key.

## October 26 failure

The captured kernel panic names `SimMetalHost (Guidance QA: …)` and
`AppleIntelKBLGraphics` 23.0.7:

```text
Enter debugger: submitToRing: Work queue failure detected
IGHardwareRingBuffer.cpp:1545
```

The backtrace includes Intel Metal blits and coalesced command submission.
The panic reports healthy compressor and swap limits. A simulator extraction
service separately dirtied about 2.15 GB in 397 seconds. Resource pressure and
the GPU-driver panic are distinct findings; the former does not prove the latter.

After the owner's hard restart, Simulator reopened the last Guidance guest and
load reached 647 within two minutes. Shutting down that exact guest and quitting
Simulator allowed load to settle. Neither a smaller device nor non-video UIKit
content alone makes this driver path safe. No physical-phone fallback is authorized.

The Intel driver, HD 620 identity, framebuffer and WhateverGreen were present.
Do not install arbitrary graphics root patches or assume that a missing loose
kext executable means the loaded kernel-collection driver is missing.
The graphics repair source and evidence are in
[`hackingtosh/graphics`](../../../hackingtosh/graphics/README.md).

## Xcode launcher mismatch: do not repeatedly initialize components

Xcode 26.3's `devicectl` and `simctl` are shell launchers. They compare exact
component versions and call `xcodebuild -runFirstLaunch` before executing the
installed tool when those strings differ. This machine has newer Apple hotfixes:
CoreDevice 506.8 versus the stub's506.7; CoreSimulator 1051.17.11 versus1051.17.8.
First-launch status is already successful, so repeating setup does not resolve
that comparison. The phone monitor invoked it before its probes. The setup churn
is established; its causal contribution to the GPU panic is not.

Use `native/scripts/apple-tool simctl ...` and `apple-tool devicectl ...`.
They execute the same installed Apple Mach-O binaries the launchers ultimately
execute, without repeating installation. `apple-tool status` prints their actual
versions. Missing native components fail clearly; background health checks never
install them. Apple launchers and signed bundles remain unmodified.
After an actual Xcode installation/update, initialize components once with all
workloads stopped, then check the installed tools. Do not downgrade a working
hotfix to satisfy an older launcher's string comparison.

The pairing monitor now shares the workload lock and skips automatic checks
during high startup load. Monthly renewal runs its builder through the guard.
Explicit phone deployment remains separate from simulator testing.

## Use the attached workload guard

`native/scripts/mac-workload` runs on the Mac, inside its logged-in GUI bootstrap.
It creates no permanent service. Examples from this PC:

```sh
ssh mac 'sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 /Users/visar/Developer/ios-tools/native/scripts/mac-workload status'

ssh mac 'sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/caffeinate -i /usr/bin/python3 /Users/visar/Developer/ios-tools/native/scripts/mac-workload build --timeout 900 -- /usr/bin/python3 /Users/visar/Developer/guidance/apps/ios/scripts/build.py'
```

Before starting, the guard requires load at most 6, normal kernel memory pressure,
at least 12 GiB free, no running `xcodebuild`, and no booted simulator.
It waits at most 30 seconds for the existing signing lock, including the inherited descriptor used by
renewal builders. Signing, compilation and simulator sessions cannot overlap
when run through it. Keep repository signing locks too.

Direct `xcodebuild` and `swift build/test` commands get two jobs. Wrapper scripts
must also limit their internal compiler to two jobs. Compile the simulator app
**before** booting the guest. Do not build in a second SSH session while it boots.

The guard samples CPU idle time, queue load, kernel memory pressure, free disk
and the health-probe latency every two seconds. Critical memory pressure or less
than 8 GiB free stops the job. Sustained warning pressure or slow probes stops it;
high queue load together with a probe over three seconds stops it immediately.
Large queue counts with normal memory and responsive probes can occur during
initialization and are recorded rather than treated as a kernel freeze.

The preflight still requires a quiet host before adding work. Builds are capped
at fifteen minutes; simulator sessions default to five and are capped at ten.
A recorded trial/profile can calibrate queue alert levels, but cannot remove
memory, disk, responsiveness or deadline checks. These controls contain workload
failures; they cannot intercept a GPU driver kernel panic.
Reports are private `~/Library/Caches/ios-app-refresh/workload-*.jsonl` (20 retained).

## Simulator sessions

Check `mac-workload status` and the graphics repair status first. A new,
unreviewed kernel panic report blocks simulator startup. Driver experiments require an explicitly recorded,
time-limited trial whose expected driver setting is verified before boot.
Do not bypass quarantine with raw `simctl boot` or opening Simulator.app.

On a verified graphics stack, pass the exact UUID of a project-owned, shut-down
guest and the complete test command:

```sh
# Run on the Mac in the same GUI bootstrap as above; replace the UUID explicitly.
~/Developer/ios-tools/native/scripts/mac-workload simulator --visible --device UUID --timeout 600 -- /usr/bin/python3 /path/to/simulator-only-check.py --device UUID
```

Use the logged-in GUI bootstrap and `--visible` on this Intel host. The guard
opens Simulator through Launch Services, waits for boot completion, and runs the
command. Do not launch the app executable directly or background `launchd_sim`;
those changes were unvalidated during diagnosis. Other hosts may use headless mode.
It shuts down only that guest in `finally`, including on test failure, timeout
or cancellation. It refuses to take over a device already booted by someone else.
Never use `shutdown all`, erase device data, or restart shared CoreSimulator
services while another device is in use. Never loop fresh boots or migrations
after an abort. Read the telemetry and let the host settle first.

`native/scripts/sim` and `restore-check` require `SIM`/`--device`; they no longer
choose an old iPhone 17 Pro Max or implicitly boot it. Their actions require an
active guarded session for that same device. Terminating an explicitly selected
app remains available for recovery. One NativeKit app uses port 8765 at a time.
Use `/layout` and `/timeline` first; take a few screenshots for visual verification.
Avoid recording video. Never test video playback on this host's simulator.

Close Simulator.app after guest shutdown so macOS cannot reopen it and reboot
the guest at the next login. Guarded visible sessions also close the GUI they opened. A pre-existing GUI is never taken over.
Keep validation mirrors separate from approved physical-delivery mirrors, so
simulator changes cannot silently invalidate monthly app renewal fingerprints.

## Recovery

If SSH slows, stop issuing more builds and boots. `mac-connect` now lets the actual
pinned SSH connection wait up to 30 seconds on the documented Wi-Fi/Tailscale
addresses; its old extra two-second key scan could falsely reject a loaded Mac.
Discovery of other addresses still requires the pinned key. A failed SSH probe
does not determine sleep, power, Ethernet state or the reason for failure.

Use the existing trusted route to stop the exact owned guest:

```sh
ssh mac '~/Developer/ios-tools/native/scripts/apple-tool simctl shutdown UUID'
```

Capture load, memory pressure, disk and `/Library/Logs/DiagnosticReports` after
recovery. Preserve panic evidence privately; commit only a sanitized diagnosis.
Do not change unrelated network adapters, reset trust records, repeatedly restart
services, or switch to physical-phone automation. A kernel panic may require a
physical restart; user-space cleanup cannot run while the kernel is halted.


## Verified recovery run

On October 26 the stock driver completed a real UIKit game batch in 285.4 seconds:
factory turn, tabs, portrait/landscape, private draft, offline read, and exact
cold/warm restoration from 0 ms. Captures were inspected. Peak queued load was 339.34,
maximum probe latency 2.45 seconds, and memory pressure remained normal. No new
panic appeared; the guest, GUI and lease were all cleaned up. This is bounded
validation, not a guarantee for every future GPU workload.

The runtime policy records acknowledged historical panic reports. A new report
blocks simulator work pending inspection and revalidation; it never causes an
automatic repeated boot. Recovery retains stock graphics and default GPU power
settings. The experimental custom WEG patch was not accepted.
