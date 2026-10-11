I've read every tracked source file, doc, script and verification JSON, plus the git history that matters (169 commits, clean tree at 946801f). Nothing was modified. All paths below are absolute; `R` is shorthand for `/home/visar/Documents/work/manga/gallery-reader`.

# Inventory: Hitomi and Imhen, ahead of a native rewrite

## 0. Key findings

1. **Swift is only a thin host (359 lines).** It provides the WKWebView, a `gallery://` scheme handler, a URLSession proxy, an on-disk image cache and storage of WebKit's `interactionState`. Everything else runs in WebKit: UI, routing, storage, provider parsing, backup and sync. That is about 1,950 lines of TypeScript plus 373 lines of CSS, split between the page and a Blob web worker.
2. **Neither provider needs a JavaScript engine or a browser.**
   - Hitomi's `gg.js` is parsed with regexes, Nozomi index files are binary big-endian uint32 lists, and `galleries/<id>.js` is a JSON assignment.
   - Imhentai is HTML parsed with plain string searches.
   - Both need a correct `Referer` header. Neither needs a browser user agent, cookies, or anti-bot handling.
3. **The authoritative user data is in WebKit IndexedDB** under origin `gallery://app`, in two databases. Native code cannot easily read it. Migration needs either a one-time hidden WKWebView at the same origin (same bundle ID, same scheme and host) or a PC backup restore. The PC backup format must stay the same shape.
4. **Back and Forward exist only as WebKit's edge swipes.** There is no back button anywhere, and the reader has no on-screen controls. The bfcache silently provides horizontal strip offsets (never saved), the info modal still being open after Back, the page each home entry was showing, thumbnails that are already loaded, and the instant feel.
5. **Reader position exists only in the URL** (`page`, `f`) inside WebKit's session history, saved in the `interaction-state` file. It is not in IndexedDB and not in PC backups, although `notes.md:35-36` says it is.
6. **Several docs describe the old Safari-userscript behaviour.** Examples: hash pagination, `hashchange`, `pagereveal`, Imhentai having no bfcache, and saving 100 ms after `scrollend`. The current code differs; see section 9.

---

## 1. Architecture

### Native side: `R/apps/ios/GalleryReader`

- **`AppDelegate.swift`** (18 lines)
  - Uses the old AppDelegate lifecycle; there is no UIScene.
  - Forces dark mode and makes `WebController` the root.
  - `applicationWillResignActive` and `applicationDidEnterBackground` both call `saveSession()` (lines 16-17).
- **`WebController.swift`** (123 lines)
  - Data root is `Library/Application Support/GalleryReader`; the session file is `interaction-state` (14-15).
  - Reads `GalleryServerURL` and `ReaderProvider` from Info.plist and derives the provider origin (16-18).
  - WebView config (27-38):
    - registers the scheme handler `LocalFiles` for `gallery`
    - adds the message handler `gallery` in the `.page` content world
    - sets `ignoresViewportScaleLimits = true`, `allowsBackForwardNavigationGestures = true` and `isInspectable = true`
    - sets `contentInsetAdjustmentBehavior = .never`
  - Hides the status bar and auto-hides the home indicator (23-24).
  - On launch, applies the saved `interactionState` if the file exists; otherwise loads `gallery://app/` (41-46).
  - The navigation policy allows only `gallery://app` and sets `restoring` for back/forward navigations (86-91).
  - `didFinish` calls `saveSession` (92). If the WebContent process terminates, it calls `webView.reload()` (93).
  - The `LocalFiles` scheme handler is at 98-123.
- **`GalleryAPI.swift`** (121 lines)
  - `LocalTrust` (6-31) trusts the bundled `LocalCA.cer` as the only anchor, and only for the PC host. It still checks hostname and validity.
  - `TransferGate` (35-69) allows 12 concurrent transfers. Image requests are "urgent" and jump the queue.
  - `GalleryAPI` (77-121) uses two URLSessions:
    - **PC session:** used for the host of `GalleryServerURL`. It never retries.
    - **Public session:** has `waitsForConnectivity` turned on.
    - **Shared settings:** 25 s request / 90 s resource timeouts, 12 connections per host, a shared `URLCache` of 8 MB memory / 64 MB disk (87-94).
  - Only `https` URLs are accepted (98).
  - `Referer` is the request's https referrer, otherwise `<origin>/` (102-103).
- **`GalleryStore.swift`** (55 lines), an actor
  - `fetch` returns a JSON string `{status, headers, body: base64}` (20-25).
  - `localResource` serves `/`, `index.html`, `app.js` and `style.css` from the bundle's `Web/` folder (51-53).
  - It also serves `/image?url=<https URL>` (28-50):
    - cache file is `cache/<sha256(url)>` plus a `.mime` sidecar
    - one download per URL with a set of waiters; when the last waiter cancels, the download stops (16-19, 45-49)
    - only HTTP 200, `image/*`, non-empty responses are cached (39-40)
    - nothing is ever evicted
- **`Models.swift`** (42 lines)
  - `ReaderError`.
  - `retryableResponse`: status 408/429/500/502/503/504, honouring `Retry-After` (13-24).
  - `recoverNetworkRead`: retries forever with backoff from 1 s doubling to 30 s, on transient `URLError` codes; cancellation stops it (25-42).

### Web side: `R/src`

- **`app/`**
  - `app.ts`: entry point; installs the fetch bridge, calls `init`, then routes (13-17).
  - `fetch.ts`: replaces `fetch` for https URLs with the native bridge.
  - `native.ts`: the `postMessage` bridge and the `gallery://app/image?url=` builder.
  - `worker.ts`: worker entry; its fetch goes through `postMessage` to the page.
  - `index.html`.
- **`core/`**
  - `backup-engine.ts`: worker-side backup protocol and the backup identity database.
  - `pc-backup.ts`: backup UI.
  - `image-retry.ts`, `scroll-settle.ts`, `favorites-sync.ts`.
  - `platform.ts`: the `restoring` flag and reader positioning.
  - `takeover.ts`: left over from the userscript.
- **`core/compute/`**
  - `state.ts`: the main IndexedDB database.
  - `worker-entry.ts`: operation dispatcher.
  - `transport.ts`: lazy worker creation and RPC.
  - `worker.ts`: Blob worker factory and network relay.
  - `context.ts`: referrer.
