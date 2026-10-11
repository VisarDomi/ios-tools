# Native rewrite: status

Update this file at the end of every working session: tick what is done, write what is
next, note anything half-finished with where it stands. [PLAN.md](PLAN.md) has the why.

## Now

- Steps 2 (Gallery Reader), 3 (local video apps), 4 (Hitomi, Imhen), 5 (manga) and 6
  (Video Vault) and 7 (Tango) built and simulator-tested; they wait only for the phone checks
  at the end. Step 8 (Ytb) is dropped: ytboob.com and vidhost.me no longer exist (NXDOMAIN
  from public DNS, 2026-10-11; the owner: "those are dead"). Next: step 9 (cleanup), a final
  simulator sweep, then the report to the owner.
- Final deploy needs `systemctl --user restart video-server` (the Tango phone-session
  endpoint) after the native Tango is installed; `packages/auth` and `packages/server` dist
  were rebuilt from the native branch (only additions: phoneSession.js, the endpoint).
- The PC's `packages/pipeline/dist` was rebuilt from main's `ptrexPhone.ts` on purpose: the
  phone still runs the web Video Vault. After installing the native Video Vault, rebuild it
  on the native branch (`npm run build -w pipeline`) so `ptrex:connect-iphone` uses devicectl.
- Owner, 2026-10-11: page heights must be reserved before images load in every reader, so
  resume and kill-restore never jump. Done: gallery apps have sizes (Gallery Reader's
  manifests, Hitomi's galleries, Imhentai's g_th); manga uses site sizes or records them
  from the images on the phone before layout; KitReader pins a resumed page's top.

## Repositories (on this PC; Mac mirrors under ~/Developer/<name>)

| Repository | Path | Apps |
|---|---|---|
| gallery-downloader | /home/visar/Documents/work/manga/gallery-downloader | Gallery Reader |
| gallery-reader | /home/visar/Documents/work/manga/gallery-reader | Hitomi, Imhen |
| manga-reader | /home/visar/Documents/work/manga/manga-reader | six manga apps |
| video-platform | /home/visar/Documents/work/video/video-platform | Tango (+ local), FC2 local, SC local, Video Vault |
| km-explorer | /home/visar/Documents/work/video/km-explorer | Ytb |

## Working rules

- Each app repository does the rewrite on a `native` branch (pushed); `main` stays what the
  phone runs until the final phone checks, then `native` merges.
- Phone checks happen once, at the very end (the owner asked); until then the simulator:
  `native/scripts/sim` (screenshots, KitTestHooks requests, install, launch). UI tests and
  WebDriverAgent cannot run on this Mac's simulator (Xcode lacks the simulator's
  `lib_TestingInterop.dylib`); KitTestHooks replaces them for simulator builds.
- Simulator builds of Gallery Reader save only what is viewed unless launched with
  `-downloads`.
