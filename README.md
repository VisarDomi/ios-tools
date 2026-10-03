# ios-tools

Shared iOS tooling for the app repositories, used from the Mac
(`~/Developer/ios-tools`):

- [renewal](renewal/PAID-REFRESH.md): monthly renewal of the paid-signed iPhone
  apps. Each app repository lists its apps in `apps/ios/scripts/renewal.py` and has
  its own scheduler; this folder holds the shared runner.
- [inspector](inspector/README.md): attach to an installed app's WebKit page on
  the paired iPhone and print a snapshot, console output, screenshot or
  evaluation result. Each repository keeps its own page snapshot.

Mac-only settings (signing team and phone UDID) live in `ios-tools.local.json`;
start from `ios-tools.example.json`.

```sh
npm test   # renewal tests
```
