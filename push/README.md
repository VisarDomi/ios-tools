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
build-script failure is reported as failed, using the current attempt's log even
when older attempts are retained. Completed failed-build compiler caches are
discarded without removing their frozen source, signed apps or diagnostic logs.

## Build cache

Queued Xcode builds enable Apple's local content-addressed compilation cache via
a generated xcconfig outside the frozen source. The shared cache is under
`~/Library/Caches/ios-tools/CompilationCache.noindex`, so fresh job paths and
per-job DerivedData cleanup no longer discard cached compiler outputs. Xcode's
own pruning targets 2 GiB per CAS store; no cache-cleanup daemon is added. Build
logs include cache diagnostics, and receipts record compilation seconds.

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
Mac checkpoints and completed compiler caches are pruned. Metadata/private logs live
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
The shared tool mirror publishes committed HEAD, keeping unfinished tool edits out
of the Mac worker. Commit tested tool updates before running the Mac installer.

`projects.json` maps existing NativeKit checkouts. Recipes come from each app's existing
`scripts/renewal.py`; team/device come from the Mac's private `ios-tools.local.json`.
Video Platform's `deploy.py APP prepare` and Gallery Reader's `--prepare-only` prepare
resources without contacting the Mac. Maid Heroes captures `web/` as `Resources/Web`.
Initial account/LAN provisioning remains project-specific; ordinary pushes preserve it.

Deep Town's missing PC-side RoboVM bundle can only be inherited from its existing
approved Mac input. Prepare a changed game payload through its project runbook first;
the queue never invents one. New projects can be added with their renewal declaration
and resource-preparation recipe. Diagnostic builds are not product push targets.
