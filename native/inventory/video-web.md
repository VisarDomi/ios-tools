I've read the docs and code you listed, and I probed the live server with GET requests only (no writes, no edits, no list changes). Line numbers refer to the current tree (`main` at 315b300, clean).

**Short answer:** the local apps get two things from the website that the native viewer doesn't replace yet. One is the list itself, including a full reload every time the app comes back to the foreground; that reload is the only thing that corrects stale rows. The other is a few calls back into the page. Editing and the +/- button already go to the PC directly. The website also serves Safari, desktop browsers and several other API callers, so the server API and the web list/viewer have to stay as they are.

### Files referenced (short names below)
- `/home/visar/Documents/work/video/video-platform/packages/app/src/`: `main.ts`, `constants.ts`, `types.ts`, `routes/videoList.ts`, `routes/videoViewer.ts`, `routes/nativeViewer.ts`, `providers/local.ts`, `services/{api,hls,catalog,downloadList}.ts`, `player/{PlayerUnit,PlaybackTimeline,GestureController,OverlayView,DownloadListButton}.ts`, `utils/format.ts`, `style.css`
- `/home/visar/Documents/work/video/video-platform/packages/server/src/`: `main.ts`, `api/video.routes.ts`, `api/hls.routes.ts`, `api/providers/{list-routes,tango.routes,fc2.routes,sc.routes}.ts`, `services/video/{retrieve,move,edit}.service.ts`, `core/{utils,constants,playlist-daemon}.ts`, `core/go/playlist_parser.go`
- `/home/visar/Documents/work/video/video-platform/apps/ios/VideoApp/`: `WebController.swift`, `ViewerBridge.swift`, `ViewerPC.swift`, `ViewerController.swift`, `ViewerUnit.swift`, `ViewerVideo.swift`, `ViewerMedia.swift`, `ViewerOverlay.swift`; `/home/visar/Documents/work/video/video-platform/apps/ios/scripts/{project.py,deploy.py}`
- Docs: `/home/visar/Documents/work/video/video-platform/{decisions.md,notes.md,issues.md}`, `packages/app/{decisions.md,PROVIDERS.md}`, `packages/server/{notes.md,decisions.md}`, `apps/ios/PORT.md`. There is no top-level `PROVIDERS.md`; it only exists under `packages/app/`.

---

## 1. Endpoints the local apps use

**General (server `main.ts`)**
- Express 5.2.1 serves everything on HTTPS port 9999.
- **Auth:** none on any route.
- **CORS:** `cors()` with defaults (line 40): every origin is allowed, preflight allows all methods and echoes the requested headers. The Tango app's script on tango.me needs this (see section 6).
- **JSON body limit:** 10 MB.
- **Static files** (59-66): `/assets/*` are cached for a year; `index.html` is `max-age=0` with ETag/Last-Modified.
- **Catch-all GET** (68-70): any unmatched GET returns `index.html` with status 200, including `/api/typo` and `/favicon.ico`. A native client must check the status and the content type, not just "200".
- **TLS** (72-91): mkcert certificate at `~/.local/share/mkcert/pwa/{cert,key}.pem`.
  - It names only `localhost` and the IP `192.168.1.197`, and expires on 2028-03-05.
  - If the files are missing, the server silently falls back to plain HTTP on the same port, and the apps' `https://` URLs break.
  - The phone must have the "mkcert visar@z440" root CA installed and fully trusted. `GET /api/cert` serves `rootCA.pem` (video.routes.ts 17-30).
- **App settings** (project.py 100-102, 114): `NSAllowsLocalNetworking`, a local-network permission string, iOS 17.0 minimum (project.py:38).
- **Caching:** API and HLS responses send no `Cache-Control`, only weak ETags. A matching `If-None-Match` gets a 304 (verified). Responses are not gzip-compressed. `issues.md` already lists the missing `no-store` as an open issue.

