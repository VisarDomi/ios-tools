#!/usr/bin/env python3
"""Register existing builders; manga app identities come from its provider registry."""
import argparse
import json
from pathlib import Path
from refresh import save

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--manga-root', required=True, type=Path)
parser.add_argument('--gallery-root', required=True, type=Path)
parser.add_argument('--gallery-reader-root', type=Path, help='Optional shared Hitomi/Imhen native app root')
parser.add_argument('--ytb-root', type=Path, help='Optional single-source Ytb native app root')
parser.add_argument('--team', required=True, help='Team already used for the native readers')
parser.add_argument('--device', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
manga = args.manga_root.resolve()
registry = json.loads((manga / 'build/providers.json').read_text())
host = 'com.visar.readerextensions.paid'
apps = [dict(name='reader-extensions', root=str(root), app='build/Debug-iphoneos/Reader Extensions.app',
             bundleIds=[host + suffix for suffix in ['', '.Extension', '.KMExplorer', '.MangaReader', '.StreamViewer']],
             inputs=['apple', 'dist/gallery-reader-extension', 'dist/km-explorer-extension',
                     'dist/manga-reader-extension', 'dist/stream-viewer-extension', 'scripts/build-on-mac.sh'],
             build=['/bin/bash', 'scripts/build-on-mac.sh'],
             environment={'SIGNING_TEAM': args.team, 'READER_HOST_BUNDLE_ID': host})]
for key, provider in registry.items():
    apps.append(dict(name=key, root=str(manga),
                     app='build/' + key + '.paid/Release-iphoneos/' + provider['productName'] + '.app',
                     bundleIds=[provider['bundleIdentifier'] + '.paid'],
                     inputs=['AsuraReader', 'AsuraReader.xcodeproj', 'Resources', 'build/providers.json',
                             'Package.swift', 'Package.resolved', 'scripts/build-guest.py'],
                     build=['/usr/bin/python3', 'scripts/build-guest.py', key],
                     environment={'DEVELOPMENT_TEAM': args.team, 'DEVELOPMENT_DEVICE': args.device,
                                  'READER_BUNDLE_SUFFIX': '.paid'}))
gallery = args.gallery_root.resolve()
apps.append(dict(name='gallery', root=str(gallery),
                 app='apps/ios/build/Debug-iphoneos/GalleryReader.app',
                 bundleIds=['com.visar.GalleryReader.paid'],
                 inputs=['apps/ios/GalleryReader', 'apps/ios/GalleryReader.xcodeproj',
                         'apps/ios/Resources', 'apps/ios/scripts/build.sh', 'apps/ios/scripts/prepare-web.sh',
                         'gallery-server/downloader/public/offline'],
                 build=['/bin/bash', 'apps/ios/scripts/build.sh'],
                 environment={'DEVELOPMENT_TEAM': args.team, 'GALLERY_BUNDLE_ID': 'com.visar.GalleryReader.paid', 'SIGNING_DEVICE': args.device}))
if args.gallery_reader_root:
    online = args.gallery_reader_root.resolve()
    for provider, product in json.loads((online / 'providers.json').read_text()).items():
        apps.append(dict(name=provider, root=str(online),
                         app='build/' + provider + '/native/Release-iphoneos/' + product['name'] + '.app',
                         bundleIds=[product['bundleId']],
                         inputs=['GalleryReader', 'GalleryReader.xcodeproj', 'Resources/Info.plist',
                                 'Resources/LocalCA.cer', 'providers.json', 'build/' + provider + '/Web',
                                 'build/' + provider + '/provider.xcconfig', 'scripts/build.sh', 'scripts/build-provider.py'],
                         build=['/bin/bash', 'scripts/build.sh', provider],
                         environment={'DEVELOPMENT_TEAM':args.team,'SIGNING_DEVICE':args.device}))
if args.ytb_root:
    ytb = args.ytb_root.resolve()
    apps.append(dict(name='ytb', root=str(ytb), app='build/native/Release-iphoneos/Ytb.app',
                     bundleIds=['com.visar.Ytb.paid'],
                     inputs=['Ytb', 'Ytb.xcodeproj', 'Resources/Info.plist', 'Resources/LocalCA.cer',
                             'build/Web', 'scripts/build.sh', 'scripts/build-native.py'],
                     build=['/bin/bash', 'scripts/build.sh'],
                     environment={'DEVELOPMENT_TEAM':args.team, 'SIGNING_DEVICE':args.device}))
entries = []
for app in apps:
    app.update(team=args.team, device=args.device, interval='monthly',
               profileCache=str(Path.home() / 'Library/Developer/Xcode/UserData/Provisioning Profiles'),
               stateDir=str(root / 'build/installed-refresh' / app['name']))
    path = root / 'build/installed-refresh/config' / (app['name'] + '.json')
    save(path, app)
    entries.append(dict(config=str(path), runner=str(root / 'scripts/refresh.py')))
output = root / 'refresh-apps.local.json'
save(output, dict(device=args.device, logDir=str(root / 'build/installed-refresh'), apps=entries))
output.chmod(0o600)
print(output)
