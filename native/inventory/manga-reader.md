I have everything needed. Here is the full inventory.

# Inventory of manga-reader for a native rewrite

The repo is at HEAD `45c3272` (2026-10-11), with a clean working tree. `AGENTS.md:1` now says the agent owns every file. Older docs that call AGENTS/README/test.txt "user-owned" are out of date.

## File index (short names below refer to these)

- **Native (8 files):** `/home/visar/Documents/work/manga/manga-reader/apps/ios/AsuraReader/{AppDelegate,WebController,ReaderStore,ImageDownloader,BackgroundDownloads,ReaderHTTP,Models,PCBackup}.swift`
- **Web:** `/home/visar/Documents/work/manga/manga-reader/src/app/*.ts`, `.../src/core/*.ts`, `.../src/core/compute/*.ts`, `.../src/provider/*.ts`, `.../src/routes/{home,reader}.ts`, `.../src/style.css`, `.../src/core/sites.json`
- **Docs:**
  - `/home/visar/Documents/work/manga/manga-reader/{README.md,notes.md,test.txt,AGENTS.md}`
  - `.../apps/ios/{DEVELOPMENT,PAID-NATIVE,ROBUSTNESS}.md`
  - `.../server/BACKUPS.md`
  - `.../investigation/*.md` and `*.json`
- **Build:**
  - `/home/visar/Documents/work/manga/manga-reader/scripts/build-ios.mjs`
  - `.../apps/ios/scripts/{prepare-web.mjs,build-guest.py,build.sh,deploy.py,renewal.py,test.sh,inspector-snapshot.js}`
  - `.../apps/ios/{Package.swift,AsuraReader.xcodeproj/project.pbxproj,Resources/Info.plist,Resources/Native/*,deploy.local.json}`
- **Tests:**
  - `/home/visar/Documents/work/manga/manga-reader/tests/unit/*.test.ts`
  - `.../apps/ios/Tests/{CoreTests.swift,builder.test.mjs,test_signing_lock.py}`
  - `.../server/backups.test.mjs`
- **Server:** `/home/visar/Documents/work/manga/manga-reader/server/{backups.mjs,manga-reader-backups.service}`

---

## 1. Architecture

### Size per area

The code is very dense (long lines), so bytes are a better guide than lines.

| Area | Files | Lines | Bytes |
|---|---|---|---|
| Native Swift app | 8 | 668 | 37 KB |
| `src/app` (entry, bridge, fetch shim, download planner) | 10 | 370 | 22 KB |
| `src/core` (shell, restore, retry, scroll settle, Home helpers) | 14 + sites.json | 333 + 65 | 15 KB + 1.7 KB |
| `src/core/compute` (worker: progress, history, migrations, backup, PC) | 10 | 642 | 26 KB |
| `src/provider` (6 providers, catalogs, types) | 15 | 1330 | 51 KB |
| `src/routes` (home.ts 465, reader.ts 421) | 2 | 886 | 36 KB |
| `style.css` | 1 | 200 | 3.6 KB |
| Unit tests (66 cases) | 16 + 3 stubs | 1330 | — |
| Native/builder tests | 3 | 154 + 22 + 43 | — |
| PC server and its test | 2 | 156 + 49 | 11 KB |
| Build/deploy scripts | 8 | ~240 | 16 KB |

### What is native

Native code is limited to hosting, storage, transport and lifecycle. It never parses provider data (`ReaderStore.swift:3`).

- **AppDelegate**
  - Data root is `Application Support/<CFBundleName>` (`:10`). The provider origin comes from the Info.plist key `ReaderOrigin` (`:11`).
  - Lifecycle wiring: `didBecomeActive→resume` (`:20`), background URLSession events (`:21-23`), `willResignActive→capturePosition` (`:24`), `didEnterBackground→pause` (`:25`).
- **WebController**
  - Sets up a single WKWebView (`:21-34`): `asura` scheme handler and message handler (`:24-25`), `ignoresViewportScaleLimits` (`:26`), `isInspectable` (`:28`), back/forward swipe (`:29`), black background and `contentInsetAdjustmentBehavior=.never` (`:30-31`), loads `asura://app/` (`:33`).
  - Status bar hidden and home indicator auto-hidden (`:19-20`).
  - Lifecycle JS calls (`:38-61`), the bridge (`:62-104`), navigation allow-list (`:105-110`), WebContent crash reload (`:113-115`).
  - `LocalFiles` scheme handler (`:118-137`).
- **ReaderStore (actor)**
  - Opaque JSON key/value store limited to 6 keys (`:22`), chapter manifest files, download windows, view checkpoints, bootstrap, local resources.
- **ImageDownloader (actor)**
  - The only image network/cache owner. It handles priority, deduplication, pruning and pause/resume.
- **BackgroundDownloads**
  - Hands unfinished downloads to a background URLSession while the app is away.
- **ReaderHTTP (actor)**
  - Three URLSessions: PC, images, and metadata (8 connections per host).
  - Retry policy, forced `Referer`, and the image commit protocol.
- **Models**
  - Helpers: SHA-256 file keys, atomic writes, the retryable-status rules (`:22-33`), and `recoverNetworkRead` backoff (`:34-51`).
- **PCBackup**
  - `LocalTrust`: pins the bundled LAN CA for the PC host only.

### What is web

Everything else lives in the web layer:

- provider extraction (all parsing)
- Home UI and reader UI
- read/partial rules, progress schema and migrations
- the backup format and the PC Load/Save logic
- which chapters to download (`src/app/downloads.ts`)
- position capture and restore (`src/app/app.ts`, `src/core/platform.ts`)
- image retry and scroll settling

### How the two sides talk

1. **JS → native**
   - Call: `window.webkit.messageHandlers.asura.postMessage({command,args,document})`, replying with a JSON string (`native.ts:9-20`, `WebController.swift:62-104`). It uses `WKScriptMessageHandlerWithReply` and only accepts main-frame `asura://app` callers.
   - Commands:
     - `init` (bootstrap plus `cold` flag), `activate` (`{home}`, which also sets the idle timer)
     - `fetch` / `fetch-cancel`
     - `read` / `write` (keys: `database`, `views`, `routes`, `windows`, `images`, `covers`)
     - `chapter-read` / `chapter-write`
     - `windows-retain`, `window-current`, `window`
     - `prepare`, `prepare-covers`
     - `downloads-active`, `downloads-status`
     - `view-save`
   - **Document handshake:** each page load has a `crypto.randomUUID()` document ID. When a new document sends `init`/`activate`, native cancels the previous document's requests and rejects the old document with "Document is no longer active" (`WebController.swift:68-74`).