- **`routes/`**: `home.ts`, `search.ts`, `reader.ts`.
- **`provider/`**: `index.ts`, `types.ts`, `data-provider.ts`, plus `hitomi/*` and `imhentai/*`.
- **`storage/`**: RPC wrappers, the old-localStorage migration, scroll-restore helpers.
- **`ui/`**: `shell.ts`, `gallery-row.ts`, `paginated-grid.ts`, `saved-searches.ts`, `info-modal.ts`.
- **`css/style.css`**: inlined into `app.js` through `?inline` (`shell.ts:4,22-24`).

Build output is `R/apps/ios/build/<provider>/Web/app.js` (about 82 KB), with the worker bundled in as a string.

### How the two sides talk

- **App URLs** (`R/src/provider/index.ts:15-16`, `R/src/routes/reader.ts:45-47`):

  | Route | URL |
  |---|---|
  | Home | `gallery://app/` |
  | Search | `/?q=<encodeURIComponent(query)>&p=<page>` |
  | Reader | `/?read=<provider>-<gid>&page=<1-based>&f=<0..1, 3 decimals>` |

- **Message handler commands** (`WebController.swift:56-84`, called from `R/src/app/native.ts:1-3`). Messages are accepted only from the main frame at `gallery://app`.
  - `init` returns `{"restoring":true}` or `{}` (line 81).
  - `fetch {requestID, url, method, headers, referrer, body}` returns `{status, headers, body(base64)}`.
  - `fetch-cancel {requestID}` cancels it.
- **Fetch bridge** (`R/src/app/fetch.ts:2-22`): https only. It decodes base64 into a `Response`, and an `AbortSignal` sends `fetch-cancel`.
- **Worker network path:** the worker cannot reach `webkit.messageHandlers`. `R/src/app/worker.ts:5-16` posts `{networkId, request}` to the page, which relays it to native (`R/src/core/compute/worker.ts:26-38`).
- **Worker RPC** (`R/src/core/compute/transport.ts:7-30`; operations in `R/src/core/compute/worker-entry.ts:8-87`):
  - provider operations, `hitomi-suggestions`
  - `state-ready`, `state-migrate`, `backup-control`, `favorites-publish`
  - favorites: `favorites`, `favorites-export`, `favorites-json`, `favorite-is`, `favorite-toggle`, `favorite-import`, `home-page`
  - searches and positions: `searches`, `search-save`, `search-remove`, `page`, `page-save`, `scroll`, `scroll-save`
  - Storage reads and writes go through one promise chain in order. Provider, suggestion, backup and publish operations run in parallel (89-99).

### Line counts

| Area | Lines / bytes |
|---|---|
| Native Swift app | 359 / 19 KB |
| Native test (`Tests/NetworkTests.swift`) | 60 |
| `src/app` | 74 |
| `src/core` (excluding compute) | 413 |
| `src/core/compute` | 253 |
| `src/routes` | 186 |
| `src/provider` (index/types) | 87 |
| `src/provider/hitomi` | 460 |
| `src/provider/imhentai` | 426 |
| `src/storage` | 82 |
| `src/ui` | 444 |
| `src/css/style.css` | 373 |
| `server/backups.mjs` + tests + systemd unit | 161 + 71 + 15 |
| `tests/unit` | 603 |
| `apps/ios/scripts` | 155 |

---

## 2. Providers

### Hitomi (`R/src/provider/hitomi/`)

- **Hosts:** `ltn.`, `tn.` and `w<N>.gold-usergeneratedcontent.net` (`constants.ts:1`), plus `tagindex.hitomi.la`.
- **Search** (`decoder.ts:4-17`, `66-126`)
  - Terms are split on whitespace; a leading `-` makes a term negative.
  - Each term maps to a Nozomi file:
    - `language:X` → `n/index-X.nozomi`
    - `female:x` / `male:x` → `n/tag/female:x-all.nozomi` (underscores become spaces)
    - `ns:tag` → `n/<ns>/<tag>-all.nozomi`
    - a bare term → `n/tag/<term>-all.nozomi`
  - The response body is a list of big-endian uint32 gallery IDs (56-64).
  - Fetching and combining:
    - up to 6 requests at once; positive terms are intersected, negative terms removed
    - result order follows the last positive term
    - if any term fails, the whole search fails
    - with no positive terms the result is empty
  - Results are cached in worker memory by query (`data-provider.ts:6,46-62`). Page size is 25; the total is exact.
  - The Nozomi URLs contain raw spaces. Today `new Request` in `fetch.ts:5` encodes them; native code must percent-encode explicitly.
- **Gallery data** (`data-provider.ts:12-22`)
  - Fetched from `ltn…/galleries/<gid>.js` with `Referer: https://hitomi.la/reader/<gid>.html`.
  - Parsed as `text.split('=')[1]`. This breaks if the JSON contains `=` (for example a title like "=LOVE").
  - Fields used:
    - `files[{hash,width,height}]`, `title`, `japanese_title`, `type`, `language`, `date`
    - `artists`, `groups`, `parodys`, `characters`, `tags{tag,female,male}`
- **Thumbnails:** `https://tn…/webpsmalltn/<h[-1]>/<h[-3:-1]>/<hash>.webp`, one per page (139-142).
- **Image URLs need `gg.js`** (`decoder.ts:25-54`, `data-provider.ts:144-152`)
  - `gg.js` is parsed with regexes:
    - `case N: … o = V`
    - `if (g === N) o = V`
    - the default from `var o = N` / `default: o = N`
    - the base path from `b: '…'`
  - Image index = `parseInt(h[-1] + h[-3:-1], 16)`. URL: `https://w<(map[idx] ?? default)+1>.gold-usergeneratedcontent.net/<b>/<idx>/<hash>.webp`.
  - The parsed `gg.js` is cached for the worker's lifetime with no expiry.
  - The `b` path changes over time; `R/apps/ios/image-parity-verification.json` records an old prefix returning 404. That is why URLs are worked out again for each reader page and never saved (`R/notes.md:5-9`).
  - **No JS engine is needed today, but this is the most fragile point.** If Hitomi changes the shape of `gg.js`, the regexes break; evaluating it in JavaScriptCore would be a fallback.
