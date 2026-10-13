# Native iPhone apps and NativeKit

Every custom iPhone app is a native UIKit app (since October 11, 2026). This folder holds
what they share: **NativeKit** (`Kit/`, a Swift package) and the scripts to test and measure
them (`scripts/`). Each app repository documents its own apps in `apps/ios/README.md`; read
that and this file before changing an app.

| Repository (this PC; Mac mirror `~/Developer/<name>`) | Apps | App doc |
|---|---|---|
| `/home/visar/Documents/work/manga/manga-reader` | Asura, Scythe, Yaksha, QiScans, Lua, EzScans | `apps/ios/README.md` |
| `/home/visar/Documents/work/manga/gallery-reader` | Hitomi, Imhen | `apps/ios/README.md` |
| `/home/visar/Documents/work/manga/gallery-downloader` | Gallery Reader (offline, from the PC) | `apps/ios/README.md` |
| `/home/visar/Documents/work/video/video-platform` | Tango local, FC2 local, SC local, Video Vault, Tango | `apps/ios/README.md` |

Not native, on purpose: Twitter (an x.com wrapper), Maid Heroes (a Unity WebGL game), World
Rumble (App Store); Deep Town was native already. The Safari Web Extensions (Tango Login,
FC2 live, SC live) live inside the Tango app. Ytb (km-explorer) was dropped: its site is gone.
Mac and phone access, signing and the phone's UDID:
[mac-access.md](../../../environment/mac-access.md). Renewal: [renewal](../renewal/README.md).

## What every app must do (the owner's rules)

- **Instant, offline where possible, kill-robust.** Every change of state (position,
  progress, navigation, downloads) is written durably and atomically when it happens, in the
  background (`BackgroundWriter`); leaving for the background waits for pending writes. A
  kill, a power-off or iOS ending the app loses nothing.
- **Relaunch to the exact screen, first frame included** (cold and warm). Kept data is read
  before the first frame; images already on the phone decode before it
  (`ImagePipeline.beginRestore`); lists go straight to their anchor
  (`ScrollAnchoring.restore`, no layout needed); the screens below the top are rebuilt after
  the first frame (`LiveNavigation`). Test with `restore-check` (below).
- **The main thread only shows.** Parsing, merging, comparing lists, describing rows,
  decoding, file I/O and system calls that wait (the audio session's activation and
  deactivation, JPEG encoding, JSON encoding of long lists) run elsewhere; the main thread
  sets the result. A list that changes while a finger or momentum moves it waits until it
  stops (setting the offset stops a fling dead). Work goes by priority: what is on screen
  first (high), the nearest next, everything else eventually (low, a few at a time); a
  screen being read outranks the screens under it. Measure it (FrameMonitor, below): the
  goal is no frame over 25 ms while anything scrolls.
- **Show the phone's copy, then become consistent.** A list shows what the phone has at
  once, refreshes in the background and merges without moving the rows on screen.
- **Page heights are known before images load** (site sizes, or sizes recorded from the
  images on the phone), so resuming never jumps.
- **Never uninstall an app to update it**: install over the same bundle ID (uninstalling
  loses the data and the sessions).

## NativeKit

UIKit, built in code, UIScene, iOS 26, Swift 6 with strict concurrency (video-platform builds
in Swift 5 mode), no third-party packages.

