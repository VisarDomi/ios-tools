# Native rewrite: status

Update this file at the end of every working session: tick what is done, write what is
next, note anything half-finished with where it stands. [PLAN.md](PLAN.md) has the why.

## Now

- Step 2 (Gallery Reader) built and simulator-tested; waiting only for the phone checks at
  the end. Next: step 3 (Tango local, FC2 local, SC local).

## Working rules

- Each app repository does the rewrite on a `native` branch (pushed); `main` stays what the
  phone runs until the final phone checks, then `native` merges.
- Phone checks happen once, at the very end (the owner asked); until then the simulator:
  `native/scripts/sim` (screenshots, KitTestHooks requests, install, launch). UI tests and
  WebDriverAgent cannot run on this Mac's simulator (Xcode lacks the simulator's
  `lib_TestingInterop.dylib`); KitTestHooks replaces them for simulator builds.
- Simulator builds of Gallery Reader save only what is viewed unless launched with
  `-downloads`.
- Renewal inputs change with each app (Kit, no web bundle): run `configure-refresh.py` for
  the repository and approve at the final install.

## 2026-10-11

- Surveys of all codebases saved in `inventory/` (scope, manga-reader, gallery-reader,
  gallery-downloader, video-ios, video-web, ytb).
- Plan written. Mac toolchain: Xcode 26.3, Swift 6.2.4, iOS 26.2 SDK, iOS 26.3 simulator
  runtime, 46 GB free. Phone: iOS 26.6.2.
- Before the rewrite, the same day: Gallery Reader loads images nearest the screen first and
  a relaunched reader returns to a finished list (gallery-downloader 69891ad); the video
  apps' swipes no longer stutter in long lists (video-platform 315b300). Both deployed.

## Steps

### 1. Foundations
- [x] `Kit/Package.swift`: KitCore, KitNet, KitHTML, KitImages, KitNavigation, KitLists, KitReader, KitLifecycle, KitTestHooks
- [x] `scripts/vendor-kit.py` (copy, `--check`)
- [x] Project template: gallery-downloader's `GalleryReader.xcodeproj` (synchronized folder, local Kit package, UIScene, iOS 26, Swift 6, Release)
- [x] Mac loop: `scripts/kit-test.sh` (macOS tests + iOS build), `scripts/sim` (simulator)
- [x] KitCore: durable files, background writer, debug-state dump
- [x] KitNet: client, retry policy, LocalTrust, app-owned cookie jar
- [x] KitHTML: libxml2 (`import libxml2`), XPath, CSS-subset selectors
- [x] KitImages: downsampling pipeline, nearest first, bounded memory (disk cache: per app for now)
- [x] KitNavigation: live stack, edge back, swipe forward, saved and rebuilt at launch
- [x] KitLists: thumbnail strips, pagination bar, scroll anchors
- [x] KitReader: zoomable strip, appending, image plus fraction, settling
- [x] KitLifecycle: resign versus background, background transfers (Gallery still uses its own BackgroundDownloads)
- [ ] KitVideo: viewer moved from video-platform (with step 3)

### 2. Gallery Reader (gallery-downloader, branch `native`) — parity list: inventory/gallery-downloader.md
- [x] Store kept (all files and formats); typed API instead of the web bridge
- [x] Library: rows, strips, info button, pagination in place, Favs as new screen, footer, catalog updates keep rows and place
- [x] Reader: zoomable strip, manifest sizes, tapped page at the middle, saved page exact, messages, failure text
- [x] Info sheet
- [x] Positions: view-state.json format kept; navigation.json stack; first launch migrates from view-state
- [x] Lifecycle and automatic work ported (sync, downloads, warm-up, hand-off, reclaim, idle timer)
- [x] Simulator: relaunch restores stack and exact places (library, strips, reader), back/forward keep screens, page numbers, info, zoom
- [x] Store tests pass; offline web UI and its test removed; docs updated
- [ ] Phone (end): install over the web version (data kept: 22 GB, positions), scrolling feel with thousands of thumbnails, zoom and edge swipes, Control Center versus background, downloads while locked, offline reads
- [ ] Animated GIF pages (WebKit animated them; rare)
- [ ] Renewal: configure-refresh.py, approve at install
### 3. Tango local, FC2 local, SC local (video-platform) — inventory/video-web.md, video-ios.md
### 4. Hitomi, Imhen (gallery-reader) — inventory/gallery-reader.md
### 5. Manga, six apps (manga-reader) — inventory/manga-reader.md
### 6. Video Vault (video-platform) — inventory/video-ios.md
### 7. Tango (video-platform) — inventory/video-ios.md
### 8. Ytb (km-explorer) — inventory/ytb.md
### 9. Cleanup

Each app step expands into its own checklist when it starts: screens, data migration,
providers, lifecycle, parity items from the inventory, simulator tests, phone checks,
deploy and renewal approval, docs.
