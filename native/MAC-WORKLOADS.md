# Builds and virtual iPhones on the shared Intel Mac

Read this before using Xcode or CoreSimulator. This Mac is a Dell Latitude 5480
Hackintosh: i5-7200U (two physical/four logical cores), HD 620, 8 GiB RAM.
The PC is canonical; access is `ssh mac`, using the pinned host key.

## Collect evidence before diagnosing the Mac

Use the existing route checker for transport, then the shared host report. These
commands do not wake/unlock the desktop, change power settings, dismiss windows,
restart services or operate the phone:

```sh
/home/visar/Documents/environment/mac-access/mac-connect --check
ssh mac 'sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 /Users/visar/Developer/ios-tools/native/scripts/mac-health --ui --save'
ssh mac 'sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 /Users/visar/Developer/ios-tools/native/scripts/mac-workload status'
```

`mac-health` separates command responsiveness, network configuration, power
preferences, console session flags, the current workload lease, scoped GUI alerts
and dated crash metadata. Its private JSON receipt is under the existing workload
cache. Missing/denied/timed-out probes remain unknown; they are never reported as
healthy. `--ui` reads only known alert hosts and may require existing Accessibility
permission; an unavailable UI probe is not permission to enable it or dismiss alerts.

`CGSSessionScreenIsLocked=true` alone does **not** establish a password-protected
lock. Display-off shielding can set it while loginwindow later reports that the
keybag was never locked. It establishes neither a disconnected Mac nor the cause
of a failed Simulator input. Read the loginwindow event/actual app-state evidence
before attributing a failure. Preserve existing display/sleep/security preferences.
Builds and SSH can work while the desktop is shielded. For unattended lifecycle
tests, use a prebuilt XCTest driver (`XCUIDevice.shared.press(.home)` and
`XCUIApplication.activate`) and assert the application's real lifecycle/save state;
a successful keyboard/menu/launch request is not proof of a background transition.
Build the driver with no active guest, then run `test-without-building` inside the
same exact-device simulator guard, with parallel test destinations disabled.

An old crash alert must be matched to its original report date, process, guest and
termination reason before attribution. November 9's retained MobileCal alert was a
November 7 background Calendar launch watchdog in the shared guest; it was not a
new Maid Heroes crash or Mac kernel panic. Keep reports and graphics quarantine.

For this unattended build host, the owner authorized noninteractive crash dialogs:

```sh
ssh mac '~/Developer/ios-tools/native/scripts/mac-health crash-dialogs noninteractive'
ssh mac '~/Developer/ios-tools/native/scripts/mac-health crash-dialogs status'
# Explicit rollback to the original preference, including an originally absent key:
ssh mac '~/Developer/ios-tools/native/scripts/mac-health crash-dialogs restore'
```

This persists only `com.apple.CrashReporter DialogType=none`, with a durable private
rollback receipt. It does not disable ReportCrash, diagnostics, crash watchers,
notifications or system/user services. Preserve and inspect an existing alert before
closing that specific alert; this command does not dismiss current windows. Verify
fresh `.ips` capture and the absence of a blocking dialog with a bounded owned probe
before relying on it. No background dialog-clicker, keep-awake job or agent session
is a required dependency.

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
12 GiB free, no running `xcodebuild`, and no booted simulator other than the
idle guest the guard itself holds warm (see "The guest stays warm for an hour").
Simulator admission also requires load at most 6. A build, or a session that
reuses the warm guest, may start with a higher residual load average after three
successive samples show at least 50% CPU idle and a health probe below 0.5
seconds; the other checks still apply. A session that has to boot always waits
for the load limit.
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

## T3 Code's Device panel on this Mac

The owner switched on T3 Code's Devices feature on 2026-11-12 (Settings → Devices): the Device
panel can show an iOS Simulator next to a thread, and agents get `device_*` tools and an
`agent-device` command. T3 installs its own helpers (a device hub and `agent-device`) with npm
under `~/.t3`; Node 24 was installed for that, for the user only, in `~/.local/share/node` with
`node`, `npm` and `npx` linked into `~/.local/bin`. Nothing was added at startup.

