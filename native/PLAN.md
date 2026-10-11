# Native rewrite: plan

Every custom iPhone app that runs its interface in WebKit becomes a native UIKit app. No app
state, navigation or feel depends on WebKit or Safari any more. The owner decided this on
2026-10-11 and handed the rewrite to the coding agent; the owner provides the phone and the
few decisions listed under "Decisions" below.

Read this file, then [STATUS.md](STATUS.md) (what is done and what is next), then the app's
inventory in [inventory/](inventory/) before touching an app. The inventories are the
read-only surveys of 2026-10-11: every feature, stored file, provider request, owner
requirement and hidden dependency of the current apps. They are the parity checklist.

## Scope

| Codebase | Apps | Today | Native target |
| --- | --- | --- | --- |
| gallery-downloader | Gallery Reader | Web UI over native storage and downloads | Native list and reader on the existing store |
| gallery-reader | Hitomi, Imhen | Web UI, web storage, web providers | Native everything; providers in Swift |
| manga-reader | Asura, Scythe, Yaksha, QiScans, Lua, EzScans | Web UI and providers, native storage | Native everything; providers in Swift |
| video-platform | Tango local, FC2 local, SC local | PC web page list, native viewer | Native list on the PC API |
| video-platform | Video Vault, Tango | Site pages with content scripts, native viewer | Native lists, scrapers and gateway client |
| km-explorer | Ytb | Web UI, web video player | Native grid, native player |

Out of scope: Twitter (an x.com wrapper; a native client would need X's private API and
App Attest), Maid Heroes (a compiled Unity WebGL game; it needs a browser engine), Deep Town
(already native), World Rumble (the App Store app). The three Safari Web Extensions (Tango
Login, FC2 live, SC live) run inside Safari by definition and stay, embedded in the Tango app.

The video-platform website stays as it is for Safari and desktop browsers; only the iPhone
apps stop using it. The manga, gallery-reader and km-explorer web UIs exist only for the apps
and are deleted once their native app has parity on the phone.

## Where WebKit may still appear

1. One-time migration readers. Hitomi/Imhen and Ytb keep their user data in WebKit IndexedDB
   at their `gallery://app` / `ytb://app` origins, and the video apps keep logins in
   WebKit's cookie store. The first native build opens a hidden WKWebView at the old origin
   once, exports that data into native files, and never touches WebKit again. The PC backups
   are the fallback. The reader is deleted in a later build once the export is confirmed.
