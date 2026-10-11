I've inventoried the five iPhone apps and the web code they load. The native viewer is already done. The list pages, logins, catalogs and provider logic are still web, and they lean on WebKit in places nobody owns.

**Doc locations.** `apps/ios/notes.md` and `apps/ios/decisions.md` don't exist. The iOS rules live in the root `notes.md` and `decisions.md` and in `apps/ios/PORT.md`. `packages/live-extensions/notes.md` and `setup.md` cover the FC2/SC extensions.

**Doc contradiction.** `PORT.md:112-113` says "the app has no native token refresh or media relay". The code does have both: `ViewerMedia.swift:46-270` holds `TangoTokens` and the `TangoPlaylists` resource loader. `PORT.md:57-61` and `apps/tango/notes.md:11-12` describe the code correctly.

---

## 1. Architecture per app

**One host for all five apps.** `AppDelegate.swift` creates a single `WebController`: a full-screen WKWebView acting as "a Safari tab". The native `ViewerController` is added as a child over the page. Everything is configured per app from Info.plist keys that `scripts/project.py:97-114` writes from `providers.json`: `StartURL`, `SiteHosts`, `DurableCookie`, `LoginURL`, `KeepCookies`, `SiteWorkers`, `TangoLogin`, `DownloadList`, `LoginKeychainGroup`.

**Line counts.**

| Area | File (lines) |
|---|---|
| App shell, web side | WebController 332, AppDelegate 24, Policy 21 |
| App shell, online apps | SiteCookies 115, SiteWorker 104, TangoSession 72, DownloadList 43 |
| Viewer (native) | ViewerController 846, ViewerUnit 499, ViewerOverlay 462, ViewerMedia 270, ViewerVideo 166, ViewerPC 105, ViewerBridge 88, ViewerSession 82 |
| Total `VideoApp/` | 3,229 |
| Tango Login appex | Shared/Login.swift 71, Login/Handler.swift 31, Login/Resources 48 (cookies.js 16, manifest 9, popup.html 1, popup.js 22) |
| FC2/SC live appex | Extension/Handler.swift 8 (no-op) |
| Tests | Tests/PolicyTests.swift 66 |
| Scripts | project.py 125, deploy.py 116, renewal.py 29, build-provider.py 21, inspector-snapshot.js 7 |

