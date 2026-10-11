I've read the whole Ytb app: all 5 Swift files, every file in `src/`, the tests, the build/deploy/renewal scripts, the PC backup server, the docs and verification files, the git history, the sibling `km-cache` repo and the ios-tools renewal setup. All paths are under `/home/visar/Documents/work/video/km-explorer/` unless written in full.

The repo has no `notes/`, `decisions.md` or `features.md`. The design docs are `README.md`, `notes.md`, `flow.md`, `test.txt`, `apps/ios/PORT.md`, `apps/ios/ROBUSTNESS.md` and `server/BACKUPS.md`.

**Two things to know first:**
- **The new position saving is probably not on the phone.** The `ke-video-time` change (commit c793c5e, Oct 11) is not in the prepared bundle `apps/ios/build/Web/app.js` (dated Oct 4; it doesn't contain the string). There is no verification record for it.
- **The app owns almost none of its behaviour.** WebKit provides the Back gesture, history, page caching (bfcache), video decoding, zoom, storage and the background/lock behaviour. Details are in section 7.

---

## 1. Architecture

**Native Swift: 372 lines, a thin host.**
- `apps/ios/Ytb/AppDelegate.swift` (19 lines)
  - Creates a dark window with `WebController` as root (lines 8-15).
  - `applicationWillResignActive` calls `capturePosition()`, `didEnterBackground` calls `pause()` (which does the same thing), and `didBecomeActive` calls `resume()`, which is empty (lines 16-18).
- `apps/ios/Ytb/WebController.swift` (161 lines)
  - Full-screen WKWebView (lines 27-43) with:
    - the `ytb` scheme handler and a `ytb` message handler (28-29);
    - `allowsInlineMediaPlayback = true` (30);
    - `mediaTypesRequiringUserActionForPlayback = []` (31);
    - `ignoresViewportScaleLimits = true` (32);
    - `allowsBackForwardNavigationGestures = true` (34) and `isInspectable = true` (35);
    - status bar and home indicator hidden (23-24);
    - initial load of `ytb://app/` (43).
  - `capturePosition()` runs `window.ytbViewState?.save()` in the page (50-52).
  - The message handler (55-125) accepts only main-frame requests from `ytb://app`. Commands:
    - `fetch` and `fetch-cancel`: the network proxy (66-80);
    - `init`: route position plus relaunch redirect/resume logic (85-108);
    - `activate` (109-111);
    - `view-save`: accepted only from the active document (112-116);
    - `clipboard`: writes `UIPasteboard` (117-120).
  - Navigation policy allows only `ytb://app` (126-130).
  - `webViewWebContentProcessDidTerminate` calls `webView.reload()` (131).
  - `LocalFiles` is the `WKURLSchemeHandler` (137-161).
- `apps/ios/Ytb/YtbStore.swift` (38 lines)
  - Reads and writes `view.json`; saves are atomic (9-23).
  - Wraps responses as base64 JSON for the bridge (24-28).
  - Serves `/app.js`, `/style.css` and `index.html` for any route that `ViewPosition.route` accepts (29-37).
- `apps/ios/Ytb/YtbAPI.swift` (85 lines)
  - URLSession: 25 s request / 90 s resource timeouts, 12 connections per host, 8 MB memory / 64 MB disk URLCache (51-54).
  - Picks a waits-for-connectivity session when offline, using NWPathMonitor (58-60, 77).
  - Only `https` is allowed (64). Every request gets `Referer: https://ytboob.com/` (68-69).
  - `LocalTrust` pins the bundled mkcert CA, but only for the PC host (5-32).
- `apps/ios/Ytb/Models.swift` (69 lines)
  - `ViewPosition.route` route classifier (6-19).
  - `ViewState {lastPath, libraryPath, positions}` (24-28).
  - Retry policy: GET/HEAD and the Typesense POST retry on transient URLErrors and HTTP 408/429/5xx, with backoff from 1 s up to 30 s and `Retry-After` honoured. A missing host gets at most 3 attempts (37-69). The PC is never retried.

**Web (TypeScript in `src/`): 1,977 lines of TS plus 261 lines of CSS.** Built with esbuild into a single 44.5 KB `app.js` (target `safari17`). The worker is inlined as a string and the CSS is inlined via `?inline` (`apps/ios/scripts/build.mjs:16-27`). `index.html` is one line; `style.css` is an empty placeholder.
- Entry point: `src/app/app.ts`, which handles lifecycle, view checkpoints and route dispatch (44-49).
- Routes: `src/routes/favs.ts` (Favorites `/`), `search.ts` (the numbered listing pages; it is **not** a text search), `channel.ts` (`/actor/<slug>`), `video.ts`.
- UI: `src/ui/video-card.ts`, `pagination.ts`, `navigation.ts`, `shell.ts`, `video-gesture.ts`.
- Recovery: `src/app/media-recovery.ts`, `image-recovery.ts`.
- Storage runs in a blob Web Worker: `src/core/compute/transport.ts`, `worker-entry.ts`, `database.ts`.
- PC backups: `src/core/backup-engine.ts` (worker side), `pc-backup.ts` (UI).
- Provider: `src/provider/ytb.ts` (219 lines), the only content provider.

**Bridges.**
1. **Message handler with reply** (`src/app/native.ts:1-3`): `webkit.messageHandlers.ytb.postMessage({command,args})`, reply parsed with JSON.parse.
2. **Fetch proxy** (`src/app/fetch.ts:2-33`): `globalThis.fetch` is replaced. Every `https://` request goes to native `fetch` with a UUID request ID. Aborting or `pagehide` sends `fetch-cancel`. The response body comes back base64 (line 25).
   - In the worker, `src/app/worker.ts:5-8` patches fetch too and relays through the main thread (`transport.ts:30-35`), then to native.
3. **Scheme handler**: `ytb://app/<route>` always serves the bundled `index.html`. Site scripts never run.
4. **Native calling JS**: `evaluateJavaScript("window.ytbViewState?.save()")`.

**Other code:** tests 312 lines, scripts 140 lines, PC server 228 lines (`server/backups.mjs` plus its test).

## 2. Where content comes from

| What | Source | Code |
|---|---|---|
| Listing (newest first) | Typesense `POST https://ts-api.ytboob.com/multi_search?x-typesense-api-key=2mFxuIpLuESx5X1aPGkDOx4ZAtM5jG46` (public search-only key), body `Content-Type: text/plain`, `collection:'post', q:'*', sort_by:'sort_by_date:desc', per_page:12`, fields `permalink,post_thumbnail,post_id` | `src/provider/ytb.ts:4,13-25,50-69` |
| One client page | 50 parallel Typesense POSTs = 600 videos. No listing cache: every listing load re-fetches all 50 | `ytb.ts:71-75,189-198`; `search.ts:26` |
| Page count | `ceil(found/600)` from page 1 | `ytb.ts:200-203` |
| Favorites / ID lookup | Typesense `filter_by: post_id:=[…]`, in chunks of 100 | `ytb.ts:77-101`; `src/core/videos.ts:5-26` |
| Thumbnails | `post_thumbnail` with the WordPress `-WxH` suffix stripped, so the **full-size original** is loaded. Loaded by WebKit `<img loading=lazy>` directly, not through the bridge | `ytb.ts:27-29`; `video-card.ts:69-72` |
| Video page / source | GET `https://ytboob.com/<slug>/` HTML, regex for `<meta itemprop="contentURL" content=…>`, falling back to `https?://vidhost.me/videos/…`. Actor links are taken from the `<a href=…/actor/…>` regex | `ytb.ts:103-130` |
| Actor (channel) | `GET /wp-json/wp/v2/actors?slug=` gives the term ID, then `GET /wp-json/wp/v2/posts?actors=<id>&per_page=12&page=N` sequentially until the `X-WP-TotalPages` header says stop. Only IDs are kept; stubs come from Typesense | `ytb.ts:132-161`; `src/core/actor-videos.ts:14-30` |
| Playback | `<video src=videoSrc>`, loaded directly by WebKit/AVFoundation (vidhost.me) | `video.ts:35-43` |
| PC backups | `https://192.168.1.197:7733/api/reader-backups/ytb/ytboob[/<uuid>]`, header `X-Reader-Backup-Key` | `backup-engine.ts:45-65`; `server/backups.mjs` |

- **Playback format:** the code just uses one URL from `contentURL` (test fixtures use `.mp4`). There is no HLS or DASH handling, no URL signatures, no cookies and no custom media headers.
  - Media and thumbnail requests carry whatever User-Agent and Referer WebKit sends from a `ytb://` document. The app sets neither.
  - Bridged requests use URLSession's default UA (`Ytb/… CFNetwork`) with the forced Referer `https://ytboob.com/`.
  - Unsupported codecs give a media error, which shows Copy for KMPlayer (`video.ts:63`).
- **No JS engine or browser is needed for any content.** Everything is JSON APIs plus regex over HTML. Nothing executes site JavaScript.
- **No anti-bot handling at all.** Risk: the retired `km-cache` sibling (`/home/visar/Documents/work/video/km-cache`, "end of life commit" 755bc14) needed Cloudflare `cf_clearance` solving with a headed Chromium for ytboob.com (`km-cache/decisions.md`, "Cloudflare solve uses a visible browser"; `packages/server/src/utils/cloudflare.ts`). If Cloudflare challenges come back, a native URLSession client breaks the same way the current one would.
- **km-cache is not used.** Ytb doesn't reference it; grep finds no "km-cache" anywhere in the video folder. Its only server is its own `server/backups.mjs`: systemd user unit `server/km-explorer-backups.service`, mkcert TLS from `~/.local/share/mkcert/pwa`, data and key in `~/.local/share/km-explorer/backups/`.

## 3. Every user-facing feature and behaviour

**Screens.** All are documents at `ytb://app/...`; each navigation loads a new document.
- **Favorites `/`** (`src/routes/favs.ts`)
  - One unpaged grid of all favorites, newest first (89-114).
  - Pagination bar above and below: a red "Favs" button, then 1..N once the count loads (106, 109-113).
  - "Import / Merge" panel: a textarea for IDs separated by space, newline or comma; Merge reports "Added X of Y IDs". "Export" just fills the textarea with the IDs, one per line; there is no file or clipboard export (24-87).
  - PC backup runs here (104).
  - Favorites missing from Typesense silently disappear from the grid but stay stored (`videos.ts:23-25`).
- **Listing `/page/N/`** (N ≥ 2) (`src/routes/search.ts`)
  - One client page = 600 videos. Site pages are 30 videos, so 20 site pages map to one client page (`ytb.ts:6-11,205-213`).
  - Client page k links to `/page/{(k-1)*20+1, min 2}/`.
  - Positioning: saved IndexedDB scroll, else `scrollIntoView` of the card at index `(sitePage-1)*30-(clientPage-1)*600` (42-47).
- **Actor `/actor/<slug>`** (`channel.ts`): cached grid, then a fresh fetch. **No UI links to this route.** It is reachable only by URL or by restoring an old `view.json`.
- **Video `/<slug>/`** (`video.ts:199-252`)
  - Shows "Loading video…" (202-205); detail comes from IndexedDB, else it is scraped and cached (17-26).
  - Error states: "Could not load this video's source: … Reload to retry." (there is no reload control in the app) and "No video source is available."
  - Player plus the grid of the first actor's videos (cached first, then always re-fetched). The current video is outlined `.selected` and can't be tapped (175-197, 234-251).

**Cards** (`video-card.ts:53-106`)
- Thumbnail only: no titles, no durations.
- Heart toggle in the top-right; toggling writes immediately (74-93).
- Tapping a card awaits a `highlight-save` of `{id,pageUrl}` and then navigates (95-104).
- The last-opened card gets a blue outline (`.ke-returned-card`). On a fresh (non-cached) load it is centered once per document (22-28).
- When a page comes back from bfcache, busy flags are cleared and the highlight re-synced (37-50).
- Layout: 2 columns, or 4 at ≥ 768 px (landscape) (`style.css:54-63`), 16:9 cards.

**Player** (`video.ts:28-157`; `style.css:168-261`)
- `<video>` attributes: `autoplay`, `muted`, `playsInline`, `controls=false`, `preload=auto`. Full width, max height 75vh, `object-fit: contain`.
- Time display "MM:SS.mmm / MM:SS.mmm", with HH added past an hour (159-173). Monospace, 18 px, bold.
- 100 px-tall progress bar. Seeking happens **only on pointerdown at the tapped ratio**; dragging the bar does nothing (133-139).
- Play/pause button (emoji U+23F8 / U+25B6) and mute button (U+1F507 / U+1F50A). Playback always starts muted, and mute state is never saved.
- Copy overlay: shown on `error`, hidden on `playing`. Tapping copies through native `UIPasteboard` and shows "Copied" or "Copy failed — tap to retry" (47-64).
- **Swipe gesture** (`src/ui/video-gesture.ts`):
  - One finger, horizontal after an 8 px threshold: scrubs 60 s per viewport width from the start position, setting `currentTime` on every touchmove with `preventDefault`. On release it calls `play()`.
  - Vertical movement goes to page scroll. Multi-touch goes to the browser (pinch). Touches starting within 28 px of the left edge go to WebKit's Back swipe (lines 1-3, 11-47).
- **Zoom:** there is no custom zoom. It is WebKit pinch-zoom of the whole page, enabled by `ignoresViewportScaleLimits` (WebController 32) and `.ke-video { touch-action: pan-y pinch-zoom }` (`style.css:178`). The progress bar uses `touch-action: manipulation` (207). Zoom is never saved.
- **Media recovery** (`media-recovery.ts`):
  - Network errors (MEDIA_ERR_NETWORK, or offline) are swallowed with `stopImmediatePropagation` at document capture, so Copy does not appear (47-50).
  - Recovery reloads the same element with `load()`, keeping time, mute and pause choice, with backoff from 1 s to 30 s.
  - A stall (`waiting`/`stalled` while playing, no progress for 15 s and readyState < 3) triggers a reload (51-59).
  - Recovery holds while the page is hidden or offline and resumes on `online`, `pageshow` or becoming visible (62-66).
  - Failed thumbnails retry the same way (`image-recovery.ts`).
- **Recent `ke-video-time` change** (`video.ts:222-229`):
  - On `visibilitychange` to hidden, `localStorage['ke-video-time:'+videoUrl] = currentTime`. The key is the full `https://ytboob.com/<slug>/` href.
  - On the next load of that video, it seeks there on the first `loadedmetadata`, if the value is > 0.
  - Keys are never cleared, even after a video finishes, so they grow without limit.
  - It applies to any later open of that video, not just reloads. If WebKit fires `visibilitychange` when navigating away (the spec says it should), it saves on navigation too.

**Lock / background**
- Native only checkpoints scroll position (AppDelegate 16-18). `resume()` does nothing.
- There is no `UIBackgroundModes` (Info.plist) and no AVAudioSession, Now Playing or `isIdleTimerDisabled` code. Pausing on lock, whether playback resumes on return, the audio category and display-sleep prevention are all decided by WebKit.
- When WebKit pauses the video, media-recovery records `playing=false`, so the app never auto-resumes.
- If the WebContent process dies, the page reloads (WebController 131). Scroll comes back from `view.json` and video time from `ke-video-time`; the video starts muted and autoplays.

**Position memory: three overlapping mechanisms**
1. Native `view.json`, saved on `scrollend`, `pagehide`, resign-active and background (`app.ts:17-20`). It stores `{path,y}` per route plus lastPath/libraryPath. Restore happens 3 animation frames after render, unless the user has already touched, scrolled or typed (`app.ts:30,52-53`).
2. IndexedDB `preferences.scroll[pathname]`, listing pages only, saved on `scrollend` (`search.ts:10-16,42-50`). **Its pagehide save never does anything:** the transport's earlier pagehide listener sets `active=false`, and `compute('scroll-save')` then resolves without writing (`transport.ts:12-13,22`).
3. Centering the highlighted card (`video-card.ts:22-28`).
- Scroll is stored as a y offset in CSS px, so it depends on layout and orientation (2 vs 4 columns).

**Relaunch restore** (WebController 92-107, `app.ts:33-59`)
- On the first `init` after launch, if lastPath was a video:
  - the library loads first (via a `location.replace` redirect if needed);
  - after it renders, a hidden `<a>` is clicked to push the video on top.
  - Result: a 2-entry history of library then video ("history length 2" in `verification.json`).
- Otherwise it redirects to lastPath.
- The library document stays non-`ready` so it can't overwrite lastPath. `view-save` is ignored from any document that isn't active.

**Back navigation**
- The only mechanisms are WebKit's edge swipe back and **forward** (`allowsBackForwardNavigationGestures`). There is no Back button (`notes.md`: "No custom Back control, pushState router, or synthetic history entries").
- Card taps and pagination buttons (including "Favs") push entries by clicking a hidden link (`navigation.ts:3-14`). Related videos use `location.replace` (`video.ts:186`).
- Restoring a page from bfcache: `pageshow` with `persisted` set; a page whose render was interrupted is reloaded instead (`app.ts:21-28`).

**Other:** forced dark mode; portrait plus landscape; status bar hidden.

**PC backup UI** (`pc-backup.ts`)
- The first time the PC is reachable, a modal offers "Back up this phone", "Restore from PC" (choose a phone and its current/previous snapshot) or "Later".
- After that, every home visit and every bfcache return to home uploads the **entire** snapshot silently (`navigator.locks` with a fallback, 105-118).
- Errors show a sticky toast. An unreachable PC is silent (`backup-engine.ts:57-58`).

## 4. Persisted data and what to migrate

| Store | Location | Contents | Migrate? |
|---|---|---|---|
| IndexedDB `ytb` v5, origin `ytb://app` (WebKit default persistent data store) | `database.ts:3-9,61-78` | `videos` {id,thumbnail,pageUrl}; `details` {pageUrl,videoSrc,actors[]}; `channels` {actorUrl,termId,videoIds[]}; `preferences['state']` = {favorites: string[] newest first, highlight {id,pageUrl} or null, scroll {pathname: y}} | **favorites: must** (503 at last check); highlight and scroll: nice to have; caches can be rebuilt (in Sept: 12,633 videos, 4,966 details, 105 channels) |
| IndexedDB `ytb-pc-backup-state-v1`, store `identities`, key `ytb:ytboob` | `backup-engine.ts:12-42` | {id uuid, label, revision} | Yes, to keep writing to the same PC backup file (otherwise re-enroll) |
| localStorage | `video.ts:224-228` | `ke-video-time:<url>` = seconds | Yes, if the new build was ever deployed |
| Native `Library/Application Support/Ytb/view.json` | `YtbStore.swift:9-23` | {lastPath, libraryPath, positions{"library:/…"/"video:/…": {path,y}}} (grows without limit) | Yes (already native) |
| URLCache (64 MB) and shared HTTPCookieStorage | `YtbAPI.swift:54` | HTTP cache | No |

- The `migrate` worker op can read legacy localStorage keys (`ytb-favorites-v1`, `ke-card-highlight`, `ke-scroll*`), but the app calls it with `{}` (`initialize.ts:6`; `database.ts:293-299`), so that path is dead.
- The 503 favorites reached the app by a manual merge (`verification.json`: "legacyBackup").
- **Ready-made migration source:** the PC snapshot `~/.local/share/km-explorer/backups/ytb/ytboob/<uuid>.json`. Format: `{id,label,current:{revision,savedAt,data:{version:1,indexedDB:{videos,details,channels,preferences}}},previous}` (`server/backups.mjs:78-96`). It contains all four stores but not `ke-video-time` or `view.json`. The in-app Export (ID text) is a second route for favorites.
- Reading the WebKit IndexedDB files directly would mean parsing WebKit's internal serialization format.
- Installing over the same bundle ID keeps the app container.

## 5. Tests, build, deploy, renewal

**Tests**
- `npm run test:ios` runs:
  - `tsc` over `src`;
  - `apps/ios/Tests/boundaries.mjs`: a storage-init retry test, despite the name;
  - `Tests/app.mjs`: Playwright **desktop WebKit** with a mocked bridge, served at `https://ytb.test`, **not** `ytb://`. It fakes pagehide/pageshow by dispatching synthetic `PageTransitionEvent`s (110-112, 151-156), so real bfcache is never tested;
  - `media-recovery.mjs` and `image-recovery.mjs`.
- `apps/ios/scripts/test-network.sh` compiles `Models`, `YtbAPI`, `YtbStore` with `Tests/NetworkTests.swift` using `swiftc` on the Mac.
- `Tests/Routes.swift` is run by hand, concatenated with `Models.swift`; no script runs it, and there is no XCTest target.
- `npm run test:server` runs 3 node tests.
- Device checks use the ios-tools Web Inspector (`isInspectable`) with `scripts/inspector-snapshot.js`.

**Build and deploy**
- `npm run build:ios -- --prepare-only` (Linux) writes `apps/ios/build/Web`. It embeds `__READER_BACKUP_URL__` and the private key from `~/.local/share/km-explorer/backups/access-key` (`build.mjs:11-13`).
- `deploy.py sync|build|install` (`apps/ios/scripts/deploy.py`):
  - Mac `visar@192.168.1.198`, mirror `/Users/visar/Developer/km-explorer/apps/ios`, device `00008101-000639912881401E`, team `65U58U86DD`.
  - `build` runs `build-native.py` attached in the GUI session; it copies `build/Web` into `Resources/Web` and runs `xcodebuild`.
  - `install` checks bundle, name, no icon, signature, team, device and expiry more than 45 days out, then calls `deliver.py installed`.

**Identity** (`project.pbxproj:26-34`, `Resources/Info.plist`)
- Bundle `com.visar.Ytb.paid`, display name "Ytb", no icon.
- iOS 17.0, iPhone only, Swift 5 with strict concurrency, build 4, marketing version 1.0.
- Info.plist has `BackupServerURL` `https://192.168.1.197:7733`, `NSAllowsLocalNetworking` and `NSLocalNetworkUsageDescription`.
- The Swift fallback URL uses the old port 7777 (`WebController.swift:17`).

**Renewal**
- LaunchAgent `com.visar.renewal.km-explorer`, monthly. Shared runner: `/home/visar/Documents/work/ios-tools/renewal/PAID-REFRESH.md`.
- Config: `/home/visar/Documents/environment/mac-renewal/renewal/km-explorer/config/ytb.json`.
- **Renewal inputs** (`apps/ios/scripts/renewal.py:71-72`): `Ytb`, `Ytb.xcodeproj`, `Resources/Info.plist`, `Resources/LocalCA.cer`, `build/Web`, `scripts/build.sh`, `scripts/build-native.py`. A rewrite changes these, which blocks unattended renewals until a new build is deployed and approved; then re-run `configure-refresh.py`.
- Last recorded renewal: 2026-09-22, next due 2026-10-22, profile expires 2027-09-22 (`robustness-verification.json`).
- The verification JSONs (builds 2-4) record a 503-favorite cold restore, Back, muted inline playback and network recovery. Limits noted there: one video tested, "No physical scrubbing/gesture smoothness measurement".

## 6. Requirements the owner stated

- `README.md`:
  - "Ytb, an iOS app that overhauls the ui of ytboob"
  - "UX of site itself is not good enough"
  - "Cache the urls in indexeddb so that navigation is faster"
  - "use the copy button and paste the link in KMPlayer in ios to watch videos the app can't play."
- `test.txt` ("Frozen critical behavior"):
  - "Every favorite is rendered in one grid, newest first… not divided into pages"
  - "One client listing page contains up to 600 provider videos"
  - "pagination appears above and below"
  - "Red `Favs` appears in the page-0 position"
  - "One Back swipe restores the listing from bfcache… retains its DOM, active client page, ready-card state, and exact viewport position"
  - "A normal listing reload highlights and centers the stored card; bfcache restoration never performs that centering"
  - "The video has no native controls… starts muted… Precise current-time and duration numbers… A one-finger horizontal swipe on the video scrubs by 60 seconds per viewport width and resumes playback on release… Vertical movement, multi-touch, and a swipe beginning in the 28px leading-edge Back area remain WebKit-owned… Icon-only play/pause and mute/unmute"
  - "The page does not automatically scroll after opening"
  - "Every video has exactly one actor… No actor selector"
  - "Further actor-video selections continue replacing… One Back swipe from any replacement video returns directly to the original Favorites or listing page"
  - "Shared routing and UI do not import ytboob-specific operations directly"
- `flow.md` ("Gold Standard Flow"):
  - "Thumbnail click → immediately navigate…; no detail fetch or clipboard work"
  - "media failure shows Copy over the video, and only a tap copies"
  - "Repeat video replacements → one Back swipe returns to the original Favorites/listing bfcache entry"
- `notes.md`:
  - "There is no automatic clipboard write. Only a media error reveals a **Copy** button… success says **Copied**, rejection says **Copy failed — tap to retry**. Working playback has no copy UI."
  - "PC backups include all four stores, never video media or cookies"
- `PORT.md`:
  - "Display/product/target: **Ytb**, no custom icon."
  - "installs over the existing app, keeping its data"
  - "never substitute an accept-all TLS handler"
  - "An unavailable PC stays silent."
  - "A video resumes where it was when the app last went away"
  - Also: "There is no VLC, AVPlayer, media download or codec workaround." This describes the current app and conflicts with the new native-AVPlayer goal.
- Owner commit messages: "play video on the 'actor' page" (48f324c); "only vidhost.me. favs as page 0" (171f3e2); "keep mainthreadui pure and move everything 'bloaty' to workers" (59b8d9a).
- **Where the docs disagree:**
  - Scroll save timing: `test.txt` §3 says "scrollend + 100 ms"; `flow.md` §4 says "without a 100ms delay". The code saves immediately.
  - `test.txt` §4/5/6/8 still require card "readiness", copying during the tap gesture, and highlight in localStorage. The deleted `test.md` (in git at `a8d94b1^`) says these were "superseded".
  - `test.txt` says opening shows Favorites, but cold launch restores the last route.
  - The latest `AGENTS.md` (ef032d6) says the agent may now edit `README.md`, `test.txt` and `AGENTS.md`.

## 7. Hidden dependencies (behaviour the app relies on but doesn't own)

**bfcache / pageshow / pagehide** (used heavily)
- Where:
  - `app.ts:20-28`: save, suspend the network, reload a page whose render was interrupted;
  - `transport.ts:12-20`: terminate the worker, revoke the blob URL, cancel requests;
  - `video-card.ts:37-50`: re-sync the highlight;
  - `pc-backup.ts:116`: back up when Favorites returns from bfcache;
  - `scroll-settle.ts:7-8`, `media-recovery.ts:64-66`, `image-recovery.ts:26-28`.
- `test.txt` and `flow.md` make "restored from bfcache with exact viewport" a requirement.
- Without bfcache, Back reloads the page:
  - a listing re-fires 50 Typesense POSTs and rebuilds 600 cards;
  - the position comes from `view.json`/IndexedDB, and the card is re-centered;
  - the back-swipe preview shows a snapshot, then "Loading…".
- bfcache under the `ytb://` scheme has never been tested automatically; the tests use https and synthetic events.

**WebKit session history, swipe and snapshots**
- The entire Back/Forward model: push by hidden link click (`navigation.ts`, `app.ts:57`), replace (`video.ts:186`, `app.ts:34`), edge swipe (WebController 34) and WebKit's swipe snapshots.
- The forward swipe back into a video is an accidental feature.
- `navigation.ts:4-7` relies on a WebKit rule: assigning `location.href` while the document is still loading *replaces* the history entry.

**interactionState:** not used. History isn't saved across launches; only the 2-entry library-then-video stack is rebuilt from `view.json`.

**Scroll restoration**
- `history.scrollRestoration` is never set (default `auto`).
- Exact positions depend on bfcache. On reload, the app's own `scrollTo` 3 frames later (`app.ts:52-53`) competes with WebKit's own restore, `search.ts:42-47` and card centering.
- y is in CSS px, so it depends on layout and orientation. One measured cold restore came back at 10371 instead of 10119.

**Page zoom:** pinch-zoom exists only through `ignoresViewportScaleLimits` and the `touch-action` CSS. The gesture code hands multi-touch to WebKit (`video-gesture.ts:12-15,26-28`).

**WebKit media playback**
- Decoding and codec support: unsupported files give error 4, which shows Copy. AVPlayer uses the same AVFoundation, so KMPlayer is still needed.
- Inline playback and the autoplay policy: config 30-31 plus `muted`/`playsInline`.
- Not used: fullscreen (no API calls), PiP (no API calls; WKWebView allows it by default but there is no control).
- WebKit decides: suspending the video on lock or background, the audio session category and the silent switch, whether the display may sleep, Now Playing.
- Media network loading, range requests, UA and Referer are WebKit's.
- The `pause` events WebKit sends on interruption feed media-recovery's `playing` flag.

**WebKit-owned storage and eviction**
- Favorites, the only irreplaceable data, live only in WebKit IndexedDB at origin `ytb://app`, apart from the PC backup.
- `ke-video-time` is in WebKit localStorage.
- That data is subject to WebKit's storage quota and eviction policy, and is tied to the scheme and host. Changing `ytb://app` would orphan it.
- Related WebKit features in use: `durability:'strict'` (`database.ts:277,315`; `backup-engine.ts:30`), IndexedDB inside a worker, `navigator.locks`.

**Cookies:** none in the WebKit store and none used. URLSession's shared cookie storage silently accepts any `Set-Cookie`.

**Timers and visibilitychange when backgrounded**
- `ke-video-time` saving depends entirely on WebKit firing `visibilitychange` (`video.ts:227`).
- The recovery timers pause when hidden (`media-recovery.ts:23`, `image-recovery.ts:9`).
- `requestAnimationFrame` gating in `app.ts:31,52` stalls while the page is hidden.
- `navigator.onLine` and the `online` event are WebKit's.

**WebContent process termination:** handled only by `reload()` (WebController 131). bfcache entries and in-memory state are lost; time recovery relies on `ke-video-time` having been written before the kill.

**Custom scheme behaviour**
- `ytb://app` must count as a secure context for `crypto.randomUUID` (`app.ts:15`, `fetch.ts:12`, `backup-engine.ts:109`) and `navigator.locks`.
- `new Worker(blob:)` works from that origin (`transport.ts:24`).
- `message.frameInfo.request.url` supplies the route for `init` (WebController 57-64).
- An unknown route makes the scheme handler fail, and there is no failure UI.

**CORS bypass (essential):** all ytboob, Typesense and PC requests go through native code.
- The PC server sends no CORS headers; its test asserts this (`server/backups.test.mjs:222`).
- The forced `Referer` header (`YtbAPI.swift:68-69`) is one a browser would not allow.

**Newer JS/CSS features:** `scrollend` (`app.ts:19`, `scroll-settle.ts:4`), `Promise.withResolvers` (`database.ts:57`), `AbortSignal.throwIfAborted`, `Object.hasOwn`, `crypto.randomUUID`, Web Locks, IndexedDB durability, `loading=lazy`, `aspect-ratio`, `inset`, `attachShadow` (`pc-backup.ts:29`), `scrollIntoView({block:'center'})`, `-webkit-tap-highlight-color`.

**iOS-level behaviour**
- There's no `UIBackgroundModes` and no AVAudioSession, remote-command or idle-timer code, so all of it is WebKit's.
- Also WebKit's: keyboard handling for the import textarea, the native `<select>` picker in the backup modal, safe-area insets (no `viewport-fit`), image decoding and memory for 503+ full-size thumbnails, the WebKit HTTP image cache, and Web Inspector for device testing.

**Code comments about working around WebKit/Safari:**
- `src/ui/navigation.ts:2-7`: Safari history and bfcache; `window.stop`/`document_start` makes `location.href` replace history.
- `src/app/app.ts:24-25`: an interrupted render reloads; finished documents use bfcache.
- `src/app/app.ts:56`: "Preserve the library document underneath the resumed video for Safari Back."
- `src/core/compute/transport.ts:10-11`: a cached document must not hold an IndexedDB transaction.
- `src/core/compute/database.ts:85,107,132`: navigation cancels the open; "blocked by another page"; "even if Safari no longer considers the transaction abortable".
- `src/core/backup-engine.ts:24,57`: "blocked by another tab"; "DNS/TLS/CORS failure".
- `src/routes/video.ts:55-56`: "This real tap grants Safari clipboard access". Stale: copying is native now.
- `src/routes/video.ts:222-223`: "a reload after iOS ended the page".
- `src/routes/video.ts:231`: autoplay rejected.
- `src/app/media-recovery.ts:1-2,48`: "WebKit owns decoding and playback".
- `src/app/fetch.ts:1` and `apps/ios/Ytb/YtbStore.swift:3`: "Media… stream[s] directly in WebKit".
- `apps/ios/Ytb/WebController.swift:134-135`: "WebKit decodes/renders images".
- `src/ui/shell.ts:8`: takeover precedes the site's head (left over from the userscript).
- `apps/ios/Tests/app.mjs:9`: asserts that `document.open()` and `window.stop()` don't appear in the bundle.

## 8. Other findings
- The `ke-video-time` change isn't in the prepared bundle and is likely not deployed (see top).
- `search.ts:50`: the pagehide scroll save is a no-op.
- `/actor/` pages can't be reached from the UI.
- There's no reload control, although error messages say "Reload to retry".
- `view.json` positions and `ke-video-time` keys grow without limit.
- Fallback URL port 7777 vs 7733 (`WebController.swift:17`).
- `Tests/Routes.swift` isn't wired into any script.
- Stale gitignored userscript/extension builds in `dist/` contain the private backup key.