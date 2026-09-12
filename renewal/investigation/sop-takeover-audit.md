# SOC takeover audit — 2026-09-11

All four extensions changed userscript takeover during the September 8 migration.
This audit inspected the current entry points, Vite transforms, build scripts,
manifest generators and local/staged built bundles. No evidence establishes
intentional concealment; the source and existing documentation recorded the changes.

| Extension | Migration change | Introducing commit | Current restoration |
| --- | --- | --- | --- |
| Gallery Reader | Defaults to `guarded-replace`; Vite substitutes DOM replacement for open/close | `987ff22` | Default changed locally to `guarded-stop`; controlled experimental modes remain explicit |
| Manga Reader | Vite unconditionally replaces open/close in extension builds | `05777c1` | Transform removed locally |
| KM Explorer | Same open/close substitution | `054376a` | Transform removed locally |
| Stream Viewer | Originally same substitution, later switches takeover default from rewrite to replace | `35435cb`, adjusted in `7065094` | Transform removed locally; shared rewrite default retained |

Before these edits, all four local and staged bundles used DOM-only replacement.
Source/staged content hashes matched in this audit. This does not establish the
currently installed phone bytes: Manga staging differs from its installed baseline.

The recorded reason was synchronous document-start reinjection during Safari
`document.close()`, causing recursive initialization. Gallery documentation also
records that a Window-lifetime guard fixed recursion. All four entry points already
set their own non-configurable Window boot guard before takeover. DOM replacement
was the default used in later warm-start/back-swipe checks; no evidence was found
that SOC with a working guard could not be retained. A loading readyState and an
unwanted script in a no-stop experiment were recorded; neither proves DOM-only
replacement is an adequate equivalent. The next acceptance check is guarded SOC
on real iPhone Safari, with reentry tracked and original listeners audited.

The host `scripts/suite.mjs` copies and hashes declared bundle files. No source
rewriting was found in the host staging path. Worker self-revoke stripping occurs
in Gallery/Manga/KM userscript and extension builders; it is shared behavior, not
an extension-only move of work onto the UI thread. All four static scripts use
MAIN world, document_start and top frame only.

Other material extension differences found, preserved pending their own evidence:

- Gallery: response-header CSP rules on owned documents, bundled-worker allowance,
  plus explicit opt-in takeover/performance experiments. Current code no longer
  reloads Hitomi site JavaScript. These do not make DOM replacement equal to SOC.
- Stream: extension background cookie persistence for XVideos, cookies/webRequest
  permissions, native-login/OAuth exemptions and shared authentication flow.
  These are explicit features from its provider addition, not SOC cleanup.
- Every extension has its own route gate and duplicate-start guard. Workers and
  storage stay in shared source; no additional build transform moving computation
  onto the main thread was found in the reviewed files.

Manga trace confirms the consequence: after takeover, Asura VisualViewport and
Window scroll handlers continue executing. One Asura viewport handler caused a
12.386ms JS microtask during the first gesture. Zero remaining script elements
was insufficient validation. See manga-reader/investigation/iphone-extension-debugging.md
for timings, private trace locations and the corrected build-path finding.

Status update: the user requires pure unguarded SOC before alternatives. A separate
Manga-only HEAD baseline build importing its userscript entry directly, with the
Vite SOC substitution removed and no startup guard/probe, was built, signed and
installed. Other three installed bundles are unchanged. The restored defaults
in their source repos are still local. Native startup recording is in progress;
see Manga runbook. Existing signing renewal remains paused.
User-owned README/readme.md and test.txt were not edited.