**Web code the apps use** (`packages/app/src`):
- content/: boot.ts 50, vault.ts 14, tango-live.ts 5
- providers/: uploadSite.ts 183, xvideos.ts 112, porntrex.ts 82, vault.ts 127, tango-live.ts 218, types.ts 88, local.ts 35
- services/: catalog.ts 156, downloadList.ts 93, hls.ts 56
- routes/: videoList.ts 282, nativeViewer.ts 178
- The bundles also contain the web viewer (videoViewer.ts 615 plus player/*), which the apps never show. The built `content.js` is about 581 KB (tango-live) and 587 KB (vault) because it includes hls.js.

**Tango local, FC2 local, SC local**
- Web: the whole list page, loaded live from `https://192.168.1.197:9999/videos/<p>` (`main.ts`, `videoList.ts`, `nativeViewer.ts`). No script is bundled, so deploying the website updates the list.
- Native: the viewer, save/cut/return and +/- (`ViewerPC.swift`), progress and checkpoint, audio, pull-to-refresh control, failure view.
- Bridge: `videoViewer` only. Local videos carry `media` (the PC HLS URL from `mediaHint`, `local.ts:15`), so the viewer never asks the page for a source.
- Navigation is limited to the start URL and its subpaths (`Policy.swift:10-11`).

**Video Vault** (`com.visar.Ptrex.paid`)
- Web: the vault content script runs on `https://www.porntrex.com/video-vault/` (Porntrex's 404 page). It builds the list, pages both sites, resolves playback sources, shows notices and does the redirects.
- Native: the viewer, media requests with Referer/UA/cookies (`ViewerMedia.swift:25-37`), +/- via `Membership` (`ViewerPC.swift:66-105`), the `SiteWorker` hidden xvideos.com web view, and `SiteCookies`.
- Bridges: `videoViewer`, `vaultSite`, `downloadList`.

**Tango** (`com.visar.Tango.paid`)
- Web: the tango-live content script on `https://tango.me/`. It builds the list, refreshes the session every 30 min and the tokens every 5 s, and handles follow/block/related through `__videoApp`.
- Native:
  - Login: `TangoSession` moves the Keychain inbox into the web view's cookies and injects the account/session IDs; the login screen itself is in `WebController.swift:276-303`.
  - Playback: the `TangoPlaylists` loader plus `TangoTokens`.
  - Also: +/- via `ViewerPC` and `SiteCookies`.
- Bridge: `videoViewer`, plus the injected session script.
- It also hosts three appex: Login, FC2Live, SCLive.

**Bridges in detail**
- **`videoViewer`** (`ViewerBridge.swift:34-61`, page world, every app)
  - Page to native: `ready{origin,userAgent}`, `list`, `append` (`nativeViewer.ts:134-146`), `open{videos,index,progress}` (`:148-160`). Only the main frame of an allowed page may post.
  - Native to page: `callAsyncJavaScript("window.__videoApp.call(name,args)")` (`ViewerBridge.swift:67-77`) with `resolve`, `related`, `follow`, `block`, `remove`, `append`, `highlight`, `login` (`nativeViewer.ts:86-113`). Replies are `{ok}` or `{error, auth}`.
  - `call` loops until `ready` and has **no timeout** (`:68`). `pageChanged()` clears `ready` on every commit and on WebContent termination (`WebController.swift:236-240, 270-273`).
- **`vaultSite`** (`SiteWorker.swift:43-57`, Vault only)
  - Request `{site:"xvideos", path}`, reply `{status,url,text}`.
  - Accepted only from the main frame of an https porntrex host, for paths that pass `AppPolicy.workerURL` (`Policy.swift:16-20`).
  - The hidden 1×1 WKWebView loads `https://www.xvideos.com/robots.txt` at launch, shares the data store and UA, and runs a JS `fetch(..., credentials:"same-origin", cache:"no-store")` with a 30 s abort (`:14-19`). It reloads after failure or process death (`:60-72, 98-103`).
- **`downloadList`** (`DownloadList.swift:17-42`, Vault only)
  - Request `{list, action, identifier}`, reply `{status, body}`, for `/api/tango|fc2|sc/member|exists|add|remove` on the PC.
  - **Effectively unused in the app now.** Only `downloadList.ts:72-80` calls it, from the web viewer's overlay, which never runs in the app (`boot.ts:37-40`). The native overlay calls the PC directly.
- **`window.tangoNative`** is declared in `constants.ts:9,22` but never set by any Swift code, so `mediaOrigin` is always `''`. Dead.
- **Content-script injection** (`WebController.swift:152-161`): `WKUserScript` at document start, main frame only, `.page` world. Tango puts its session script first (`TangoSession.swift:55-58`). The takeover runs `window.stop(); document.open(); document.close()` (`boot.ts:22-27`) so site JavaScript never runs on taken-over routes.
- **Policy** (`Policy.swift:6-12`, `WebController.swift:201-235`):
  - Blocks credentials in URLs and `.`/`..` segments.
  - Online apps: https only, no port, listed hosts only; subframes are allowed (captcha frames, `:213`).
  - `videoapp://login` is intercepted (`:205-211`); `window.open` loads in the same tab (`:231-235`).
  - The Porntrex redirect handling at `:219-226` is **dead**: `providers.json` has no `loginUrl`, so `login` is nil.

## 2. Online providers

### Video Vault, XVideos (`xvideos.ts`)

**Listing**
- Pages: `/account/uploads`, `/account/uploads/N` (`LIST_PATH`, line 6). The cursor is JSON `{pending, visited}`.
- Pagination: `.pagination a[href]` limited to `LIST_PATH`, sorted by page number, `/0` and trailing `/` stripped (`:13, 40-59`). Ad links are skipped (`uploadSite.ts:51-53`).
- Rows: `[id^="listing-video-"]` (the id is the upload ID). The title link is the first `.title a[href]` that matches the video route and is a pipeline title. Duration comes from the text after "Duration:" in `.title + p` (`:29-37`).
- Video route: `/^\/video(?:\.[a-z0-9]+|[0-9]+|-[a-z0-9]+)\/[^/]+\/?$/i`.
- Signed-out detection (`:15-27`):
  - no rows plus `a.social-login-icon[data-method="signin"]` or a password input means sign-in is needed;
  - no rows and no `a[href="/account/uploads/new"]` is a generic error;
  - a redirect to another page is an error.

**Playback** (`:61-107`)
- The video page is fetched through `vaultSite` and parsed, never executed. A regex finds `html5player.setVideoHLS('…')` (`uploadSite.ts:169-176`).
- `hls_low.m3u8` is rewritten to `hls.m3u8` because Safari's low master omits HD.
- The master is fetched with `credentials:"omit"`. The highest `RESOLUTION` (pixels), then `BANDWIDTH`, is chosen. Masters with `AUDIO=`/`VIDEO=` groups are rejected.
- Fallbacks: `setVideoUrlHigh`, then `setVideoUrlLow` (MP4).
- Private uploads 404 when signed out (`verification.json:282`).

**Login and cookies**
- Login uses XVideos' own `/account` page in the main web view. Site JavaScript runs there and a captcha frame may appear.
- The content script on xvideos.com polls the uploads page every 3 s (`uploadSite.ts:107-116`) and then calls `location.replace(VAULT_URL)` (`content/vault.ts:10-13`).
- XVideos keeps the login in `session_token_auth`, a session-only version-1 cookie. `SiteCookies` gives it `session_token`'s expiry and stores it as version 0 (`SiteCookies.swift:99-111`), re-checking every 3 s and at resign/background (`WebController.swift:82-84`).

### Video Vault, Porntrex (`porntrex.ts`)

**Listing**
- Page 1 is `/my/videos/`. Page N is `/my/videos/?mode=async&function=get_block&block_id=list_videos_my_uploaded_videos&sort_by=&from_my_videos=N` (`:34-37`). A next page exists only if `a[data-parameters*='from_my_videos:']` links page+1 (`:40-44`). 30 uploads per page.
- Rows: `#list_videos_my_uploaded_videos [data-item-id]` (numeric), link `p.inf a[href*="/video/<id>/"]`, duration `.durations` (`:23-30`).
- Signed out means no list plus either a landing path other than `/my/videos/` or a password input (`:14-21`).

**Playback** (`:56-77`)
- Regex over the page scripts for `video_url`, `video_alt_url`, `video_alt_urlN` and their `*_text` labels. The highest `(\d{3,4})p` wins and plays as MP4.
- A value starting `function/` (the player's encoded form) throws.
- Sources are resolved only when needed and never stored (`PROVIDERS.md:34-35`; the test checks this at `providers.mjs:146`).

**Session**
- The phone never logs in. `npm run ptrex:connect-iphone` (`pipeline/src/phone/ptrexPhone.ts:56-127`) launches the app with `devicectl` and evaluates a script in its porntrex.com page through the ios-tools **WebKit inspector**.
- That script sets `PHPSESSID` and `confirmed` through **`document.cookie`** with a 400-day expiry, deletes `kt_member`, and checks login with a synchronous XHR to `/upload-video/`.
- `keepCookies` backs up `kt_member`, `PHPSESSID` and `session_token`, **not `confirmed`**.

### Vault as a whole (`vault.ts`)
- Both sites' next pages load in parallel. Each site has its own cursor; a site's sign-in error becomes a notice plus an "incomplete" flag; other failures retry (`:46-71`).
- Filenames are `<site>-<id>`. Order is oldest first by the label's `YYYY-MM-DD HHMMSS`, stable, with untimestamped uploads last (`:91-95`).
- Marks: the same recording (date, time, streamer) on both sites shows `Xvid` or `Ptrex` (`:97-107`).
- Filter: only `[… YYYY-MM-DD HHMMSS …]` titles are listed (`uploadSite.ts:133-135`). The label is the bracket's contents (`:137-142`). The +/- streamer comes from `^\d{4}-\d{2}-\d{2}\s+\d{6}\s+(.+?)(?:\s+\|.*)?$` (`:104`).
- Notice texts are at `vault.ts:38-42`; the XVideos one links `https://www.xvideos.com/account`.
- Routes:
  - `/video-vault/` is the list; `/video-vault/<site><path>` is a viewer route (`:81-85, 109-113`).
  - On porntrex.com, any other page redirects into the vault (`:124-127`, `content/vault.ts:6-9`).
  - On xvideos.com, uploads and video pages redirect to the vault, and `/account` stays native until signed in.

### Tango live (`tango-live.ts`)

**Gateway calls** (all to `https://gateway.tango.me`, credentialed XHR with `Accept: application/json; charset=UTF-8`, `:14-25`):
- Session: `POST /session-service/public/v2/session/web/refresh` with body `{accountId, sessionId}` and the `Tango-RT` cookie, which sets `Tango-ST` (1 h) and sometimes rotates `Tango-RT` (`:61-65`).
- Tokens: `GET /proxycador/api/public/v1/live/stream/v1/tokenData` sets the `tt`, `ttu`, `tte` cookies (10 s) (`:67-69`).
- Lists: `POST /recommendator/social/v2/list/following?includeAlias=true` and `…/following_recommendations`, both with body `{}` (`:99-104, 130-143`).
- Records kept: `stream.status === "LIVING"` and (`isPublic` or `streamKind === "PUBLIC"`); ID from `anchor|stream.encryptedAccountId`; `stream.id`, `stream.masterListUrl`, `firstName`, `aliases[0].alias` (`:90-97`).
- Blocklist: `GET /abregistrar/connection/v1/blocklist`, answered as an array or `{users}` (`:106-109`).
- Names: `POST /proxycador/api/public/v1/profiles/v2/batch?basicProfile=true&liveStats=false&followStats=false` with an array of IDs, best effort (`:112-127`).
- Follow: `POST …/follow/add|remove` with the raw ID as body (`:183-185`).
- Block: unfollow first, then `POST /abregistrar/connection/v1/blocklist` with `{action:"BLOCK", account_id:[id]}`, expecting `error_code: 0` (`:186-194`). Unblock (action `UNBLOCK`) exists only in `apps/tango/scripts/tango-unblock-blocklist.mjs`.
- Co-streamers: `POST …/live/stream/v2/watch?requestId=<uuid>` with the stream ID as body; reads `multiBroadcast.streams[].stream.{mbDescriptor{accountId,streamId},streamURL}` (`:195-216`).

**List rules**
- Followed streams first, one entry per streamer, blocked ones removed. Titles are `alias||id firstName`; `pageUrl` is `/stream/<streamId>` (`:81-88`).
- Playlists are kept in sessionStorage `tango-live-media` (`:72-77`); `mediaHint` reads them (`:149-152`).
- `live.start()` runs refresh and tokens, then `setInterval` every 5 s and every 30 min, plus a `pageshow` token refresh (`:175-182`).
- `loginUrl` is `videoapp://login`.
- Session IDs come from localStorage `latest_account_id` and sessionStorage `username`, which TangoSession injects. The fallbacks `persist:production:user` and `persist:production:sessionDetails` belong to the Tango website (`:46-59`).

**Native Tango playback** (`ViewerMedia.swift`)
- `TangoTokens` (actor):
  - runs every 5 s while the viewer is open (`:68-76`), using an ephemeral cookie-less URLSession with a hedged second request after 1 s (`:128-148`);
  - refreshes the session itself only when the app is backgrounded and `Tango-ST` has less than 300 s left (`:108-110, 151-170`), with `Origin`/`Referer: https://www.tango.me`, and writes the new ST/RT back into the WKHTTPCookieStore;
  - reads ST/RT from the web view's cookie store (`:184-191`).
- `TangoPlaylists`:
  - the `tangohls://` scheme sends every playlist request (including live reloads) through the loader with `Cookie: tt=;ttu=;tte=` (`:84-95`) and retries once on 401;
  - segment, key and map URIs are rewritten to absolute https (`:245-269`); segments need no tokens;
  - 404/410 maps to file-does-not-exist, which removes the stream.

**Tango Login extension and keychain**
- `cookies.js` uses `browser.tabs.query` plus `cookies.getAllCookieStores()` filtered by the active tab's ID. It reads `Tango-RT`, `-DI`, `-DeviceId`, `-ST`, `-WST` for the URL `https://gateway.tango.me/session-service/public/v2/session/web/refresh`.
- `popup.js:12` calls `runtime.sendNativeMessage('com.visar.Tango.paid', …)`.
- `Login/Handler.swift:9-23` validates: at most 5 cookies, allowed names, domain `gateway.tango.me`, path starting `/`, non-empty value under 32 KB, not expired. It sets `handoffComplete=false` and saves to the Keychain.
- Keychain item: generic password, service `TangoLogin`, account `session`, access group `<TEAM>.com.visar.Tango.paid`, `AfterFirstUnlockThisDeviceOnly` (`Shared/Login.swift:30-60`). The entitlement is generated at `project.py:40-48`.
- App side (`TangoSession.swift:13-34`):
  - pending inbox shows "Confirm … cleared";
  - on confirm, the cookies are set into the WK store and the inbox is deleted;
  - an RT JWT with `accountId`/`sessionId` claims gives `.ready(script)`; otherwise `.required`.
- The user must delete Tango's Safari website data and must not use Log out (`popup.js:15`).

**What needs a browser engine, and the native alternative**

| Today | Needs a browser? | Native option |
|---|---|---|
| XVideos login (site JS, possibly Friendly Captcha in a frame) | Yes | A WKWebView only for `/account`, then copy cookies from `WKHTTPCookieStore` into the app's own cookie jar. ASWebAuthenticationSession can't return the cookies. |
| Tango Google login | Yes (Google blocks embedded web views) | Keep the Safari handoff (Tango Login extension and Keychain inbox) and import cookies into a native jar. ASWebAuthenticationSession ends on tango.me with HttpOnly gateway cookies, so it can't hand them back. |
| Porntrex session | Today it depends on the WebKit inspector plus `document.cookie` | Replace with a native path: copy a file into the app container with `devicectl … copy to --domain-type appDataContainer`, or a LAN endpoint on the PC. |
| Listing, video pages, flashvars | No; pages are parsed, never executed | URLSession plus an HTML parser (SwiftSoup or equivalent) for the selectors above. |
| XVideos from porntrex.com (CSP/CORS workaround, SiteWorker, vault-on-404 trick) | No, only needed because of web origins | Plain HTTP; the whole hosting trick disappears. |
| Tango gateway, PC API | No | URLSession; the CORS reliance goes away. |
| JS challenges (Cloudflare and similar) | None handled today | Same Apple network stack, so TLS looks like Safari's, but header sets differ (`Sec-Fetch-*`, Accept). Watch for challenges. |

## 3. User-facing features and behaviour

**List rows** (`videoList.ts:150-191`, `style.css:42-113`)
- Anchors `.video-row`, 52 px tall. Name on one line with ellipsis, 16 px. Monospace meta line, 13 px grey: duration (`h:mm:ss`, `mm:ss` or `--:--`, or `LIVE` for Tango), an orange mark, and a size estimate in MiB (duration × 2.3 Mbps for local, 4 Mbps for vault; bold when over 350 MiB; empty for live).
- Classes: `current-video` (background `#0e0e0e`, bold), `live` (red name: local `.active` recordings and Tango), `edited` (orange name).
- Every row is rendered; no virtualization or filtering (`app/decisions.md:13`).
- No safe-area padding on the list. The page uses `viewport-fit=cover` and the scroll view's insets are `.never`.

**Order**
- Local: the server sorts by filename (`retrieve.service.ts`), and polling re-sorts (`videoList.ts:237`).
- Vault: oldest recording first.
- Tango: followed, then recommended, with co-streamers appended at the end.

**Highlight**
- Stored in localStorage `video-highlight:<provider>`.
- The viewer sends `highlight(filename, false)` on every current change (`ViewerController.swift:293`) and `(…, true)` on close (`:778`); the list scrolls the row into view only if it's offscreen (`videoList.ts:140-148`).
- First load scrolls the highlighted row to centre. Online lists instead restore `history.state.videoListY`, which a row tap writes with `replaceState` (`:62-67`).

**Refresh, polling and paging**
- Pull-to-refresh: a native `UIRefreshControl` calls `webView.reload()` or retries the failed URL (`WebController.swift:95-97, 192-199`). A reload makes `catalog.open(reuse=false)`, so Tango fetches a fresh list and the vault opens its kept list and reloads behind it.
- Local polling: every 1 s, `/api/videos?provider=&after=<last>`, additions only, only while visible. On `pagehide` or hidden, polling stops; on `pageshow` (persisted), visible again or `online`, the full list is refetched and reconciled without scrolling (`videoList.ts:76-120, 204-248`).
- Online paging (`catalog.ts`):
  - The first page renders, later pages append. Retries back off from 1 s, doubling to 30 s.
  - A sign-in error calls `location.assign(loginUrl)` (`:69`). Paging stops when hidden.
  - The catalog is cached in sessionStorage `video-catalog:<p>` (`:128`) and reused only when the navigation type is `back_forward` (`videoList.ts:62`).
  - The vault keeps its last complete list in localStorage `video-catalog:vault:complete` (`:124`), opens with it (`restart:true`), and keeps a site's earlier rows when that site is incomplete (`:113-125`).
  - `cachedVideo` finds a route's video in either cache (`:149-156`).
  - Live list edits from the viewer: `append`, `remove`, `update` (`:92-108`).

**+/- download lists** (native, `ViewerOverlay.swift:154-257`, `ViewerPC.swift:46-105`)
- States: ⏳ loading or changing, ➕/➖ with a green or red border, ⚠️ unavailable, a yellow ring after a failed change (keeping the last confirmed state), 🔍 not found, and one small button per list while choosing.
- Local recordings use the streamer from the filename; Tango uses the streamer ID on the tango list.
- Vault: membership is asked on all three lists. ➕ asks `GET /api/<list>/exists` on all three: one hit adds, several offer a choice, none shows 🔍. ➖ with several lists asks which.
- A change is confirmed by asking membership again.
- PC endpoints: `GET /api/<l>/member?identifier=`, `GET /api/<l>/exists?identifier=`, `POST /api/<l>/add|remove {identifier}` returning `{success:true}`.
- Edits: `POST /api/videos/<f>/edited?provider=`, `POST /api/edit {filename,segments,provider}`, `POST /api/videos/<f>/original?provider=` (`ViewerPC.swift:36-44`). A 404 removes the video from the viewer (`ViewerController.swift:645-653`).

**Notices and messages**
- Vault notices above the list (`videoList.ts:194-202`).
- "Loading…", "No videos found.", boot errors in red (`boot.ts:41-48`).
- The viewer shows "No live streams are available." (`ViewerController.swift:331`).

**Login detection**
- Tango: `TangoSession` states. A 401/403 in `live.start()` sends the boot to `location.replace('videoapp://login')` (`boot.ts:42`). A viewer auth error closes the viewer and sends `login` (`ViewerController.swift:714-717`).
- Vault: per-site notices.

**Failure view**
- A failed provisional navigation (not cancelled, not WebKit error 102) shows "Can't reach your PC." or "Can't reach <host>." with the error and Retry (`WebController.swift:250-269, 311-331`).

**Restore on relaunch**
- The page: `interaction-state`, written on `didFinish` and at resign/background (`WebController.swift:179-187, 241-246`). A blank restore falls back to the start page after 1 s (`:165-173, 244`).
- The viewer: `viewer-checkpoint.json` is loaded in `viewDidLoad` and shown at once (`:104-107`). It is cleared on close (`ViewerController.swift:769`).
- An old viewer address opens the list with that video in the viewer (`boot.ts:37-40`, `main.ts:22-31`, `nativeViewer.ts:163-178`). If the same video is already showing, only the list is updated (`WebController.swift:112-119`).

**Lock and background**
- The page is suspended, so polling and paging stop and bridge calls queue.
- Viewer on background (`ViewerController.swift:739-747`): players are detached from their layers, neighbours pause, progress and checkpoint are flushed.
- Viewer on foreground (`:749-755`): layers are reattached and units resume; neighbours rejoin the live edge.
- After a call or Siri interruption ends, playback resumes (`:758-761`).
- The idle timer is disabled while the viewer is open (`:172, 777`).
- The app delegate saves on resign and on background inside a background task (`AppDelegate.swift:17-23`).

## 4. Persisted data and what to migrate

| Store | Key or file | Owner | Migrate? |
|---|---|---|---|
| `Library/Application Support/LocalVideos/viewer-progress.json` | `{filename: seconds}` | native | keep |
| `…/viewer-checkpoint.json` | `{provider, current: filename␟type, videos:[raw]}` | native | keep or convert |
| `…/interaction-state` | WKWebView back/forward blob | WebKit | drop |
| `…/login-cookies.plist` | binary plist of cookie properties for `keepCookies` plus the durable cookie, protection `completeUntilFirstUserAuthentication` | native (online apps) | fallback source of cookies |
| WKWebsiteDataStore cookies | Vault: `PHPSESSID`, `confirmed`, `kt_member`?, XVideos `session_token`, `session_token_auth` and others. Tango: `Tango-RT`, `-DI`, `-DeviceId`, `-ST`, `-WST` | WebKit | **must migrate.** Read once from `WKHTTPCookieStore` in the first native build; the plist lacks `confirmed` and other XVideos cookies. Make sure the latest rotated `Tango-RT` is the one taken. |
| localStorage | `video-progress-<filename>` (old web progress; only seeded per opened list, `nativeViewer.ts:154-158`) | WebKit | optional one-time export (needs a WKWebView on each origin) |
| localStorage | `video-highlight:<provider>` | WebKit | migrate or reset |
| localStorage | `video-catalog:vault:complete` | WebKit | cache, can rebuild |
| localStorage / sessionStorage | `latest_account_id` / `username` (Tango, injected each launch) | WebKit | none (derived from RT) |
| sessionStorage | `video-catalog:<vault|tango-live>`, `tango-live-media` | WebKit | none |
| history.state | `videoListY` (per history entry, inside interactionState) | WebKit | becomes a native scroll position |
| Keychain | `TangoLogin`/`session` in `<TEAM>.com.visar.Tango.paid` (an inbox, normally empty) | native + appex | keep the format |

Bundle IDs must stay the same, otherwise sessions and data are lost (`PORT.md:20-21, 153-154`: "Never uninstall to update"). IndexedDB and service workers are not used.

## 5. Tests, verification, build, deploy, renewal

**Tests**
- `Tests/PolicyTests.swift`: policy and registry only (allowed and blocked URLs, `workerURL`, names, bundle IDs, host counts 2 or 4). Run on the Mac via `deploy.py test`.
- `packages/app/test/providers.mjs`: Playwright WebKit against the built content scripts with fixtures. Covers the vault, Tango live, the FC2 live bar and local lists. It exercises the **web viewer** path with the `downloadList`/`vaultSite` stand-ins, **not** the native bridge.
- `scroll-settlement.mjs`: the web viewer only.
- `viewer.mjs`: Chromium against the deployed site. It is the only check of the native-message protocol (`list`, `ready`, `append`) (`:101-112`).
- Elsewhere: server tests for the list routes; `pipeline/test/ptrexSession.test.mjs` for the phone cookie script.
- There are no Swift tests for the viewer, bridge, SiteCookies or TangoTokens.

**Stale checks**
- `apps/tango/scripts/phone/*.js` and the video part of `scripts/inspector-snapshot.js` query web viewer DOM (`.video-stage`, `.streamer-name`, `.current-scope video`) that no longer exists in the apps.
- `verification.json` (dated 2026-10-02/04) predates the native viewer (commit 087d530, 10-11) and records Tango build 18 while `providers.json` says 22.

**Build, deploy, renewal**
- `project.py`: one Xcode project per provider, iOS 17.0, no icon, `UIBackgroundModes: [audio]`, `NSAllowsLocalNetworking`, local-network usage text, portrait and landscape orientations, `content.js` as a resource for online apps, appex targets.
- `build-provider.py`: shared signing lock, Release, `-allowProvisioningUpdates`.
- `deploy.py sync`: runs `node build-content.mjs`, stages `build/<p>/content.js`, builds and stages `dist/extension/{fc2-live,sc-live}`, rsyncs to the Mac.
- `deploy.py install` (`:71-115`): asserts the Info keys, that the content script matches the staged copy, the extensions, no icon, signature, team, device, keychain group and more than 45 days of expiry, then runs `devicectl install`, `deliver.py installed` and launch.
- `renewal.py`: inputs are `VideoApp`, `Shared`, `providers.json`, `project.py`, `build-provider.py`, plus `build/<p>/content.js` for online apps and `Login`, `Extension`, `build/tango-live/{FC2Live,SCLive}` for Tango.
- A native rewrite changes the inputs, the `deploy.py` asserts and `PolicyTests`, and needs `configure-refresh` re-run.

## 6. Owner requirements as written

- Play until the end: "the videos must play on until they end" (`decisions.md:210-211`). "Videos play on through lock and the background until they end (background audio), and nothing pauses, reloads or jumps on the way back" (`PORT.md:37-39`). "Videos never stop by themselves: a failed or stalled item recovers at its position, except a live stream that ended" (`ViewerUnit.swift:5-6`).
- Zoom: "A pinch zooms the current video anywhere on screen. Zoomed, the list stays put and the left edge is not Back: drags pan the picture as in Safari, except the upper half's horizontal seek (which then starts anywhere). Zoomed back out, swipes move through the list again. The left edge otherwise slides the viewer away to the list." (`PORT.md:45-48`; `flow.md:4,10`).
- Feed: the same three-scope feed, "neighbours touching during a swipe, a runway landing moving one video", upper-half seek, lower-half controls swipe, "all three videos muted until unmuted, progress every 3 s" (`PORT.md:42-44`; `app/decisions.md:38-80`).
- Audio: unmuted takes the audio "like Safari's video with sound", with lock-screen play/pause, scrubber and next/previous; muted mixes with other apps; resumes after a call or Siri (`PORT.md:62-66`).
- Lists like Safari: "Like a restored Safari tab … In the list: edge-swipe Back/Forward, pinch zoom, inline playback, portrait/landscape and pull-down reload. An unreachable PC or site shows a message with Retry" (`PORT.md:123-127`). "Physical finger feel (swipes, momentum, pull-down reload, landscape) remains for the user to compare with Safari" (`verification.json:217`). "Preserve native Safari list/viewer navigation, bfcache restoration, and edge-back ownership" (`app/decisions.md:153-154`). "A bfcache `pageshow` refetches without moving the restored scroll" (`decisions.md:194-195`).
- Tango: list order kept, co-streamers appended without duplicates, refresh Home for a new list, two-step block (`apps/tango/notes.md:4-9`, `flow.md:1-10`).
- Porntrex: "Do not log in on the phone: it stops the pipeline" (`PORT.md:101-102`).
- **Volume control: no doc mentions it.** The only control is the 🔇/🔊 mute on the current video (`ViewerOverlay.swift:320`); volume is the hardware buttons.

## 7. Hidden dependencies

| Dependency | Used? Where | What breaks if it changes | Native replacement |
|---|---|---|---|
| bfcache, `pageshow`/`pagehide` | Yes, rarely in the apps: list `pageshow` restore (`videoList.ts:102-106`), Tango token refresh on `pageshow` (`tango-live.ts:181`). It only triggers on web back/forward, e.g. back after the XVideos login round trip. | A list restored without reconcile, stale tokens | Viewer-close and foreground hooks that reconcile without moving scroll |
| WebKit session history, back-swipe, snapshots | Yes: `allowsBackForwardNavigationGestures` (`WebController.swift:86`) on the list. The viewer's back is native (`ViewerController.swift:573-586`). | List Back/Forward gestures | A navigation stack, if wanted at all |
| `interactionState` restore | Yes (`WebController.swift:165-187`), iOS 15+; the 1 s blank fallback works around restores with no navigation callback | Reopening the last page and its history, `videoListY` | Persist the list scroll position and route natively |
| Navigation type `back_forward` and sessionStorage across a restore | Yes (`videoList.ts:62`, `catalog.ts:32-47`). **Not verified:** whether a relaunch restore counts as `back_forward` and whether sessionStorage survives decides if Tango shows a fresh list or the previous run's. | Unpredictable relaunch freshness | An explicit native rule |
| Scroll restoration | Yes, by hand: `history.state.videoListY` (online) or the highlight (local). WebKit's own restoration is mostly moot because rows render asynchronously. | List position after a kill or reload | Native offset |
| WebKit page zoom | Yes: `ignoresViewportScaleLimits` (`:45`), pinch-zoom on the list | List pinch zoom | Drop or reimplement |
| WK cookie store and its sync with native code | Yes. `ViewerMedia.swift:32-36` passes WK cookies to `AVURLAsset`. `TangoTokens` reads and writes the WK store (`:184-191, 166-169`). `SiteCookies` exists because WebKit writes cookies to disk only on suspension and change notifications don't fire for response cookies (`verification.json:206-210`). SiteWorker shares the store (`SiteWorker.swift:32`). PC calls use `URLSession.shared` with no cookies. | Logins, media authorization, the RT rotation race (page and native both refreshing) | One `HTTPCookieStorage` or own jar with a single refresh owner |
| localStorage/sessionStorage owned by WebKit | Yes (table in section 4). Possible eviction: storage pressure or ITP caps; observed not capped for the 400-day `PHPSESSID` | Highlights, the vault's kept list, old progress | Native files |
| Site JS and DOM | Pages are never executed (takeover plus DOMParser). Exceptions: the XVideos `/account` login, and any tango.me path the script doesn't match (`boot.ts:14-15`). Depends on site HTML: selectors, the `setVideoHLS` and flashvars formats, Porntrex 404 at `/video-vault/` with no CSP. | Scrapers when the sites change; the vault host trick | Same selectors in Swift; the host trick goes away |
| CORS bypasses through native code | Yes: `vaultSite`, `downloadList`, native media headers, plus XVideos CDN CORS (`credentials:"omit"`), gateway credentialed CORS, and PC `cors()` (`server/src/main.ts:40`) | Not needed natively. Keep PC CORS for the Safari extensions. | n/a |
| User agent | Online apps append `Version/<major>.0 Mobile/15E148 Safari/604.1` (`WebController.swift:52`). The page reports `navigator.userAgent` and native media reuses it. Local apps use WebKit's default. | Site acceptance; Porntrex `get_file` with Referer and UA | Explicit Safari UA string and Referer |
| Timers and visibility when backgrounded | Yes: page timers stop when suspended (hence native `TangoTokens`). `call()` waits forever for a suspended or unready page (`ViewerBridge.swift:68`): in the background, vault next/previous (no `media`) and co-streamer discovery stall until foreground. | Background behaviour | Fully native, no page |
| WebContent process termination | Handled: reload plus `pageChanged` (`WebController.swift:270-273`), SiteWorker reload | List re-posts and catalog refetch | n/a |
| Safari Web Extensions | Tango Login: MV3, cookies API with per-tab cookie stores, native messaging, shared keychain, Safari's Google login. FC2/SC live: run in Safari on live.fc2.com and stripchat.com and fetch the PC (`live-extensions/src/extension/background.ts`); they need no app code but must stay embedded in some host app. | Login handoff; FC2/SC bars | Keep the appex targets in the rewrite |
| WebKit inspector (`isInspectable`, `:87`) | **Yes**: `ptrex:connect-iphone` (`ptrexPhone.ts:122`), the phone scripts, inspector-snapshot | **Porntrex session handoff breaks** | devicectl file copy or a LAN endpoint |
| Recent web features | `scrollend`, wakeLock (web viewer only), `crypto.randomUUID`, `throwIfAborted`, `100dvh`, `callAsyncJavaScript`/`WithReply` (iOS 14), `interactionState` (iOS 15), `isInspectable` (16.4); the bundle targets Safari 17 | iOS floor | iOS 17 target |
| PC server and certificate | Hardcoded `https://192.168.1.197:9999`: `providers.json`, `DownloadList.swift:11`, `ViewerPC.swift:7`, `constants.ts:50`, `live-extensions/src/core/config.ts:2`. mkcert root trusted on the phone, `NSAllowsLocalNetworking`, local-network permission. Without its certificate the server falls back to HTTP (`notes.md:78-79`), which breaks every URL. | Everything local; +/- | Make the server address configurable; keep the same trust |
| iOS behaviours | Background audio also while muted (`.playback`+`.mixWithOthers`, `ViewerSession.swift:56-65`). Player layers detached in the background (`ViewerController.swift:737-747`). Lifecycle split: app delegate saves on resign and background; the viewer reacts only to did-enter-background and will-enter-foreground. Interruption resume ignores the system's should-resume flag (`:758-761`). | Unchanged by a rewrite | Carry over |

**Code comments that mention WebKit or Safari workarounds**
- `WebController.swift`: 4-8, 51, 80-81, 94, 164, 168, 181, 191, 212, 216-218, 243, 259-260, 310.
- `SiteCookies.swift`: 5-13, 104. `AppDelegate.swift:19`. `SiteWorker.swift:4-9`. `TangoSession.swift:4-8`. `ViewerMedia.swift:40-45`.
- `ViewerController.swift`: 13-21, 125, 572, 737-738. `ViewerSession.swift:5-9`. `ViewerBridge.swift:66`. `ViewerVideo.swift`: 75, 113, 132-134, 153. `project.py:94`.
- `nativeViewer.ts:7-11`, `types.ts:30-31`, `xvideos.ts:66-67`, `tango-live.ts`: 44-45, 178. `boot.ts:20-21`. `vault.ts:9-12`. `videoViewer.ts:419` ("Never write scroll position during iOS momentum").
- `app/decisions.md`: "Native live finalization", "Transparent fixed overlay" (a painted backdrop makes Safari's chrome opaque), "Player recovery".

## Other gaps the rewrite must decide on

- `ProgressStore` writes to disk only on background or viewer close (`ViewerVideo.swift:97-110`), so a foreground crash loses progress.
- Bridge calls have no timeout.
- Dead code: the `LoginURL` branch, `tangoNative`, and the `downloadList` handler in the apps.
- In the foreground, Tango tokens are refreshed twice: by the page and by native code.
- `SiteCookies` doesn't back up `confirmed`, `Tango-ST` or `Tango-WST`.