- The Mac has 8 GB and two cores: a booted iOS 26 simulator swaps it into the hundreds of
  load (SSH stalls). Boot it for one batch of checks, never leave video playing (a local
  video app restores its viewer at launch: delete viewer-checkpoint.json in the container
  first), and `xcrun simctl shutdown all` right after. Only one app may run at a time
  (KitTestHooks' port 8765). The simulator trusts the PC's mkcert CA (added with
  `simctl keychain add-root-cert`).
- Renewal inputs change with each app (Kit, no web bundle): run `configure-refresh.py` for
  the repository and approve at the final install.
- Bot checks: sites behind Cloudflare (Imhentai) challenge curl from this PC but accept
  Apple's network stack, so fixtures come from a small URLSession program on the Mac (what
  the apps use). When that is blocked too, use the agent Chromium profile
  (/home/visar/Documents/environment/browser/chromium-agent.md; close it afterwards).

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
- [x] Library is one continuous list (owner's go-ahead to fix pagination); the old page's place carries over
- [ ] Phone (end): install over the web version (data kept: 22 GB, positions), scrolling feel with thousands of thumbnails, zoom and edge swipes, Control Center versus background, downloads while locked, offline reads
- [ ] Animated GIF pages (WebKit animated them; rare)
- [ ] Renewal: configure-refresh.py, approve at install
### 3. Tango local, FC2 local, SC local (video-platform, branch `native`) — inventory/video-web.md, video-ios.md
- [x] PC server: recordings index with change feed, gzip, ETag (deployed, on main too: 0.1 s → 0.007 s, 460 KB → 59 KB)
- [x] Native list (LocalList.swift): rows as on the website, kept on the phone, change feed long-polling, highlight, pull to reload, failure view
- [x] Viewer behind ViewerHost (native list or page bridge); local recordings keep their playlist across edits; progress written on every change
- [x] One-time migration of highlight and progress from the website's localStorage (KitMigration)
- [x] Scene lifecycle, iOS 26, Kit vendored, simulator builds (`SIMULATOR=1 build-provider.py`)
- [x] Simulator: list from the feed, cached relaunch, new recording arrived through the feed
- [ ] Phone (end): FC2 and SC builds, playback through lock, edits, +/-, first-launch migration
- [ ] deploy.py install checks for local apps (no StartURL page any more), configure-refresh
### 4. Hitomi, Imhen (gallery-reader, branch `native`) — inventory/gallery-reader.md
- [x] Swift providers: Hitomi (Nozomi intersection, galleries/<id>.js, gg.js, suggestions), Imhentai (HTML); fixture tests
- [x] Phone copies: gallery details, images (one transfer per image, stopped when abandoned, 2 GB LRU), searches
- [x] Lists: favorites and search as one continuous list each; floating search header (slides away down, back on any scroll up); saved searches; suggestions; heart and info
- [x] Cached search first, background search, merge without moving the rows on screen (Hitomi replaces, Imhentai prepends new results); Imhentai pages as the end nears
- [x] Reader: strip reader, exact position per gallery, opened page's top at the middle
- [x] Details card is part of the list: open under a search started from it, back with Back and relaunch
- [x] PC: backup setup sheet and silent backups (KitBackup), favorites sync to Gallery Downloader after enrollment
- [x] One-time migration out of WebKit's IndexedDB (state and backup identity, KitMigration)
- [x] Retries: failed reader pages (backoff to 30 s), thumbnails while on screen, row details every 5 s while on screen
- [x] Simulator: backup sheet (chose Later), favorites, search, saved search, reader, relaunch stack, background merge, details through Back and relaunch
- [x] Docs (README, features, notes, PORT), deploy.py mirrors native sources; web-era evidence removed
- [ ] Phone (end): install over the web version (migration of favorites, searches, backup identity), real sites (Cloudflare on Imhentai via URLSession), swipe feel, header, suggestions with the Japanese keyboard
- [ ] Delete the web `src/` and `tests/` after phone parity; renewal configure-refresh, approve at install
### 5. Manga, six apps (manga-reader, branch `native`) — inventory/manga-reader.md
- [x] Swift providers for all six (JSON APIs; Scythe and Yaksha with libxml2); fixture tests; Asura's last page without has_more; Yaksha's missing chapter = unavailable; Scythe's coin locks
- [x] database.json kept (format, validation, v1→v3 migrations), saved chapters and lists under the web's keys, routes, image caches carry over; views.json → navigation stack once
- [x] Home: phone's catalog at once, background walk (full when incomplete or a day old, else until a page changes nothing), pull to refresh, merge keeps the screen; cards, colours, countdowns, First chapter, status, PC Load/Save
- [x] Reader: strip with appended newer chapters, statuses as footer, progress on settle, exact relaunch, idle timer off; resume at a page's top (pinned while sizes settle)
- [x] Downloads: current + next per started series (previous dropped), chapter on screen first, then most recent series, then covers; pruning after readers close; background session hand-off; background app refresh for new chapters
- [x] Page sizes before layout (site sizes, else recorded from images on the phone)
- [x] Simulator: Asura (catalog 354, resume, window move and prune, PC Load of 31 series, colours), Scythe (catalog, sizes recorded, exact relaunch), Lua (pinned resume)
- [x] Docs, deploy.py, renewal inputs, build-guest.py (providers.json, SIMULATOR=1)
- [ ] Simulator sweep at the end: Yaksha, EzScans, QiScans in the app
- [ ] Phone (end): install over the web version (progress, routes, caches kept; views.json migration), background downloads while locked, background refresh, swipe and zoom feel, PC Load/Save
- [ ] Delete the web `src/` and `tests/` after phone parity; configure-refresh for renewal, approve at install
### 6. Video Vault (video-platform, branch `native`) — inventory/video-ios.md
- [x] Vault.swift: XVideos and Porntrex uploads pages, sources (full-quality HLS master, highest MP4), labels, order, marks, two-site paging with signed-out notices; tests (scripts/test.sh) with the web suite's page shapes and a stub network
- [x] VaultList.swift: kept complete list at launch, reload behind it, notices, +/- on all three lists, viewer sources with Referer, Safari UA and the jar's cookies
- [x] Cookie jar (KitNet) instead of WebKit's store; one-time move of WebKit cookies and the login-cookie backup
- [x] XVideos sign-in sheet (WKWebView only here); cookies move into the jar once the uploads page answers
- [x] Porntrex session via devicectl inbox and result file (pipeline ptrexPhone.ts and tests); no inspector
- [x] Shared VideoList base for local apps and Vault; exact list place after a kill (Tango local checked)
- [x] SiteWorker, DownloadList, workerURL removed; providers.json `native`, project.py, deploy.py, renewal.py (renewal name kept)
- [x] Simulator: real sites signed out → both notices; sign-in sheet opens XVideos' page
- [ ] Phone (end): install over the web version (cookies move, highlight, progress), list of both sites, playback of both, +/-, `ptrex:connect-iphone` end to end (then rebuild pipeline dist), XVideos sign-in
### 7. Tango (video-platform, branch `native`) — inventory/video-ios.md
- [x] Tango.swift: list (followed, recommendations, blocklist, names), Follow, two-step Block, co-streamers; TangoSession single session owner (refresh with rotation saved first, stream tokens, playlists); tests
- [x] TangoList.swift: kept list, refresh behind it, stable order (pull or 30 min), co-streamers appended, ended/blocked removed
- [x] Login: Safari extension handoff kept (Keychain inbox, confirm), wording kept; PC shortcut button when the PC answers
- [x] PC: packages/auth phoneSession.ts (fresh profile login → new session), server POST/GET /api/tango/phone-session (key, one at a time) with tests; phone key staged into the build (Private/, gitignored) and checked at install
- [x] One-time move of the newest session out of WebKit
- [x] WebController, ViewerBridge, SiteCookies, Policy, inspector snapshot removed; RegistryTests; every app is native
- [x] Simulator: login screen; a PC-minted session → 135 live streams from the gateway; a stream played
- [ ] Phone (end): install over the web version (session moves out of WebKit), list, playback through lock, Follow/Block/co-streamers, +/-, Safari handoff, "Log in from the PC" (after restarting video-server), FC2/SC live extensions still present
- Owner, 2026-10-11: keep the Safari login extension with all its steps (Tango must work
  away from home). Add a shortcut: when the app finds a PC set up for Tango login, the PC
  logs in with a new throwaway browser profile, hands the phone the new session and drops
  the profile, so each device holds its own single refresh token (never the PC's own).
### 8. Ytb (km-explorer) — dropped
- The site and its video host are gone (NXDOMAIN). Nothing to port. For the owner: the
  installed Ytb app and its monthly renewal (`com.visar.renewal.km-explorer`) can go.
### 9. Cleanup
- [x] Ytb dropped; WebController/ViewerBridge/SiteCookies/SiteWorker/DownloadList/Policy/inspector snapshots removed; renewal inputs updated in every repository; all suites green (2026-10-11)
- [ ] After the phone checks: delete gallery-reader `src/`+`tests/`, manga-reader `src/`+`tests/`+`scripts/build-ios.mjs`, video-platform `packages/app` content builds used only by the apps (vault, tango-live)
- [ ] After the phone checks (one release later): remove the one-time migration readers (WebKit IndexedDB, cookies, views.json, view-state.json)
- [ ] Merge each `native` branch into main, `configure-refresh.py` per repository, approve renewals at install

## Hand-over to the owner (2026-10-11)

Deploy order when the phone is here (install over the same bundle IDs; never uninstall):
1. gallery-downloader: Gallery Reader. gallery-reader: Hitomi, Imhen. manga-reader: asura,
   scythe, yaksha, qiscans, lua, ezmanga. video-platform: tango, fc2, sc (local), vault,
   tango-live. Each: `deploy.py sync`, `build`, `install`.
2. After Video Vault: `npm run build -w pipeline` on the native branch, then
   `npm run ptrex:connect-iphone` (devicectl inbox) end to end.
3. After Tango: `systemctl --user restart video-server` (phone-session endpoint), then
   "Log in from the PC" on the phone (or the Safari handoff).
4. Phone checks: the "Phone (end)" items of steps 2–7 above.

Decisions for the owner (defaults applied until answered):
- Continuous lists instead of page numbers in Gallery Reader, Hitomi, Imhen (positions are
  anchors; the search header floats back with any scroll up).
- Pinch zoom on list screens: off (readers and videos zoom).
- The Ytb app and its monthly renewal can be removed (site gone).

Each app step expands into its own checklist when it starts: screens, data migration,
providers, lifecycle, parity items from the inventory, simulator tests, phone checks,
deploy and renewal approval, docs.