**`GET /api/videos?provider=tango|fc2|sc[&after=<filename>]`** (video.routes.ts 32-42, retrieve.service.ts 8-84)
- Missing provider defaults to `tango`. An unknown provider returns 500 `{"error":"Failed to retrieve videos"}`.
- **Response:** an array of `{filename, type:"original"|"edited", size:0, duration:<seconds>, isLive:bool}`.
  - `size` is always 0; the client estimates it.
  - `duration` is the sum of the playlist's segment durations, computed by a Go helper and cached by playlist modification time. It is 0 for live rows.
- **Where rows come from:**
  - `downloaded/.active`, only folders that already have a `playlist.m3u8` → `isLive: true` (35-43)
  - `downloaded` → `original`
  - `edited` → `edited`
  - Hidden folders are skipped (`.pending`, `.building-*`). A recording therefore disappears from the list between the end of the live stream and publication.
- **Order:** sorted with Node's `localeCompare` (line 81), which effectively means oldest first.
- **`after`:** a plain character-by-character comparison, `name > after` (45-47). This differs from `localeCompare`. Real SC data proves it: `"... 152129 kanata_mu_ch"` sorts before `"... 152129 RIN_RIN__"` under `localeCompare`, but `RIN... > kanata...` is false.
- **Measured today:**

  | Provider | Rows | Size (uncompressed) | Time |
  |---|---|---|---|
  | Tango | 4,041 (3,288 edited, 751 original, 2 live) | 459,137 bytes | ~0.18 s |
  | SC | 987 | 112 KB | |
  | FC2 | 157 | 15.6 KB | |

  A poll with nothing new returns `[]`.

**Edits** (no request body needed; `provider` goes in the query; the server finds the folder itself in `.active` → `downloaded` → `edited`, utils.ts 27-44)
- `POST /api/videos/:filename/edited?provider=` → save.
- `POST /api/videos/:filename/original?provider=` → return original.
- `POST /api/videos/:filename/trash?provider=` also exists; the frontend doesn't use it.
- All three answer `{success:true}`, or 404 `{success:false,error}`, or 500 `{success:false,error}`. Moving to the folder a recording is already in raises "File is already at the destination." as a 500.
- `POST /api/edit` with JSON `{filename, segments:[names], provider}` (44-66).
  - Empty `segments` returns 400 as **plain text**, not JSON.
  - 404 and 500 are JSON.
  - It also answers 200 `{success:true}` when **none** of the names match a `.ts` file. That is a silent no-op (edit.service.ts 134-137).
- The two repair routes are maintenance only and unused by the UI.

**HLS** (hls.routes.ts)
- `GET /hls/:provider/:filename/playlist.m3u8` (10-30).
  - Uses the same folder search, so **the same URL serves the edited and the original version**; `?type=` in viewer URLs means nothing to the server.
  - Content type `application/vnd.apple.mpegurl; charset=utf-8`.
  - 404 returns the text "Video not found.", including while a recording sits in `.pending`. An unknown provider gives 500.
- `GET /hls/:provider/:filename/<segment>.ts|.mp4` (32-59).
  - The whole file is read into memory. **`Range` is ignored** (always 200 with the full body, verified).
  - 404 "Segment not found."; 400 for other extensions.
  - Segment paths in playlists are relative names.
- **Playlist formats:**
  - FC2/Tango: MPEG-TS, version 3, segment names like `n_identity_seq.ts`.
  - SC: fMP4, version 7, with `#EXT-X-MAP:URI="init.mp4"`/`init_<n>.mp4`, but its segments are **still named `.ts`**.
  - A 52-minute FC2 playlist is 137 KB.
- **Live recordings:**
  - No `#EXT-X-ENDLIST` and no `PLAYLIST-TYPE` tag.
  - The downloader appends entries non-atomically (playlistManager.ts 547-569), so a read can end in the middle of an entry.
  - At the end it writes ENDLIST atomically and renames the folder to `.pending`. The URL then returns 404 until publication. I saw this live: `tango/2026-10-11 142847 m0del_im_ana` was listed as live and returned 404 minutes later; two SC recordings are in `.pending` right now.
  - Publication can rewrite segment durations and add discontinuity tags.
