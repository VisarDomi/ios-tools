I found 18 custom iPhone apps under monthly renewal, which matches the "eighteen apps" in mac-access.md. They carry 21 bundle IDs, because the Tango app also contains three Safari Web Extensions. Of the 18, 16 run their interface in WKWebView, one is a WebGL game in WKWebView, and only Deep Town is already native with no WebKit.

## How the 18 were counted

| Repo (LaunchAgent `com.visar.renewal.<repo>`) | Apps | Where the list comes from |
|---|---|---|
| manga-reader | 6 | `apps/ios/build/providers.json` (generated from `src/core/sites.json`) plus `.paid` |
| gallery-reader | 2 | `apps/ios/providers.json` |
| gallery-downloader | 1 | hard-coded in its renewal.py |
| km-explorer | 1 | hard-coded |
| video-platform | 5 | `apps/ios/providers.json` |
| environment (twitter) | 1 | hard-coded |
| maid-heroes | 1 | hard-coded |
| deep-town | 1 | hard-coded |
| **Total** | **18** | |

The recovery copy in `/home/visar/Documents/environment/mac-renewal/renewal/*/config/` has exactly 18 per-app configs, and their bundle IDs match the table below. In the docs, "native" (for example "Six native provider apps") means paid-team signed installs, not a native interface. Swift and web line counts are from `wc -l` and leave out tests.

## The 18 apps

