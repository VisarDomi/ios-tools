# ios-tools

Shared iOS tooling for the app repositories, used from this PC and the Mac
(`~/Developer/ios-tools`):

- [native](native/README.md): start here for any iPhone app. NativeKit (the Swift package
  every native app vendors), the rules all apps follow (exact relaunch, the main thread only
  shows), measuring on the phone (`native/scripts/frames`), the simulator and deploying.
- [renewal](renewal/README.md): monthly renewal of the paid-signed iPhone apps. Each app
  repository lists its apps in `apps/ios/scripts/renewal.py` and has its own scheduler;
  this folder holds the shared runner.
- [inspector](inspector/README.md): attach to a WebKit app's page on the phone (Maid Heroes).

Mac-only settings (signing team and phone UDID) live in `ios-tools.local.json`;
start from `ios-tools.example.json`. [`mac-sync`](mac-sync) mirrors this repository to the
Mac, leaving that file and generated files alone; the PC's `ios-tools-mac-sync.timer`
runs it every 5 minutes, and running it by hand syncs at once. Nothing is copied by hand. Mac and phone access:
[mac-access.md](../../environment/mac-access.md).

On a fresh Mac the mirror alone does not install the phone monitor. Restore
`ios-tools.local.json` (the actual team/device settings are backed up in the environment
repository's `mac-renewal/config/`), then run `native/scripts/phone-pairing --install` in
the logged-in GUI session. Its generator recreates `com.visar.phone-pairing.plist` and
the 30-second schedule. Confirm a real `devicectl device info processes` request succeeds.
The pairing state file is a disposable cache and need not be restored. Exact commands
and the source/configuration backup map are in
[Mac recovery](../../environment/mac-renewal/RECOVERY.md#restore-wireless-phone-recovery-and-network-access).

```sh
npm test   # renewal and phone-recovery tests
```