- **Suggestions** (`suggestions.ts:5-26`)
  - Runs in the worker. URL: `https://tagindex.hitomi.la/<field|global>/<c>/<h>/….json`, one path segment per character (space → `_`, `/` → `slash`, `.` → `dot`).
  - 404 means no results. Returns at most 100 `[name, count, namespace]` entries; a new request aborts the previous one.
- **Headers:** Referer `https://hitomi.la/` (forced in `compute/worker.ts:23` and by the native default). The user agent is CFNetwork's default. No cookies are needed.

### Imhentai (`R/src/provider/imhentai/`)

- **Hosts:** HTML from `imhentai.xxx`; images and thumbnails from `m<N>.imhentai.xxx`, taken from the page.
- **Query syntax** (`decoder.ts:38-107`): comma-separated `language:x`, `ns:value` and plain keywords.
  - One namespace only → `/<ns>/<value-with-dashes>/`.
  - Language only → `/language/<lang>/`.
  - Language plus one namespace → keyword search.
  - Otherwise `/search/?lt=1&pp=0&m=1&d=1&w=1&i=1&a=1&g=1&apply=Search&dl=0&tr=0&jp/en/es/fr/kr/de/ru=0|1&key=<keywords joined by ','; _ and - become spaces>&page=N`.
  - With more than one namespace, the namespaces are silently dropped. There is no negation.
- **Search results** (`data-provider.ts:162-185`)
  - IDs come from `href="/gallery/<id>/"`.
  - Page count is the largest `page=N` in `class='page-link' href='…'`.
  - Total = pages × 20 (approximate); page size is 20.
- **Gallery page** `https://imhentai.xxx/gallery/<gid>/` (11-64)
  - The image base comes from the first `data-src`.
  - The JSON inside `$.parseJSON('…')` is extracted as a string, not executed. It maps page → "ext,w,h", where ext is j/p/g/w/a.
  - Image URL is `<base><n>.<ext>`. Thumbnail URLs come from the listed `<n>t.<ext>` entries, with a template for the rest.
  - Fallback when the JSON is missing: count from `load_pages` or `/view/` links, assume `.jpg`, size 0×0. That means no aspect-ratio placeholder, so layout shifts as images load.
- **Metadata** (66-113): `<h1>`, `class="subtitle">`, the `class="galleries_info"` block (`href='/<ns>/…'` links with trailing counts removed, `/category/`), and `>Posted: `.
- **Cookies:** `credentials:'include'` (`decoder.ts:5`) is ignored by the bridge; URLSession's shared cookie store applies instead.
- **Info-modal search links** (`data-provider.ts:215-218`): `language:<lang>,<value>`, so the namespace is dropped.
- **No autocomplete.**

Links in the info modal go through the provider's own site URL and then back to an app query via `matchRoute` (`R/src/provider/index.ts:17-22`). Provider capabilities and cache headers are summarised in `R/investigation/sites.md`.

---

## 3. User-facing features and behaviour

### Global

- Black background, forced dark mode, status bar hidden, home indicator auto-hidden.
- Content extends under the safe areas.
- Portrait and landscape (`R/apps/ios/Resources/Info.plist:42-47`).
- Document title is "Hitomi" or "Imhen".
- No icons.

### Home and search screens

Both are built by `R/src/ui/shell.ts:98-111` and contain:
- a search textarea (the Search button is hidden)
- the saved searches
- a count line: "~N Favorites" or "~N Results"
- the gallery rows
- a bottom bar with a "Favs" link and **every** page number (`R/src/ui/paginated-grid.ts:44-77`). Hitomi `language:japanese` gives about 21k page links.

### Gallery rows

(`R/src/ui/gallery-row.ts`, `R/src/ui/paginated-grid.ts:32-38`)
- A 300 px placeholder per gallery, in provider order.
- Then thumbnails of **every** page of the gallery:
  - 100×300 px, center-cropped
  - horizontally scrollable with no scrollbar
  - `loading=lazy`, added 32 at a time with a yield between batches
  - each registered for retry
- Tapping a thumbnail opens the reader at that page (35-37).
- Bottom-right overlay:
  - an "i" button that opens the info modal
  - a heart button: shows "…" until the favorite lookup returns, then ❤️ or 🤍 (52-84)
- A failed row shows `Gallery <gid>: <message>`.

### Favorites

- Toggling prepends the gallery (newest first) or removes it (`worker-entry.ts:52-58`).
- The row is not redrawn.
- A favorites sync is scheduled.

### Pagination

- Tapping a page waits for it to render, then calls `grid.scrollIntoView()`, which puts the first row at the top instantly (`paginated-grid.ts:68-71`).
- **Search:** results come from cache; the screen redraws in place, the URL is replaced with `history.replaceState`, the saved search is updated with the new page, and the saved-search list redraws (`R/src/routes/search.ts:7-26`).
- **Home:** the page is saved to the database (`state.page`); the URL does not change (`R/src/routes/home.ts:9-26`).

### Home extras

(`R/src/routes/home.ts`)
- 25 favorites per page; opens on the saved page.
- **Import / Merge:** takes every run of digits in the pasted text, prepends new IDs in paste order, and shows "Added X of Y IDs".
- **Export:** puts space-separated IDs into the textarea.
- Redraws when a restore fires `reader-data-restored`.
- Starts the PC backup after the content is shown (line 104).

### Search input

(`R/src/ui/shell.ts:27-68`)
- Enter submits (not with Shift, and not while a Japanese IME is composing).
- An empty query becomes `language:japanese`.
- Submitting opens the query on its saved page; this adds a history entry.
- The textarea grows to fit its content (`field-sizing`).

### Hitomi autocomplete

(`R/src/provider/hitomi/autocomplete.ts`)
- Suggests for the term at the cursor, keeping a leading `-`.
- Each suggestion shows name (namespace) and count.
- Tapping, or Arrow keys then Enter, replaces the term with `ns:name_with_underscores ` and keeps focus.
- Escape, tapping outside, or leaving the page clears the list. Results that arrive late are dropped.

### Saved searches

