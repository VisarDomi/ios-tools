# Installed-app renewal: paid monthly

The single Mac scheduler is `com.visar.installed-apps-refresh`. It enumerates the
phone's installed developer apps, matches them to their existing builders, and
uses the signing profile's team and `LocalProvision` flag to distinguish free
from paid signing. It skips apps that have been deleted and reports installed
apps that do not yet have a registered builder.

All ten current apps are paid: Gallery Reader, Reader Extensions, Asura,
Scythe, Yaksha, QiScans, Lua, EzScans, Hitomi and Imhen. Each renews one calendar month after
its last successful update. The user deleted free Gallery and LiveContainer;
their daily renewal configs/jobs are retired. No free app is scheduled.

One LaunchAgent checks every ten minutes and at login, so offline/locked phones
can be retried. It builds only due apps, sequentially, retaining reading data by
installing over the existing bundle ID. It does not depend on Linux or Codex.
The Mac must be awake and logged in, with the paired phone reachable/unlocked.
`caffeinate` holds the Mac awake only during an attempt.

## Existing builders, one scheduler

`scripts/refresh-installed.py` handles enumeration and scheduling.
`scripts/refresh.py` is the existing Reader Extensions renewal runner with an
optional `interval: monthly` and per-app state directory. Each successful renewal
must extend every installed provisioning-profile deadline; merely reinstalling
unchanged profiles does not count. Single-target apps run first and obtain a fresh
profile. Later paid apps reuse that profile if it has newer deadlines and was
created after their previous successful renewal. This avoids repeatedly replacing
a shared wildcard while Xcode prepares an extension host's multiple targets.
Failed attempts restore staged profiles and retry later.

