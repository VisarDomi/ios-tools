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
start from `ios-tools.example.json`. Mac and phone access:
[mac-access.md](../../environment/mac-access.md).

```sh
npm test   # renewal tests
```
