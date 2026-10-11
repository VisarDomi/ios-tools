I've read every file in the app, the offline UI, the server code it syncs from, the tests and the docs, plus the relevant git history and the sibling gallery-reader repo. Line numbers below refer to commit `69891ad`.

**The working tree moved while I was reading.** At 14:34 today the uncommitted changes you mentioned were committed as `69891ad` ("Thumbnails and pages load nearest the screen first; a relaunched reader returns to a finished list"). The working tree is now clean. The code I read is identical to that commit, so "working tree" and HEAD are the same thing below. That commit also edited `offline-reader-behavior.test.mjs`, `apps/ios/README.md` and `apps/ios/PAID-NATIVE.md`, and left `webView.isInspectable = true` in on purpose. The Xcode build number is still 11, as it was on Sep 22. Nothing records whether the Oct 11 native changes (background downloads, Control Center handling, the queue) are on the phone yet.

**File index.** Short names below refer to these files.
- App: `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/GalleryReader/{AppDelegate,WebController,GalleryStore,GalleryAPI,BackgroundDownloads,Models}.swift`
- Bridge, settings and CA: `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/Resources/{native.js,Info.plist,LocalCA.cer}`
- Stale build copy, dated Sep 13, still contains `sw-status`: `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/Resources/Web/`
- UI: `/home/visar/Documents/work/manga/gallery-downloader/gallery-server/downloader/public/offline/{app.js,index.html,style.css}`
- Server: `/home/visar/Documents/work/manga/gallery-downloader/gallery-server/downloader/src/*.ts`, `/home/visar/Documents/work/manga/gallery-downloader/gallery-sources/src/*`, `/home/visar/Documents/work/manga/gallery-downloader/gallery-server/gallery-dl/gallery_dl/extractor/hitomi.py` (a modified, untracked checkout)
- Tests: `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/Tests/*.swift`, `/home/visar/Documents/work/manga/gallery-downloader/gallery-server/scripts/offline-reader-behavior.test.mjs`
- Scripts: `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/scripts/{build.sh,prepare-web.sh,test.sh,renewal.py}`
- Docs: `/home/visar/Documents/work/manga/gallery-downloader/{AGENTS.md,README.md,decisions.md,notes.md}`, `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/{README,PAID-NATIVE,REFRESH,ROBUSTNESS}.md`, `/home/visar/Documents/work/manga/gallery-downloader/apps/ios/*-verification.json`

---

## 1. Architecture

**Line counts**

| Part | Files | Lines |
|---|---|---|
| Swift app | AppDelegate 22, BackgroundDownloads 89, GalleryAPI 162, GalleryStore 604, Models 198, WebController 265 | 1,340 |
| Web UI | app.js 511, native.js 55, index.html 27, style.css 50 | 643 |
| iOS tests | CoreTests 270, StartupBenchmark 50, TransferBenchmark 35 | 355 |
| iOS scripts | build.sh 26, prepare-web.sh 9, test.sh 13, renewal.py 21 | 69 |
| Server source | offline-api 150, queue.manager 344, imhentai-downloader 244, favorites-sync 160, main 158, others | about 1,553 (plus 370 test lines) |

**AppDelegate.swift**
- Uses the old app-delegate lifecycle, with no scene manifest in Info.plist.
- Forces dark mode and makes `WebController` the root (lines 8-15).
- When the app resigns active (16): saves the position, then hands downloads to iOS.
- When it becomes active (20): `resume()`. When it enters the background (21): `pause()`.
- Background URLSession relaunch events are forwarded at 17-19.

**WebController.swift** (one view controller with one WKWebView)
- Data root is `~/Library/Application Support/GalleryReader` (30). The PC address comes from Info.plist `GalleryServerURL` (31). The bundled CA is `LocalCA.cer` (32).
- Web view setup (42-54):
  - the `gallery` URL scheme is served by `LocalFiles`;
  - a message handler with replies is registered in the page world;
  - zoom limits are ignored, so the user can always pinch;
  - WebKit's back/forward swipe gestures are on (47);
  - `isInspectable = true` (48);
  - black backgrounds, and no automatic safe-area insets.
- A black cover view sits over everything at launch and is removed on the first `continue` message or after 3 s (24-26, 56-58, 84-87). It also blocks touches while it is up.
- Loads `gallery://app/` (59).
- Store events (60-70): each event sets `isIdleTimerDisabled = foreground && busy` and schedules a UI update. If the number of loaded galleries grew, it starts the download run.
- `NWPathMonitor`: whenever the network is available, it starts the automatic work (71-75). A 30 s poller does the same (76-81).
- `scheduleUpdate` (92-104) coalesces updates for 100 ms, then dispatches a `native-library` event into the page via `callAsyncJavaScript`.
- `capturePosition` (105-107) runs `window.galleryViewState?.save()`.
- `handOffDownloads` (110-116) wraps the hand-off in a background task.
- `pause` (117-125) cancels the download, sync and warm-up tasks and all transfers.
- `resume` (128-133) always cancels the background-session transfers. It restarts the app's own work only if the app was really in the background.
- `startAutomaticWork` (134-156) runs a catalog refresh, metadata warm-up and the download run. It only runs when `foreground && documentReady`.
- `runDownload` (157-168).
- Message handler (169-229): accepts messages only from the main frame of `gallery://app`.
- Navigation policy (230-234): only `gallery://app` URLs may load.
- If the WebContent process dies, it calls `reload()` (235).