2. **Native → JS:** `evaluateJavaScript("window.mangaApp?.save()|pause()|resume()")` (`WebController.swift:39,53,59`). `mangaApp` is defined at `app.ts:33`.
3. **Custom scheme `asura://app/`** (`ReaderStore.resource`, `:102-113`)
   - `/app.js` serves the bundle; any other path serves `index.html`. Every route is a full document load of the same bundle.
   - `/image?url=<enc>[&cover=1]` is served by `ImageDownloader`. A `retry=` parameter is ignored.
   - Navigation to anything other than `asura://app` is cancelled (`WebController.swift:105-110`).
4. **Compute worker**
   - A dedicated Worker created from a Blob URL of an embedded code string (`transport.ts:8-24`; built in `prepare-web.mjs:30`).
   - Ops: `manual-pc`, `backup-export`, `backup-import`, `save-progress`, `history-resolve`, `fetch-home`, `page-context` (`messages.ts:43-51`). State ops are serialized through a write queue (`worker-entry.ts:106-127`).
   - The worker cannot reach native directly. It posts `{bridgeID,command,args}` to the main thread, which forwards it (`worker-bridge.ts`, `transport.ts:13-15`). After every write the worker posts `{progressChanged,progress}` (`store.ts:9`).
5. **Fetch shim**
   - `globalThis.fetch` is replaced in both the page and the worker. Every `https://` request goes to native `fetch` with a `requestID`; aborting sends `fetch-cancel`.
   - The body comes back base64-encoded and is rebuilt into a `Response` (`fetch.ts:2-26`).
   - Referer is forced to the provider origin unless the caller passes an https referrer (`fetch.ts:16-20`, `ReaderHTTP.swift:33`).
6. **Build-time provider selection**
   - esbuild produces one bundle per app (`@selected-provider`).
   - It defines `__IOS_ORIGIN__`, `__READER_BACKUP_URL__` and `__READER_BACKUP_KEY__` (`prepare-web.mjs:15-29`).

---

## 2. Providers

There are 6 apps and 6 providers, defined in `src/core/sites.json` and listed in `PAID-NATIVE.md:3-10`.

| Builder arg | `provider.key` (progress/PC namespace) | Site | iOS name | Product (data dir) | Bundle ID |
|---|---|---|---|---|---|
| asura | asurascans | asurascans.com | Asura | AsuraReader | com.visar.AsuraReader.paid |
| scythe | scythescans | scythescans.com | Scythe | ScytheReader | com.visar.ScytheReader.paid |
| yaksha | yakshacomics | yakshacomics.com | Yaksha | YakshaReader | com.visar.YakshaReader.paid |
| qiscans | qimanga | qimanga.com | QiScans | QiMangaReader | com.visar.QiMangaReader.paid |
| lua | luacomic | luacomic.org | Lua | LuaReader | com.visar.LuaReader.paid |
| ezmanga | ezmanga | ezmanga.org | EzScans | EzMangaReader | com.visar.EzMangaReader.paid |

### Common to all six

- **No login, no tokens, no server-side tracking.** These were removed on 2026-09-16 (`asura-resume-download-window.md:39-42`).
- **Headers**
  - Providers set none. Referer is the provider origin (e.g. `https://asurascans.com/`). Worker catalog calls pass the page href mapped onto the origin (`transport.ts:26`, `context.ts:2-5`). Images use `Referer: ReaderOrigin` (`ReaderHTTP.swift:50`, `BackgroundDownloads.swift:43`).
  - User-Agent is URLSession's default CFNetwork UA. Nothing sets a browser UA.
  - Cookies are never handled in code (see section 8).
- **Unavailable chapters:** `isChapterUnavailable` treats 404 or `res.redirected` as unavailable (`core/http.ts:1-5`).
- **Concurrency limits**
  - Metadata: 2 background / 6 urgent (`metadata-queue.ts:7`).
  - Home: up to 3 catalog pages in flight (`home-pages.ts:16`).
  - Images: 3 background / 4 foreground (`ImageDownloader.swift:117`).
  - Connections: 8 per host for metadata (`ReaderHTTP.swift:22`), 4 per host for the background session.
- **Retries**
  - Indefinite retries for GET/HEAD on connectivity errors and HTTP 408/429/500/502/503/504. Backoff runs 1→30 s and honours `Retry-After` (`Models.swift:22-51`).
  - Timeouts: 20 s per request, 90 s per resource (`ReaderHTTP.swift:11`).
  - PC requests and non-GET requests are never retried.

### Asura (JSON API, `api.asurascans.com/api`)

- **Home** (runs in the worker): `GET /series?sort=latest&order=desc&limit=50&offset=…`
  - Reads `data[].{slug,title,cover,public_url,latest_chapters[].{number,is_premium,early_access_until,published_at}}` and `meta.{total,has_more}`.
  - The URL slug comes from `public_url` (`/comics/<slug-with-hex>`).
  - `historyId` is the API slug with `-[0-9a-f]{8}` removed (`asura.ts:24-28`).
  - Covers are rewritten from `…/covers/*.webp` to `*-400.webp`.
  - Locked means premium and either no `early_access_until` or one in the future.
  - Next page exists only if `has_more` is true. Up to 3 pages are prefetched based on `total` (`asura-catalog.ts:38-79`).
- **Chapter:** `GET /series/<slug>/chapters/<n>` returns `data.chapter.pages[{url,width,height}]`, `data.series.title`, `is_locked` (`asura.ts:30-50`).
- **Chapter list:** `GET /series/<slug>/chapters?nocache=<now>`, which deliberately bypasses the 1-hour edge cache (`asura.ts:73-81`).
- **Routes:** `/comics/<slug>/chapter/<n>#<idx>`.
- **Rotating slug:** the hex suffix changes over time. `routes.json` maps identity to the current slug.

### EzScans / QiScans (shared "Angular" JSON adapter)

APIs: `vapi.ezmanga.org/api/v1` and `api.qimanga.com/api/v1`.

- **Home** (worker):
  - First `/home/latest?page=N&perPage=50`, then `/series?perPage=100&page=N` (the whole catalog). Cursors are `latest:N` and `catalog:N`.
  - Locked means `price>0` and not yet free (`angular-catalog.ts:26-96`).
  - `perPage=1000` returns HTTP 400 (`investigation/2026-09-17-qi-startup.json`).
- **Chapter:** `/series/<slug>/chapters/<chapterSlug>` returns `{isFree,requiresPurchase,images[{url,width?,height?}],series.title}`. If `!isFree || requiresPurchase`, the chapter is unavailable (`angular.ts:16-34`).
- **Chapter list:** `/series/<slug>/chapters?perPage=100&page=N`, looped (`angular.ts:37-50`).
- **Routes:** any 3-segment path; the slug is the second segment.

### Lua (JSON API plus HTML scraping)

- **Home** (worker): `api.luacomic.org/query?…orderBy=latest&adult=true…`
  - The first 100 series load first, then one `perPage=1000` request fetches the whole catalog. Offset pages are avoided because they repeat and skip series (`lua-catalog.ts:29-81`).
  - Paid and free chapters are merged and sorted by number.
