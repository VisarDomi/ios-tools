# Installed-app renewal: paid monthly

Every app repository renews its own apps. Its `apps/ios/scripts/renewal.py` names
the repository and lists its apps (name, bundle IDs, build inputs, builder
command); its own Mac LaunchAgent, `com.visar.renewal.<repo>`, runs this folder's
shared runner for those apps only. All apps are signed with one paid team and
renew one calendar month after their last successful update.

| Repository | Mac mirror (`~/Developer/…`) |
| --- | --- |
| manga-reader | `manga-reader/apps/ios` |
| gallery-downloader | `gallery-downloader/apps/ios` |
| gallery-reader | `gallery-reader/apps/ios` |
| km-explorer | `km-explorer/apps/ios` |
| video-platform | `video-platform/apps/ios` |
| maid-heroes | `maid-heroes/apps/ios` |
| deep-town | `deep-town/apps/ios` |
| environment | `environment/twitter` |

Each scheduler checks every ten minutes and at login, so offline or locked phones
are retried. It builds only its due apps, sequentially, installing over the
existing bundle ID so app data is kept. The Mac must be awake and logged in, with
the paired phone reachable and unlocked. Idle system sleep is disabled with
`pmset -a sleep 0`; display sleep is independent. Every scheduled run also reports
installed developer apps that no repository renews.

## How a renewal works

`scripts/refresh-installed.py` enumerates the phone's installed apps and runs
`scripts/refresh.py` for each of the repository's apps that is installed and due.
It distinguishes free from paid signing by the signed profile's team and
`LocalProvision` flag. A renewal counts only when every installed provisioning
profile gets a later deadline; reinstalling unchanged profiles does not count.

The apps share one wildcard profile in the Mac's single Xcode profile cache.
Single-target apps run first and obtain a fresh profile; later apps, in any
repository, reuse it when it has newer deadlines and was created after their own
previous success. This avoids replacing the wildcard while Xcode prepares an app
with embedded extensions. One signing lock
(`~/Library/Caches/ios-app-refresh/signing.lock`, inherited by every builder)
serializes all schedulers: a scheduler that finds it held retries on its next
check. Failed attempts restore staged profiles and stay due. A known Xcode
provisioning-cache race can fail one attempt; an unchanged retry succeeds.

Each app's `inputs` are fingerprinted at approval; a changed input blocks
unattended builds until the new baseline is deployed and approved, so a renewal
never installs anything that was not deliberately installed first. There is no
Git pull, source migration, app-data copy, certificate revocation or uninstall.
Profile renewal does not renew the signing certificate or the Apple membership.
The current paid development certificate expires September 12, 2027 at 15:23:01
UTC. See [Apple's free provisioning limits](https://developer.apple.com/help/account/basics/about-your-developer-account)
and [profile validity](https://developer.apple.com/documentation/technotes/tn3125-inside-code-signing-provisioning-profiles).

## Approval at deployment

Each repository's `deploy.py` runs `scripts/deliver.py` around its build and
install (gallery-downloader's manual steps do the same): `begin` before the build
and `built` after it record the inputs and the built app if the inputs did not
change during the build; `installed`, right after a successful install, approves
that app as its renewal baseline. Approval keeps the renewal date unless a
delivered profile expires before the renewed one, so no rebuild follows the
deployment, and it waits for the signing lock. It is skipped, with the reason
printed, if the inputs or the app changed since the build (for example another
sync to the shared mirror), if the deploy built a different bundle ID (an
unsuffixed manga build) or if the app is not registered. A skipped app stays
blocked until a later deploy or a manual approval below.

## Setup

Start with [shared Mac access](/home/visar/Documents/environment/mac-access.md);
SSH falls back to the Mac's Wi-Fi automatically when Ethernet is down (`mac-connect --check`).
The Mac mirror of this repository is `~/Developer/ios-tools`. On a fresh clone,
copy `ios-tools.example.json` to `ios-tools.local.json` at the repository root
(Mac-only, never committed; the inspector reads it too) and fill in the signing team ID (Xcode → Settings → Accounts) and the phone's
UDID (in parentheses in `xcrun xctrace list devices`, not the CoreDevice
identifier).

Register a repository from its Mac mirror. This writes its configs to
`~/Library/Application Support/ios-tools/renewal/<repo>/` (outside the mirrors,
so deployment syncs never touch them), refuses an app that another repository
already renews, and never builds, installs or resets a success timestamp:

```sh
/usr/bin/python3 ~/Developer/ios-tools/renewal/scripts/configure-refresh.py ~/Developer/<mirror>
```

Rerun it after the repository adds or removes an app. A new app's first deploy
approves it and makes it due. To approve by hand (a skipped deploy, or a recovery),
approve the delivered baseline, then run one attached renewal in the GUI session
(it provides Keychain access without a temporary LaunchAgent). `approve` makes the
app due; `--keep-schedule` keeps its renewal date as deploys do:

```sh
R="$HOME/Library/Application Support/ios-tools/renewal/<repo>"
/usr/bin/python3 ~/Developer/ios-tools/renewal/scripts/refresh.py approve --config "$R/config/<app>.json"
sudo -n launchctl asuser 501 sudo -n -H -u visar /usr/bin/python3 \
  /Users/visar/Developer/ios-tools/renewal/scripts/refresh-installed.py refresh --force --repo <repo>
```

Require exit 0, then enable the repository's scheduler (it refuses to replace a
loaded one):

```sh
/usr/bin/python3 ~/Developer/ios-tools/renewal/scripts/refresh-installed.py install --repo <repo>
```

## Inspect and maintain

```sh
/usr/bin/python3 ~/Developer/ios-tools/renewal/scripts/refresh-installed.py status --repo <repo>
launchctl print gui/501/com.visar.renewal.<repo>
# Pause only when idle. Deploys do not need a pause.
launchctl bootout gui/501/com.visar.renewal.<repo>
# Resume.
launchctl bootstrap gui/501 "$HOME/Library/LaunchAgents/com.visar.renewal.<repo>.plist"
```

A repository's scheduler log is `last-check.log` in its folder above; each app's
state and build logs are in `<repo>/<app>`. Success is recorded only after
installation. The recovery copy of the configs and LaunchAgents is
`/home/visar/Documents/environment/mac-renewal`; refresh it whenever renewal
scripts or configuration change.

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
