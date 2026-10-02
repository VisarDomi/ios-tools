# Installed-app renewal: paid monthly

The single Mac scheduler is `com.visar.installed-apps-refresh`. It enumerates the
phone's installed developer apps, matches them to their existing builders, and
uses the signing profile's team and `LocalProvision` flag to distinguish free
from paid signing. It skips apps that have been deleted and reports installed
apps that do not yet have a registered builder.

All apps are signed with one paid team and renew one calendar month after their
last successful update. No free app is scheduled. This repository holds only the
scheduler, the per-app runner and the config generator. Each app repository lists
its own apps (name, bundle IDs, build inputs, builder command) in
`apps/ios/scripts/renewal.py`, which runs on its Mac mirror:

| Repository | Mac mirror (`/Users/visar/Developer/…`) |
| --- | --- |
| manga-reader | `asura-reader` |
| gallery-downloader | `gallery-downloader/apps/ios` |
| gallery-reader | `gallery-reader/apps/ios` |
| km-explorer | `ytb/apps/ios` |
| video-platform | `video-platform/apps/ios` |

One LaunchAgent checks every ten minutes and at login, so offline/locked phones
can be retried. It builds only due apps, sequentially, retaining app data by
installing over the existing bundle ID. It does not depend on Linux or Codex.
The Mac must be awake and logged in, with the paired phone reachable/unlocked.
The LaunchAgent runs Python directly. The Mac's idle system sleep is disabled
with `pmset -a sleep 0`; display sleep remains independent.

## How a renewal works

`scripts/refresh-installed.py` handles enumeration and scheduling.
`scripts/refresh.py` is the per-app runner (`interval: monthly`, per-app state
directory). Each successful renewal must extend every installed provisioning-profile
deadline; merely reinstalling unchanged profiles does not count. Single-target
apps run first and obtain a fresh profile. Later apps reuse that profile if it has
newer deadlines and was created after their previous successful renewal. This
avoids repeatedly replacing a shared wildcard while Xcode prepares a multi-target
app (an app with embedded extensions). Failed attempts restore staged profiles and stay
due without repeating successful apps. A known Xcode provisioning-cache race can
fail one attempt; an unchanged retry succeeds.

Source approval, signature/identity checks and the shared signing lock
(`~/Library/Caches/ios-app-refresh/signing.lock`, inherited by every builder)
apply to every run. Each config's `inputs` are fingerprinted at approval; a
changed input blocks unattended builds until the new baseline is deployed and
approved. There is no Git pull, automatic source migration, app-data copy,
certificate revocation, or uninstall in this workflow.

The purpose is to maximize the usable time away from the Mac. Profile renewal
does not renew the signing certificate or the Apple membership. The current paid
development certificate expires September 12, 2027 at 15:23:01 UTC; do not
promise indefinite use. See
[Apple's free provisioning limits](https://developer.apple.com/help/account/basics/about-your-developer-account)
and [profile validity](https://developer.apple.com/documentation/technotes/tn3125-inside-code-signing-provisioning-profiles).

## Paths and setup

Start with [shared Mac access](/home/visar/Documents/environment/mac-access.md).
Mac entry point: `/Users/visar/Developer/ios-app-renewal`, mirrored from this
repository. Build output and `*.local.json` files are Mac-only and never committed.

On a fresh clone, copy `renewal.example.json` to `renewal.local.json` and fill in
the signing team ID (Xcode → Settings → Accounts), the phone's UDID (shown in
parentheses by `xcrun xctrace list devices`; not the CoreDevice identifier) and the
Mac mirrors, in the order they should be listed. Then generate the index `refresh-apps.local.json` and the per-app configs
under `build/installed-refresh/config`:

```sh
/usr/bin/python3 scripts/configure-refresh.py
```

Each mirror's `scripts/renewal.py` prints that repository's entries; the generator
adds the team, device, monthly interval and state paths, and rejects duplicate
names. A new provider or app changes only its own repository: deploy it, then
rerun the command. A new repository adds its mirror to `sources` in
`renewal.local.json`. The command reproduced the deployed configs byte for byte (verified October 3) and does not build,
install, or reset a successful-refresh timestamp.

For each newly registered or deliberately changed app, run its configured
runner's `approve --config <app-config>` after delivering the intended baseline.
Then run an attached wireless renewal in the GUI session, which provides Keychain
access without a temporary LaunchAgent:

```sh
sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 \
  /Users/visar/Developer/ios-app-renewal/scripts/refresh-installed.py \
  refresh --force --wireless --scheduled --config \
  /Users/visar/Developer/ios-app-renewal/refresh-apps.local.json
```

Require exit 0 and successful states, then enable the scheduler:

```sh
/usr/bin/python3 scripts/refresh-installed.py install --config refresh-apps.local.json
```

The installer writes the LaunchAgent with this checkout's paths and refuses to
replace a loaded scheduler.

## Inspect and maintain

```sh
/usr/bin/python3 scripts/refresh-installed.py status --config refresh-apps.local.json
launchctl print gui/501/com.visar.installed-apps-refresh
# Pause only when idle, before changing a delivered baseline.
launchctl bootout gui/501/com.visar.installed-apps-refresh
# Resume the existing scheduler after deliberate deployment/approval.
launchctl bootstrap gui/501 "$HOME/Library/LaunchAgents/com.visar.installed-apps-refresh.plist"
```

The scheduler's bounded log is `build/installed-refresh/last-check.log`; per-app
state and build logs are under `build/installed-refresh/<config>`. Success is
recorded only after installation. The recovery copy of the scripts, configs and
LaunchAgent is `/home/visar/Documents/environment/mac-renewal`; refresh it
whenever renewal scripts or configuration change.

## Paid signing lessons

- Installation failing with `0xe8008012` means the phone is missing from the
  profile (device not registered), not the free three-app cap. Build for the
  physical phone (builders pass `SIGNING_DEVICE`/`DEVELOPMENT_DEVICE`) so
  automatic provisioning registers it with the existing Xcode login.
- A physical destination rejected with `iOS <version> is not installed` needs the
  matching iOS platform support from Xcode's toolbar **Get**; afterwards
  `xcodebuild -showdestinations` lists the phone.
- A regenerated profile can go stale during packaging; rebuild. Never delete
  profiles or revoke certificates as a shortcut.
- New Safari extension identities must be enabled (and their sites allowed) in
  iOS Settings after the first install.