- **Chapter:** scrapes the HTML of `https://luacomic.org/series/<slug>/<chapter-N>`.
  - Uses a regex on `<img …src="https://media.luacomic.org/file/…/uploads/series/….(webp|jpg|png)">`. `\bsrc=` also matches `data-src`, which covers the mixed src/data-src pages.
  - The title comes from `<title>X - Chapter N - Lua Comic</title>` (`lua.ts:16-44`).
  - No image dimensions are available.
- **Chapter list:** `GET /series/<slug>` for the id, then `/chapter/query?perPage=30&query=&order=desc&series_id=…`. The first 4 pages run in parallel (`lua.ts:47-83`).
- **Referer is required:** the API returns HTTP 403 without the real referrer (`DEVELOPMENT.md:117-119`).

### Scythe (WordPress MangaReader theme, HTML scraping with DOMParser on the main thread)

- **Home**
  - `/` and `/page/N/`: find the `.bixbox` whose `.releases h2` reads "Latest Update". Cards are `.listupd .bs`, with `.bsx > a[href*="/manga/"]`, `img[src]`, `.tt`, chapters at `ul.chfiv > li > a` and dates at `.fivtime` ("N hours" becomes "N hours ago").
  - Then `/manga/?status&type&order=update&page=N`, where `.epxs` shows "Chapter N" and the chapter id is synthesized (`scythe.ts:50-98,271-295`).
- **Chapter:** `GET /<chapterId>/`
  - Find `<script defer src="data:text/javascript;base64,…">`, base64-decode it to `ts_reader.run({…})`, then `JSON.parse`. Images come from `sources[defaultSource].images`.
  - The title comes from `<div class="allc">` (`scythe.ts:113-151`, `ts-reader.ts`).
  - No dimensions; images use 1000px placeholders.
- **Chapter list (cached pages only):**
  - `#chapterlist a[href]` from `/manga/<slug>/` (deduplicated), plus that series' chapters from the first Latest Update page, prepended.
  - Gaps are filled by following each chapter page's `prevUrl`, up to 10 steps or 10 s. Otherwise the cached list is returned unchanged; a list with a hole is never returned (`scythe.ts:200-246`).
  - Never cache-bust: the origin takes 6–85 s on a cache miss (`investigation/2026-10-06-scythe-next-chapter.md`).
- **Routes:** a single path segment ending in `-chapter-N(.M)?(-K)?` (WordPress collision suffix).

### Yaksha (WordPress Madara theme, HTML scraping)

- **Home:** `/`, `/page/N/` with `.page-listing-item .page-item-detail`, `.post-title a`, `.item-thumb img`, `.list-chapter .chapter-item .chapter a`, `.post-on`. A next page exists if there is an "Older Posts" link (`yaksha.ts:76-119`).
- **Chapter:** `/manga/<slug>/<ch>/`, `<img class="wp-manga-chapter-img" src>`, title from the breadcrumb.
- **Chapter list:** regex on `li.wp-manga-chapter … Chapter N` gives `chapter-N` (`yaksha.ts:18-56`).

### Does anything need a browser engine?

No. There is no JavaScript execution, no challenge solving and no login.

- DOMParser (Scythe/Yaksha Home and Scythe list) can be replaced by a native HTML parser.
- The rest is regex, base64 and JSON.

Historical context: the Valir provider (removed) needed a Cloudflare challenge wait and tile decryption (commit `8f566cb`). Violet was removed because its `Cache-Control: no-store` defeated bfcache (commit `933ff6e`).

---

## 3. User-facing features and behaviour

### App shell

- Full screen: status bar hidden, home indicator auto-hidden, content drawn under the notch.
- Black throughout.
- Portrait and both landscape orientations (`Info.plist:42-47`).
- No icons (`PAID-NATIVE.md:14-15`), no search, no settings screen, no favourites or library.

### Home (`routes/home.ts`, `style.css:16-172`)

- **Loading:** "Loading latest updates…" centred (`home.ts:401-404`) until the first page arrives.
- **Content:** the provider's full catalog in provider order (latest updates first), eventually every series.
  - The first page renders synchronously. Later pages are appended as they arrive, with 3 buffered and no timers (`home.ts:436-464`, `home-pages.ts`).
- **Cards:** stacked edge to edge, each 200px tall.
  - Grid: 150px cover column and details column, 20px gap; list padding 0 16px (`style.css:27-53`).
  - Cover: 150×200, radius 6, object-fit cover.
- **Chapter rows:** up to 5 per card (`home.ts:219`): label, optional amber lock icon, and right-aligned relative time ("Just now", "Nm ago", "Nh ago", "Nd ago", "last week", "N weeks ago").
  - Locked chapters show "Nh Nm" or "Locked", with the countdown refreshed every 60 s (`home.ts:234-246,456`).
  - Below them, an app-only **"First chapter"** link (`platform.ts:20-22`).
  - A card with no chapters shows "No chapters available".
- **Colours:** unread `#f4f4f5`, read `#a592f0`, partial `#f969e2`, locked `#fbbf24` (`style.css:131-141`).
  - Computed in the worker by `resolveHistory`. Relative to the saved chapter in the row: older chapters are read; the saved chapter is partial or read depending on completion (`history.ts:51-94`, `home.ts:248-292`).
- **Taps**
  - Cover:
    - partial: opens the saved chapter at the saved image;
    - complete: opens that chapter at its last image, so the next chapter appends as you continue;
    - none: opens the first chapter.
    - While resolving it shows the overlay "Finding first chapter…"; on failure, a red outline and the title "Failed to open series" (`home.ts:183-213`, `style.css:55-76`).
  - Chapter: unread opens at the start; partial opens at the saved image (`#idx`); read with no hash fetches the chapter and opens its last image; locked does nothing (`home.ts:139-163`).
- **Status line:** "Loaded N[ of M] series[ · loading more…]" (`home-format.ts:27-30`). PC **Load / Save** controls appear below it (section 3, PC backup).
- **Pausing:** Home pauses while hidden or on pagehide, keeps successful in-flight pages, and retries cancelled ones on return (`home.ts:360-399`).
- **No catalog refresh while the document lives:** a completed Home never re-fetches on Back or foreground; only a new document does. Returning re-applies the history overlay and resets link spinners (`home.ts:450-455`; `third-port-fidelity-audit.md:18-22`).

### Following / tracking

- There is no explicit follow. Any series with a saved progress entry is "started": its download window is prepared and its row is coloured.
- Started series are **not** pinned or listed separately on Home.

### Chapter list

- There is **no chapter-list screen**. Only the 5 newest chapters per card plus "First chapter" are reachable from Home.
- The reader only appends **newer** chapters; it never prepends older ones (`reader.ts:158-165,346-355`).
- Lists are used internally for continuation and download windows.