**LocalFiles** (WebController.swift 240-265)
- Runs on the main actor. For each request it asks `store.localResource(url)`.
- It delivers the response with the whole file as `Data` on the main thread.
- When WebKit stops a request, it cancels the matching Swift task.

**GalleryStore** (GalleryStore.swift, an actor)
- State (30-56): the library of loaded galleries, per-gallery headers, saved progress, sparse "extras" sets (out-of-order pages), the shared transfer map, priority galleries, and the catalog items. Events are an `AsyncStream` that keeps only the newest event (63).
- Progress checkpoint (73-92): writes `progress.json` when there are at least 16 changes or 0.25 s has passed, or when forced.
- `webSnapshot` (127-159) builds the UI payload. `webGallery` (176-182) answers `describe`/`open`.
- `localResource` (184-212):
  - `gallery://app/media/<key>/<pages|thumbnails>/<index>` loads the manifest if needed, marks the gallery as priority when a thumbnail is requested (201), then reads the file or downloads it urgently first.
  - Any other path may only be `index.html`, `app.js`, `style.css` or `native.js` from the bundle's `Web/` folder.
- `load` (214-265):
  - marks the root folder excluded from backup (217-218);
  - reads `index.json`, or migrates an old `library.json` once (224-240);
  - reads `catalog.json` (247) and validates `progress.json` (248-260).
- View state: `viewState`, `saveViewPosition`, `recordStartup` (267-295).
- `ensureManifest` (315-359) reads the local manifest, or fetches it from the PC (6 at a time during refresh) and saves it.
- `refreshCatalog` (361-396).
- `downloadAll` (408-474): 8 gallery pipelines, each doing thumbnails and then originals one page at a time. A network or disk-full error stops the whole batch (446-449).
- `backgroundWork` (478-496) lists up to 2000 unfinished pages for iOS to take over.
- `nextGallery` (498-504) picks priority galleries first.
- `ensureMedia` (516-568):
  - shares one transfer per file;
  - reading a saved file is a plain read, with no transfer or progress event (533);
  - commits the file, then advances the contiguous count or records an extra.
- File layout is defined at 570-576.
- `DurableFile` (579-604): files must match the expected size; writes are atomic and fsynced; downloads are committed with a POSIX `rename`.

**GalleryAPI.swift**
- `LocalTrust` (6-31): only the configured host may use the bundled CA. It checks the hostname with the SSL policy and trusts only that anchor.
- `TransferGate` (46-80): 12 slots. Urgent requests take the next free slot. A queued request can be promoted. Cancelling removes it from the queue.
- `GalleryAPI` (82-162):
  - ephemeral session, no cache, 25 s request / 90 s resource timeouts, 12 connections per host, one serial delegate queue;
  - only `https` `/offline-api/` paths on the same host and port are allowed (106-112);
  - downloads require HTTP 200, an `image/*` type and the exact byte size (138-159).

**BackgroundDownloads.swift**
- Background URLSession named `<bundle id>.pages` (19-27). Not discretionary, sends launch events, 12 connections, no cache.
- `handOff` (43-52) skips files already being transferred. Each task's description is `"<relative file>\n<size>"`.
- `reclaim` (54-56) cancels every task.
- On completion (70-76) it checks 200, `image/*` and size, then commits through `DurableFile.commitDownload`. It never updates `progress.json`.
- No background mode or entitlement is declared, and the docs say none is needed.

**Models.swift**
- `GalleryItem` (3-10), `Catalog`, `MediaPage` (17-24, with optional width and height), `ThumbnailManifest` (26-30).
- `GalleryMetadata` (32-40) has only title, title_jpn, artists, groups, tags, language and type.
- `GalleryManifest.validate` (51-81):
  - key must be `provider-id`; providers are hitomi or imhentai; ids are positive integers;
  - page counts must match; revision must be 24 hex characters;
  - file names must look like `<prov>_<id>_[thumb_]N.(avif|gif|jpe?g|png|webp)`;
  - sizes must be between 1 byte and 512 MiB; offsets must be contiguous; URLs must match exactly.
- `CatalogSelection` (111-124): keeps only `ready && pages > 0` items, removes duplicates, and orders them as the remote list followed by saved items no longer in it.
- `GalleryHeader` (127-158) is one launch record per gallery.
- `ViewPosition.route` (168-183) turns a path into `reader:<key>` or `library:<p>` and rejects anything else.
- `ViewState` (193-198).