The purpose is to maximize the usable time away from the Mac. Free provisioning
still lasts seven days, so daily renewal cannot protect a free-signed app during
a longer trip. Current paid profiles last until September 2027, but signing
certificates also expire and can be revoked. The current paid development
certificate expires September 12, 2027 at 15:23:01 UTC. Profile renewal does not
renew that certificate or the Apple membership; do not promise indefinite use.
See [Apple's free provisioning limits](https://developer.apple.com/help/account/basics/about-your-developer-account)
and [profile validity](https://developer.apple.com/documentation/technotes/tn3125-inside-code-signing-provisioning-profiles).

Gallery now uses this same shared monthly runner, signed as
`com.visar.GalleryReader.paid` with team `65U58U86DD`. Its builder sets
`GALLERY_BUNDLE_ID` and selects the physical phone with `SIGNING_DEVICE` so its
explicit profile includes the device. The Gallery polling runtime is unchanged;
APNs/background work remains paused. Old free Gallery/LC runner adapters are no
longer referenced or included in the recovery copy. Manga provider identities
come from `build/providers.json`; no provider-specific renewal implementations
exist.

Existing source approval, signature/identity checks and the shared signing lock
remain. Changing source deliberately requires deploying/reviewing that baseline,
then approving it for unattended builds. There is no Git pull, automatic source
migration, app-data copy, certificate revocation, or uninstall in this workflow.
Xcode login, signing certificates and paid membership must remain valid; running
this job does not renew the Apple membership or guarantee perpetual certificates.

## Paths and setup

Start with [shared Mac access](/home/visar/Documents/environment/mac-access.md). Ethernet is now
`192.168.1.198`; USB wireless remains DHCP.

Mac entry point: `/Users/visar/Developer/reader-extensions`.
Index: `refresh-apps.local.json`. Generate it using the existing project mirrors:

```sh
/usr/bin/python3 scripts/configure-refresh.py \
  --manga-root /Users/visar/Developer/asura-reader \
  --gallery-root /Users/visar/Developer/gallery-downloader \
  --gallery-reader-root /Users/visar/Developer/gallery-reader/apps/ios \
  --team 65U58U86DD --device 00008101-000639912881401E
```

This writes the ten paid per-app configs under `build/installed-refresh/config`. The configuration step does not
build, install, or reset a successful-refresh timestamp. Run it again after
adding a provider to the shared registry and deploying its native app.

For each newly registered or deliberately changed app, use its configured
runner's `approve --config <app-config>` after delivering the intended baseline.
Then run the scheduler's initial `refresh --force --wireless --config
<absolute-index>` in a temporary GUI LaunchAgent, with USB disconnected. The GUI
session provides Keychain access. Verify successful states and exit 0 before:

```sh
/usr/bin/python3 scripts/refresh-installed.py install --config refresh-apps.local.json
```

The installer refuses to replace a loaded scheduler. There is no separate paid scheduler. The account interval selects when the
existing renewal operation runs; profile checks verify that it actually renewed.

## Inspect and maintain

```sh
/usr/bin/python3 scripts/refresh-installed.py status --config refresh-apps.local.json
launchctl print gui/501/com.visar.installed-apps-refresh
# Pause only when idle, before changing a delivered baseline.
launchctl bootout gui/501/com.visar.installed-apps-refresh
# Resume the existing scheduler after deliberate deployment/approval.
launchctl bootstrap gui/501 "$HOME/Library/LaunchAgents/com.visar.installed-apps-refresh.plist"
```

The scheduler's bounded log is `build/installed-refresh/last-check.log`.
Paid per-app state/build logs are under `build/installed-refresh/<name>`.
All ten current apps use this shared state location; old Gallery/LC daily state
is historical only. Success is
recorded only after installation; a failed app remains due without repeating
successful apps. The scheduler's periodic attempt log captures offline errors.

## Verification

September 12, 2026: all seven paid apps already passed physical wireless renewal
and installation. Their success timestamps were migrated into the unified
scheduler after verifying source hashes and profile UUIDs; no success was
invented during migration. The earlier multi-target wildcard problem came from replacing the same profile
for every app. The shared-profile reuse rule avoids that repeated regeneration.

Historical verification before Gallery migration: the nine-app wireless renewal finished at
17:17 UTC with exit 0. All nine successful states recorded `localNetwork`, later
profile deadlines and no error. The scheduler was enabled at 17:17 UTC; its
immediate check enumerated the nine apps and skipped their builds because all
were current. That earlier configuration scheduled daily renewals for September
13; those daily entries have since been retired. Current monthly renewals are
due October 12. The obsolete individual labels remain disabled, and temporary test
jobs were unloaded. The superseded paid-only prototype was removed.

Evidence on the Mac: `build/installed-refresh/wireless-verification.json` plus
per-app states/build logs. Current profile expiry: free apps September 19, 2026;
paid apps September 12, 2027. Tests passed: 17 renewal behavior checks, two
installed-app scheduler checks, three packaging checks, and four shared-provider
builder/lock checks.

## Paid Gallery migration, September 12

Gallery's paid install, launch and wireless monthly renewal passed. Its profile
advanced from 2027-09-12 17:25:34 UTC to 17:27:50 UTC. Phone inventory confirmed
the old free Gallery and LC were gone. The active index now contains eight paid
apps, and the environment recovery copy includes paid Gallery instead of the
two free adapters. Historical nine-app test evidence above predates this change.

Hitomi/Imhen use the shared gallery-reader `apps/ios/providers.json` registry and
`build-provider.py` builder. Prepared per-provider Web bundles are renewal inputs;
the shared Resources/Web staging directory is an output, never an approved input.
The builder shares the existing inherited signing lock.

## Ytb

The standalone Ytb app (`com.visar.Ytb.paid`) is the eleventh paid entry. Add
`--ytb-root /Users/visar/Developer/ytb/apps/ios` alongside the other roots when
running `scripts/configure-refresh.py`. Its single-source builder is
`/bin/bash scripts/build.sh`; no provider parameter. The initial September 12
renewal passed with USB connected and retained the user-imported favorites.
See `../video/km-explorer/apps/ios/PORT.md` and the environment recovery copy.