### Reader (`routes/reader.ts`, `style.css:174-195`)

- **Layout:** continuous vertical strip, images full width with auto height and no gaps, 50svh padding top and bottom.
- **Image sizing:** each image gets an aspect ratio from the provider's width/height, otherwise a 1000px placeholder. It is corrected to the real ratio on load (`reader.ts:18-23,97-120`).
- **No custom UI:** no controls, tap zones, page counter or chapter navigation.
- **Gestures:** only WKWebView's own scrolling, pinch zoom (forced on by `ignoresViewportScaleLimits`), edge swipe back/forward, and link taps.
- **Loading model**
  - Every image element is created at once with `loading='lazy'`; WebKit decides when to request it.
  - The network side is eager: every image of the previous, current and next chapters is downloaded natively regardless of scroll position (`DEVELOPMENT.md:77-80`).
- **Continuation:** on each settled position, if the visible chapter is the last one appended, the next listed chapter is appended immediately ("Loading newer chapter…", then images) (`reader.ts:369-400`).
  - The list comes from the saved list at once, then the provider's answer (`reader.ts:288-299`).
  - A provider answer can never remove a newer chapter already known (`withNewerChapters`).
  - The list is re-fetched when it is older than 5 min while you are on the newest listed chapter, and on `visibilitychange` (`reader.ts:139,346-355,404-406`).
  - Failures retry after 15 s on a later settle (`reader.ts:142`).
- **Status texts:** "Loading chapters...", "Failed to load chapter list", "Loading newer chapter...", "Chapter unavailable", "Failed to load chapter", "Progress sync failed".
- **Image retry:** a registry polls failed images. First retry at 1 s, then exponential backoff per image, only while the page is visible. It clears `src` and reassigns it with a `retry=` parameter (`image-retry.ts`).
- **Title:** `document.title = "<chapterId> <seriesTitle>"`, following the visible chapter. It is not visible in the app.

### Position memory

There are four separate mechanisms.

1. **Progress per series**
   - Saved on each settled position by `tracker.track`, which sends `save-progress` to the worker and rewrites the whole `database.json`.
   - Fields: `{chapterId, imageIndex, totalImages, updatedAt}`. The image is the lowest *loaded* image whose top is at or above mid-screen. Writes only happen when the chapter or image changes (`tracking.ts`, `reader.ts:372-395`).
2. **View checkpoint (`views.json`)**
   - `{view, home}`, saved on `scrollend`, click (capture), `pagehide`, native resign-active and pause (`app.ts:23-26,34-37`).
   - `View = {path, home, y, fraction, series, chapter?, index?}`.
   - **The `f` fraction** (`app.ts:13-22`):
     - Anchor element: on Home, the card crossing the top edge; in the reader, the image crossing mid-screen.
     - `fraction = clamp(-rect.top/rect.height, 0, 1)`.
     - Restore scrolls to `anchorTop + fraction*height` (`platform.ts:9-13`).
     - Saves are gated by `ready` (route rendered) and `skipSaving`.
3. **URL hash `#idx`** via `history.replaceState` on each settle (`reader.ts:391`). This lives only in WebKit's session history.
4. **`routes.json`:** identity to current slug.

### Launch restoration flow (`app.ts:39-65`)

1. `init` returns `{view, home, routes, cold}`. `cold` is true for the first init of the process, or after a crash on a non-asura URL.
2. **Cold start at Home with a saved reader view:**
   - Home starts loading.
   - `skipSaving=true`, then `location.assign(<reader URL with saved index>)`. The comment is "Keep a functioning Home underneath the reader for native swipe back" (`app.ts:54-59`).
3. **Reader document:**
   - If the saved view's path matches, it opens at the saved index (`app.ts:46,62`).
   - `restoreScroll` scrolls through each preceding image to force it to load, or jumps once if all are cached (`reader.ts:52-86`).
   - Then `readerRestored` aligns using the fraction (`platform.ts:27-30`).
   - Any touch, pointer, wheel or keydown cancels restoration (`reader.ts:202-207`, `platform.ts:8`).
4. **Home document:**
   - `views.home` is used to anchor the matching card when it renders.
   - A ResizeObserver re-aligns until the first input (`platform.ts:14-25`).

The flow is verified by the kill/restart and Back records in `investigation/2026-09-17-pagination-verification.json`.

### Back and forward

- WebKit's back/forward list provides the navigation stack: each Home→reader tap is a full document navigation. Edge swipes go back and also **forward**.
- The stack is not persisted across launches; the cold flow rebuilds Home→reader.
- Forward to a reader whose path differs from `views.view` restores from the URL hash (image index only, no fraction).

### bfcache-specific code

- `app.ts:36-37`: pagehide saves and pauses downloads; pageshow with `persisted` re-activates the bridge, reloads progress and resumes downloads.
- `native.ts:4-8`: holds all bridge calls after pagehide until re-activation.
- `lifecycle.ts` (`onBfcacheRestore`), used by:
  - `shell.ts:27` (page context);
  - `home.ts:374` (resume pagination) and `home.ts:455` (reset link states, re-resolve history);
  - `reader.ts:402` (re-check position).
- `home-backup.ts:28` (PC probe), `scroll-settle.ts:19-20`, `image-retry.ts:40`.

### Downloads and prefetch (`src/app/downloads.ts`, `ReaderStore`, `ImageDownloader`)

- **Window:** for each series with progress, keep previous, current and next, following the provider's list order (`downloads.ts:44-65`).
  - Home schedules every started series immediately (`downloads.ts:18`; build 6 requirement).
  - A reader document schedules only its own series (`downloads.ts:33`).
- **Order of work:** current-chapter metadata starts without waiting for the list. A changed list or Home row moves the window (`provider.ts:46-112`). The latest window wins through generations.
- **Pruning:** obsolete chapter manifests and images are deleted; history stays (`ReaderStore.swift:33-40,53-67`, `ImageDownloader.swift:56-78`).
- **Priority:** a visible image request preempts and requeues background transfers (`ImageDownloader.swift:44-47`).
- **On-demand pages:** pages outside the window are fetched on demand and **deleted after serving** (`ImageDownloader.swift:145`).
- **Completion marker:** a file counts as complete only when its `.mime` file exists (`ReaderHTTP.swift:55-61`).
- **Chapter manifests:** cached in `chapters/` and reused without a network call (`provider.ts:13-33`). Saved lists live under `["chapters",identity]` (`provider.ts:40-51`).

### Covers

- Every catalog page registers all its cover URLs, including offscreen rows (`provider.ts:120`).
- `covers.json` persists them, they are prepared again at bootstrap, and they are **never pruned** (`ReaderStore.swift:72-75,97`).
- Served as `asura://app/image?url=…&cover=1`.

### PC backup (Load / Save)

