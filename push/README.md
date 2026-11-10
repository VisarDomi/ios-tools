# One-command iOS updates

```sh
ios-push filehost
ios-push gallery-a
ios-push manga-reader:asura
ios-push guidance
ios-push t3-watch
```

Run from the app's checkout (worktrees are supported), or use `--source /path/to/checkout`.
`ios-push list` lists the configured projects/apps. Short names `filehost`, `fmp4`, `ladder`,
`vault` and `tslive` select their Video Platform apps; `tslive-local` is explicit.

The command prepares resources, freezes the current source bytes and returns **Queued
JOB**. Working edits and declared ignored inputs are captured; committing is recommended
but not required. Wait for this acknowledgement before editing the same inputs. Build,
signing, installation and approval then run independently of the terminal/thread.

```sh
ios-push status JOB
ios-push status JOB --follow
ios-push logs JOB
ios-push cache
ios-push cache --json
ios-push retry JOB
ios-push cancel JOB
ios-push ota JOB
```

Following is optional; stopping the follower never stops the job. Agents should submit,
continue working and check status at a natural checkpoint. Enqueue success is not
installation success: only **installed** confirms in-place installation and renewal
approval. Product apps are never launched or uninstalled; the phone UI is never driven.

**awaiting_ota** means a signed package was published through the existing tailnet
installer because direct installation was unavailable. Pass on
`https://mac.tailf47c4e.ts.net:8443/`. This is not claimed as installed; delivery retries
when the authenticated phone returns. Once installation/publication might have happened,
finish or supersede the delivery with a newer push instead of cancelling it into an
older renewal baseline.

`ios-push ota JOB` requests OTA publication for an already queued delivery,
including one whose source is still uploading. It preserves the frozen source
and bypasses local phone discovery for its initial publication. Later checks
can still confirm delivery when the phone is reachable. New builds/publications
run before retries for already-published OTA packages.

`--validate-only` builds/verifies without any phone operation. `--force` rebuilds even
when an exactly matching verified artifact could be reused. The caller still runs the
appropriate app tests; signing checks do not replace UI or codec verification.

T3 Watch uses the same queue for its iPhone companion, embedded native Watch app,
and complication. The paired Watch UDID belongs in `watchDevice` in the Mac's
private `ios-tools.local.json`. All nested profiles, device platforms and App
Group entitlements are checked. **awaiting_watch** means the phone delivery was
verified but the Watch installation or its version confirmation is pending.
The worker releases the shared lock and retries with bounded backoff; other apps
can proceed. It retains the exact signed checkpoint, avoids reinstalling the
already verified phone artifact, and approves renewal only after both devices
are verified. A worker restart or power cut preserves that state. `ios-push logs
JOB` includes the Watch install log. No product app is launched.

If direct Watch developer discovery fails, the worker can deliver the same signed
Watch bundle through the existing trusted iPhone's standard lockdown/companion
service. This does not open a competing Python RSD connection or remount a DDI.
It validates the Watch identity/profile, installs in place, and reads the actual
Watch inventory before approval. Merely finding the same version installed does
not approve a new artifact or a same-version profile renewal. Missing phone/Watch
access still returns to `awaiting_watch` and releases the lock.

A new project's first verified signed installation starts its monthly renewal
clock and registers its own existing-style renewal scheduler. Later updates keep
the existing renewal date. Scheduler setup can resume after interruption without
reinstalling already verified apps, and updates preserve intentionally paused
existing schedulers.

Free-space, current-resource and shared-guard refusals stay pending and retry.
Queued delivery has priority over simulator QA: new sessions defer and an active
guarded guest yields through its normal cleanup. Source upload does not wait for
an obsolete load average; compilation still proves actual CPU/memory headroom. A compiler or
build-script failure is reported as failed with its first compiler diagnostic,
using the current attempt's log even when older attempts are retained. `logs`
also includes early compiler errors before the log tail, so an Xcode traceback
cannot hide the cause. Completed failed-build compiler caches are
discarded without removing their frozen source, signed apps or diagnostic logs.