**Web UI**
- `index.html`: library (12), then footer (13-16), then reader (17). An inline script (18-24) shows the reader instead of the list on `?read=` URLs before `app.js` runs.
- `prepare-web.sh` (lines 5-9) copies the files into `Resources/Web` and rewrites `<script type="module" src="/app.js">` into `<script src="/native.js"></script><script defer src="/app.js"></script>`. In the app, `app.js` is therefore a classic deferred script, not a module.
- `native.js`:
  - hides the Download button (1);
  - gives each document an id from `crypto.randomUUID()` (2);
  - `nativeGallery.savePosition`, `reportStartup` and `continueLoading` post messages (5-13);
  - `createWorker()` (14-54) imitates the removed web worker over `window.webkit.messageHandlers.gallery`:
    - for `init` it handles `redirect` with `location.replace`, and `resumeReader` with `whenScreenComplete(1500)` followed by `location.assign` (23-31);
    - it turns `native-library` events into `catalog`, `native-progress`, `download-status` and `previews-ready` messages (39-52).
- `app.js`:
  - scroll-settle and image-retry helpers copied from gallery-reader (1-85);
  - position memory (100-146), `screenComplete` / `galleryViewState` (149-181);
  - image queue (217-263), `loadImage` (271-300), rows (307-329), `renderCatalog` (330-380), `showPage` (381-389), info dialog (390-422), reader (423-450);
  - `start` (451-491), `pagehide`/`pageshow` handlers (501-510), boot after two animation frames (511).

**Messages between the page and Swift**

Page to Swift, via `postMessage` with a reply:

| Command | Arguments | Reply / effect |
|---|---|---|
| `init` | document id | Full snapshot `{supported, downloads[], running, message, catalog?{version:1, items}}`, plus `position?`, `redirect?`, `resumeReader?` (WebController 184-208) |
| `view-save` | document id, position | Ignored unless the document is the most recent one to send `init` (209-213) |
| `continue` | none | Removes the cover, sets `documentReady`, starts the automatic work (214-218) |
| `startup` | boot marks | Writes `startup.json` (219-222) |
| `describe` / `open` | key | `{manifest, state:{key, downloaded, total, complete, bytes}}` (223-224) |
| `download` / `stop` | none | Not handled; the reply is "Unknown native request". The button that sends them is hidden. |

Swift to page: `evaluateJavaScript("window.galleryViewState?.save()")`, and `callAsyncJavaScript` dispatching `CustomEvent('native-library', {detail})`. The detail is a snapshot that includes the catalog only if it changed, and the download states only for galleries that changed.

The `page`/`thumbnail` commands were removed in `69891ad`. Images are now plain `gallery://` URLs.

---

## 2. The PC server the app depends on

The server is `https://192.168.1.197:7777` (Express over HTTPS, `main.ts:39`). The offline API is mounted at `main.ts:57`. Every `/offline-api` response carries `Cache-Control: no-store` and `Cross-Origin-Resource-Policy: same-origin` (`offline-api.ts:18-22`).