- **Controls:** `<p class=hs-home-pc>` with Load and Save buttons and a status span, hidden unless the PC answers.
  - Probed on open, on pageshow with `persisted`, and when Home becomes visible (`home-backup.ts`).
  - Status texts: "Loaded", "Saved", or an error message ("No saved reading state on PC", "PC request failed", "Wrong provider in PC state", …).
- **Client** (`manual-pc.ts`): 5 s timeout, header `X-Reader-Backup-Key`, base URL `https://192.168.1.197:7711` from `BackupConfig.json`.
- **Endpoints** (prefix `/api/reader-backups/manual/manga-reader/<provider.key>`):
  - `GET …/status` returns `{available:true}`;
  - `GET …` returns the snapshot, or 404;
  - `PUT …` replaces the snapshot.
- **Save:** runs migration, then PUTs the full `DatabaseBackup` filtered to this provider.
- **Load:** validates, rejects a wrong provider, keeps local tokens, and replaces `database.json`. This triggers re-windowing and a Home history refresh.
- **Server** (`server/backups.mjs`):
  - Stores `{current, previous, savedAt}` per provider in `~/.local/share/manga-reader/backups/manual-manga-<provider>.json`.
  - Durable writes (temp file, fsync, rename, directory fsync); 5 MB limit; 401 without the key; `no-store`.
  - Uses the mkcert certificate from `~/.local/share/mkcert/pwa`, and runs as the systemd user unit `manga-reader-backups.service`.

### Lock and background behaviour

- **Resign active** (Control Center, Face ID, lock): `save()`, then hand unfinished files to the background session in this order: each series' window in order, current chapter first, page order, then covers (`WebController.swift:38-45`, `ReaderStore.swift:91-95`).
- **Did enter background:** `pause()` holds a background task until the JS returns, then sets the downloader inactive (`:55-61`).
- **Became active:** reclaim, i.e. cancel all background tasks (`:48-54`). JS `resume()` runs only if the app had really gone to the background.
- **Background session:** identifier `<bundleID>.images`, non-discretionary, `sessionSendsLaunchEvents`. It writes into the same cache files with the same `.mime` commit (`BackgroundDownloads.swift`).
- **Limits:** only already-prepared chapters download while away; force-quit stops them.

### Idle timer

`isIdleTimerDisabled = foreground && !home`: the screen never auto-locks in the reader (`WebController.swift:49,56,97`).

### Gaps and dead code found

1. **Unavailable initial chapter shows a blank page.** "First chapter" with no chapters, and covers or chapters that resolve to `seriesUrl`, navigate to a local series path that matches no route. `main()` then throws "Invalid reader route" and only logs it, leaving a black page (`actions.ts:34-36`, `reader.ts:219-222`, `app.ts:43,66`). `test.txt:20` expected a series page.
2. **Redirect detection never fires.** `res.redirected` is always false through the bridge because the `Response` is synthetic (`fetch.ts:23`), and URLSession follows redirects. Yaksha's redirect-based unavailability detection (`http.ts:2`) therefore cannot trigger; it shows a parse error instead.
3. **Dead code:**
   - the `reader-data-restored` listener is never dispatched (`home.ts:448`);
   - the `backup-import` op has no caller;
   - `initializeProviderRoute` is used only by tests;
   - `__IOS_PROVIDER__` is unused.
4. **No backup exclusion.** App data is not excluded from iCloud backup; image files sit in Application Support.

---

## 4. Data (what a rewrite must migrate)

### Where it lives

`<container>/Library/Application Support/<ProductName>/shared/` (`AppDelegate.swift:10`, `ReaderStore.swift:23`). `<ProductName>` is from the table in section 2.

**WebKit storage is not used at all.** There is no IndexedDB, localStorage, Cache API or service worker anywhere in the code.

JSON is written atomically with sorted keys (`Models.swift:12-17`).

| File | Shape | Migrate? |
|---|---|---|
| `database.json` | `{version:1, indexedDB:{progress:[{id:"<provider>\u0000<seriesId>", provider, seriesSlug, chapterId, imageIndex, totalImages, updatedAt(ms)}], tokens:[{key,value}] (legacy, empty), metadata:[{key:"progress-schema-version",value:3}, …legacy rows e.g. "asura-ios-v1" {history:{…}}]}}` | **Must.** This is the reading state. Keep unknown metadata rows (`backup.ts:3-41`, `migrations.ts`). |
| `views.json` | `{"view":View,"home":View}` | Should: seamless first launch. |
| `routes.json` | `{identity: currentSlug}` | Should for Asura (rotating slugs); otherwise rebuildable. |
| `windows.json` | `{seriesIdentity: [chapterKey…]}` where `chapterKey = JSON.stringify([identity, chapterId])` | Optional (cache). |
| `images.json` | `{chapterKey: [remote image URL…]}` | Optional. |
| `covers.json` | `[remote cover URL…]` | Optional. |
| `chapters/<sha256(key)>.json` | `ChapterData {chapterId, seriesSlug, historyId?, seriesTitle, images[{url,width?,height?}]}`, or the saved list `[{chapterId}…]` for key `["chapters",identity]` | Optional; saved lists make resume instant. |
| `images/<sha256(url)>` plus `.mime`; `covers/<sha256(url)>` plus `.mime` | Raw bytes; the `.mime` file marks completion | Optional; avoids re-downloading and keeps offline prepared chapters. |

### Rules any migration must preserve

- **Identity and chapter-ID formats:**
  - Asura `historyId` strips the hex; chapterId is the chapter number.
  - Scythe chapterId is the full slug (`magic-emperor-chapter-1`).
  - Angular chapterId is the chapter slug.
  - Lua uses `chapter-N`; Yaksha uses `chapter-N`.
- **Completion:** a chapter is complete when `imageIndex >= totalImages-1`.
- **Migrations** run v1→v2→v3 (v3 strips Asura hex) (`migrations.ts:65-94`).
- **PC server validation** requires schema 3, matching `provider` and `id` (`backups.mjs:43-61`).

### Implicit state outside the app's files

- `HTTPCookieStorage` (Library/Cookies): provider cookies.
- Background-session tasks under `<bundleID>.images`.
- WebKit caches in Library/WebKit and Caches: discardable.
- A possibly stale `state.json` from builds before 7 (unused; `shared-codebase-refactor.md:40-42`).

**Keep the `.paid` bundle IDs** to keep the containers. The established fallback when the container can't be kept is PC Save in the old app, then Load in the new one (`shared-codebase-refactor.md:26-28`).

### Sizes

No byte totals are documented. Known counts:

- Series with progress (2026-09-16): Asura 31, Scythe 5, Yaksha 1, QiScans 1, Lua 7, EzScans 9.
- Catalog sizes, one cover file each: 58 (Yaksha) to ~977 (QiScans).
- Typical chapter: 6–25 images; one Asura image response was 734 KB.

---

