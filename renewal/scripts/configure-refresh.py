#!/usr/bin/env python3
"""Register one repository's apps (from its scripts/renewal.py) for that repository's own scheduler."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from refresh import save

FIELDS = ['name', 'root', 'app', 'bundleIds', 'inputs', 'build', 'environment']
STORE = Path.home() / 'Library/Application Support/ios-tools/renewal'
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help="The repository's Mac mirror directory containing scripts/renewal.py")
parser.add_argument('--config', type=Path, default=root.parent / 'ios-tools.local.json',
                    help='Mac-only signing team and phone; start from ios-tools.example.json')
args = parser.parse_args()
if not args.config.exists():
    raise SystemExit('Missing ' + str(args.config) + ': copy ios-tools.example.json and fill in this Mac\'s values')
settings = json.loads(args.config.read_text())
team, device = settings['team'], settings['device']
listing = json.loads(subprocess.run([sys.executable, str(args.source.expanduser().resolve() / 'scripts/renewal.py'),
                                     '--team', team, '--device', device],
                                    check=True, capture_output=True, text=True).stdout)
repo = listing.get('repo', '')
if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', repo):
    raise SystemExit(str(args.source) + ' must name its repository (lowercase letters, digits, dashes)')
apps = []
for app in listing['apps']:
    if sorted(app) != sorted(FIELDS):
        raise SystemExit(str(args.source) + ' lists an app without exactly these fields: ' + ', '.join(FIELDS))
    apps.append({field: app[field] for field in FIELDS})
names = [app['name'] for app in apps]
if len(set(names)) != len(names):
    raise SystemExit('Duplicate app names: ' + ', '.join(sorted({name for name in names if names.count(name) > 1})))
# Another repository's scheduler must never renew the same app.
mine = {bundle for app in apps for bundle in app['bundleIds']}
for index in STORE.glob('*/apps.json'):
    if index.parent.name == repo:
        continue
    for item in json.loads(index.read_text())['apps']:
        taken = mine & set(json.loads(Path(item['config']).read_text())['bundleIds'])
        if taken:
            raise SystemExit(index.parent.name + ' already renews ' + ', '.join(sorted(taken)))

store = STORE / repo
entries = []
for app in apps:
    app.update(team=team, device=device, interval='monthly',
               profileCache=str(Path.home() / 'Library/Developer/Xcode/UserData/Provisioning Profiles'),
               stateDir=str(store / app['name']))
    path = store / 'config' / (app['name'] + '.json')
    save(path, app)
    entries.append(dict(config=str(path), runner=str(root / 'scripts/refresh.py')))
for stale in (store / 'config').glob('*.json'):
    if stale.stem not in names:
        stale.unlink()
output = store / 'apps.json'
save(output, dict(repo=repo, device=device, logDir=str(store), apps=entries))
output.chmod(0o600)
print(output)
