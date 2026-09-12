# Reader Extensions with the paid account

Shared Mac connection instructions: [mac-access.md](/home/visar/Documents/environment/mac-access.md).
Ethernet is now `192.168.1.198`; USB wireless remains DHCP.

Monthly renewal setup and current activation evidence: [PAID-REFRESH.md](PAID-REFRESH.md).

Verified September 12, 2026: installed and launched on the real iPhone using
Erdal's paid individual team. No further account-owner action was required.
Gallery and LC remain installed under their previous identities. The subsequent
six-provider batch is also installed natively; see the sibling Manga Reader
`apps/ios/PAID-NATIVE.md` for its exact names, identities and verification.

## Current configuration and repeat deployment

Ignored `deploy.local.json` selects:

- `signingTeam`: `65U58U86DD`
- `hostBundleId`: `com.visar.readerextensions.paid`
- `registerDevice`: `true`
- `device`: `00008101-000639912881401E`
- Existing trusted Mac `visar@192.168.1.198`, mirror
  `/Users/visar/Developer/reader-extensions`, GUI UID 501.

The project derives the host and all four extension identities from
`READER_HOST_BUNDLE_ID`. Default identity remains the personal-team host if the
setting is omitted. `registerDevice` selects a physical scheme destination;
without it, the generic target/SDK path can build for an already-enrolled phone.
Do not hardcode another identity into individual extension targets.

```sh
npm run mac -- sync
npm run mac -- build
npm run mac -- status
# Require no PID, LastExitStatus=0, and BUILD SUCCEEDED.
npm run mac -- check
npm run mac -- install
npm run mac -- finish
```

The build runs in the GUI session so Xcode can use the existing account and
Keychain. `check` and `install` verify every staged resource hash, the complete
signature, and every embedded profile's team, identity, expiry and phone UDID.
The phone must be paired and Developer Mode enabled. New Safari extension
identities require the user to enable extensions/site access in iOS Settings.
The app and extension UI/runtime bundles were not changed for paid signing.

## What unblocked registration

The first generic build signed successfully but its profile contained only the
account owner's phones. Installation failed with `0xe8008012`; that was a missing
device registration, not the free three-app cap. Adding `-destination` to the
old target-only invocation did not register this phone.

Physical scheme selection initially rejected the phone with `iOS 26.2 is not
installed`, despite the SDK compiling successfully. The user's Xcode toolbar
**Get** download installed the compatible **iOS 26.3.1 Universal Simulator**.
After verification, `xcodebuild -showdestinations` listed the phone as available.
This repaired the Mac's platform setup; a simulator is not inherently required
for paid-account app installation.

The subsequent physical scheme build with automatic provisioning registered the
phone using the existing Xcode login. An intermediate regenerated profile path
became stale during packaging; unloading that completed job and rebuilding fixed
it without deleting profiles or revoking certificates.

The installed host and four extensions all passed device/profile validation.
Their profile expiry is **2027-09-12 16:21:11 UTC**. `devicectl` confirmed install,
and launch succeeded for `com.visar.readerextensions.paid`. The user had removed
the personal-team Reader Extensions app. No agent-driven app deletion occurred.
This verifies this native app, not an eight-app installation or Safari gesture test.

## Cleanup and renewal state

No copy/build/inspection command remains active. Temporary Gallery data copies,
Gallery paid staging, Asura/Scythe paid builds and the APNs probe were removed.
The background/APNs source draft is retained and paused. A cancelled devicectl
copy had continued inside CoreDeviceService; stopping that service (with no
wanted device operation active) and checking stable file counts was required.
See `notes.md` for the evidence and cancellation caveat.

The old Gallery, Reader Extensions and LC renewal labels remain disabled from
the cancelled fresh-install setup. Do not enable the old Reader Extensions
personal-team renewal config against this paid source mirror. The new paid
identity has no scheduled renewal job yet; configure one deliberately if needed.
The user postponed broader fan/idle investigation until active setup work ends.