## 5. Tests

- **Unit tests** (vitest + jsdom, 66 cases): `npm run test:unit`. Asura is the stubbed provider (`vitest.config.ts`, `tests/unit/stubs/*`).

  | File | Cases | Covers |
  |---|---|---|
  | `reader.test.ts` | 16 | retry, 1000px placeholder, URL/tracking/append once, stale-list recheck, saved list, visibility, retries, stuck states, restore, cached sizes, input cancels restore, one-jump restore |
  | `home-providers.test.ts` | 6 | — |
  | `scroll-settle.test.ts` | 5 | — |
  | `ios-downloads.test.ts` | 5 | — |
  | `scythe-chapter-list.test.ts` | 6 | — |
  | `ios-chapter-list.test.ts` | 4 | — |
  | `manual-pc.test.ts` | 4 | — |
  | `compute.test.ts` | 4 | — |
  | `home-pages.test.ts`, `chapter-list.test.ts`, `provider-registry.test.ts` | 3 each | `provider-registry` checks the `test.txt` URLs |
  | `tracking.test.ts`, `provider-actions.test.ts` | 2 each | — |
  | `ios-activation.test.ts`, `manual-pc-ui.test.ts`, `asura-empty-series.test.ts` | 1 each | — |

- **Native tests:** `apps/ios/Tests/CoreTests.swift` runs on the Mac via `swift run ReaderCoreTests` (`Package.swift`, `scripts/test.sh`). It covers:
  - retry, permanent-error and write rules, cancellation;
  - downloader slots, promotion, deduplication, cache, pruning, pause/resume, partial-file recovery, covers;
  - store window pruning that keeps history;
  - background hand-off order.
- **Builder tests:** `builder.test.mjs` (provider selection and registry) and `test_signing_lock.py`, run with `npm run test:ios:builder`. The server test is `npm run test:server`.
- **Type check:** `npx tsc --noEmit -p apps/ios/tsconfig.json`.
- **Physical verification records:**
  - `apps/ios/robustness-verification.json`
  - `investigation/2026-09-17-{verification,pagination-verification,qi-startup}.json`
  - `investigation/{home-preparation,asura-resume-download-window,port-fidelity,third-port-fidelity}-verification.json`
  - `investigation/app-visible-text-inventory.json`
- **Inspector:** `apps/ios/scripts/inspector-snapshot.js` is a one-line DOM snapshot (url, visibility, scrollY, card/chapter counts, loaded images, srcs, errors, text). It is used by the external `~/Developer/ios-tools/inspector/app-inspector.py --url-prefix asura://app/`.
- **Stale leftovers:** `tests/ios/__pycache__` (sources removed in `8d2f1b2`) and an empty `tests/browser`. Chromium fixtures were removed at the owner's request: "do not reinstate those fixtures" (`shared-codebase-refactor.md:57-59`).

---

## 6. Build, deploy and renewal

1. **Prepare (Linux):** `npm run build:ios -- <provider> --prepare-only`.
   - Writes `apps/ios/build/providers.json` (identity plus origin) and runs `prepare-web.mjs`.
   - esbuild produces the IIFE bundle, targeting safari17, into `build/<provider>/Web/{app.js,index.html}`.
   - The PC URL and key are inlined into the JS.
2. **Sync:** `deploy.py sync <provider>` rsyncs to the Mac mirror `/Users/visar/Developer/manga-reader/apps/ios`.
   - The host comes from `deploy.local.json`: `visar@192.168.1.198`, with a Wi-Fi fallback.
3. **Build:** `deploy.py build`.
   - Runs over ssh: `sudo -n launchctl asuser 501 sudo -u #501 env DEVELOPMENT_TEAM=65U58U86DD READER_BUNDLE_SUFFIX=.paid DEVELOPMENT_DEVICE=00008101-000639912881401E caffeinate -i scripts/build.sh`.
   - It is wrapped in `ios-tools/renewal/scripts/deliver.py begin|built`.
4. **What `build-guest.py` does**
   - Writes an xcconfig with `PRODUCT_NAME`, `PRODUCT_BUNDLE_IDENTIFIER`, `READER_PROVIDER`, `READER_DISPLAY_NAME`, `READER_ORIGIN` (`//` escaped as `/$()/`).
   - Takes the signing lock `~/Library/Caches/ios-app-refresh/signing.lock`, or inherits it via `IOS_REFRESH_LOCK_FD`.
   - Refuses to run if `xcodebuild` is already running.
   - Copies the provider's Web folder into `Resources/Web`.
   - Runs `xcodebuild -target Reader -sdk iphoneos -configuration Release` with `-allowProvisioningUpdates`.
   - Verifies `CFBundleIdentifier/Name/DisplayName/ReaderProvider`, the absence of `CFBundleIcon*`, the codesign, the profile team and that the phone is in the profile.
5. **Install:** `deploy.py install` checks the codesign and the SHA-256 of every Web and Native resource, runs `devicectl install`, then `deliver.py installed`, which approves the build as the renewal baseline. `deploy.py launch` starts the app.
6. **Xcode project:**
   - One target, `Reader`; iOS 17.0; Swift 5 mode with strict concurrency; build 10; iPhone only.
   - Folder references to `Resources/Native` and `Resources/Web`.
   - No asset catalog, no entitlements, no UIScene manifest.
7. **Info.plist keys:** `CFBundleDisplayName=$(READER_DISPLAY_NAME)`, `ReaderOrigin`, `ReaderProvider`, `NSAllowsLocalNetworking`, `NSLocalNetworkUsageDescription`, orientations.
8. **Renewal:** `scripts/renewal.py --team --device` prints JSON for the Mac scheduler `com.visar.renewal.manga-reader`. It lists the app path, the `.paid` bundle IDs, the fingerprinted inputs (`AsuraReader`, xcodeproj, `Info.plist`, `Resources/Native`, `build/<key>/Web`, `providers.json`, `Package.swift`, `build-guest.py`) and the build command. Renewal is monthly (`PAID-NATIVE.md:50-52`).
9. **What the Mac needs**
   - Xcode 26.x, python3 and swift.
   - GUI login UID 501 and passwordless sudo for `launchctl asuser`.
   - The `ios-tools` checkout (renewal and inspector).
   - The paired phone and a trusted SSH known-hosts file.
   - No Node: bundles are prepared on Linux.
10. **Private inputs** (gitignored): `Resources/Native/BackupConfig.json` and `LocalCA.cer` (mkcert CA, valid until 2035-11-16), and `deploy.local.json`.

---

## 7. Documented decisions and requirements (quoted)

### README and `test.txt`