| # | App | Bundle ID | Repo / folder | What it is | UI technology | Swift / web lines | What WKWebView does | What "fully native, no WebKit" means |
|---|---|---|---|---|---|---|---|---|
| 1–6 | Asura, Scythe, Yaksha, QiScans, Lua, EzScans | `com.visar.{Asura,Scythe,Yaksha,QiManga,Lua,EzManga}Reader.paid` | `work/manga/manga-reader/apps/ios` (target `AsuraReader`, one codebase); web UI in `manga-reader/src` | Manga readers, one per site: Home, reader, downloads, PC backup | WKWebView with a bundled web UI on the custom scheme `asura://app/` | 668 Swift (shared) / ~3,770 TS, CSS, HTML (shared) | Hosts the whole app UI. No login, no remote pages, no content scripts. Swift already does all networking (a fetch bridge to URLSession), image caching and background downloads | **Feasible native rewrite.** Asura, EzManga, QiScans and Lua use the sites' unofficial JSON APIs. Yaksha and Scythe parse HTML with `DOMParser`, so they need a Swift HTML parser; Scythe reads only pages Cloudflare has cached |
| 7 | Hitomi | `com.visar.HitomiReader.paid` | `work/manga/gallery-reader/apps/ios`; web UI in `gallery-reader/src` | Gallery browser and reader | Bundled web UI on `gallery://app/` | 359 Swift (shared with #8) / ~2,800 web (providers 973) | Whole UI only. Swift does networking and the image cache | **Feasible native rewrite that depends on the site's private endpoints**: `ltn.hitomi.la` `gg.js` (parsed with regex), the binary `.nozomi` indexes, `galleries/<id>.js` and `tagindex` |
| 8 | Imhen | `com.visar.ImhenReader.paid` | same as #7 | Same, for imhentai.xxx | same | same | same | **Feasible**, but it scrapes HTML with regex |
| 9 | Gallery Reader | `com.visar.GalleryReader.paid` | `work/manga/gallery-downloader/apps/ios`; the UI comes from `gallery-server/downloader/public/offline` | Offline library of PC favorites, synced from the PC server at `192.168.1.197:7777` | Bundled web UI on `gallery://app/` | 1,340 Swift / 588 web plus a 55-line `native.js` adapter | Whole UI only. Swift owns storage, downloads and networking | **Easiest feasible rewrite**: it talks only to your own server, has the smallest UI, and Swift already does the heavy work |
| 10 | Ytb | `com.visar.Ytb.paid` | `work/video/km-explorer/apps/ios`; web UI in `km-explorer/src` | ytboob favorites browser and video player | Bundled web UI on `ytb://app/`, playing video with an HTML `<video>` element | 372 Swift / ~2,240 web | Whole UI and video playback | **Feasible native rewrite** on ytboob's Typesense search API and WordPress `wp-json` REST, with AVPlayer instead of `<video>`. Codec limits stay (KMPlayer is the fallback) |
| 11 | Tango local | `com.visar.TangoLocal.paid` | `work/video/video-platform/apps/ios` (shared `VideoApp/`) | PC recordings list plus player | WKWebView loading the PC's own website (`https://192.168.1.197:9999/videos/tango`). The video viewer is already native (AVPlayer, `Viewer*.swift`) | 3,229 Swift (`VideoApp`, shared by #11–15) / web is `packages/app/src` (~3,800, served by the PC) | Only the list page. A row opens the native viewer through `ViewerBridge` | **Feasible native rewrite** on your own PC API (`/api/videos`, edited, original). Only the list page and its bridge need replacing |
| 12 | FC2 local | `com.visar.FC2Local.paid` | same | same, for `/videos/fc2` | same | same | same | Same as #11 |
| 13 | SC local | `com.visar.SCLocal.paid` | same | same, for `/videos/sc` | same | same | same | Same as #11 |
| 14 | Video Vault | `com.visar.Ptrex.paid` | same | Lists your pipeline's uploads on Porntrex and XVideos | WKWebView loading porntrex.com with an injected content script (the `packages/app` bundle, ~587 KB built), plus a native AVPlayer viewer | shared / shared | Pages: porntrex.com. Content script at document start. A hidden second WKWebView (`SiteWorker.swift`) on `xvideos.com/robots.txt` makes same-site fetches. The XVideos login uses the site's own form inside the app | **Feasible but needs scraping.** Porntrex and XVideos HTML (`uploadSite.ts` uses `DOMParser`) would be fetched with URLSession and a cookie jar; the hidden WKWebView only exists to get around browser CORS. XVideos login needs a native form POST or a cookie import (the Porntrex session is already imported from the pipeline). The sites' bot defences are a risk |
| 15 | Tango | `com.visar.Tango.paid` (+ `.Login`, `.FC2Live`, `.SCLive`) | same; extensions in `Login/`, `Extension/`, `packages/live-extensions` | Live Tango streams | WKWebView loading tango.me with a content script (~581 KB built), plus a native AVPlayer viewer with a token-refreshing loader | shared / shared; extensions about 200 JS lines | Pages: tango.me. Content script. Cookies imported into WebKit (`TangoSession.swift`) | **Needs a site's private API**: everything would run on `gateway.tango.me`, using the imported `Tango-RT` cookies for refresh. Google sign-in cannot happen inside the app, so the Safari login handoff (the Tango Login extension) stays |
| 16 | Twitter | `com.visar.Twitter.paid` | `environment/twitter` | x.com without ads | WKWebView loading x.com, with the vendored Control Panel for Twitter script injected | 255 Swift / 8,263 JS (third-party `Vendor/.../script.js`) | Pages: x.com. Content script. A child WKWebView for Apple/Google sign-in popups. Other sites' links open in `SFSafariViewController`, which is also WebKit | **Inherently a website wrapper.** A native version would be an unofficial X client on its private GraphQL API, and the README notes X's app login needs App Attest. Not realistic |
| 17 | Maid Heroes | `com.visar.MaidHeroes` | `work/games/maid-heroes/apps/ios`; game in `maid-heroes/web` | Patched abandoned Unity game, fully offline | Unity WebGL in WKWebView on `maidheroes://game` | 436 Swift (saves, iCloud) / index.html 271 + shim 44, plus a 38 MB Unity build (wasm, data, framework.js) | The entire game | **A WebGL game that cannot run without a browser engine.** There is no game source, only IL2CPP-compiled wasm, so "native" would mean rewriting the game from scratch |
| 18 | Deep Town | `com.visar.DeepTown` | `work/games/deep-town/apps/ios` | Patched libGDX game, offline and ad-free | RoboVM/libGDX native ARM binary inside a 3-line C stub (`Stub/main.c`) | 0 Swift; 768 Java in `launcher/` plus 1,254 Java in `remap/` tooling | None (grep finds no WebKit) | **Already native.** Nothing to do |

## Safari Web Extensions

All three ship inside app #15 (Tango), renew with it, and run inside Safari by definition (`com.apple.Safari.web-extension`):

- **Tango Login** (`com.visar.Tango.paid.Login`): `Login/Handler.swift` (31 lines) plus 48 lines of JS. It reads Tango's cookies from Safari and saves them to the shared Keychain. It exists only because Google sign-in cannot run inside the app, so it stays even if Tango goes native.
- **FC2 live** (`com.visar.Tango.paid.FC2Live`) and **SC live** (`com.visar.Tango.paid.SCLive`): Manifest V3 extensions. They add download-list bars on live.fc2.com and the SC site and call the PC's `/api/fc2|sc/...`. Source is `packages/live-extensions/src` (156 lines); the native handler `Extension/Handler.swift` does nothing. These cannot become native; they can only be kept or dropped.

## Things that are not part of the 18

- **World Rumble** is the official App Store app, used unchanged. The Mac only stands in for Unity's cloud-save servers (`com.visar.world-rumble-cloud`, port 8077). It has no renewal.py and no custom build, so it is out of scope.
- **`work/video/stream-viewer`** is the older version of the Tango app; its `providers.json` files are leftovers. Its bundle ID `com.visar.Tango.paid` now belongs to video-platform's Tango, and stream-viewer is not registered for renewal.
- **`gallery-reader/extension/apple/Gallery Reader Extension.xcodeproj`** is an empty shell with no `project.pbxproj`.
- **PhotoRestore** (`com.visar.PhotoRestore`, a one-off photo import tool) and **HackintoshCheck** (`com.visar.HackintoshCheck`) are not renewed; mac-access.md says the HackintoshCheck and PhotoRestore folders on the Mac are not app mirrors. I could not see the phone, so I can't confirm whether either is still installed. Each renewal run on the Mac lists installed apps that no repo renews.

## Scope buckets for the plan

- **Already native (1):** Deep Town.
- **Feasible native rewrite on your own server (4):** Gallery Reader, Tango local, FC2 local, SC local. The three local apps already have the native viewer.
- **Feasible, but built on sites' unofficial APIs or scraping (10):**
  - JSON APIs: Asura, EzScans, QiScans, Lua, Ytb.
  - HTML or undocumented endpoints: Yaksha, Scythe, Hitomi, Imhen, Video Vault.
- **Needs a private API and keeps a Safari login extension (1):** Tango.
- **Inherently a website wrapper (1):** Twitter.
- **Needs a browser engine (1):** Maid Heroes.
- **Safari-only, cannot become native (3 extensions):** Tango Login, FC2 live, SC live.

On code reuse: the five apps in each of the two big groups share one Swift host and one web codebase (6 manga apps, 5 video apps). The 18 apps therefore come down to about 7 separate rewrites (manga, gallery-reader, Gallery Reader, Ytb, video-platform, Twitter, Maid Heroes), not 18.