- **Edited playlists** are derived ones, with discontinuity tags at the cuts, ending in ENDLIST.

**Download lists** (list-routes.ts; `provider` = tango, fc2 or sc)
- `GET /api/<p>/member?identifier=` → `{member}`.
  - 400 `{error:"identifier required"}`; 500 `{error:"Failed to check membership"}`.
  - The server answers by streamer ID, so an old alias still counts (89-109).
- `GET /api/<p>/exists?identifier=` → `{exists}`; 502 `{error}` when the provider can't answer (113-128).
- `POST /api/<p>/add {identifier}` → `{success:true}`; 400, 404 `{error:"Could not resolve: X"}`, or 500 `{error:"Failed to update file"}` (47-85). Tango first unblocks and follows the account (tango.routes.ts 96-109); a failure there also comes back as the 500.
- `POST /api/<p>/remove {identifier}` → `{success:true}`, even when the streamer wasn't listed (130-153).
- `/list` and `/resolve` exist but the UI doesn't use them; the pipeline uses `/resolve`.
- **Query parsing:** Express 5's simple parser decodes `+` as a space (verified). `ViewerPC.request` uses `URLComponents.queryItems` (ViewerPC.swift:19), which leaves `+` unescaped. A native client should percent-encode `+`.

**The local frontend never calls** `/api/<p>/list`, `/resolve`, `/repair-*` or `/trash`.

## 2. List screen behaviour (`videoList.ts`)

**Open** (57-80)
1. Shows "Loading…".
2. Reads the highlight key `video-highlight:<provider>` from `localStorage` (82-86).
3. Does a full fetch (122-131), builds the rows, then scrolls the highlighted row to the centre with `scrollIntoView({block:'center'})` (133-137).
4. Then starts polling and attaches the lifecycle listeners.

**Rows** (179-191, 251-266; CSS in style.css 46-113)
- Plain links to `/videos/<p>/<encoded filename>?type=<type>`.
- Fixed 52 px height. One line for the name (title or filename), cut off with "…".
- A monospace line below, left to right: duration, a mark (always empty for local), size.
- **Duration:** `h:mm:ss`, or `mm:ss` under an hour; `--:--` when 0 (format.ts).
- **Size:** estimated as duration × 2.3 Mbps ÷ 8 (constants.ts:52), shown as `X.X MiB`, or `-- MiB` when 0. Above 350 MiB (about 21 min 16 s of video) the size is drawn bold and light (the "large" marker).
- **Live rows** (local): red name, `--:--`, `-- MiB`. The `LIVE` label is only used for online live providers.
- **Edited rows:** orange name.
- **Highlighted (last viewed) row:** bold on a darker background. It is matched by filename only.
- **Row identity:** `filename + "\u001f" + type` (268-270). The native viewer uses the same key.

**Order**
- Server order, oldest at the top. After each poll the client re-sorts with WebKit's `localeCompare` (237).
- New recordings appear at the bottom.