- **Features** (`README.md:5-9`): "1. load newer chapter while reading current chapter. 2. on reload, restore to the appropriate page 3. the home page eventually loads all entries 4. prepared chapters keep downloading while the phone is locked or the app is in the background"
- **Why** (`README.md:12`): "ios26 top and bottom bar transparency behaves well when (document) body scrolls and behaves badly when there is a virtual window controlled by the site."
- **How** (`README.md:15`): "Infinite reader style on reader. full entries on home."
- **Reader contract** (`test.txt:4-8`): "On scrollend + 100 ms, each visible chapter may append its immediate newer chapter exactly once… save the current loaded image in the page URL + local/server tracking… Opening or refreshing a reader URL, the app may restore to the corresponding image". The 100 ms was later removed: "Use scrollend immediately" (`scroll-settle.ts:1`).
- **Home contract** (`test.txt:10-15`): "show all entries (eventually)… the single local resume position… always wins… clicking on cover resumes… clicking on chapters resumes the chapter (unread - start_page, read - end_page, partial - saved_page)."
- **Special features** (`test.txt:17-21`): "bfcache - going back (swipe back) from reader to home loads home from cache; image self register to retry in case they fail to load; if resume/initial is unavailable, location.href to series page…; if no provider height, use 1000px height which will then get replaced by actual heights".

### `notes.md`

- PC (`notes.md:13-17`): "Save replaces the shared PC reading state; Load replaces local reading state with that save, even if older. No timestamp merging, automatic home backup, progress publisher, or periodic imports… Offline PC hides the controls."
- Downloads (`notes.md:27-30`): "Each manga keeps previous + current + next chapters downloaded… There is no server history, tracking or provider authentication. Both reader ends use 50svh padding."

### `DEVELOPMENT.md`

- "Resuming must never wait for the network." (`:52`)
- "all images in the retained chapters are downloaded independently of scrolling. Do not introduce a second IntersectionObserver, image queue, DOM-window removal or app-specific retries." (`:78-80`)
- "Every Home catalog page registers **all** its cover URLs… including offscreen rows… Home rendering does not await their downloads." (`:95-98`)
- "No server tracking, authenticated provider sessions, automatic PC history sync, new reader controls or custom image error overlays are introduced." (`:121-122`)
- App-only features to keep (`:114-116`): "First chapter link per Home card", "Cold Home/reader/position restoration and WebKit back-swipe navigation".
- "Providers must keep list requests to cached or fast endpoints" (`:61-63`).
- **This one directly conflicts with the rewrite and needs the owner to supersede it explicitly** (`:5-6`): "Do not copy these into Swift or a second app UI."

### Other docs and commits

- "All images and image links disable callouts, selection and dragging… taps and scrolling are unchanged." (`PAID-NATIVE.md:46-48`)
- "Neighbours follow provider chapter-list order, not numeric arithmetic… a locked next chapter is not skipped… Obsolete preparation stops when the current chapter changes; the latest requested window wins. Backgrounding pauses new batches" (`asura-resume-download-window.md:27-36`)
- "every entry with a current position must prepare its window on Home as soon as possible" (`asura-resume-download-window.md:87-89`)
- "Title changes follow the tracked visible chapter… Identical native checkpoints no longer rewrite state… Explicit locked/404 responses show `Chapter unavailable` while keeping current pages" (`third-port-fidelity-audit.md:25-42`)
- Home rows must not flash or replace covers (`third-port-fidelity-audit.md:10-17`).
- "`First chapter`… Explicitly requested app adaptation, keep" (`app-visible-text-audit.md:25,117-118`). That file is the inventory of visible text.
- "Never clone app logic for additional providers." (`2026-09-12-handoff.md:90`) "Keep existing app IDs" (`:9`).
- "PC requests remain finite and optional; POST/write operations are not replayed." (`ROBUSTNESS.md:6-7`)
- Commit `933ff6e`: "our app requires bfcache support". Commit `fe8f5bb`: "Resource scheduling belongs to the runtime, not the app."
- **Zoom and gestures:** nothing in the docs mandates "Safari-like zoom" or tap zones. Pinch zoom exists only through `ignoresViewportScaleLimits = true` (`WebController.swift:26`). The no-new-controls rule is the documented constraint.

---

## 8. Hidden dependencies (behaviour the app relies on but doesn't own)

