#!/usr/bin/env python3
"""Register the apps that each repo's scripts/renewal.py lists; this repo knows no app layouts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from refresh import save

FIELDS = ['name', 'root', 'app', 'bundleIds', 'inputs', 'build', 'environment']
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('sources', nargs='+', type=Path, help='Mac mirror directories containing scripts/renewal.py')
parser.add_argument('--team', required=True, help='Team already used for the native apps')
parser.add_argument('--device', required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
apps = []
for source in args.sources:
    listed = json.loads(subprocess.run([sys.executable, str(source.resolve() / 'scripts/renewal.py'),
                                        '--team', args.team, '--device', args.device],
                                       check=True, capture_output=True, text=True).stdout)
    for app in listed:
        if sorted(app) != sorted(FIELDS):
            raise SystemExit(str(source) + ' lists an app without exactly these fields: ' + ', '.join(FIELDS))
        apps.append({field: app[field] for field in FIELDS})
names = [app['name'] for app in apps]
if len(set(names)) != len(names):
    raise SystemExit('Duplicate app names: ' + ', '.join(sorted({name for name in names if names.count(name) > 1})))

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
