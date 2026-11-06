# Builds and virtual iPhones on the shared Intel Mac

Read this before using Xcode or CoreSimulator. This Mac is a Dell Latitude 5480
Hackintosh: i5-7200U (two physical/four logical cores), HD 620, 8 GiB RAM.
The PC is canonical; access is `ssh mac`, using the pinned host key.

The Mac already has persistent sleep prevention configured. Per the owner's
standing requirement, do not wrap workloads in `caffeinate`, add wake/keep-awake
helpers or startup jobs, or change sleep/power settings unless explicitly asked.
Every setup must be power-off/reboot robust: persistent state and intended startup
services must restore normal behavior. A temporary agent/session dependency is
a recovery bug, not a substitute for persistent configuration. The workload guard
below provides resource isolation; it is not a keep-awake mechanism.

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

ssh mac 'sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 /Users/visar/Developer/ios-tools/native/scripts/mac-workload build --timeout 900 -- /usr/bin/python3 /Users/visar/Developer/guidance/apps/ios/scripts/build.py'
```

Before starting, the guard requires normal kernel memory pressure, at least
12 GiB free, no running `xcodebuild`, and no booted simulator. Simulator admission
also requires load at most 6. A build with a higher residual load average may
start after three successive samples show at least 50% CPU idle and a health
probe below 0.5 seconds; the other checks still apply.
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

The preflight still requires measured host headroom before adding work. Builds are capped
at fifteen minutes; simulator sessions default to five and are capped at ten.
A recorded trial/profile can calibrate queue alert levels, but cannot remove
memory, disk, responsiveness or deadline checks. These controls contain workload
failures; they cannot intercept a GPU driver kernel panic.
Reports are private `~/Library/Caches/ios-app-refresh/workload-*.jsonl` (20 retained).

## Build delivery has priority

Queued app deliveries take priority over simulator QA. An incoming upload records
its intent before waiting for the shared lock; an interrupted upload's intent
expires after ten minutes. Runnable queue work prevents a new simulator session.
If a delivery arrives during a guarded simulator run, the guard stops its owned
command and performs its normal exact-guest/GUI shutdown before releasing the lock.
It never starts a compiler alongside a live guest or bypasses a failed cleanup.
Jobs waiting for a future transport retry do not reserve the Mac indefinitely.

## Simulator sessions

### Build and diagnose the Intel fixture efficiently

Routine QA builds on this Mac need only `ARCHS=x86_64 ONLY_ACTIVE_ARCH=YES`;
do not compile an unused arm64 simulator slice. Physical-phone builds remain
arm64. Use Release optimization for CPU comparisons and record work counts as
well as elapsed/process CPU time. Keep instrumentation out of the product target.

If simulator installation stalls before the app launches, collect the simctl,
CoreSimulatorService and guest installd/lsd stacks inside the existing bounded
session. Do not attribute pre-launch host work to the app or keep extending its
timeout. End the owned session normally. With all guests shut down, no pending
delivery and the shared lock held, an evidence-preserving restart of the exact
current-user CoreSimulatorService is an available bounded recovery; it does not
erase a guest or replace a runtime. Record whether it actually helps.

The November 6 Manga Reader check first stalled in installation with its old
120-second script budget. With no booted guest, one exact, verified user-owned
CoreSimulator service PID was sampled and sent SIGTERM; XPC relaunched it on
demand. This service had no fixed `gui/501/com.apple.CoreSimulator.CoreSimulatorService`
launchctl label. Do not guess a label, use `killall`, or stop it while another
workload is active. The corrected 240-second install budget and that bounded
idle recovery were followed by successful reader checks, including a later
build 27 run without another service reset. Both test apps/data were uninstalled,
the shared guest/owned GUI closed, and disposable QA build products removed.
This is recovery evidence, not a claim that the Intel simulator's cold startup
or installation delays are permanently solved.

The November 4 reader trial used an exact-revision x86_64-only fixture after one
idle-service restart and passed installation, a 50,000-page CPU scenario, image
geometry, zoom and continuous cached chapter scrolling. Startup remained slow;
a host `diskimagesiod` sample showed LZFSE decompression before the app launched.
This distinguishes runtime startup overhead from reader CPU work; one passing
trial does not establish the sole cause of the earlier installer stalls.

### Reuse the shared devices

Routine QA uses one initialized iPhone and one initialized Watch, with only one
guest running at a time. They cover different operating systems; individual
apps do not need their own copy of an iPhone simulator.

| Purpose | Device UUID | Runtime |
| --- | --- | --- |
| Shared iPhone 12 Pro Max: iOS apps, readers and media | `87BA7A13-DE72-44E5-B227-F930B01613C9` | iOS 26.3.1, build 23D8133 |
| Shared 41 mm Watch: native watchOS UI and complications | `B2AC5E80-CBAC-447B-822C-4E5952691827` | watchOS 26.2, build 23S303 |

Use the explicit UUID with `--device`/`SIM`; never pick the first available
device. These are simulator identifiers, not the physical signing targets in
`ios-tools.local.json`. Historical app-specific names such as “Guidance QA” in
panic reports do not imply that another simulator must be kept for that app.

Build first with all guests shut down, then enter one bounded guarded session.
Use fixture data and separate app bundle IDs or test-data directories. Reset
only the owned app's fixture when needed; do not erase the shared device between
projects. Update a diagnostic app in place during a testing session, stop it
after each attempt, and uninstall it after the final check. The guard shuts
down the exact guest and closes its owned GUI; retain the initialized shared
device for the next project.

Create a temporary device only when a test actually requires another model,
OS version or isolated device state. Record its owner, reason and UUID. Remove
that temporary device through `apple-tool simctl delete UUID` after its final
check and any needed state/evidence backup. Never delete another active or
reserved device, and do not remove either shared device as routine cleanup.
Transport, parser, model and non-iOS checks belong on the PC or in a guarded
native command without booting a guest. Batch related UI checks within one
boot instead of creating or rebooting a simulator for each case.

Check `mac-workload status` and the graphics repair status first. A new,
unreviewed kernel panic or GPU reset report blocks simulator startup. Driver experiments require an explicitly recorded,
time-limited trial whose expected driver setting is verified before boot.
Do not bypass quarantine with raw `simctl boot` or opening Simulator.app.

On a verified graphics stack, pass the exact UUID of a listed shared or owned, shut-down
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
Avoid recording the simulator screen as video. Playback checks are allowed with
**one actively decoded stream at a time**. This two-core i5/HD 620/8 GiB Mac has
limited decoding headroom: keep playing neighbours, other video tests and second
guests stopped. Use static surfaces for unrelated UI checks. Measure each new
codec/resolution and keep the normal workload, pressure, deadline and GPU-reset
guards enabled. Try a single stream before concluding that the virtual iPhone
cannot handle a playback test or moving a test to the physical phone.

On 2026-11-02, an owned iPhone 12 Pro Max guest played one 1280×720 H.264/AAC HLS
recording. Its clock and sampled video buffers advanced in sequential seek/play
windows, including the encoder change around 15 minutes. Memory pressure stayed
normal and the host remained responsive, with no new GPU-reset/panic report.
Cold guest initialization took about 224 seconds; the combined comparison batch
later reached its ten-minute deadline. This validation covers single-stream
720p H.264. Other codecs/resolutions require their own measurements, and the
historical Intel driver failure retains its separate guard.

Close Simulator.app after guest shutdown so macOS cannot reopen it and reboot
the guest at the next login. Guarded visible sessions also close the GUI they opened. A pre-existing GUI is never taken over.
Keep validation mirrors separate from approved physical-delivery mirrors, so
simulator changes cannot silently invalidate monthly app renewal fingerprints.

Keep only current runtimes and initialized devices needed by the active test
pool. Archive a verified installer on the PC rather than retaining another copy
on the Mac. Completed mutable compiler caches are pruned by the existing renewal
runner, including older flat per-provider Xcode layouts. Do not delete signed
apps, source inputs, profile/state stores or approved/pending queue checkpoints
to make room. Inspect physical APFS usage: mounted simulator runtime images have
their own virtual capacities and must not be counted again as extra physical
disk consumption. Do not add a parallel cleanup service or lower the shared
build-admission reserve.

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

## October 27 diagnostic improvements

The previous pressure probe spawned `/usr/sbin/sysctl`. Under simulator startup
contention that measured child scheduling/exec delay (over a second), even while
kernel memory pressure remained normal. The guard now reads the same value
through in-process `sysctlbyname`, alongside the existing Mach CPU counters.
Mac comparisons matched the CLI's pressure value; idle measurements were about
0.00002–0.0002 seconds for the direct read versus 0.06 seconds for the CLI.
Critical/warning memory, disk, responsiveness, deadlines, ownership and graphics
policy checks remain. This is a measurement repair, not increased abort limits.

Admission now waits up to 180 seconds for the unchanged quiet-host conditions
(`--wait-for-idle 0` disables waiting, maximum 300). Nothing is booted or compiled
while waiting. Another guest/build, critical pressure or insufficient disk still
refuses admission. A shutdown's lagging load average need not provoke repeated
manual attempts. Existing GUI ownership is rechecked before boot.

A tiny native app took 70 seconds to install on this Mac after boot. The shared
`sim install` therefore allows up to 240 seconds for the actual Mac operation,
with a slightly longer SSH allowance; launch/container operations remain bounded.
This does not assert that every install should take that long. Builds and first
runtime migrations are separate phases, and the outer session deadline remains.
App relaunches terminate the prior selected simulator app so launch arguments and
JSC configuration cannot silently be ignored.

Use [simulator-health](simulator-health/README.md) to separate native controls,
plain WebKit JS/canvas and a tiny Wasm module. Its October 27 baseline, checked
and repeated checked launches passed real load/store, memory growth and a caught
bounds trap on an iPhone 12 Pro Max guest. Actual WebContent environments and
modified-options dumps verified the checked configuration. This does not prove
large Unity modules work: the real Maid Heroes test remains a separate gate.

### Recorded Intel Wasm profile

The host now records `simulatorWasmMode=compat`. The default guarded simulator
command therefore supplies the validated app/XPC flags automatically: explicit
bounds checks, baseline Wasm JIT (BBQ), IPInt off, optimizing Wasm tier (OMG) off.
This follows a controlled same-binary A/B comparison, not a guess based on load.
Small Wasm passed even in the failing default runtime path, so the actual large
application remains an essential validation gate. The Mac's stock graphics,
Apple framework binaries, host-global JSC settings and phone behavior are unchanged.

Use `--native-wasm` for a deliberate platform-default control, `--checked-wasm`
for memory-only diagnosis, or `--wasm-compat` to select the compatibility profile
explicitly. These are simulator configuration controls, not performance results
for a physical iPhone. See [simulator-health](simulator-health/README.md) for
source rationale, reproducible checks and the differences between execution tiers.

Ordinary simulator sessions now stop after a newly launched WebContent process
in their owned guest crashes. This prevents an application's automatic recovery
from generating a rapid crash/reload storm and prolonging host saturation. A
specific `--allow-webcontent-crash` diagnostic may compare known failing modes;
normal memory/disk/deadline/ownership safeguards remain in force.

### GPU reset review and failure containment

A separate `SimMetalHost` GPU Reset report at October 27 21:00:14 CET
(20:00:14 UTC) records an Intel HD 620 RCS-ring hang. This precedes the later
successful cold compatibility and plain-background UI batches. It is not a
kernel panic, and the Wasm execution-profile repair does not establish that this
GPU fault is fixed. Preserve the reset report/tailspin privately; do not describe
all simulator graphics problems as resolved solely because the UI batches pass.
The reset occurred during the failed no-JIT Unity trial, before simulator QA stopped
on the first WebContent termination. That timing does not prove that a reload storm
caused the GPU hang. Later full UI cold sessions at 20:21, 20:29, 20:41 and 20:51 UTC
passed, with no additional reset report; the last used the requested plain scenery.

The guard now watches host `.gpuRestart` and `.panic` reports throughout boot and
testing, including immediately after the command exits. A new report stops the owned
workload and cleanup runs normally if macOS is responsive. GPU reset detection cannot
be disabled by `--allow-webcontent-crash`. The private policy separately records
`acknowledgedGpuResetReports`; an unreviewed reset refuses the next boot, including
reports that arrive after the previous command ended. Admission rechecks reports
after waiting for an idle host. The historical reset was reviewed against the later
successful runs, and the real Mac preflight was verified to reject it with an empty
acknowledgement list without starting a guest. No driver change is claimed.

### Final October 27 verification

Five separate full Unity UI cold sessions passed with the recorded compatibility
profile (20:21, 20:29, 20:41, 20:51 and 20:59 UTC). Their monitored batches took
165–186 seconds, kernel memory pressure stayed normal, and the largest direct
probe took 0.0041 seconds. Actual JSC option dumps verified BBQ on and IPInt/OMG
off. The last two runs also verified the requested plain battle background.

The corrected saved health comparator then passed a fresh cold session at
21:05 UTC: native controls, JS/canvas, and Wasm load/store/grow/caught bounds traps
in default, checked and repeated checked launches. Live WebContent environment
records proved the default control contained only `dumpOptions`, with no inherited
compatibility flags. Its installation took 53.85 seconds. Captures were inspected.
The earlier 180-second admission wait expired safely at load 7.75 without a boot;
`--wait-for-idle 300` admitted the final check once the unchanged limit was met.

The final audit verified no booted guests, no Simulator GUI, no active lease,
a released shared lock, matching PC/Mac script hashes and no additional GPU reset
or kernel panic reports. Private evidence is under PC
`~/.cache/mac-simulator-repair/{final-guard,final-controls}` and Mac
`~/Library/Caches/ios-app-refresh/simulator-repair-final-audit.json`.
The saved source passes 36 workload, 3 simulator-client and 3 diagnostic-control
regressions. All fixes are simulator/workflow scoped; no physical-phone automation,
installation, Apple framework patch, OS/runtime update or driver change was used.
