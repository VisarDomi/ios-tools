# Reader Extensions

One iOS containing app, four independent Safari Web Extensions. This repository
owns **packaging and deployment**, not reader/provider/storage logic.

| Extension | Source | Sites |
| --- | --- | --- |
| Gallery Reader | [gallery-reader](https://github.com/VisarDomi/gallery-reader) | Hitomi, IMHentai |
| Manga Reader | [manga-reader](https://github.com/VisarDomi/manga-reader) | EzManga, Qi Manga, Yaksha, Asura, Scythe, Lua |
| KM Explorer | [km-explorer](https://github.com/VisarDomi/km-explorer) | ytboob.com |
| Stream Viewer | [stream-viewer](https://github.com/VisarDomi/stream-viewer) | tango.me |

Each source repo owns its manifest, extension entry, runtime and behavior tests.
There is no combined userscript, shared runtime service or provider-aware host.
Website-origin data stays with Safari. This is **not** the offline Gallery Reader
native app. The retained macOS Xcode targets package Gallery only; the four-way
suite documented here targets iOS.

## Fresh machine setup

### 1. Tools and checkout

Use Node.js 22.12+ and npm, Git, and (for remote deployment) SSH/rsync. Building
the Apple app requires a Mac with Xcode and an iOS SDK compatible with the phone.
Open Xcode once to finish first-launch setup, select its command-line tools,
add the signing Apple account and connect/trust the iPhone. Enable Developer
Mode on the phone when required. The host project deployment target is iOS 18.

From the directory where you want this workspace:

```sh
mkdir -p manga video
git clone https://github.com/VisarDomi/reader-extensions.git
git clone https://github.com/VisarDomi/gallery-reader.git manga/gallery-reader
git clone https://github.com/VisarDomi/manga-reader.git manga/manga-reader
git clone https://github.com/VisarDomi/km-explorer.git video/km-explorer
git clone https://github.com/VisarDomi/stream-viewer.git video/stream-viewer
git clone https://github.com/VisarDomi/userscript-ios-test.git
```

The last repo is needed by the sources' local `file:../../userscript-ios-test`
development dependency, even if you do not run its phone-injection tests.
It is not a dependency of this packaging repo, is not shipped in the extensions,
and does not need to be installed/enabled on the phone. Its name refers to the
older development injection harness, not the production deployment format.

Install dependencies in each reader (the packaging repo has no dependencies):

```sh
for repo in manga/gallery-reader manga/manga-reader video/km-explorer video/stream-viewer; do
  (cd "$repo" && npm install)
done
```

For another checkout layout, copy `readers.example.json` to `readers.local.json`
inside this repo and edit source paths. Relative paths resolve from this repo;
absolute paths are supported. Keep the readers' test-transport sibling dependency
available at its declared path. Local overrides are ignored by Git.

### 2. Private web-bundle configuration

Gallery, Manga and KM builds require the PC backup access key. A fresh checkout
does **not** contain this key. In each of those three source repos, copy its
`.env.example` to `.env.local` and set:

```dotenv
VITE_READER_BACKUP_URL=https://YOUR_PC_ADDRESS:7777
VITE_READER_BACKUP_KEY=YOUR_EXISTING_SERVER_BACKUP_ACCESS_KEY
```

Gallery also accepts `VITE_GALLERY_SERVER_URL` for its favorites/downloader sync;
set that in Gallery's `.env.local` if it differs from its existing LAN default.
Use a URL reachable by the phone, not `127.0.0.1`.

Obtain the existing key privately from your configured Gallery Downloader
server's `backups/readers/access-key`; see its
[backup setup guide](https://github.com/VisarDomi/gallery-downloader/blob/main/READER-BACKUPS.md).
If that server repo already occupies the expected `manga/gallery-downloader`
sibling location, builds can read the key file automatically. You do not need
to clone or run the server just to compile when `.env.local` supplies the key.
Do not invent a different key and expect it to authenticate to an existing server.
Stream Viewer has no corresponding build-time backup-key requirement; its server
and login behavior remain documented in its source repo.

**The key is embedded in generated bundles.** Never commit/upload `dist/`, signed
apps, `.env.local`, provisioning profiles or signing keys—even to this public
repo's Releases or Actions artifacts. `.gitignore` excludes generated/private
files. `package.json` is npm-private to prevent accidental npm publication; the
GitHub repository is public.

For actual LAN backup/sync, the phone must trust the server's HTTPS certificate.
For a private CA, install its profile and enable full trust in iOS Certificate
Trust Settings. Verify the HTTPS URL opens without a certificate warning first.
An unreachable backup server is silent by design; it is not proof of a successful
backup. Confirm server snapshots before erasing a device.

### 3. Build and stage

From `reader-extensions`:

```sh
npm run build
npm run verify
npm test
```

`build` invokes each reader's existing extension builder, without incrementing
its version, then copies its complete bundle into `dist/<name>-extension/`.
Gallery's three files (`content.js`, `manifest.json`, `rules.json`) must travel
together so the takeover code and response policy stay aligned. Other readers have two files.
The Xcode project uses these paths directly; no converter regeneration is needed.

For an individual update:

```sh
npm run build -- manga-reader
```

Or stage an already built bundle without rebuilding it:

```sh
npm run stage -- manga-reader
```

No names means all four. Selected updates leave other staged bundles untouched.
Do not run staging while Xcode is building. `verify` checks all required files
and manifest references and prints SHA-256 hashes, not file contents. A fresh
machine needs a full build before an individual update can produce a complete app.
Tests here cover packaging; the source repos own runtime/iPhone tests.

### 4. Sign on a Mac

You can build locally on the Mac using this same checkout layout:

```sh
SIGNING_TEAM=YOUR_APPLE_TEAM_ID bash scripts/build-on-mac.sh
```

Run this from a logged-in GUI Terminal so signing can access the Keychain.
Output is `build/Debug-iphoneos/Reader Extensions.app`. The technical project and
target retain their historical names; the installed product is Reader Extensions.
In Xcode, the iOS host and four extension targets must use the same signing team.
The containing app deliberately supplies no custom app icon, splash graphic or
in-app logo, matching the minimal native Gallery Reader app. iOS owns the fallback
Home Screen/App Library appearance; this does not hide or uninstall the host.

Existing owner's IDs are intentionally unchanged:

| Product | Bundle ID |
| --- | --- |
| Host | `com.visar.galleryreader.extensiontest` |
| Gallery | `com.visar.galleryreader.extensiontest.Extension` |
| Manga | `com.visar.galleryreader.extensiontest.MangaReader` |
| KM | `com.visar.galleryreader.extensiontest.KMExplorer` |
| Stream | `com.visar.galleryreader.extensiontest.StreamViewer` |

Keep these IDs when updating the existing installation. For a different Apple
account, if Xcode cannot register these IDs, choose a unique host prefix and
update all corresponding `PRODUCT_BUNDLE_IDENTIFIER` settings in the project
(extensions must use the host prefix), plus the identifier in
`apple/Shared (App)/ViewController.swift`. That is a **new installation identity**,
not a transparent update. Free-account signing remains subject to Apple's app,
identifier and provisioning limits; rebuilding does not bypass them.

### 5. Optional Linux → Mac deployment

On the Mac, enable Remote Login and verify SSH access. Copy `deploy.example.json`
to ignored `deploy.local.json` here. Supply the SSH host, verified known-hosts
file, `/Users/<mac-user>/Developer/reader-extensions`, GUI user ID (`id -u` on the
Mac), signing Team ID, and phone UDID (`xcrun devicectl list devices`). The example
LAN address/user are examples, not required values. Nothing reads these settings
from the other reader repos.

Establish SSH trust before automation: connect once with ordinary `ssh user@host`
and compare the displayed fingerprint against the Mac's host-key fingerprint
shown locally by `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Accept only
after verification. Set `knownHosts` to that known-hosts file and configure your
SSH key/agent so `ssh -o BatchMode=yes user@host true` succeeds without a prompt.
The deployment command enforces strict host verification; it never disables it.

```sh
npm run mac -- sync
npm run mac -- build
npm run mac -- status
```

`sync` copies only Apple source, the four staged private bundles and the Mac
build launcher to the configured Mac directory. It generates an ignored
LaunchAgent plist with your settings. `build` starts a one-shot GUI-session job
so Keychain signing works even when invoked over SSH. It returns before Xcode
finishes; `status` shows job/log status. Wait for `** BUILD SUCCEEDED **` and
`LastExitStatus = 0` with no running PID before installation:

```sh
npm run mac -- install
npm run mac -- finish
```

`install` checks every embedded web file against local staged hashes and verifies
the complete app signature before calling `devicectl`. It refuses mismatched
bundles. `npm run mac -- check` runs those same checks without installing anything.
`finish` unloads the completed build job; it does not uninstall the app.
After a failed build, inspect/fix the error, unload the stopped job with `finish`,
then retry. Do not unload a running build just to start another one.

Without the deployment helper, install from a GUI Terminal on the Mac:

```sh
codesign --verify --deep --strict 'build/Debug-iphoneos/Reader Extensions.app'
xcrun devicectl device install app --device YOUR_IPHONE_UDID 'build/Debug-iphoneos/Reader Extensions.app'
```

If SSH times out before authentication, check sleep/LAN connectivity first.
The existing Hackintosh sleeps after one idle minute. A temporary
`caffeinate -i -t 1800` in a Mac Terminal can keep it awake for the build; this
does not change power settings or wake a closed/sleeping machine.

### 6. Enable and verify on the phone

In Settings → Apps → Safari → Extensions, enable each extension you use and allow
its sites. Disable its matching userscript, then reload. First-time permission
activation is not a startup timing test. Check home entries, reader/media loading,
saved progress/favorites, and native swipe Back on each provider you use.
Do not clear Safari data or delete the app as an update step. Deleting the host
can reset toggles/access; reinstalling with the same ID is the normal update.

The user currently tests with AdGuard off following a confirmed Gallery Reader
image-URL assignment slowdown. Do not "fix" that by silently introducing custom
image loading. Follow each source repo's native Safari validation notes. Personal
team provisioning expires; use [daily wireless renewal](REFRESH.md) for automatic
full signing/install with retries while the phone is unavailable or locked.

## Repository provenance and migration

The Apple project's three original commits were extracted with `git subtree split`
from `VisarDomi/gallery-reader` at `8505f74` (`extension/apple/`), then moved under
`apple/` here. Original complete history remains in that repo. No existing repo
history was rewritten. Suite orchestration and deployment documentation now live
here; each reader retains its own extension builder and behavior tests.

The current Linux checkout is `/home/visar/Documents/work/reader-extensions`;
the Mac build mirror is `/Users/visar/Developer/reader-extensions`. The old
`gallery-reader-extension` Mac directory is retained only for historical builds
and its existing inspector Python environment; it is no longer the deployment
source. Provider-specific inspector tests still belong to their source repos.

Migration validation: packaging tests passed; the relocated project built and
signed through the new GUI-session launcher, with all four embedded bundles
matching their pre-move contents. No runtime, provider state, Apple bundle ID or
phone permission change was required. This validates the existing Mac setup,
not a claim that another machine's signing account is already provisioned.