| Item | Used? / where | What breaks if it changes, or what a rewrite must own |
|---|---|---|
| **bfcache, pageshow `persisted`, pagehide** | Heavily: see the bfcache list in section 3. | Home (60–1000 cards, scroll, finished pagination, kept responses, history overlay) survives a reader visit only because WebKit cached it. On eviction, Back builds a new Home: full catalog re-fetch behind "Loading…", then an anchor restore from `views.home`. The bridge re-activation logic exists only because of bfcache event ordering (`DEVELOPMENT.md:127-134`). A rewrite must keep the list view controller alive, own its scroll and "catalog complete" state, and refresh the history overlay when it reappears. |
| **WebKit session history, back-swipe and its snapshots** | `allowsBackForwardNavigationGestures` (`WebController.swift:29`). Every navigation is a document load (`home.ts:157,208`, `platform.ts:21`, `app.ts:58`, `reader.ts:221`). `replaceState` keeps `#idx` (`reader.ts:391`). `interactionState` is **not** used; the stack lives in memory and the cold flow rebuilds it. | The back-swipe animation, its snapshots and **forward** swipe are all WebKit features. A UINavigationController gives interactive pop but no forward unless built. |
| **`history.scrollRestoration` / WebKit scroll restore** | Not set (default `auto`). The app restores its own anchor (`platform.ts`, `reader.ts:52-86`). | bfcache keeps scroll implicitly. After `reload()` or history loads, WebKit may restore scroll too, and the app re-aligns anyway. A rewrite must persist and restore offsets itself. |
| **Scroll anchoring** | CSS `overflow-anchor` is not used. The app's own anchoring: a ResizeObserver plus rAF alignment of anchor+fraction until the first input (`platform.ts:8-15`), and provider aspect ratios or 1000px placeholders reconciled on load (`reader.ts:18-23,105-118`). | After the first input, layout shifts above the viewport are not compensated. A native list must anchor its content offset when cell heights change. |
| **Pinch zoom, `visualViewport`, `ignoresViewportScaleLimits`** | `ignoresViewportScaleLimits=true` (`WebController.swift:26`). Viewport meta `width=device-width, initial-scale=1`, set twice (`index.html`, `shell.ts:12-15`). No `visualViewport`, no double-tap code. | Zoom feel, double-tap behaviour, minimum scale and zoom persistence are all WebKit's. The `innerHeight/2` midpoint (`app.ts:15`, `reader.ts:372`) changes meaning when zoomed. |
| **Image loading, decoding, lazy loading, memory cache, cancellation** | `loading='lazy'` (`reader.ts:114`, `home.ts:178`). WebKit decides when to request, decodes and tiles very tall strips, keeps the memory cache and evicts decoded images. A scheme-handler `stop` cancels the waiter (`WebController.swift:136`, `ImageDownloader.swift:52-55`). Retry workarounds in `image-retry.ts:67,70`. | Pages outside the window are deleted after serving (`ImageDownloader.swift:145`), so after WebKit evicts them they are re-downloaded. A rewrite must own downsampling for tall webtoon strips, a memory cache, prefetch distance and an on-demand cache. |
| **WebContent process termination / jetsam** | `webViewWebContentProcessDidTerminate` reloads in place (`:113-115`). | Termination loses bfcache entries. Natively, jetsam means a full relaunch, so the restore path must cover every screen. |
| **Storage WebKit owns (IndexedDB, localStorage, Cache API, service workers, ITP)** | **None used.** All state is native files. The legacy userscript IndexedDB `manga-reader-compute` v2 lived in Safari, not in these apps. | Nothing to migrate from WebKit. The JSON keeps the IndexedDB-like shape only for backup compatibility. |
| **Timers, rAF, `visibilitychange`, pagehide while backgrounded; JS suspension** | Saves rely on `scrollend`, click capture and pagehide (`app.ts:34-36`), plus native-triggered `save()` on resign-active and `pause()` on background. | The background task ends when `evaluateJavaScript` returns (`:58-59`), not when the native write finishes, so the last save is best-effort. JS is frozen in the background. Timers in use: image retry (skips hidden), 60 s unlock countdown, 5 s PC timeout, 10 s Scythe gap. List re-checks use due times evaluated on settle or visibility, not timers. |
| **Web worker inside WKWebView** | Blob-URL dedicated worker with a serialized write queue (`transport.ts:8-10`, `worker-entry.ts:106-127`). It can be frozen with the page; workaround at `native.ts:5-7`. | Replace with an actor or serial queue. Keep the guarantee that a history read sent after a save sees that save. |
| **Cookies (WKWebsiteDataStore vs HTTPCookieStorage)** | WebKit's cookie store is unused (no WebKit requests to providers). `HTTPCookieStorage.shared` is used **implicitly** by the `.default` and background sessions (`ReaderHTTP.swift:8-24`). | Provider `Set-Cookie` headers (e.g. Cloudflare) are stored and replayed silently. Switching to ephemeral sessions could change provider behaviour (unverified). |
| **fetch, CORS, custom scheme semantics** | The page origin is custom/opaque (`native.ts:24`), so all https traffic is bridged (`fetch.ts`). Referer is forced; Lua returns 403 without it. Requests belong to a document and are cancelled by the next document's `init` (`WebController.swift:68-74`). Home re-fetches cancelled pages on Back (`home.ts:385-399`). DOMParser and `atob` are used for parsing. | Native networking removes CORS. Keep the per-request Referer. Tie cancellation to screens. URLSession follows redirects, which also breaks the `res.redirected` check (gap 2 in section 3). |
| **Recent CSS/JS features** | `scrollend` (`scroll-settle.ts:11`, `app.ts:34`) is a recent WebKit addition (Safari 26.x as far as I know; needs checking). The deployment target is **iOS 17.0** (`project.pbxproj:32-33`). Other features need Safari 15.4+: `svh`, `:has`, `aspect-ratio`, `crypto.randomUUID`, `loading=lazy`, `Object.hasOwn`, `Array.at`, `AbortSignal.throwIfAborted`. ResizeObserver; esbuild target `safari17`. `dialog closedby` is not used. | Without `scrollend`, the reader never saves progress after the first scroll, because `scrolling` stays true. |
| **Text selection and callout suppression** | Callout, selection and drag are disabled only for `img` and `a:has(img)` (`style.css:1-7`). | Long-press link previews and text selection still work on chapter text links; `allowsLinkPreview` is left at its default. |
| **Momentum and overscroll** | Default UIScrollView deceleration and bounce, black backgrounds, `contentInsetAdjustmentBehavior=.never`, 50svh reader padding. The "held finger" settle logic depends on WebKit touch and scroll events (`scroll-settle.ts:12-18`). | A native rewrite must reproduce the settle semantics: save only when not touching and scrolling has ended. |
| **PC server 192.168.1.197 and bundled local CA** | URL and key are compiled into `app.js` and `BackupConfig.json`. `LocalCA.cer` is pinned for that host only (`PCBackup.swift`, `ReaderHTTP.swift:12-24`). Local-network permission in `Info.plist:29-35`. | A new IP or key requires a rebuild. The CA expires 2035. The key ships inside the bundle, so bundles must never be published. |
| **iOS behaviour** | Background URLSession with launch events (`AppDelegate.swift:21-23`). Hand-off at resign-active because "iOS defers transfers started from the background" (`BackgroundDownloads.swift:7-8`). Control Center triggers hand-off and immediate reclaim without pausing the page; ImageDownloader keeps running, so it can race the background session on the same file. Force-quit kills transfers. Idle timer. Legacy UIApplicationDelegate window with no UIScene, which Apple has signalled will become mandatory with SDKs after iOS 26. | All of this must be re-owned explicitly in a rewrite. |
| **Other implicit behaviour** | Default CFNetwork User-Agent, which providers currently accept. URLSession auto-decompression. WebKit decodes WebP. Home keeps ~1000 cards in the DOM with no virtualization; WebKit tiling makes that work. | A native list should virtualize. Check whether providers still accept a native UA. |

### Places where the code works around WebKit (comments)

- `native.ts:5-7`: "Frozen workers can deliver queued messages before pageshow"
- `native.ts:11-12`: "A cached document must reacquire the bridge before its shared pageshow callbacks"
- `WebController.swift:69-70` and `DEVELOPMENT.md:129-132`: "Do not clear that ownership in `didCommit`: on a cached Back navigation it can run after reactivation"
- `image-retry.ts:67`: "Safari iOS doesn't fire img.onerror on 429s"
- `image-retry.ts:70`: "Safari iOS needs the source cleared before reassigning the same URL"
- `image-retry.ts:40`: "Frozen (bfcache) or backgrounded"
- `reader.ts:28-29`: "Safari can expose intrinsic dimensions before delivering load"
- `reader.ts:136`: "A reader can stay open for days (a suspended app, Back/Forward cache)"
- `fetch.ts:18-19`: "The local app origin is opaque to Fetch… instead of Request reducing it to about:client"
- `context.ts:2-5`: "a worker's default referrer is not the page URL"
- `home.ts:394-395`: "Native navigation can cancel the departing document's requests"
- `home.ts:454`: "A restored DOM carries the history overlay from before the reader was opened"
- `app.ts:55`: "Keep a functioning Home underneath the reader for native swipe back"
- `WebController.swift:57`: "A moment for the page to write its position before iOS suspends it"
- `WebController.swift:111-112`: "iOS ended the page while the app was away: reload it"
- `BackgroundDownloads.swift:7-8`
- `investigation/bfcache-home-blocking.md`: a historical analysis of Home's main thread blocking on swipe back.