**`GET /offline-api/catalog`** (69-78)
- Cached on the server for 10 s.
- Built by `loadCatalog` (48-67): Hitomi ids from `gallery-server/favorites/hitomi.json`, then IMHentai ids, each in snapshot order. Snapshots look like `{provider, ids[], updatedAt}`.
- Each item is `{key, provider, id, title, pages, ready}`.
- `ready` is true only if `gallery()` (26-46) succeeds: there is no `.downloading-<id>` marker, `info.json` exists, and the full pages match `info.count` (Hitomi's count is allowed to be doubled).
- Title is `title_jpn || title || "<provider> <id>"`, so Japanese comes first.
- Today the snapshots list 607 Hitomi ids and 15 IMHentai ids.

**`GET /:provider/:id/manifest`** (80-123)
- Pages are sorted numerically. Each page is `{name, size, offset, width?, height?, url}`.
- Dimensions come from reading image headers only (`image-size-next`, with EXIF orientation applied).
- `revision` is the first 24 hex characters of sha256 over `name:size:mtimeMs` lines (98). **It depends on file modification times on the PC.**
- `thumbnails` is either a full set `{key, kind, revision, pages, bytes}` or `null`. It is null unless every page has a thumbnail (120-121).
- `metadata`: title, title_jpn, artists, groups, parody, characters, tags, language, type, date.
- Errors return 409 with `{error}`.

**`GET /:provider/:id/pages/:name`** and **`/thumbnails/:name`** (125-148)
- The file name is validated against a regex and served with `sendFile`, so the content type comes from the extension.

**Files on the PC**
- Galleries live in `~/Pictures/gallery-dl/<provider>/<id>/`.
- Names are `<prov>_<id>_NNNN.<ext>` and `<prov>_<id>_thumb_NNNN.<ext>`.
- Hitomi names come from the modified gallery-dl extractor (`hitomi.py:47,111-137`; thumbnails from `webpsmalltn`).
- IMHentai names come from `imhentai-downloader.ts:203-237`. Its thumbnail extension can differ from the original's.

**Favorites sync**
- gallery-reader's Hitomi and Imhen apps send `PUT /api/favorites/<provider>` with the complete list `{ids}`, newest first (gallery-reader `worker-entry.ts:34-40`).
- `writeFavorites` writes the snapshot durably and atomically, then calls `requestSync` (`main.ts:118`).
- `FavoritesSyncController.syncOnce` (`favorites-sync.ts:68-96`):
  - removes stale queued items for that provider;
  - `computeDiff` (`diff.ts`) treats an incomplete gallery, or one missing any thumbnail, as needing to resume;
  - queues galleries to resume first, then galleries to download, in snapshot order (89).
- Sync runs at startup (`main.ts:152-156`). It never deletes anything. Only `reconcile` deletes, and it is manual.

**PC download queue**
- One gallery at a time (`queue.manager.ts:183-219`), with a `.downloading-<id>` marker while it runs.
- Hitomi uses a gallery-dl subprocess with `--write-info-json` and `archive=null`. It skips existing files and resumes `.part` files.
- IMHentai uses a visible Chromium (Playwright on Xvfb display :112) to read the manifest, then fetches files 200 ms apart and skips existing files.
- Retries back off 30 s, 2 min, 10 min, 1 h, 6 h, up to 6 attempts (`download-failure.ts`). Retry state is kept in `.retry-state.json`, the queue in `.queue-backup.json`.
- **A failure on a thumbnail file still removes the marker** (`queue.manager.ts:133`). The gallery then shows as ready with `thumbnails: null`.

**TLS**
- The CA is mkcert "mkcert visar@z440", valid until 2035-11-16.
- The server certificate (`~/.local/share/mkcert/pwa/cert.pem`) covers localhost and 192.168.1.197, and **expires 2028-03-05**.

---

## 3. User-facing features and behaviour

**Favorites list**
- 25 galleries per page, from `catalog.slice` (`app.js:342-343`). Order: current Hitomi favorites, then current IMHentai favorites, then saved galleries that are no longer favorites.
- Each row (351-357, `style.css:19-29`) is at least 300 px tall and holds a horizontal strip of 100×300 thumbnails (`object-fit: cover`, `#101010` placeholder).
- **No title is visible once the strip loads.** The title text with a link to page 1 exists only in `.row-message`, which is shown before the strip loads or when loading fails.
- A white italic "i" button (44 px) sits at the bottom right of each row.
- Tapping a thumbnail goes to `/?read=<key>&page=<n>`.
- Rows load their details nearest to the screen centre first (302-306).
- A failed row shows "`<title> · <error>`".

**Catalog updates while viewing** (336-364)
- A change to the key, title or `ready` value of any item rebuilds the page. Rows with the same key and title are reused with their loaded thumbnails.
- Before rebuilding, the position is captured; afterwards it is re-anchored and the strips' horizontal offsets are restored.
- A gallery that briefly stops being ready on the PC moves to the end of the list. This comes from the ready filter plus the "keep saved items" ordering (Models 115, 122).

**Pagination** (365-389)
- Below the 25 rows: a "Favs" link, page numbers, and the current page as a bold span.
- Number links: change the URL with `history.replaceState` (no back entry), rebuild the rows in place, `scrollIntoView` the grid so the **first row** is at the top, reset the strips, then save.
- "Favs" is a real link to `/`. It creates a back entry, and it restores page 1's saved position instead of starting at the first row.

**Info dialog** (390-422)
- A `<dialog>` with `closedby="any"`, a backdrop tap that closes it, and a Close button. Tapping the dialog's own padding also closes it.
- Shows the title (Japanese first), then `metadata.title` if different.
- Rows: Artist, Group, Series, Characters, Type, Language, Date, Pages, Source (the key), Device ("x/N pages · y thumbnails"), Error, and plain tag chips.
- **Series, Characters and Date never appear**, because the Swift model drops parody, characters and date. Error never appears either, because the app never sends an error field.

**Footer**
- Shows "`N Favorites`" and a status line.
- The status line effectively always shows the store's latest message (480 overrides 208). Examples:
  - "564 galleries · x/y pages saved · 22.47 GB total"
  - "Thumbnails · gallery i/n · p/q"
  - "Saved for offline reading. …"
  - "PC unavailable; keeping saved galleries. …"
  - "N downloads waiting for automatic retry. …"
  - "Paused. Downloads continue when the app is active."
- **The Download/Stop button is hidden** (`native.js:1`). Its handler (492-500) sends commands Swift does not handle. It is dead code.

**Reader** (423-450, `style.css:35-39`)
- Pages run full width with no gaps, on black, with 50 svh of padding above and below.
- Each page reserves space using the manifest's width and height (2/3 if missing), then switches to the image's natural size once loaded.
- There is no toolbar, page counter or back button. The page title becomes the gallery title.
- "Opening saved pages…" shows while opening, and "x/y pages saved" if the gallery is incomplete.
- The tapped page is scrolled so its top edge sits at the middle of the screen (444), unless a saved position applies.
- Errors: "Page N: Saved image could not be loaded." overlaid on that page (294).
- Opening a page that is not saved downloads it from the PC immediately with priority (`localResource` → urgent `ensureMedia`). When offline, failed images retry at about 1, 3, 7, 15 s and so on, doubling without a cap, and only while the page is visible.
- Zoom is WebKit's pinch zoom. There are no gesture recognizers of the app's own.
- Landscape is supported (Info.plist 40-45).

**Image loading** (217-300)
- Every thumbnail on the page (about 7,150 on a full page) and every reader page (2,000 has been tested) loads. Nothing is ever released when it goes offscreen.
- At most 8 load at once. The next one is always the nearest to the screen, counting each strip's horizontal scroll. The order is re-sorted at most every 100 ms after scrolling.
- If an image takes more than 10 s, its slot is freed but the image keeps loading.
- Each image is registered for retries.

**Position memory**
- The focal point is the centre of the visible viewport, so it follows zoom (104).
- List: saves the row under the centre as `anchor`, how far down that row the centre is as `fraction`, `y`, and `strips` (each row's horizontal offset, merged with what was saved before).
- Reader: saves the page index as `page` and the `fraction`. It also rewrites the URL to `/?read=k&page=N` with `replaceState` on every save (120).
- When it saves:
  - at `scrollend` on the window, only if not mid-scroll and not hidden (130);
  - at `scrollend` of a strip (191);
  - when the page becomes hidden (192);
  - on any link tap, before navigating (193);
  - on `pagehide`;
  - when Swift asks (resign active / background);
  - in `showPage`, and after restoring.
- Saves are skipped until the position is restored, while suspended, or in a list document that is about to forward to the reader.
- Swift drops saves from any document except the latest one to send `init`.
- Restoring finds the anchor row or page and applies the fraction, otherwise falls back to `y`.
- In the reader, a ResizeObserver on `#reader-pages` keeps the anchor in place as images load, until the first touch, pointer, wheel or key event (182-189).
- A saved reader position is used only if its path exactly matches the current URL (166). Tapping a different thumbnail therefore wins over the saved position.

**Launch restoration** (WebController 191-206)
- The app always starts at `gallery://app/`.
- If the last screen was a list page other than page 1: `redirect` via `location.replace(lastPath)`.
- If the last screen was a reader:
  - if the start document is already the saved list page, it gets `resumeReader`;
  - otherwise it is redirected to the list page, and that page's `init` gets `resumeReader`.
  - With `resumeReader`, the list renders, waits for `whenScreenComplete(1500)` (on-screen rows described and on-screen thumbnails loaded or failed, at most 1.5 s), waits two frames, then `location.assign(reader)`.
- The history ends up as [list, reader], and the first swipe back shows a finished list.
- The black cover hides the documents that are only passing through until `continue` arrives or 3 s pass.
- This logic runs only on the first `init` of the process. A reload after a WebContent crash does not redirect.

**Back and forward**
- Entirely WebKit's edge swipes, in both directions. There are no buttons.
- A new back entry is created when opening a reader, tapping "Favs", or during launch restoration. Paging and reader page changes only rewrite the current entry.
- Returning to a cached page runs `start(true)` (510): it reconnects to Swift, keeps the DOM and both scroll directions, and re-queues images that were cut off mid-load.

**Sync and foreground downloads**
- The catalog refreshes on the first `continue`, whenever the network becomes available, and every 30 s.
- New galleries get their manifests fetched and saved. The download run starts when the number of loaded galleries grows.
- `downloadAll` runs priority galleries first: those whose thumbnails were requested, which with eager loading means every row on the current page. Then come the rest in the order their metadata was loaded.
- The remaining metadata is loaded one gallery at a time, paused while the UI is waiting on anything (110-125).

**When the app is away, locked, or covered**
- Resigning active (Control Center, Face ID, notification shade, app switcher, locking) hands up to 2000 pages to the background session.
- Entering the background pauses: the position is saved, the idle timer is re-enabled, and the app's own work and transfers are cancelled.
- Becoming active always cancels the background transfers. Only after a real background trip does it set foreground again and refresh the catalog and downloads.
- Files committed by the background session are counted when `downloadAll` reaches them, because the size check skips the network.
- Force-quitting stops everything.

**Other behaviour**
- The status bar and home indicator are hidden (38-39).
- The screen will not auto-lock while busy (63).
- iPhone only, iOS 17 and later, no app icon, display name "Gallery Reader".
- The Local Network permission prompt reads: "Automatically sync favorites from your PC and save their images for offline reading."
- Startup timing marks are written to `startup.json`.

---

## 4. Data on the device (`Application Support/GalleryReader`, excluded from backup)

All of these files are written atomically and fsynced, with the default file-protection class.

| File | Format | Notes |
|---|---|---|
| `index.json` | Array of `{item{key,provider,id,title,pages,ready}, revision, thumbnailRevision?, bytes, thumbnailBytes, originalCount, thumbnailCount, originalSavedBytes, thumbnailSavedBytes}` | Written only when a new manifest is saved. **Its counts are stale, usually 0.** |
| `catalog.json` | Array of `GalleryItem` in display order | Falls back to the order in `index.json` |
| `manifests/<key>.json` | Swift-encoded `{key, title, revision, pages[{name,size,offset,url,width?,height?}], bytes, thumbnails?{revision,pages,bytes}, metadata?{title,title_jpn,artists,groups,tags,language,type}}` | **No parody, characters, date, or `thumbnails.key`/`kind`.** Never fetched again once saved. |
| `progress.json` | `{key: {revision, thumbnailRevision?, originalCount, thumbnailCount, extraThumbnails[], extraOriginals?[], originalBytes?, thumbnailBytes?}}` | **The real progress record.** Ignored for a gallery if its revisions don't match its header. |
| `view-state.json` | `{version:1, lastPath, libraryPath, positions:{"library:N"\|"reader:<key>": {path, anchor?, page?, fraction, y, strips{}}}}` | Grows without limit, one entry per page and per gallery ever opened |
| `startup.json` | `{native:{store_load_ms, launch_gallery_records, launch_image_records}, web:[{label, ms}]}` | Diagnostics only |
| Media | `<key>/<revision>/pages/<prov>_<id>_NNNN.<ext>` and `<key>/<thumbRevision>/thumbnails/<prov>_<id>_thumb_NNNN.<ext>` | Original bytes from the source. Each gallery has two revision folders. |
| Old files | `library.json` (single aggregate file) and `navigation.json` | Only from builds before Sep 8. The paid app was installed fresh on Sep 12, so they are probably absent. `load()` would still migrate `library.json` and never deletes it. |

Elsewhere in the container:
- `tmp/CFNetworkDownload_*` files from interrupted foreground downloads.
- The background session's temporary files, held by nsurlsessiond.
- The session `com.visar.GalleryReader.paid.pages`, which may have tasks still pending, each described as `"relative/path\nsize"`.

**WebKit storage: none is used.** No localStorage, IndexedDB, cookies, Cache Storage or service worker, now or in the app's history. The IndexedDB and OPFS storage belonged only to the removed Safari web app, which used a different container. The WebKit folders in the container hold nothing that needs keeping.

**What a rewrite must keep reading**
- `catalog.json`, `index.json`, the manifests, `progress.json` and `view-state.json`.
- The media folder layout, keyed by the revision stored in each manifest.
- If `progress.json` is lost, the truth can be rebuilt from files on disk plus the manifest sizes: about 200k files, checked by size.
- **Never fetch manifests again and re-key folders by the new revision.** Revisions change whenever file times change on the PC, and every gallery would download again (22.47 GB, 101,159 pages, 564 galleries as of Sep 17). To pick up thumbnails or metadata, fetch the manifest but match by file name and size.

---

## 5. Tests, build and renewal

**Swift tests**
- `test.sh` builds `Models`, `GalleryAPI`, `GalleryStore`, `BackgroundDownloads` and `CoreTests.swift` with `swiftc` on macOS only, as a plain executable rather than XCTest.
- Seven offline checks: cancelling a queued transfer; urgent and promoted requests; catalog selection and ordering; rejecting bad manifests; rejecting partial files and replacing atomically; an unreachable server stopping the batch (8 or fewer requests); empty catalogs keeping saved galleries; view state surviving a reload and route validation; a cold start loading the small index and visible gallery first.
- `--integration` runs against the real PC.
- `BackgroundDownloads`, `WebController`, `LocalFiles` and the whole UI have no tests. The Playwright test of the native UI and restoration was deleted on Oct 3 (`9fde8e1`).
- `StartupBenchmark` and `TransferBenchmark` are run by hand and have no script.

**Server tests**
- `npm test` runs 16 tests across offline-api, diff, favorites-store, durable-file, gallery-delete, retry-state, web-ui and imhentai-downloader.
- `test:offline` runs 3 tests that execute the shared helper section of `app.js` and check `app.js` for exact text strings, including indentation. **They pass on the current tree; I ran them read-only.**

**Build**
- `build.sh` runs prepare-web, requires macOS and `LocalCA.cer` (which is gitignored), and builds the **Debug configuration (`-Onone`)**.
- `DEVELOPMENT_TEAM`, `GALLERY_BUNDLE_ID` and `SIGNING_DEVICE` (the last switches to scheme plus device destination) are passed in by the environment.
- The project default bundle id is `com.visar.GalleryReader`. The shipping build is `com.visar.GalleryReader.paid` under team `65U58U86DD`, phone UDID `00008101-000639912881401E`, build 11, version 1.0.

**Renewal**
- `renewal.py` lists the app for the `com.visar.renewal.gallery-downloader` scheduler. Its inputs are `apps/ios/GalleryReader`, `.xcodeproj`, `Resources`, `build.sh`, `prepare-web.sh` and `public/offline`. Any change requires the `deliver.py begin`/`built`/`installed` approval steps.
- The verification JSON files still name the old scheduler `com.visar.installed-apps-refresh`.

---

## 6. Requirements the owner stated

- "downloads keep going while the phone is locked or the app is in the background. when downloads are finished, it works fully offline" / "offline apps are king." (`README.md:6,9`)
- "automatically loads **all completed favorites**", "sync never deletes them", "Display order follows the PC favorites snapshot exactly", "Download completion order never determines display order", "no separate import or download step", "25 galleries per library page", "WebKit's own back/forward navigation gestures and unrestricted viewport zoom. There are no custom swipe, pinch, or double-tap recognizers", "All library feedback and controls are below pagination", "Cold launch restores the last view", "Explicit thumbnail selections override a saved reader position", "updating the same app bundle preserves downloaded files" (`apps/ios/README.md:3-11,38,91-95`)
- "paginated thumbnail strips and a content-only full-width reader. No search, saved-search, import/export, or favorite-edit heart… Reader navigation should use real document navigation and native swipe-back/bfcache"; "All thumbnails must be downloaded from their source. Do not resize originals"; "Preserve existing gallery identities and original revisions" (`decisions.md:5-7`)
- Eager images: "with no viewport window and nothing released offscreen, the ones on screen first: eight at a time…" (`PAID-NATIVE.md`, `app.js:217-219`, "September 17"). Earlier: "Removed both IntersectionObservers, offscreen source/blob release… WebKit owns decoding."
- "Control Center or Face ID leave downloads and the catalog untouched… A changed catalog keeps the rows it still has… Page numbers replace the rows in place and start at the first row, as in Hitomi and Imhen" (`PAID-NATIVE.md`; commit `2c3b479`). gallery-reader does the same with `grid.scrollIntoView()` (`paginated-grid.ts:70`).
- "a relaunched reader returns to a finished list… so the first swipe back no longer shows the list filling in" (commit `69891ad`).
- "All images and image links disable callouts, selection and dragging" (`2f59d0b`).
- "Keep the offline UI's scroll-settle and image-retry helpers faithful to gallery-reader's" (`notes.md:23`). Only scroll checkpoints and image retry were approved for that sync; the other decisions stayed, "including early restore handling, synchronous list construction, pagination/UI, favorites, retention and polling" (Sep 13 notes).
- From the removed web-app docs: "No search, saved searches, import/export, hearts, reader toolbar, or custom Back button"; "No synthetic Back UI or SPA history emulation"; "Japanese titles take precedence". Also: no push entitlements or background modes, no custom icons.

---

## 7. Hidden dependencies

1. **Back-forward cache (`pageshow` persisted, `pagehide`).** Used heavily: `app.js:501-510`, 165, 334, and `onSettledScroll` 12-13.
   - The list's DOM, loaded thumbnails, vertical scroll and strip offsets survive the reader only through this cache.
   - If WebKit drops the cached page (memory pressure, process death, its own limits), the list reloads from `view-state.json` and fetches every thumbnail again, with a visible fill-in.
   - In-flight image loads are cut off at `pagehide` and re-queued afterwards (507).
   - Native rewrite: keep the list controller alive in the navigation stack.
2. **WebKit history, swipe gestures and snapshots.** Used: WebController 47, links, `replaceState` (`app.js:120, 383`), `location.replace`/`assign` (`native.js:24,28`).
   - The back stack exists only within a session. A cold start rebuilds just [list, reader].
   - **The forward swipe (from the right edge, reopening the last reader) has no `UINavigationController` equivalent.**
   - `whenScreenComplete` exists only because WebKit snapshots the list when the reader opens.
   - The current reader page lives in the history entry's URL.
3. **`history.scrollRestoration` / WebKit's own scroll restoration.** Not set, so it is `auto`.
   - On non-cached back navigations and on crash reloads, WebKit restores pixel scroll and zoom first. The app's anchor restore runs later and usually wins.
   - The result is double jumps, and the pixel offset is the fallback if the app's restore fails.
4. **The app's own scroll anchoring.** Used: held anchor plus ResizeObserver on the reader only (131-146, 182-189), sizes reserved from the manifest (437), natural size after load (288), strip offsets (324, 362).
   - It fights layout shifts until the first touch. Nothing re-anchors the list; it relies on fixed 300 px rows.
   - Native rewrite: lay pages out from manifest width and height, which is already stored.
5. **Zoom, pinch, `visualViewport`, ignored scale limits.** Used: WebController 45, `index.html:5`, `app.js:104`.
   - Zoom scales the whole document, list included, and is never saved.
   - Double-tap zoom behaviour is whatever WebKit decides (unclear with ignored scale limits; verify).
   - Native rewrite needs `UIScrollView` zooming with a matching focal point.
6. **Image decoding and memory.** Used: eager loading of about 7k thumbnails and 2k originals, `decoding='async'`.
   - WebKit evicts decoded bitmaps itself and caches by URL.
   - A native port that holds every decoded `UIImage` would run out of memory. "Eager" has to mean every file loaded and ready nearest-first, with a bounded decoded cache.
7. **Image-retry and cancelled loads.** Clearing `src` before reassigning, the `?retry=` cache-buster (its comparison relies on how WebKit reports the custom-scheme origin; unclear), polling, and the 10 s timeout. All of these exist because WebKit sometimes fires neither `load` nor `error` (gallery-reader `image-retry.ts:99,102`).
8. **WebContent process death.** WebController 235 calls `reload()`.
   - The back-forward cache is lost and back entries reload fresh.
   - There is no redirect logic and no cover.
   - Eager pages raise the risk of the process being killed for memory.
9. **WebKit-owned storage (localStorage, IndexedDB).** Not used. Nothing to migrate.
10. **Timers, animation frames and visibility when backgrounded.** Used:
    - `start` and `continue` wait on two animation frames (490, 511), retries skip hidden pages (48), settled saves skip hidden pages, and the final save depends on the WebContent process still running when Swift asks.
    - Animation frames don't fire in a background launch, so `documentReady` stays false. That accidentally keeps a background relaunch, which still builds the whole web view, from starting downloads.
11. **Custom scheme handler.** Used: LocalFiles (240-265).
    - The whole file is delivered on the main thread.
    - It guards against calling into a request WebKit has already stopped (251).
    - **When WebKit stops a request (navigation, `src` removal), that cancels the shared download task** (GalleryStore 545). That can cancel a page `downloadAll` is also waiting on, which shows up as a spurious "N downloads waiting for automatic retry".
    - `crypto.randomUUID` only works because WebKit treats `gallery://` as a secure context.
12. **Recent CSS and JS features.**
    - `scrollend` is critical: if it never fires, settled saves stop. It shipped in WebKit only recently (verify the version).
    - `crypto.randomUUID` is critical: if it throws, there is no bridge at all.
    - Less critical:
      - `closedby` on the dialog, which has a backdrop-tap fallback;
      - `:has()` in the callout rule;
      - `aspect-ratio` and `svh`;
      - `queueMicrotask`, `Array.at`, ResizeObserver, `visualViewport`, `showModal`;
      - `scrollbar-width` (with a `-webkit-` fallback);
      - message handlers with replies and `callAsyncJavaScript` (iOS 14), `isInspectable` (16.4).
13. **Selection and callouts.** Only images and image links are covered (`style.css:1-7`).
    - Title links, status text and the dialog can still be selected, and long-pressing a title link shows WebKit's link preview.
    - `.hs-thumb:hover` (opacity 0.8) can stay stuck after a tap.
14. **Momentum and overscroll.** WebKit defaults: page bounce, strip momentum, scroll chaining.
    - Dragging a strip near the left edge triggers the back swipe instead.
    - The page runs edge to edge (no automatic safe-area insets); only the footer pads for safe areas.
15. **The PC server and bundled CA.**
    - Hard-coded IP. Server certificate expires 2028-03-05.
    - Local Network permission and `NSAllowsLocalNetworking`.
    - Revisions depend on file modification times on the PC.
    - Thumbnails are all-or-null, and the app never re-fetches a manifest, so a gallery saved without thumbnails never gets them.
16. **iOS behaviour.**
    - Background tasks are created while the app is still active, because tasks started from the background are deferred at iOS's discretion.
    - A custom-CA certificate check inside a background session needs the app's own delegate, so progress depends on iOS waking the app for it (verify).
    - Whether local-network access works for background sessions also needs verifying.
    - Resign-active and background are handled separately. Control Center hands off up to 2000 tasks and cancels them seconds later, with the app's own downloads running at the same time. The 30 s poller can still refresh the catalog while Control Center is down.
    - Files use the default protection class, which allows writes while locked after the first unlock. **Switching to `.complete` would break commits while locked.**
    - `foreground` starts true even on a background relaunch.
    - The app has no scene manifest. Apple has said apps built with the SDK after iOS 26 must adopt the scene lifecycle (verify against the Mac's Xcode).
    - The background session id `<bundle>.pages` must be reused or deliberately invalidated.

**Places the code visibly works around WebKit**
- The `pagehide` release and re-queue of images.
- The "Keep DOM… through bfcache" check in `renderCatalog`.
- "Existing bfcache document already has its exact position" in `receive`.
- `whenScreenComplete` plus the black cover.
- The capture listener for strip `scrollend`, because it doesn't bubble.
- The image-retry tricks.
- The held anchor that releases on input.
- The two-frame waits before booting.
- The inline script that picks list or reader before `app.js` runs.
- CSS callout, selection, drag, tap-highlight and scrollbar suppression.
- The guard against calling a stopped scheme request.
- `reload` after process death.
- `ignoresViewportScaleLimits`, opaque black and no inset adjustment to avoid white flashes.

**Other problems worth carrying into the rewrite**
- A corrupt `index.json` makes `load()` throw, and the whole UI fails with no recovery.
- `openReader`'s reaction to progress updates (471), and the `progress`, `timing` and `notice` message types, are dead.
- Stale docs:
  - README: "Only visible images are requested" (19);
  - README: "throttled during scroll" (90);
  - README: "native-bridge" tests (109);
  - the verification JSONs name the old scheduler.