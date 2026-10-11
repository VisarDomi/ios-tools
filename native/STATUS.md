# Native rewrite: status

Update this file at the end of every working session: tick what is done, write what is
next, note anything half-finished with where it stands. [PLAN.md](PLAN.md) has the why.

## Now

- Step 1, foundations: not started.

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
- [ ] `Kit/Package.swift` with KitCore, KitNet, KitHTML, KitImages, KitNavigation, KitLists, KitReader, KitLifecycle, KitVideo
- [ ] `scripts/vendor-kit.py` (copy, `--check`)
- [ ] Project template (synchronized folders, UIScene, iOS 26, xcconfig per provider)
- [ ] Mac loop script: sync, `swift test`, simulator build, UI test, screenshots
- [ ] KitCore: durable files, JSON store, debug-state dump
- [ ] KitNet: client, retry policy, LocalTrust, cookie jar, PC client
- [ ] KitHTML: libxml2 module map, document, XPath, CSS-subset selectors
- [ ] KitImages: disk cache, downsampling, memory cache, priority loader, retry
- [ ] KitNavigation: live stack, edge back, swipe forward, state save and restore
- [ ] KitLists: strip rows, grids, rows; anchor plus fraction; strip offsets
- [ ] KitReader: zoomable strip, appending, image plus fraction, settling
- [ ] KitLifecycle: resign versus background, background session hand-off
- [ ] KitVideo: viewer moved from video-platform (video apps keep working)

### 2. Gallery Reader (gallery-downloader) — parity list: inventory/gallery-downloader.md
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
