#!/usr/bin/env python3
"""Register the apps that each repo's scripts/renewal.py lists; this repo knows no app layouts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from refresh import save

FIELDS = ['name', 'root', 'app', 'bundleIds', 'inputs', 'build', 'environment']
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', type=Path, default=root / 'renewal.local.json',
                    help='Mac-only signing team, phone and mirrors; start from renewal.example.json')
args = parser.parse_args()
if not args.config.exists():
    raise SystemExit('Missing ' + str(args.config) + ': copy renewal.example.json and fill in this Mac\'s values')
settings = json.loads(args.config.read_text())
team, device = settings['team'], settings['device']
apps = []
for source in settings['sources']:
    source = Path(source).expanduser().resolve()
    listed = json.loads(subprocess.run([sys.executable, str(source / 'scripts/renewal.py'), '--team', team, '--device', device],
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
    app.update(team=team, device=device, interval='monthly',
               profileCache=str(Path.home() / 'Library/Developer/Xcode/UserData/Provisioning Profiles'),
               stateDir=str(root / 'build/installed-refresh' / app['name']))
    path = root / 'build/installed-refresh/config' / (app['name'] + '.json')
    save(path, app)
    entries.append(dict(config=str(path), runner=str(root / 'scripts/refresh.py')))
output = root / 'refresh-apps.local.json'
save(output, dict(device=device, logDir=str(root / 'build/installed-refresh'), apps=entries))
output.chmod(0o600)
print(output)