## Build cache

Queued Xcode builds enable Apple's local content-addressed compilation cache via
a generated xcconfig outside the frozen source. The shared cache is under
`~/Library/Caches/ios-tools/CompilationCache.noindex`, so fresh job paths and
per-job DerivedData cleanup no longer discard cached compiler outputs. Xcode's
own pruning targets 8 GiB per CAS store (2 GiB evicted unchanged NativeKit modules between apps); no cache-cleanup daemon is added. Build
logs include cache diagnostics, and receipts record compilation seconds.

Manga Reader, Gallery Reader (online and offline) and Video Platform builds also use stable,
regenerable compiler workspaces, each capped at 2 GiB of retained compiler data. FileHost has its own
provider workspace; the other video providers and the two online Gallery Reader providers
(`shared` in `projects.json`) each build one common target in one shared workspace.

A stable path is what lets a second provider reuse the first one's app module. Xcode's
compilation cache reuses NativeKit's modules across job paths, but an app module compiled at one
checkpoint path missed at another (November 10, Intel Mac: 122/133 hits and 67–71 s at a new path,
133/133 and 19.7 s at the same path; prefix mapping and header maps were not the cause). Variant
apps therefore share one module name and one DerivedData inside one workspace: after a shared edit,
Manga Reader's second and third providers took 35.9 s and 39.0 s instead of 111–216 s. Each job still freezes its own source. The
worker copies changed inputs into the workspace, preserves unchanged timestamps,
verifies the full tree before and after compilation, then copies the verified
signed app back into that job's checkpoint. Stable paths let subsequent builds
reuse Xcode's dependency database and compiler outputs after small edits. Cache
repair and pruning happen under the existing shared guard; interrupted copies
are reconciled on the next build. Large frozen decoder inputs are initially cloned
on APFS; cache eviction counts generated compiler data and preserves source inputs.
Other projects retain their current policy.

A November 6 signed Lua validation on the Intel Mac verified both cache paths:
a cold build took 158.9 s; a real edit took 104.1 s and compiled only the app
module; an unchanged forced Xcode pass took 19.4 s with no Swift compilations;
and an ordinary identical submission reused its signed app with 0 compilation
seconds. These are build-stage measurements, excluding queue/upload/install time.
A Swift edit still recompiles that release module with whole-module optimization.

A November 7 FileHost validation on the same Intel Mac measured 758.4 s for the
first retained-workspace build, 46.5 s for an unchanged forced Xcode build with
zero Swift compilations, and 90.7 s for an app-only edit. The edit compiled only
the app module; AetherEngine and NativeKit remained skipped. All three signed
validation jobs verified without installing or changing the phone app. These
measurements cover the build stage, excluding source capture/upload/queue time.

Sources that import AppIntents retain real Swift paths: Xcode's metadata
extractor cannot resolve the cache's virtual source aliases.
Sources that do not import AppIntents skip const-value emission and App Intents metadata
extraction instead (`SWIFT_ENABLE_EMIT_CONST_VALUES = NO`, `LM_SKIP_METADATA_EXTRACTION = YES`):
3–5 s less per build on the Intel Mac, no runtime change. The shared cache
and Clang path normalization remain enabled; only Swift path normalization is
omitted for those apps so complication and shortcut metadata can be generated.

Queue builds and monthly renewals of queue-approved checkpoints use the same
guarded compilation/cache helper. Renewals retain their existing profile rotation,
approval, installation checks and calendar schedule. A completed replacement app
is staged before the previous signed output is replaced; an interrupted directory
publication recovers on the next admitted build.