**Polling** (204-248)
- Every 1 s, only while the page is visible, with at most one request in flight.
- Asks for `after=<last filename in the client's list>` and **only adds rows**, skipping keys it already has.
- Errors are only logged: no backoff, and no timeout beyond WebKit's default. A hung request stalls polling until the page is hidden.
- Because polling only adds names greater than the last one, it never:
  - updates a row from live to finished (the finished recording has the same key, so it's skipped; verified with `after=`),
  - removes a deleted recording,
  - shows a type change after an edit,
  - picks up a recording that appears with an *older* name (published from `.pending`, or an `.active` folder whose playlist arrived after a newer recording was listed),
  - picks up the case-ordering edge case above.

  Only a full refresh fixes these.

**Full refresh triggers** (88-120)
- **Hide:** `pagehide`, or `visibilitychange` to hidden → stop the timer and abort in-flight requests.
- **Refresh:** visible again, `pageshow` restored from the back-forward cache, or `online` while visible → full refetch.
  - The refetch is merged into the existing rows without scrolling (DOM nodes are reused by key).
  - The highlight is re-read.
  - Exactly one poller restarts.
  - A request counter and `AbortController` stop a stale response from overwriting a newer one.

**Empty and failed states**
- An empty list shows "No videos found." (159-163). Bug: when rows arrive later, that text stays at the top, because rows are appended after it.
- If the *first* fetch fails, `open()` throws before any listener is attached. `main.ts` (47-50) then shows red text such as "Video fetch failed: <statusText>" or WebKit's "Load failed". **No retry and no automatic recovery**; only a reload (pull-down in the app) fixes it.

**Clicks** (66-73)
- Safari follows the link to the web viewer, adding one history entry.
- In the apps (`window.webkit.messageHandlers.videoViewer` is present), the default is prevented and the page posts `open` with:
  - every video, described (nativeViewer.ts 48-73): `local`, `live`, `media` = the absolute HLS URL resolved against the page address, `membership` = `{lists:[provider], identifier: the filename after its second space}`;
  - the index of the tapped video;
  - a progress map read from `localStorage` for every listed filename (148-160).
- The page posts `list` whenever its list changes. If the list only grew, it posts `append` with just the new rows (134-146). After every full refresh all row objects are new, so the full 4,041-row `list` is posted again on every return to the foreground.
- The first message is followed by `ready` with `{origin, userAgent}`.
- A viewer address opened inside the app (`main.ts` 26-31) is rewritten to the list URL and opens the native viewer on that video. If the video isn't in the list, a stand-in with duration 0 is used (nativeViewer.ts 163-171).
- Highlight: the native viewer calls the page's `highlight(filename, reveal)` on every video change (ViewerController.swift:293) and on close with `reveal=true` (778). The page saves it to `localStorage` and scrolls the row to the centre only if it is off screen (videoList.ts 140-148).

**What the web viewer (`videoViewer.ts`) does, and the native viewer copies**
- **Feed and gestures:** three player units with 10,000 px runways; a video becomes current when it reaches the screen's midpoint; settling happens on `scrollend`; landing in the blank runway moves exactly one video.
- Horizontal drag in the upper half seeks (60 s per screen width); a swipe over 80 px in the lower half shows or hides the controls; the leftmost 28 px are left to Safari's Back gesture.
- **Playback:** all videos play muted and only the current one can be unmuted; the screen wake lock is requested; at most 8 s are spent waiting for the video's size before showing it.
- **Overlay** (OverlayView.ts 186-223):
  - name, time as `mm:ss.mmm`, current segment name, a 100 px progress bar with white markers and start/end rows;
  - buttons: mute, or undo-last-marker once markers exist; follow and block (online live only); the +/- button; return original (edited videos only); save, which turns into cut once markers exist (original videos that aren't live; cut is disabled with an odd number of markers); add marker (same condition as save);
  - all controls are disabled while a swipe settles.
- **Progress:** `video-progress-<filename>` saved at most every 3 s, on scope change, on `pagehide` and when hidden (540-544, 546-569). Local live recordings do save progress. Resuming only happens for recordings that aren't live.
- **Highlight and URL:** both are written on every video change (240-258), the URL with `history.replaceState`.
- **404 after an edit:** the video is dropped from the list; if the list is then empty, `history.back()` (526-538).
- **Recovery:** after a back-forward-cache restore, becoming visible again, or `online`, every player unit resumes (PlayerUnit.ts 137-164).
- **Live finishing while playing:** the playlist is re-checked every second while the native duration is finite but the playlist still looks live (262-311).

## 3. Editing

**Markers**
- Media-clock seconds (`currentTime`), kept sorted as they're added (videoViewer.ts 475-482). Pairs are therefore formed from the sorted order, not from the order the user placed them.
- Only allowed for local, original, non-live videos.
- Undo removes the last marker in sorted order, which is the latest point in the video, not necessarily the last one placed (466-473).
- Markers are cleared when the video changes.

**Save, no markers** (488-505)
- `POST .../edited`. The server renames the whole folder `downloaded/<rec>` → `edited/<rec>`, adding a " (n)" suffix if the name is taken (move.service.ts 25-41).
- It writes **no finalization checkpoint at the new path**, while the pipeline looks checkpoints up by path (pipeline `recordingFinalization.ts`). A read-only query found 570 of 3,288 Tango, 17 of 137 FC2 and 268 of 938 SC edited folders without a checkpoint row. That fits saved recordings not being picked up by the pipeline until `finalize-library` runs. Worth confirming.

**Cut, with markers**
1. The client fetches the playlist again (no cache), adds up the segment durations, and keeps every `.ts` segment whose time span overlaps any `[marker 0, marker 1)`, `[marker 2, marker 3)`, … pair. Boundaries therefore round outward to whole segments.
2. The marker times are scaled by playlist duration ÷ playback duration. That factor is 1 once the playlist has loaded (hls.ts 40-56).
3. `POST /api/edit` with the kept names. The server (edit.service.ts 109-206):
   - refuses if `edited/<rec>` already exists (500);
   - moves the kept `.ts` files into `edited/.building-<uuid>` and copies the init files;
   - derives the new playlist;
   - writes a "ready" checkpoint marked as derived;
   - renames the folder into `edited/`;
   - moves the rest of the original to `trash/`.

**Return original**
- `POST .../original` moves the edited folder back to `downloaded/`.
- After a cut, the cut-away segments stay in trash and are **not** restored.

**Afterwards**
- Both viewers reload the same filename with the type flipped and position 0.
- The **list is not told**. The row keeps its old colour until the next full refresh.

**Already reimplemented natively**
- Markers, undo, the odd-count rule (ViewerController.swift 592-607, ViewerOverlay.swift 310-329).
- Save, cut and return straight to the PC (ViewerPC.swift 36-44).
- `Playlist.parse` and `keep` (ViewerUnit.swift 444-499), the same algorithm with the same `.ts` filter.
- The timeline and segment name, re-checking the playlist when a live recording finishes, the 404 handling (645-653).
- The +/- button: membership through ViewerPC, the overlay's button states, re-asking membership to confirm a change.

**Still only on the web**
- The whole list: fetching, sorting, polling, refresh on return, highlight storage and scroll, empty and failed states.
- `describe()`, which builds the media URL and the streamer name for the +/- button.
- The progress seed.
- Opening a viewer address inside the app.
- `resolve`: the fallback source for a video that has no `media` entry.

**Native gaps found**
- `ViewerVideo.setting("type", …)` deletes `media` (ViewerVideo.swift 34-39). After any save, cut or return:
  - playback has to go through the page's `resolve` (ViewerController.swift 719-722);
  - the playlist check is skipped (ViewerUnit.swift 337: `guard let url = video.media?.url`), so there are no segment names or live tracking;
  - **a cut after return-original silently does nothing** (ViewerController.swift:617).
- `updateList` finds the current video by filename and type (228-230). The page's list still has the old type after an edit, so the native viewer ignores list updates until the page's next full refresh.

## 4. Data stored in each local app's WKWebView (origin `https://192.168.1.197:9999`)

- **`localStorage['video-highlight:<provider>']`**: the last-viewed filename. Each app only ever has its own provider's key, because navigation is limited to `/videos/<provider>` (Policy.swift).
- **`localStorage['video-progress-<filename>']`**: seconds, stored as a string.
  - Written only by the web viewer. In the apps that was before the native viewer existed; nothing writes these now.
  - Not provider-scoped, never cleaned up.
  - On each `open`, the native `ProgressStore.seed` copies them into `viewer-progress.json`, but only for filenames it hasn't seen before (ViewerVideo.swift 91-95). Most may already be migrated.
- No `sessionStorage`, `history.state` or cookies are used by the local providers. The `video-catalog:*` keys and `videoListY` belong to the online apps only.
- **Native files** in `Library/Application Support/LocalVideos/`:
  - `interaction-state`: WebKit's back/forward list; obsolete once the list is native.
  - `viewer-progress.json`: `{filename: seconds}`.
  - `viewer-checkpoint.json`: `{provider, current:"file\u001ftype", videos:[described videos including media]}`.
- **To seed a native list once:** load any page under the start URL in a hidden WKWebView and read both key prefixes with JavaScript. Install over the existing bundle ID (PORT.md: never uninstall), or the data is lost.

## 5. Browser and WebKit behaviour the frontend relies on without owning it

**Back-forward cache, `pageshow` (persisted) and `pagehide`**
- *Safari:* used. Back from the viewer restores the list's DOM and scroll from the cache, then refetches without scrolling (videoList.ts 102-106).
  - If the cache misses, the list loads fresh and only the highlight centring restores the position.
  - After a restore, the highlighted row can be off screen, because scroll is kept where the user left the list.
- *Apps:* not used between list and viewer (no navigation happens). The page under the native viewer just stays alive.

**History, Back and back-swipe**
- Safari owns Back (the 28 px edge exclusion, GestureController.ts 40). The viewer replaces its URL so Back always returns to the list.
- *Apps:* edge-swipe Back/Forward is enabled on the web view (WebController.swift:86), and old history is restored from `interaction-state` (165-173). Swiping back on the list to an old viewer entry *opens that video natively* (`main.ts` 26-31).

**Scroll restoration and `scrollIntoView`**
- The list never saves its own scroll position. It relies on the back-forward cache, the highlight centring on first open (133-137), and the off-screen-only reveal (146-147).
- Rows are re-appended in order on every merge, and nothing depends on CSS scroll anchoring.
- *Apps:* a pull-down reload (95-97) or a restarted web process (270-273) drops back to the highlight centring.

**WebKit storage eviction**
- Highlight and web progress live only in WebKit storage, which is lost on uninstall.
- Not verified on the device: WebKit's 7-day limit on script-written storage may also apply inside apps, and native-viewer use doesn't count as interaction with the site. Native files avoid this.

**Timers and `visibilitychange` in the background**
- Polling runs only while visible; WebKit also suspends the page in the background.
- `ViewerBridge.call` waits until the page is `ready` (ViewerBridge.swift 67-77).
- Local playback needs the page only for `highlight` (fire-and-forget) and for `resolve` after an edit.
- Coming back to the foreground means a 450 KB refetch plus a 4,041-row post to the native viewer, every time. That refresh is also the **only** thing that fixes stale live rows, edits and deletions.

**fetch and abort**
- `AbortController` per request, request counters, one poll in flight.
- No timeout (WebKit's default is about 60 s) and no backoff.
- Fetch gets 304 revalidation for free through WebKit's HTTP cache. URLSession's `reloadIgnoringLocalCacheData` (used in ViewerPC/Playlist) throws that away.

**The page origin is the PC**
- All API calls and row links are relative; no cookies; same-origin, so no CORS is needed for the website itself.
- Media URLs are made absolute from the page address (nativeViewer.ts 44-46, 70).
- `window.tangoNative.serverURL` / `mediaOrigin` (constants.ts 9, 22) is dead: nothing sets it.
- `ViewerPC.server` (line 7) and `DownloadList.swift` hardcode the URL. A native list should derive origin and provider from `StartURL`.

**Certificate trust**
- Depends on the phone fully trusting the mkcert root and on the IP staying 192.168.1.197 (the only IP the certificate names).
- AVFoundation and URLSession both use the system trust store.
- Expires 2028-03-05.

**Service worker and web manifest**
- None (app decisions.md 32-36). The `pwa` folder name is historical. There's a `theme-color` meta tag, and the favicon isn't included in the build.

**Features that need recent iOS**
- `scrollend`: the web viewer only settles after a scroll once it fires (videoViewer.ts 72, 352-356). Without it, a scroll never settles and the controls stay disabled. I didn't check which Safari version first shipped it.
- `100dvh`; `navigator.wakeLock` (optional, failures are caught).
- Vite 7's default build target is Safari 16; the online apps' scripts target Safari 17.
- The message bridge with replies and `callAsyncJavaScript` (iOS 14), `interactionState` (iOS 15), `isInspectable` (iOS 16.4); the apps' minimum is iOS 17.

**Places that work around WebKit or Safari**
- Overlay:
  - a fully transparent fixed overlay, because a painted backdrop turns Safari's toolbars opaque;
  - only the horizontal seek calls `preventDefault`.
- Scrolling:
  - `touch-action: pan-y pinch-zoom`;
  - the scroll position is never written during momentum (a `translateY` offset instead), and settling waits for `scrollend`.
- Video on iOS:
  - native HLS on iOS (`USE_NATIVE_HLS`, constants.ts 54-58), hls.js everywhere else;
  - recovery reloads the video element, because native HLS has no `startLoad`;
  - the once-a-second playlist re-check when a live recording turns finite;
  - marker and segment-name timing scaled to the playlist;
  - the server rewrites segment durations from the media timestamps because Safari plays the media timeline (decisions.md §3).
- Autoplay: everything starts muted, inline playback.
- App side:
  - the blank-restore and `about:blank` fallbacks (WebController.swift 169-172, 244);
  - reload after the web process is killed;
  - the native "Can't reach your PC" screen instead of Safari's error page;
  - the `append` message and the off-main-thread checkpoint writer, because posting or encoding 4,041 rows stutters swipes;
  - the whole native viewer exists because WebKit pauses page video on lock and in the background.

## 6. Other users of the website, and what must stay

**Users**
- **Safari on the iPhone:** keeps the web viewer, as the docs state repeatedly (decisions.md:211, app decisions.md:125).
- **Desktop browsers:** the hls.js path, `/` redirecting to `/videos/tango`, row hover styles, Vite dev server on port 43210.
- **Tests:** `test/viewer.mjs` runs against the deployed origin; `npm run test:app:webkit` runs `providers.mjs`.

**Other API callers**
- FC2/SC live Safari extensions: `/api/fc2|sc/member|add|remove`.
- Video Vault through `DownloadList.swift`: member/exists/add/remove.
- The Tango app's script on tango.me: cross-origin `fetch` to `/api/tango/member|add|remove` (downloadList.ts 14, 81-84), so it **needs `Access-Control-Allow-Origin: *` and preflight**.
- The pipeline: `GET /api/<p>/resolve`.
- The native viewer: ViewerPC plus the HLS playlist re-checks.

**Must stay**
- Every endpoint and response shape above, CORS, the HLS routes.
- Serving `packages/app/build` with the catch-all route.
- `videoList.ts`, `videoViewer.ts` and `main.ts` routing.
- `nativeViewer.ts`: Video Vault and Tango bundle it in their own builds, so the website copy can go stale but must not break them.
- `WebController` for the online apps.

**Must change for native local apps**
- `deploy.py install` asserts `StartURL` and the site scope (around line 79).
- PolicyTests treats the local apps as a Safari tab.
- Website changes would then need app deploys to reach the phone.

**Suggestions for the native list**
- Do a full refresh on launch, foreground, network return and pull-down, not just `after=` polling.
- Update a row yourself after save, cut or return.
- Keep the server's order instead of re-sorting with a different collation.
- Use fixed 52 pt rows, store the highlight natively, and keep `media` when a video's type changes.