| Module | What it owns |
|---|---|
| `KitCore` | Durable files, `BackgroundWriter`, `DebugState` (debug-state.json), `FrameMonitor`, logging |
| `KitNet` | URLSession client, retry policy, `LocalTrust` (the PC's CA), the app's own cookie jar |
| `KitHTML` | libxml2 HTML documents, XPath and a CSS-selector subset |
| `KitImages` | `ImagePipeline`: decoding to display size off the main thread, on screen first, ahead at low priority, the relaunch window |
| `KitNavigation` | `LiveNavigation`: screens stay alive, edge back, swipe forward, the stack saved and rebuilt at launch |
| `KitLists` | Thumbnail strips, scroll anchors, the pagination bar |
| `KitReader` | `StripReaderView`: the zoomable vertical page strip, appending, place as page plus fraction, tall pages as slices |
| `KitLifecycle` | Resign versus background, background transfers |
| `KitTestHooks` | Simulator builds only: a local HTTP server that drives the app (below) |
| `KitMigration` | One-time readers of what the WebKit versions kept (see Open items) |
| `KitBackup` | The PC backups of the apps' own data |

**Vendoring.** `Kit/` here is canonical. Each repository builds its own copy, `apps/ios/Kit`
(renewal fingerprints only files inside a repository):

```sh
python3 scripts/vendor-kit.py <repository> [...]          # copy (replaces the old copy)
python3 scripts/vendor-kit.py --check <repository> [...]  # exit 1 when a copy differs
```

Every repository carries the same Kit: after changing it, vendor it into all four, build
and deploy the apps that changed (their renewal inputs change; installing with the deploy
script approves them).

**Renewal inputs.** Each repository's `apps/ios/scripts/renewal.py` lists the files an app
is built from (its sources, `Kit`, project and build scripts). They are fingerprinted at
approval, and a changed input blocks the unattended monthly renewal until the app is
deployed again. So never leave an input changed without deploying it, not even a comment;
docs outside those paths are free to change. `scripts/kit-test.sh` runs the macOS tests (KitCore, KitNet, KitHTML) and the iOS
build of every module on the Mac.

## Measuring on the phone: FrameMonitor

Instruments cannot record this phone, so the apps measure themselves. Wrap main-thread work
in `FrameMonitor.shared.measure("label") { ... }` and report scrolling with
`FrameMonitor.shared.scrolling(true/false)` (scroll views' drag and deceleration callbacks).
While anything scrolls, every frame over 25 ms is kept with the spans that ran in it; spans
are counted always. The apps write the report into debug-state.json ("frames") when they
leave the screen. Read it from this PC:

```sh
scripts/frames <bundle id> '<data folder>'   # folders: see the script's header
```

A long frame with no span of ours is the system's: Core Animation's commit, a large image
uploaded, a new player layer. The spans already in the apps name their work (`list.*`,
`reader.*`, `viewer.*`, `open.*`, `close.*`, ...); keep new work inside a span.

## Simulator

The Mac (8 GB, two cores) is slow with a booted iOS 26 simulator (an iPhone 17 Pro Max,
`960E5E0A-15C3-423E-B196-1206C66B28E9`): boot it for one batch of checks and
`xcrun simctl shutdown all` afterwards.

- **Never play video in the simulator.** It decodes in software here and drives the Mac's
  load past 300 within minutes. A local video app restores its viewer at launch: delete
  `viewer-checkpoint.json` in its container first.
- UI tests and WebDriverAgent cannot run on this Mac's simulator; `KitTestHooks` replaces
  them (simulator builds only; one app at a time, port 8765):
  `/state`, `/tap?x=&y=`, `/scroll?y=[&x=][&at=x,y]`, `/back`, `/forward`, `/zoom?scale=`,
  `/action?name=`, `/layout` (what is on screen, with frames), `/timeline` (the layout at
  the first frames after launch).
- `scripts/sim`: `shot`, `hook`, `install`, `launch`, `terminate`, `container`.
- `scripts/restore-check <bundle> [--warm]`: the fast relaunch test (the layout before a kill
  against the app's first frames after it). `scripts/restore-video.sh` (on the Mac) plus
  `scripts/restore-frames.py` (here): the slow, visual one, frame by frame.
- The simulator trusts the PC's mkcert CA. Gallery Reader's simulator builds save only what
  is viewed unless launched with `-downloads`.
- Sites behind Cloudflare (Imhentai) challenge curl from this PC but accept Apple's network
  stack: take fixtures with a small URLSession program on the Mac, or the agent Chromium
  profile (`/home/visar/Documents/environment/browser/chromium-agent.md`; close it after).

## Deploying

From the app's repository on this PC, three steps (sync, build, install):

| Repository | Command |
|---|---|
| manga-reader, gallery-reader | `python3 apps/ios/scripts/deploy.py <step> <app>` |
| video-platform | `python3 apps/ios/scripts/deploy.py <app> <step>` |
| gallery-downloader | `apps/ios/scripts/deploy.sh [<step>]` (all three by default) |

It syncs to the Mac, builds signed there, installs over the same bundle ID on the phone
(paired with the Mac over Wi-Fi) and approves the build as its renewal baseline. Each app
doc has its details. The owner usually tests each app as soon as it appears on the phone,
so deploy the app the change is about first.

## Open items

- Remove the one-time migration readers (`KitMigration`'s WebKit storage reader and the
  apps' moves of cookies, `views.json` and `view-state.json`): the phone ran them on
  October 11, 2026.
- Gallery Reader: animated GIF pages show their first frame (WebKit animated them; rare).
- The owner's standing defaults: continuous lists instead of page numbers (Gallery Reader,
  Hitomi, Imhen); no pinch zoom on list screens (readers and videos zoom). The installed Ytb
  app and its renewal (`com.visar.renewal.km-explorer`) can be removed.

The rewrite's plan, its surveys of the WebKit apps and its round-by-round status are in Git
history (`git show 65bec79:native/STATUS.md`, `PLAN.md`, `inventory/`).