(`R/src/ui/saved-searches.ts`)
- Most recent first.
- Shows 3, with a "Show N more" button. The expanded state lasts only for the current page.
- × removes a search. Tapping one opens it on its saved page (new history entry).
- Every search render saves the search: it moves to the top and records the page (`worker-entry.ts:73-76`).

### Info modal

(`R/src/ui/info-modal.ts`)
- Built on `<dialog>` with `showModal`, `closedby="any"`, a manual backdrop-tap close, and a Close button.
- Shows Loading… and error states.
- Fields: Japanese title, title, Artist, Group, Series, Type, Characters, Language, Pages, Date, Tags (with `female:` / `male:` prefixes on Hitomi).
- Each value is a link that opens a search in the gallery's language (the language link itself uses no extra language). This adds a history entry.

### Reader

(`R/src/routes/reader.ts`, `R/src/core/platform.ts`)
- 50svh padding above and below.
- One full-width `<img>` per page, with aspect ratio from the metadata, `loading=lazy`, added 32 at a time.
- **Positioning happens before image URLs are known:** it scrolls to `offsetTop + f×height − innerHeight/2` of image `page−1`, unless `restoring` is set.
- It then works out the URLs (`gg.js`) and assigns `src`.
- **On each scroll end** (`scrollend`, page visible) it:
  - hit-tests the screen center
  - computes `f`
  - calls `replaceState` with `?read=…&page=…&f=…` (37-48)
- No on-screen controls, page counter, tap zones or zoom controls. Zoom is WebKit pinch.
- A gallery with no images shows a message. If the gallery fails to load, the screen stays blank; there is no error message (`R/src/app/app.ts:19`).

### Image loading and retries

- **Who decides what:** WebKit decides when lazy images load.
- **Native:**
  - one download per URL, cached on disk
  - transient errors and 408/429/5xx are retried forever
  - images get priority over other requests
- **JavaScript** (`R/src/core/image-retry.ts`):
  - polls once a second, while the page is visible, for images that are complete with `naturalWidth == 0` (failed)
  - each image backs off by doubling
  - reassigns `src` after clearing it

### Position memory

| Route | What is saved | Where | Saved when | Restored when |
|---|---|---|---|---|
| Home | Favorites page | IndexedDB `state.page` | Every render | Every fresh page load |
| Home | Vertical scroll | IndexedDB `state.scroll["/"]` | `scrollend` while visible (`shell.ts:89-95`) | Next frame after render, unless the user already touched or scrolled (`R/src/storage/preferences.ts:13-40`) |
| Search | Page | URL `p` (replaced) and the saved search's page | Every render | — |
| Search | Vertical scroll | `state.scroll["/?q=…&p=N"]` | As for home | As for home |
| Reader | Page and `f` | URL only, persisted through WebKit's back-forward list and the `interaction-state` file (saved on `didFinish`, resign-active, background) | Every scroll end | See below |

