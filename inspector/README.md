# inspector

`app-inspector.py` attaches to one installed app's WebKit page on the paired
iPhone (from the Mac) and prints a page snapshot, optional console output,
screenshot, cookie flags (never values) and evaluation results. Each app
repository keeps its own snapshot expression in
`apps/ios/scripts/inspector-snapshot.js`.

Set up the Mac's inspector Python once, in this folder (it is not committed).
`requirements.txt` pins the tested versions; the Mac's Python 3.9 needs the
prebuilt `cryptography` wheel:

```sh
/usr/bin/python3 -m venv ~/Developer/ios-tools/inspector/.venv
~/Developer/ios-tools/inspector/.venv/bin/pip install --prefer-binary \
  --only-binary=cryptography -r ~/Developer/ios-tools/inspector/requirements.txt
```

The phone's UDID comes from `ios-tools.local.json` at the repository root
(see `ios-tools.example.json`), or `--device`. Example:

```sh
~/Developer/ios-tools/inspector/.venv/bin/python ~/Developer/ios-tools/inspector/app-inspector.py \
  --bundle com.visar.Ytb.paid --url-prefix ytb://app/ \
  --snapshot-file ~/Developer/ytb/apps/ios/scripts/inspector-snapshot.js --console --after 1
```

USB (usbmux) is the default; `--rsd` uses the RemoteXPC tunnel.