2. Login sheets for sites whose sign-in needs the site's own JavaScript or a captcha
   (XVideos' `/account`). The sheet only produces cookies, which go into the app's own jar;
   nothing else depends on it. Tango keeps its Safari login handoff (the Login extension
   plus the Keychain inbox), as Google blocks embedded sign-in.

Nothing else: no pages, no content scripts, no bridges, no inspector-driven workflows.

## Architecture

- UIKit, programmatic, Swift 6 language mode with strict concurrency, UIScene lifecycle,
  iOS 26 deployment target (the only phone runs iOS 26.6; Xcode 26.3 on the Mac).
- One shared Swift package, **NativeKit**, canonical in `ios-tools/native/Kit`, vendored
  into each repository as `apps/ios/Kit` by `native/scripts/vendor-kit.py` (renewal
  fingerprints only files inside a repository, so the copy is what renewals build; a
  changed copy is deployed and approved like any input). `vendor-kit.py --check` fails when
  a copy drifts from the canonical source.
- Each repository keeps its own app target(s), provider configuration and renewal entries.
  Projects use Xcode's synchronized folders, so adding a file never edits the project.
- No third-party packages. HTML is parsed with the system libxml2 (HTML parser plus XPath);
  JSON with Codable; images with ImageIO.

### NativeKit modules

| Module | Owns (replacing a WebKit behaviour) |
| --- | --- |
| `KitCore` | Atomic durable files, JSON stores, logging, the app clock, debug-state dumps (replacing the inspector) |
| `KitNet` | URLSession clients: per-request Referer, explicit user agent, retry and backoff policy (the current `Models.swift` rules), cancellation tied to screens, the PC client with the bundled CA (`LocalTrust`), one cookie jar per app |
| `KitHTML` | libxml2 HTML documents and XPath/CSS-subset queries (replacing DOMParser) |
| `KitImages` | Disk cache, ImageIO downsampling to display size, bounded decoded-memory cache, a priority loader (nearest the screen first, every image eventually when "eager" is required), retry (replacing WebKit's image pipeline and the image-retry code) |
| `KitNavigation` | A navigation stack whose screens stay alive (replacing bfcache): interactive edge-swipe back, swipe forward to the last popped screen, per-screen state saved continuously and the whole stack rebuilt at launch (replacing session history and `interactionState`) |
| `KitLists` | Large lists with stable anchors: thumbnail-strip rows, card grids, plain rows; position as anchor item plus fraction, horizontal strip offsets, keeping the anchor when sizes change (replacing scroll restoration and the app-side anchoring code) |
| `KitReader` | The vertical image strip: whole-strip pinch zoom and pan like Safari, layout from known sizes, continuous appending, position as image plus fraction, `scrollend`-style settling (finger up and momentum over) |
| `KitLifecycle` | Resign-active versus background, background URLSession hand-off and reclaim, background tasks for final saves, idle timer |
| `KitVideo` | The existing native viewer (feed, zoom, overlay, audio session, recovery), moved out of video-platform so Ytb shares it |

## Order

Each step ends with the app installed over the existing bundle ID (data kept), approved
for renewal, and its parity checklist verified on the phone.

1. **Foundations.** NativeKit skeleton, vendoring, project template, Mac test loop
   (macOS `swift test` for the non-UI modules, simulator tests and screenshots for UI).
2. **Gallery Reader.** The pilot: own server, native store already done, smallest UI. It
   proves navigation, strips, reader, zoom, eager loading and launch restore.
3. **Tango local, FC2 local, SC local.** Native list on the PC API plus the existing viewer.
   Fixes found by the survey: full refresh on foreground, rows updated after edits, `media`
   kept after a type change, server order kept.
4. **Hitomi, Imhen.** Providers in Swift (Nozomi, `gg.js` parsed, galleries; Imhentai HTML),
   search, saved searches, suggestions, info sheet, favorites, PC backup protocol,
   favorites sync, IndexedDB migration.
5. **Manga (six apps).** Home catalogs, continuous reader, chapter windows and downloads,
   progress rules and migrations, PC Load/Save; providers in Swift.
6. **Video Vault.** XVideos and Porntrex scrapers, cookie jar, XVideos login sheet, Porntrex
   session delivered without the inspector, cookie migration.
7. **Tango.** Gateway client (session, tokens, lists, follow, block, co-streamers), single
   owner of session refresh, Keychain handoff kept, cookie migration.
8. **Ytb.** Typesense and WordPress clients, favorites grid, native player sharing
   `KitVideo`, PC backup, IndexedDB migration.
9. **Cleanup.** Remove migration readers, web UIs that only served the apps, dead bridges,
   stale docs and checks; update renewal inputs and verification records.

## Testing

- Non-UI modules and providers: `swift test` on the Mac against recorded fixtures (real
  responses saved under each repository's test fixtures) plus opt-in live checks.
- Screens: simulator UI tests (iOS 26.3 runtime on the Mac) with screenshots, driving the
  real app against fixture servers. These run while the owner is away.
- Phone: WebDriverAgent (`phone.py`) and `devicectl` file copies of each app's debug-state
  dump, only while the owner is present. Uninstall the WebDriverAgent runner afterwards.

## What the apps are for (the owner, 2026-10-11)

The theme of every app: instant, offline where possible, and kill-robust (as the PC
pipelines are): a power-off, a kill or iOS ending the app in the background loses nothing.
Every change of state (position, progress, navigation, downloads, settings) is written
durably and atomically when it happens, not only when the app leaves the screen, and a
relaunch returns to exactly where the app was. Much of the current behaviour
was shaped by what a userscript in Safari could do; natively, fix it to serve the intent:

- **Manga (six apps)**: a new chapter downloads as soon as it appears. Only the current and
  the next chapter download (no longer the previous one). What is on screen comes first,
  for images and for chapters: tapping a cover to resume should open the chapter as fast as
  possible, instantly when it is already saved.
- **Gallery Reader**: the phone end of the download pipeline: images and thumbnails saved
  on the phone so everything is offline and instant.
- **Hitomi, Imhen**: browsing, searching and favoriting, built for fast navigation (saved
  searches, cached results, quick paging). New: every search is cached on the phone; a
  search shows the cached results at once, searches again in the background and merges the
  new results without moving what is on screen. This is app code shared by both providers,
  not provider code.
- **Videos**: the owner will describe later; until then their behaviour stays.

## Decisions

Taken by the agent (recorded so they are not reopened):
- Pagination: the gallery apps' page numbers existed to keep WebKit's documents small. Natively
  the lists are continuous (virtualized rows, nothing to page through), positions are
  anchors, and long lists jump with the system's draggable scroll indicator. Reported to the
  owner for a veto.
- Swipe forward is kept: WebKit gave it to every app, and the owner's flows use it.
- The manga docs' rule "do not copy these into Swift or a second app UI" and the
  gallery-reader rule "no reconstructed navigation stack" are superseded by this rewrite.

Open for the owner (the default applies until answered):
- Pinch zoom on list screens (gallery strips, card grids, video lists). WebKit allowed
  zooming every page. Default: readers and videos zoom; lists do not.