Each records `cache-report.json`: aggregate hits, per-module misses,
compile time, artifact reuse and generated-cache eviction. `ios-push cache` shows
latest health for each app; `--json` includes a bounded history of twenty builds.
Reports compare declared module inputs and toolchain identity. An unchanged
module that recompiles produces a `CACHE REGRESSION` warning in the build log and
`cacheWarnings` in job status. Skipped modules retain their comparison baseline;
artifact reuse and failed builds cannot erase it. SDK changes and known eviction
are reported without treating the next cold compile as an unexplained regression.
This monitoring runs in the existing worker and survives normal restarts; no
additional polling service or cleanup daemon is installed. Frozen-source,
signing and installation checks remain authoritative.
Renewal reports identify `buildKind: renewal` and live beside the scheduler's
normal `build.log`; they also appear in `ios-push cache`. Cache-only renewal
validation builds a disposable clone and changes neither the approved signed
artifact nor installed profiles, renewal state or device data. Older registrations
that do not point to a queue checkpoint keep their existing builder.

Release optimization and signing/profile verification stay in force. Terminal
builds skip IDE indexing. An existing `XCODE_XCCONFIG_FILE` is included before the
cache settings. Source checkpoints stay immutable; cached compiler outputs still
produce a freshly verified signed artifact. `--force --validate-only` exercises a
new checkpoint's compiler cache without installing or approving it for renewal.

## Checkpoints and recovery

One PC systemd uploader hands complete hash-checked jobs to one Mac GUI LaunchAgent.
The worker uses the existing signing lock and `mac-workload` admission, memory, disk,
deadline and graphics policies. It does not compile alongside a guarded guest. There
is no keep-awake helper or power-policy change.

Builds use `~/Developer/ios-push/checkpoints/JOB/source`. Later edits cannot enter a
queued build. Ready is published only after bytes and directory entries are flushed.
Interrupted uploads/builds resume; incomplete signed outputs rebuild before device
work. Source, artifact, identity, phone profile, expiry and installed version are
checked before approval.

After confirmation, only the requested app's renewal registration moves to the new
checkpoint. Other apps keep their approved roots. Do not edit checkpoint directories
or assume `~/Developer/REPO` remains an app's renewal root: read its registration or
the push result. Submit shared changes for each intended app; a FileHost-only update
does not silently change other apps' baselines.

A durable `pendingPush` marker makes renewal defer before installation/OTA publication,
preventing old-code renewal after a mid-delivery crash. Successful approval clears it
and preserves the monthly schedule where profiles permit. Mac-assigned queue sequence
numbers prevent PC/Mac clock skew from letting an older push supersede a newer one.

All approved/pending roots and two recent unreferenced trials are retained; obsolete
Mac checkpoints and completed compiler caches are pruned. Approved roots do not
consume the two unreferenced trial slots, and a pending build protects its newest
matching verified signed artifact so validation need not be compiled again. Metadata/private logs live
under `Library/Application Support/ios-tools/push` on the Mac and
`.local/share/ios-tools/push` on the PC.

## Installing and preparing projects

```sh
python3 push/install.py --pc
python3 push/install.py --deploy-mac
```

The intentional jobs are `ios-push.timer`/`ios-push.service` on the PC and
`com.visar.ios-push` in the Mac GUI login. They resume at login/network recovery and
perform no device work without a queued delivery. Existing renewal schedulers stay.
A completed upload (and `retry`/`cancel`/`ota`) starts the Mac worker at once; it sleeps through
retries due within five minutes, waking early for new jobs, then exits. launchd restarts it every
five minutes, so an idle queue no longer costs a Python run every 30 s (0.7 CPU-s each on the
Intel Mac).
The shared tool mirror publishes committed HEAD, keeping unfinished tool edits out
of the Mac worker. Commit tested tool updates before running the Mac installer.

`projects.json` maps existing NativeKit checkouts. Recipes come from each app's existing
`scripts/renewal.py`; team/device come from the Mac's private `ios-tools.local.json`.
Video Platform's `deploy.py APP prepare` and Gallery Reader's `--prepare-only` prepare
resources without contacting the Mac.
Initial account/LAN provisioning remains project-specific; ordinary pushes preserve it.

Deep Town's missing PC-side RoboVM bundle can only be inherited from its existing
approved Mac input. Prepare a changed game payload through its project runbook first;
the queue never invents one. New projects can be added with their renewal declaration
and resource-preparation recipe. Diagnostic builds are not product push targets.