- **Never saved:** horizontal strip offsets, whether the info modal was open, the saved-search expansion, zoom (except inside WebKit's session data).
- **Restore on relaunch:** WebKit restores the back list and loads the current entry.
  - Home and search pages reload and apply their IndexedDB scroll (`R/apps/ios/robustness-verification.json` shows scroll 7927 before and after a cold launch).
  - The reader uses `page`/`f` only when `restoring` is false: a new open, or the reload after a WebContent crash.
  - On back/forward loads that miss the bfcache, and very likely on a cold launch, `restoring` is true. The app then leaves scrolling to WebKit, which restores before the async placeholders exist and effectively lands at the top. `PORT.md:24-25` says these cold "reset scroll positions" are accepted.
  - I couldn't confirm which navigation type WebKit reports for an `interactionState` restore. Check on the phone.

### Back and Forward

- **Entries that add history** (navigations via `location.href`):
  - thumbnail tap (`gallery-row.ts:36`)
  - saved search (`saved-searches.ts:38`)
  - search submit (`shell.ts:53`)
  - info-modal link (`info-modal.ts:9,11`)
  - "Favs" (`paginated-grid.ts:53`)
- **Entries that are replaced:** search pagination and reader position.
- **When a page comes back from the bfcache:**
  - the search input is reset to that page's query (`shell.ts:84-86`)
  - the home backup runs again (`R/src/core/pc-backup.ts:120`)
  - the scroll gate is reset (`scroll-settle.ts:12`)
  - the worker is kept alive (`compute/worker.ts:11`)

### PC backup and restore

(`R/src/core/pc-backup.ts`, `R/src/core/backup-engine.ts`)

Every home load, and every return to home from the bfcache, runs one backup under a `navigator.locks` lock named `gallery-reader:<provider>`.

1. **No identity yet:** it requests the backup list (GET). If the PC is unreachable, it stops silently.
2. **Setup dialog** (shadow DOM). It contains:
   - "On this phone: N favorites, M saved searches, K scroll positions"
   - a name field (default "iPhone", max 80 characters)
   - **Back up this phone**
   - a picker listing each backup's current and previous snapshot as `label · id8 · generation · local date`, with "On PC: stats"
   - **Restore from PC** (disabled when there are no backups)
   - a note that restore replaces local data and creates a new independent backup
   - **Later**
3. **The choice:**
   - Restore replaces the whole local state, then fires `reader-data-restored`.
   - Either choice then creates a new UUID identity with `revision: null`.
4. **Save:** capture the state, PUT it, and record the returned revision.
5. **Messages:**
   - First setup shows the toast "Backed up to PC: label · provider\nstats", which disappears after 12 s.
   - Later backups are silent and clear any earlier error toast.
   - Errors show a toast that stays until tapped, with separate wording for database and PC failures. The wording still mentions Safari (line 104).
   - A 409 resets the identity, so setup is offered again next time.

### Favorites sync to Gallery Downloader

(`R/src/core/favorites-sync.ts`, `R/src/core/compute/worker-entry.ts:30-42`)
- Runs 100 ms after a favorite toggle or a merge that added IDs, and right after each successful home backup.
- Only runs if this phone is enrolled (its backup identity has a revision).
- `PUT https://192.168.1.197:7777/api/favorites/<hitomi|imhentai>` with body `{"ids":[newest first]}` and `Content-Type: application/json`.
- No key, 8 s timeout, no retry. Failures are logged and repaired by the next full send.

### Lock and background

- Resign-active and background both save the session.
- No background tasks, no `beginBackgroundTask`, no `applicationDidBecomeActive` handling.
- On the web side, while hidden:
  - scroll saving stops
  - no IndexedDB transaction is started (`shell.ts:87-91`)
  - image retries pause
  - late autocomplete results are ignored
- Database open and transactions have 10 s timeouts and commit explicitly (`R/src/core/compute/state.ts:10,37-51`).
- When WebKit kills the WebContent process, the current page reloads.

### Other

- On first run there is a one-time, read-only migration from old localStorage (`R/src/storage/initialize.ts`). It is always empty at the `gallery://app` origin.
- If storage fails to load, the grid shows "Could not load local reader data…" (`shell.ts:106`).
- **External workflow to keep working:** `README.md:13-21` describes using an iOS OCR Back-Tap shortcut with Shirabe Jisho on top of the reader.

---

## 4. Data, and what a rewrite must migrate

### Stored by WebKit at origin `gallery://app` (default persistent data store)

1. **IndexedDB `gallery-reader-data`**, version 1 (`R/src/core/compute/state.ts:2-29`)
   - Object store `state`, one record with key `'reader'`:
     - `favorites`: number[] of positive safe integers, newest first
     - `searches`: `{query: string, page?: positive int}[]`, most recent first
     - `page`: int ≥ 1 (the favorites page)
     - `scroll`: map of string → finite number ≥ 0
   - Scroll keys are `location.pathname + location.search`, for example `"/"` or `"/?q=…&p=2"`. Older keys from the userscript era (such as `/reader/42` or `/search.html?…`) may arrive through restores.
   - The map is never pruned.
2. **IndexedDB `reader-pc-backup-state-v1`**, version 1 (`R/src/core/backup-engine.ts:11-51`)
   - Store `identities`, key `gallery-reader:<provider>`, value `{id: uuid, label, revision: string | null}`.
   - Enrolled means `revision` is not null.
3. **localStorage:** read only, for the old keys `gallery-reader-favorites-v1`, `saved_searches`, `favorites` and `scroll-pos-*` (`R/src/storage/initialize.ts:6-19`). Never written.
4. **Not used:** Cache API, service workers, `navigator.storage.persist()`.

### Stored by native code

- `Library/Application Support/GalleryReader/interaction-state`: WebKit's opaque session blob (`WebController.swift:49-55`).
- `Library/Application Support/GalleryReader/cache/<sha256(url)>` plus `.mime`.
  - Never evicted.
  - Included in device backups.
  - Hitomi image URLs include the changing `gg` path, so the same page gets cached again under new keys.
- `URLCache` in the default Caches location, and `HTTPCookieStorage.shared`.
- Possibly an old `view.json` in the same folder. Builds before 13 stored per-route positions there, including strip offsets; it was removed in commit 82ee173 and the file was never deleted.

### What a rewrite must migrate

- **Main state and backup identity:** carry over both IndexedDB records so that favorites, saved searches, the page, list scroll positions and silent backups into the same PC file all survive. Two ways:
  - **(a) One-time hidden WKWebView** that loads a migration page at the **same origin** and posts both records to native.
    - Requires installing in place under the same bundle IDs (`com.visar.HitomiReader.paid`, `com.visar.ImhenReader.paid`), the default data store, and scheme `gallery` with host `app`.
    - WebKit's on-disk IndexedDB is SQLite holding values in WebKit's own serialised format, so reading it directly from Swift is impractical.
  - **(b) PC "Restore from PC".** This creates a new backup identity, which is acceptable.
- **Optional:** load `interaction-state` into a hidden WKWebView and read `backForwardList` to recover the last reader URL (`read`, `page`, `f`).
- **Image cache:** reusable as-is (the key is the SHA-256 of the URL string), or drop it.

### Backup format the PC server stores

The rewrite must keep reading and writing this exactly. Server: `R/server/backups.mjs`.

- **Endpoints and auth:**
  - `GET /api/reader-backups/gallery-reader/<hitomi|imhentai>` returns all backups for that provider, newest `current.savedAt` first.
  - `PUT …/<uuid-v4>` with body `{label (1-80 characters, trimmed), baseRevision: string | null, data}`.
  - Header `X-Reader-Backup-Key: <64 hex characters>`. Every response is `Cache-Control: no-store`. No CORS headers.
- **`data`:** `{version: 1, indexedDB: {favorites, searches, page, scroll}}`. Validated by `contentCount` (46-54) and on the client by `validateState`.
- **Stored file:** `~/.local/share/gallery-reader/backups/<provider>/<id>.json` containing `{id, label, current: {revision: uuid, savedAt: ISO, data}, previous: … | null}`.
  - Written durably: temp file, fsync, rename, fsync of the directory.
  - Folder mode 0700, file mode 0600.
- **Rules:**
  - identical data returns the existing backup without rotating
  - a stale `baseRevision` gets 409
  - empty data cannot replace a non-empty backup (409)
  - missing or wrong key gets 401; bad input gets 400; bodies over 5 MB get 413
- **Access key:** `~/.local/share/gallery-reader/backups/access-key`, created on first start. Today it is baked into `app.js` at build time.
- **Client behaviour to preserve:**
  - an unreachable PC (network error, 8 s timeout, HTTP 5xx, or a dropped response body) is silent
  - other HTTP errors are shown
  - snapshots are validated before restore is offered (an invalid one makes the whole list fail)

---

## 5. Tests

- **Vitest** (`R/tests/unit`): 12 files, about 48 cases. The verification JSONs say 50, an older count. Tests run with Hitomi selected (`R/vitest.config.ts`).
  - `backup-network`: unreachable, stalled, dropped and 5xx are silent; 401 and bad JSON are errors.
  - `backup`: old-key migration and validation.
  - `hitomi-autocomplete`: replacing the term, stale results, Enter.
  - `hitomi-search`: concurrency, result order, failures, suggestion URL.
  - `home-startup`: restore isn't blocked by a pending page save.
  - `imhentai-thumbnails`: parsing thumbnail and original URLs.
  - `pc-backup`: 9 cases covering setup, restore, silent saves, errors, Later, lost acknowledgement.
  - `reader-scroll`: midpoint bookmark and `f`; a reload uses `f`.
  - `scroll-restore`: user input cancels the restore.
  - `scroll-settle`, `startup` (Hitomi hash routes), `visible-scroll-save`.
- **Server** (`R/server/backups.test.mjs`, `node --test`): isolation, current/previous rotation, idempotent retry, conflicts, file modes, key required, no-store, no CORS, 404 and 400 cases.
- **Native** (`R/apps/ios/Tests/NetworkTests.swift`): not an XCTest target. `R/apps/ios/scripts/test-network.sh` compiles it with `swiftc` on the Mac. It covers:
  - recovery from a lost connection and a 503
  - PC requests and writes not retrying
  - cancellation, and cancelled `TransferGate` waiters
  - one download per URL
  - the disk cache surviving a new store
- **Device checks:** ios-tools inspector with `R/apps/ios/scripts/inspector-snapshot.js` (`PORT.md:74-81`). This depends on `isInspectable` and needs a replacement after the rewrite.
- **`*-verification.json`** files are evidence records, not runnable scripts. `R/test.txt` is the frozen manual flow list.

---

## 6. Build, deploy, renewal

- **Provider registry** (`R/apps/ios/providers.json`):

  | Provider | Name | Bundle ID | Origin |
  |---|---|---|---|
  | `hitomi` | Hitomi | `com.visar.HitomiReader.paid` | `https://hitomi.la` |
  | `imhentai` | Imhen | `com.visar.ImhenReader.paid` | `https://imhentai.xxx` |

- **`R/apps/ios/scripts/build.mjs`** (`npm run build:ios -- <provider> [--prepare-only]`)
  - Uses esbuild with target `safari17`.
  - Build-time values (17-20):
    - `__IOS_PROVIDER__`, `__IOS_ORIGIN__`
    - `__READER_BACKUP_URL__`: `VITE_READER_BACKUP_URL`, default `https://192.168.1.197:7722`
    - `__READER_BACKUP_KEY__`: env, or the server's access-key file
    - `VITE_GALLERY_SERVER_URL`: default `:7777`
  - Writes `build/<p>/Web/` and `build/<p>/provider.xcconfig` with `READER_DISPLAY_NAME`, `READER_PROVIDER`, `PRODUCT_BUNDLE_IDENTIFIER` and `PRODUCT_NAME` (32).
- **`R/apps/ios/scripts/build-provider.py`**
  - Takes the shared signing lock `~/Library/Caches/ios-app-refresh/signing.lock`.
  - Copies `Web` into the **shared** staging folder `Resources/Web`, so builds must never overlap.
  - Runs `xcodebuild` (Release, with the provider xcconfig).
- **Info.plist** (`R/apps/ios/Resources/Info.plist`)
  - `ReaderProvider=$(READER_PROVIDER)`.
  - `GalleryServerURL=https://192.168.1.197:7777`, hardcoded.
  - `NSAllowsLocalNetworking` and `NSLocalNetworkUsageDescription`.
  - No icons.
- **Xcode project:** deployment target iOS 17.0, Swift 5 with strict concurrency, `CURRENT_PROJECT_VERSION=14`.
- **`R/apps/ios/scripts/deploy.py`** (actions sync, build, status, install)
  - Talks to the Mac at `192.168.1.198`; phone UDID `00008101-000639912881401E`; team `65U58U86DD`.
  - Install checks the plist keys, that there are no icons, the signature, the team, the phone, and profile expiry more than 45 days away.
  - It then installs in place, approves the build for renewal via ios-tools `deliver.py`, and launches the app.
- **`R/apps/ios/scripts/renewal.py`**
  - Prints one entry per provider. Inputs: `GalleryReader`, `GalleryReader.xcodeproj`, `Resources/Info.plist`, `Resources/LocalCA.cer`, `providers.json`, `build/<p>/Web`, `build/<p>/provider.xcconfig`, `scripts/build.sh`, `scripts/build-provider.py`.
  - **A rewrite must update this input list**, otherwise renewal approval may quietly miss source changes.
  - The scheduler is `com.visar.renewal.gallery-reader` (`PORT.md:83-90`).
- **`LocalCA.cer`** is gitignored and must be copied in before deploying (`PORT.md:52-55`).

---

## 7. Documented owner requirements (quoted)

### Pagination (`R/test.txt:21-27`)

> "After the pagination numbers have been visible for one second, selecting any other page waits for that page to render and then places the first gallery row at the viewport top. … This behavior is required for Hitomi Favorites, Hitomi Search, and imhentai Search."

### Search history (`R/test.txt:30-36`)

> "Search pagination replaces the current history entry rather than adding one, so Back returns to the previous meaningful navigation … On a bfcache restore, the search input is synchronized from the restored URL."

### Back from the reader (`R/test.txt:40-43`)

> "Returning Back to Search restores the same search and viewport position. Hitomi must restore this directly from bfcache."

### Reader (`R/test.txt:47-51`)

> "every image in one vertical strip with aspect-ratio skeletons … On scrollend + 100 ms, the image crossing the middle of the viewport is saved in the provider's reader URL without adding a history entry. Opening or reloading that saved URL restores the saved image with its top at the middle of the viewport."

`R/features.md:27` (newer):

> "restore reader position on startup based on the url, which names the image at the screen's centre (`page`) and how far down that image the centre was (`f`), so a reload after iOS ended the page lands on the same point."

### Info modal (`R/test.txt:58-60`)

> "opening a related search from the modal, paginating that search, and pressing Back returns to the original gallery list with the information modal still open."

### Favorites (`R/test.txt:64-66`)

> "added … and removed again without disturbing its gallery row. Favorites are displayed newest first and remember their latest selected page."

### Back-swipe as the core feature (`R/features.md:1,8`)

> "The apps are designed around WebKit's back-forward cache when you swipe back and forth." / "Ios back swipe caching behavior is the single biggest feature of this app."

The three flows are at lines 10-12, and the search, row and pagination layout at 16-21.

### Positions and cold launch

`R/apps/ios/PORT.md:24-27`:

> "Cold launches restore the reader URL and Back history but reset scroll positions (accepted). There is no custom view-position file, anchor math, strip-scroll restoration or reconstructed navigation stack".

`shared-codebase-verification.json` ("restoration"):

> "custom position records, fractional anchors, strip restoration and Home-to-reader history reconstruction removed at user request."

### Lazy loading

`PORT.md:17-21` specifies `loading="lazy"`. The removed `test.md` (v515 section, viewable with `git show 79a52ad^:test.md`) records:

> "The user chose to disable AdGuard on Hitomi/IMHentai and retain native loading. The custom IntersectionObserver loader and detached-row experiment were removed; … loading="lazy", source image retry and ordinary document scrolling remain. No virtual window or custom tap handler was added."

`R/notes.md:16-17` adds: "Long image strips are inserted in small batches so interaction can continue."

### Image URLs (`R/notes.md:5-9`)

> "Resolve image URLs through the provider on each new reader document … Do not persist resolved URLs as offline manifests".

### Backups

See `R/notes.md:28-39` and `R/server/BACKUPS.md:7-16`: setup offered on first use; silent later; unreachable PC is silent; errors stay visible; restore gets a new ID.

### Zoom

There is no documented zoom requirement. The only related material is `ignoresViewportScaleLimits` and the caution in `R/SCROLL-AUDIT.md:122-125` that `innerHeight/2` is not the visible center when zoomed.

---

## 8. Hidden dependencies (what the apps rely on without owning it)

**bfcache, `pageshow` persisted, `pagehide` — used.**
- Where:
  - `shell.ts:84-86`
  - `pc-backup.ts:120`
  - `scroll-settle.ts:11-12`
  - `compute/worker.ts:11,20`
  - `autocomplete.ts:86`
  - `image-retry.ts:52-55`
- Silently provides:
  - horizontal strip offsets (stored nowhere)
  - the modal staying open after Back
  - the page each home entry was on (home pagination isn't in the URL; a reload shows the latest saved page)
  - already-loaded thumbnails
  - the "instant" Back
- Side effect: restored pages show stale hearts and saved searches.
- In the app, Imhen pages also come from `gallery://`, so Safari's no-store exclusion probably no longer applies. Even so, WebKit keeps only a few pages and drops them under memory pressure or when the WebContent process dies.
- A native rewrite must keep screens alive on the navigation stack, or save strip offsets and modal state.

**WebKit session history, the swipe gestures and their snapshots — used.**
- `allowsBackForwardNavigationGestures` (`WebController.swift:32`) is the **only** way back, and it also gives a forward swipe.
- WebKit shows snapshots during the swipe.
- WebKit decides between the edge swipe and the horizontal strips, which start at the screen edge.
- A rewrite needs an interactive pop gesture, deliberate gesture conflict handling, and a decision on forward swipe.

**`interactionState` restore — used.**
- Code: `WebController.swift:41-55`, `92`; `AppDelegate.swift:16-17`.
- The blob is opaque. If it fails to decode (for example after an iOS update), there is no fallback `load()`, so the app may open to a blank screen.
- The navigation type WebKit reports for this restore decides whether the reader positions itself (`platform.ts:8`, `WebController.swift:89`).

**`history.scrollRestoration` and WebKit's own scroll restoration — used implicitly.**
- `scrollRestoration` is left at its default, `auto`.
- In the reader, when `restoring` is set the app relies entirely on WebKit, which in practice resets to the top.
- List pages override WebKit with their own restore in the next frame.

**Scroll anchoring — not relied on.**
- To my knowledge WebKit doesn't implement CSS scroll anchoring.
- Layout stability comes from fixed 300 px rows and aspect-ratio reader images. The app's own anchoring code was removed in 82ee173.
- What breaks: the Imhentai 0×0 fallback shifts layout as images load.

**Zoom, pinch, `visualViewport`, `ignoresViewportScaleLimits` — used.**
- `WebController.swift:30` and the viewport meta tag (`index.html:2`, `shell.ts:17-20`) leave zoom to WebKit.
- `visualViewport` is not used. The reader midpoint uses `innerWidth`/`innerHeight` (`reader.ts:39,44`).
- WebKit's session data keeps the zoom level per history entry.
- The 16 px textarea font avoids iOS zooming in on focus (`style.css:42`).

**Image loading, decoding, lazy loading, cancellation and retry — used heavily.**
- WebKit decides lazy-load distance, decodes images, and holds them in its memory cache (jetsam risk on long galleries).
- When a page goes into the bfcache, WebKit stops its loads. That triggers the scheme handler's `stop` (`WebController.swift:120-122`) and cancels the native download.
- After Back, `image-retry.ts` is what reloads those images.
- Safari quirks are hard-coded:
  - no `onerror` on 429 (`image-retry.ts:80`)
  - `src` must be cleared before being set again (`image-retry.ts:83`)
- Inserting in batches of 32 works around the cost WebKit puts on setting `src` (WebKit bug 264235, AdGuard).
- A rewrite needs its own prefetch window, downsampling, memory limits, cancellation and retry.

**WebContent process termination (jetsam) and reload — used.**
- `WebController.swift:93` reloads the page.
- Every cached page is lost; strips and modal state are lost; back entries rebuild from IndexedDB, or start at the top for the reader.

**Storage WebKit owns versus native files.**
- The authoritative data is in WebKit IndexedDB, subject to WebKit's eviction and storage-pressure policy. It does not call `navigator.storage.persist()`, and there is no app-controlled export apart from PC backup or manual Export.
- The 10 s database timeouts and explicit commits work around WebKit suspension (`state.ts:10,37-51`; `backup-engine.ts:16,36-47`).
- Whether ITP's storage cap applies to a custom-scheme origin in a non-browser app: unverified.
- Native files are listed in section 4.

**Timers, `requestAnimationFrame`, `visibilitychange`, JS suspension — used.**
- Scroll saving is gated on `document.hidden`.
- No database writes start while hidden (`shell.ts:87-91`).
- Retries pause; scroll restore uses `requestAnimationFrame` (`preferences.ts:35`).
- The 100 ms favorites-sync debounce and the 12 s toast are delayed by suspension.
- A database transaction caught by suspension can hit its 10 s timeout on resume and be lost.

**Web workers inside WKWebView — used.**
- A Blob-URL worker on the custom-scheme origin does IndexedDB, parsing and caching (`compute/worker.ts:6-7`).
- It survives in the bfcache. Its `gg.js` and search caches have no expiry, so a long-lived reader page can hold stale `gg` paths.

**Cookies — not really used.**
- All https traffic goes through `URLSession` and `HTTPCookieStorage.shared`.
- `WKHTTPCookieStore` is never used. Imhentai's `credentials:'include'` has no effect.

**fetch, CORS, custom-scheme semantics — used.**
- The bridge removes CORS and all browser headers (user agent, Origin, Sec-Fetch); the Referer is set natively.
- Bodies travel as base64. A 2 MB+ Nozomi file becomes about 3 MB of JSON.
- WHATWG URL parsing encodes spaces in Nozomi URLs.
- Scheme-handler responses are a bare `URLResponse` with no status or cache headers.
- Only `gallery://app` may be navigated to.

**Newer CSS and JS features — used, under deployment target iOS 17.0.**
- `scrollend` (`scroll-settle.ts:10`): every position save depends on it. It is a recent WebKit addition; where it is missing, nothing is saved.
- `dialog closedby` (`info-modal.ts:48`): has a manual fallback.
- `field-sizing` (`style.css:39`): recent.
- Also used:
  - `:has()` (`style.css:2`), `svh` (`style.css:218`), `aspect-ratio` (`reader.ts:16`)
  - `crypto.randomUUID` (`fetch.ts:9`, `backup-engine.ts:118`)
  - `navigator.locks`, guarded (`pc-backup.ts:116`)
  - `IDBTransaction.commit` and durability options, `AbortSignal.throwIfAborted`
  - `attachShadow`, `loading=lazy`

**Text selection and long-press menus — used.**
- `style.css:1-7` turns off the callout, selection and drag on images only. Text elsewhere stays selectable.
- Keep the OCR Back-Tap workflow working.

**Momentum and overscroll — used.**
- WebKit's scroll view provides rubber-banding and momentum; nested horizontal scrollers have hidden scrollbars (`style.css:151-160`).
- `contentInsetAdjustmentBehavior = .never`; the status bar is hidden, so there is no tap-to-top.
- `scroll-behavior: auto` makes `scrollIntoView` instant.

**PC server at 192.168.1.197 and the bundled CA — used.**
- Three places hold the address:
  - `GalleryServerURL` (Info.plist), which also decides **which host gets the CA trust and the no-retry session**
  - the build-time backup URL (`build.mjs:18`)
  - the sync URL (`build.mjs:17`, `worker-entry.ts:34`)
- **Hidden coupling:** if the backup URL's host differs from `GalleryServerURL`, TLS fails and backups silently look "unavailable".
- Also depends on the Local Network permission and the mkcert certificate covering that IP.

**iOS app behaviour.**
- The old AppDelegate lifecycle has no UIScene. Apple's TN3187 says a future SDK will require scenes. This affects any rebuild, not just the rewrite.
- No background execution. URLSession tasks are suspended along with the app. `waitsForConnectivity` plus infinite retry means offline requests hang with no indicator.

### Places where the code works around or fights WebKit

- `style.css:15,23,94` ("fighting the site", left over from the userscript) and `style.css:39` ("ios only").
- `shell.ts:11-20` (Safari's desktop-width default), `shell.ts:83` ("bfcache in action"), `shell.ts:87-88` (Safari suspension blocking IndexedDB).
- `state.ts:40` (Safari closed the transaction), `state.ts:49-51` (navigation may suspend the worker).
- `image-retry.ts:52-53, 80, 83`.
- `scroll-settle.ts:16-17`.
- `compute/worker.ts:1-2,11`.
- `platform.ts:1-2`.
- `WebController.swift:96-97`.
- `pc-backup.ts:104` (Safari wording in the error message).
- `takeover.ts`.
- Git history makes the bfcache theme explicit:
  - e76dc87 "fixed bfache... how many times do i have to fix this"
  - 0808ba1 "appropriate bfcache flag"
  - 953f3b0 (Imhentai `no-store` breaks the bfcache)
  - eb31c15 ("no-cache control destroys this script")

---

## 9. Docs that disagree with the code, and latent bugs

### Docs out of step with the code

- **Pagination mechanism:** `features.md:12,21` describes hash pagination with `hashchange` and filling the input on `pagereveal`. The code uses `?q=&p=` with `replaceState` (`search.ts:18`) and `pageshow` persisted.
- **All-negative queries:** `features.md:16` says an all-negative query searches `language:japanese`. The code only substitutes for an empty query (`shell.ts:51`); an all-negative Hitomi query returns nothing.
- **Reader save timing and restore point:** `test.txt:49-51` says "scrollend + 100 ms" and "top at the middle". The code saves immediately (`scroll-settle.ts:1`) and restores to the saved `f` point.
- **Imhentai and bfcache:** `test.txt:42-43` says Imhentai has no bfcache. That was true in Safari; in the app this is untested.
- **Reader positions in backups:** `notes.md:35-36` says backups include "all reader scroll positions". The reader saves nothing to IndexedDB.

### Bugs and stale code

- `deploy.py:22` still rsyncs `apps/ios/web` with `--delete`. That folder moved to `src/app` in commit 79a52ad, so `deploy.py sync` should now fail.
- Hitomi `split('=')[1]` parse bug (`data-provider.ts:20`).
- **Imhentai query edge cases:**
  - extra namespaces are dropped
  - a `-term` becomes the keyword "term"
  - 0×0 fallback sizes cause layout shifts
- **Missing error UI:** none for reader or search failures.
- **Unbounded growth:** the image cache never evicts and is backed up; the scroll map is never pruned.
- **Unused code:**
  - `style.css` is shipped but unused (the CSS is inlined)
  - unused worker operations (`favorites-json`, `favorites`, `page`)
  - duplicate `matchRoute` in both Hitomi files
- **Hardcoded origins in two places:** native derives the origin from `ReaderProvider` (`WebController.swift:17-18`) separately from `providers.json`.