T3 knows nothing about this guard, so on this Mac:

- Agents do not boot, open or drive a simulator through T3 (`device_open`, `agent-device`, the
  panel's **Start**). That is a raw boot outside the guard, and `agent-device`'s first iOS tap
  compiles a test runner with Xcode outside it too. Simulator QA stays `mac-workload simulator`
  with the shared device UUIDs, exactly as described below.
- A simulator that T3 started is not the guard's warm guest. While it is booted the guard
  refuses builds and simulator sessions, so app deliveries wait (`ios-push` shows them
  pending) until it is powered off. If a delivery is stuck that way, say so and ask; do not
  shut another owner's guest down.
- The owner may use the panel himself. Watching the guard's warm guest in it is harmless.

Android does not run here: the emulator and its virtual device are on the PC
(`~/Android/Sdk`, virtual device `Pixel_9`), where T3 uses them without these limits.

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
timeout. End the owned session normally. With all guests shut down (`mac-workload
release-warm` ends the warm hold), no pending
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

Build first (only the guard's idle warm guest may be up), then enter one bounded guarded session.
Use fixture data and separate app bundle IDs or test-data directories. Reset
only the owned app's fixture when needed; do not erase the shared device between
projects. Update a diagnostic app in place during a testing session, stop it
after each attempt, and uninstall it after the final check. The guard closes
its owned GUI and keeps the exact guest warm for an hour (below), then shuts it
down; retain the initialized shared device for the next project.

Create a temporary device only when a test actually requires another model,
OS version or isolated device state. Record its owner, reason and UUID. Remove
that temporary device through `apple-tool simctl delete UUID` after its final
check and any needed state/evidence backup. Never delete another active or
reserved device, and do not remove either shared device as routine cleanup.
Transport, parser, model and non-iOS checks belong on the PC (the apps' `scripts/test.sh` and
`scripts/kit-test.sh` run there with Swift for Linux; native/README.md) or in a guarded
native command without booting a guest. Batch related UI checks within one
boot instead of creating or rebooting a simulator for each case.

Check `mac-workload status` and the graphics repair status first. A new,
unreviewed kernel panic or GPU reset report blocks simulator startup. Driver experiments require an explicitly recorded,
time-limited trial whose expected driver setting is verified before boot.
Do not bypass quarantine with raw `simctl boot` or opening Simulator.app.

### Boot only the services a check needs

A stock iOS 26.3 guest starts about 180 of its ~370 launchd jobs (Siri and
on-device intelligence, Health, Home, Mail, Calendar, telephony, Game Center,
Wallet, ads, App Store, Screen Time, iCloud sync, photo analysis, Spotlight,
location, push, widgets, watch companions, ...). On this two-core Mac they
compete with the app under test for the whole session. Guarded iOS sessions
therefore boot **lean**: the jobs listed in `native/simulator-profiles.json` are
disabled, and only groups a project needs are kept.

- `--app PROJECT` keeps the groups recorded for that ios-push project (`apps` in
  the JSON). Without `--app`, the guard takes the project named in the command's
  paths (`~/Developer/video-platform/...` → `video-platform`, `guidance-virtual`
  → `guidance`). Today only `video-platform` (`media`) and `t3-watch` (`watch`,
  `widgets`) need anything.
- `--needs a,b` keeps named groups (`media`, `photos`, `location`, `push`,
  `widgets`, `watch`, `siri`, `safari`, `store`, `icloud`). Unknown names are
  refused before boot.
- `--full` boots every job, for checks of system behaviour or to rule the
  profile out when something looks wrong.
- The session prints `Simulator profile: lean +media (app video-platform)
  (N launchd jobs disabled)` and records the profile in the lease.
- Watch guests have no profile and boot fully.

How it works: `launchd_sim` reads its persisted overrides from
`/private/var/tmp/com.apple.CoreSimulator.SimDevice.UDID/disabled.plist` at boot.
`simctl boot --disabledJob` does not work for this. It only writes
`/private/tmp/<same>/disabled.plist`, which this runtime ignores for user-domain
jobs, and 386 of the 392 jobs run in `user/501`. Verified November 11: a job
passed with `--disabledJob` still ran; the same label in the persisted file never
loaded.

The guard writes the overrides while the guest is shut down. It keeps each
label's original value in
`~/Library/Application Support/ios-tools/simulator-profile/UDID.json`, writing
that file first so an interrupted write can still be undone. A smaller profile
or `--full` restores those values exactly, including the companion jobs
CoreSimulator explicitly enables for the paired Watch. A change someone else
made since is adopted, not reverted. A boot outside the guard gets the last
session's profile.

Three services must stay on, even though nothing obviously needs them:

| Job | What happens without it |
| --- | --- |
| `com.apple.sleepd` | SpringBoard retries `com.apple.sleepd.sleepserver` in a tight loop (53,000 lookups) and the boot never finishes. |
| `com.apple.dmd` | `appprotectiond` does the same with `com.apple.dmd`. |
| `com.apple.nanoregistryd` (and `nanoregistrylaunchd`) | CoreSimulatorBridge's host-support handler deadlocks in `NRPairedDeviceRegistry`. SpringBoard is up after 16 s, but `simctl bootstatus` stays at "Waiting on BackBoard" until the deadline. |

Add a job to `lean` only after a guarded lean boot reaches `Finished`, the app
check passes, and the guest's launchd log
(`/private/var/tmp/com.apple.CoreSimulator.SimDevice.UDID/launchd.log`, lines
`failed lookup: name = X, requestor = Y`) shows no requester retrying in a loop.
Failed lookups of a disabled service normally return at once, so a few per
requester are expected. A hang shows up as bootstatus stuck at one stage.
Sample the guest processes from the host (`sample PID 3`); they are ordinary
host processes.

Measured November 11 on the shared iPhone (iOS 26.3.1), Manga Reader's offline
check: install, launch, first KitTestHooks `/layout`. "Cold" runs follow
`sudo purge`. Admission waits are excluded.

| | Full, warm (2 runs) | Lean, warm (4 runs) | Full, cold | Lean, cold |
| --- | --- | --- | --- | --- |
| Boot to `Finished` | 59–74 s | 26–30 s | 89 s | 34 s |
| `simctl install` | 75–82 s | 33–37 s | 98 s | 34 s |
| `simctl launch` returns | 9–16 s | 4.3–4.6 s | 10.9 s | 5.3 s |
| First `/layout` after launch | 22–34 s | 8.7–9.1 s | 16.1 s | 9.9 s |
| Boot to app on screen | ~170–190 s | ~75–80 s | ~214 s | ~83 s |
| Running jobs after the check | 181–183 | 71–72 | 180 | 70 |
| Guest CPU time, whole session | 529 s | 228–233 s | 568 s | 246 s |

Most of the remaining install time is installd's first install of each boot.
Its preflight walks the runtime's bundles (240 apps, ~2,400 frameworks) before installing (logged as
`Preflight/Patch`, plus 241 harmless `Info.plist missing` lines in
`~/Library/Logs/CoreSimulator/UDID/MobileInstallation`). It takes 10–20 s lean
and 50–62 s full, because the walk competes with the other daemons. Later
installs in the same boot skip it, so install every app a check needs within
one session.

What still runs lean is mostly SpringBoard (33 s of CPU), PosterBoard (11 s),
the home-screen widget renderer (7 s) and the prewarmed Spotlight UI (6 s).
None of these can be disabled without breaking the home screen.

### The guest stays warm for an hour

A session whose check finishes, passing or failing, does not shut its guest
down. The guard stops the apps the check left running (Apple's own are left
alone), closes the Simulator window it opened and leaves the guest booted and
idle. The next session on the same device within the hour reuses it: no boot,
and installd's first-install scan is already done. It prints
`Simulator warm: reusing the guest booted N min ago, idle M min (...)`, and
`--cold` boots fresh instead.

Measured November 11 on the shared iPhone (lean), installing and launching a
Manga Reader QA build:

| | Cold session | Warm reuse |
| --- | --- | --- |
| Guest ready (boot, or reattaching the window) | 32 s | 2 s |
| `simctl install` | 31.9 s | 1.0 s |
| `simctl launch` returns | 2.2 s | 1.1 s |

The idle warm guest (window closed, no app running) used 0.8% CPU and about
1 GB of memory: 57% of memory was free with it up, 70% after it shut down.
A reuse is admitted on idle CPU like a build (there at residual load 7.2,
after 17 s); a cold boot still waits for load 6. The timer checks once a minute,
so a hold ends up to a minute after its hour.

The hold ends, with a normal `simctl shutdown` of that exact guest:

- after an hour without a session (`simulatorWarmSeconds` in the policy file,
  default 3600; 0 turns the hold off);
- before a session that needs another device, services the warm guest has off
  (a lean guest cannot serve `--app video-platform`; a `+media` guest serves a
  lean check), or `--cold`;
- at once on a new kernel panic or GPU reset report, or two minutes of memory
  pressure;
- before a build is admitted under memory pressure, and during a build the
  moment the host shows pressure or slow probes (the build then continues if
  that was enough);
- on `mac-workload release-warm`, e.g. before measuring an idle Mac;
- on a check that was stopped (deadline, pressure, crash report, delivery
  yield, cancellation): those guests are shut down as before.

Builds, the push queue and renewal are admitted beside the idle warm guest;
`mac-workload status` reports it under `warm`, not `booted`. Only one guest is
ever up.

The record is `~/Library/Caches/ios-app-refresh/simulator-warm.json`. It names
the guest's `launchd_sim` process (PID and start time); a guest booted again by
anyone else no longer matches, and its record is dropped without touching the
guest. The hour is timed by a detached `mac-workload warm-expire` process, not a
service: if it is lost, every guarded workload ends an expired hold itself.
A power loss or reboot ends the guest, and nothing brings it back: the window
is closed during the hold, so Simulator.app is not reopened at login. Only the
guard's own Simulator process is started with `-DetachOnAppQuit YES` (quit
leaves the guest running); the Simulator preference itself stays at its
default, which shuts guests down on quit.

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
When the check finishes it hands the guest to the warm hold; on a timeout,
cancellation, pressure stop or crash report it shuts down only that guest in
`finally`. It refuses to take over a device already booted by someone else.
GUI ownership includes the original PID, process start and executable command.
Cleanup verifies actual exit after requesting quit. If necessary, it sends SIGTERM
only to that unchanged owned process after the guest shuts down. An unknown/reused
PID, another active guest or failed GUI exit retains a recovery lease and fails
cleanup explicitly; a successful AppleScript return alone cannot release ownership.
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
Cold guest initialization took about 224 seconds (full boot; lean sessions now reach
the app in ~83 s cold, see "Boot only the services a check needs"); the combined comparison batch
later reached its ten-minute deadline. This validation covers single-stream
720p H.264. Other codecs/resolutions require their own measurements, and the
historical Intel driver failure retains its separate guard.

Close Simulator.app after a session so macOS cannot reopen it and reboot the
guest at the next login. Guarded visible sessions close the GUI they opened,
also when the guest stays warm. A pre-existing GUI is never taken over.
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

Every guarded workload ends by bounding two regenerable caches nothing else trims:
`/private/var/tmp/SpeechModelCache` (speech services' compiled `*.bnnsir` models;
macOS never cleans `/var/tmp`, and it had reached 3 GiB of superseded ~400 MiB
sets) keeps its newest 512 MiB, and `~/Library/Developer/Xcode/DerivedData`
folders idle for three days are removed. The simulator itself is already lean:
one runtime per OS, the two shared devices and their current dyld caches
(November 10: runtimes 14.5 GiB, dyld caches 7.0 GiB, devices 4.6 GiB, of which
~1 GiB is the guests' own capped unified logs). Keep the Xcode GUI closed on
this build host: builds use `xcodebuild`, and an open Xcode window re-copies
phone/Watch symbol caches (6.5 GiB) and indexes projects in the background.

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
