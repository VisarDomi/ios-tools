#!/usr/bin/env python3
"""Enumerate installed apps, then run their existing refresh builders when due."""
import argparse
import datetime as dt
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import os
import time

from refresh import device_json, next_due


def state_for(item):
    config = json.loads(Path(item['config']).read_text())
    path = Path(config['root']) / config.get('stateDir', 'build/refresh') / 'state.json'
    return config, json.loads(path.read_text()) if path.exists() else {}


def due(config, state, now):
    return not state.get('lastSuccess') or now >= next_due(config, state['lastSuccess'])


def refresh(config, force=False, wireless=False):
    inventory = device_json(config, ['info', 'apps'])['apps']
    installed = {app['bundleIdentifier']: app for app in inventory}
    known = set()
    errors = []
    for item in sorted(config['apps'], key=lambda item: len(state_for(item)[0]['bundleIds'])):
        app, state = state_for(item)
        bundle = app['bundleIds'][0]
        known.add(bundle)
        if bundle not in installed:
            continue
        # Actual signed artifact identifies the account; never infer it from an app name.
        profile_path = Path(app['root']) / app['app'] / 'embedded.mobileprovision'
        profile = plistlib.loads(subprocess.check_output(
            ['/usr/bin/security', 'cms', '-D', '-i', str(profile_path)], stderr=subprocess.PIPE))
        interval = 'daily' if profile.get('LocalProvision') else 'monthly'
        if profile.get('TeamIdentifier') != [app['team']] or interval != app.get('interval', 'daily'):
            errors.append(bundle + ': signing account changed; regenerate its build configuration')
            continue
        print(installed[bundle]['name'] + ': ' + interval + ' (' + app['team'] + ')', flush=True)
        if not force and not due(app, state, time.time()):
            continue
        command = ['/usr/bin/python3', item['runner'], 'refresh', '--config', item['config'], '--scheduled']
        if force: command.append('--force')
        if wireless: command.append('--wireless')
        result = subprocess.run(command)
        if result.returncode:
            errors.append(bundle + ': refresh failed; see its last-check.log')
    for bundle, app in installed.items():
        if app.get('builtByDeveloper') and bundle not in known:
            print('No registered builder for installed app: ' + bundle, flush=True)
    if errors:
        raise RuntimeError('; '.join(errors))
    print('Installed-app check complete.', flush=True)


def install(config, path):
    label = 'com.visar.installed-apps-refresh'
    domain = 'gui/' + str(os.getuid())
    if subprocess.run(['/bin/launchctl', 'print', domain + '/' + label],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Scheduler already loaded; wait until idle before replacing')
    logs = Path(config['logDir'])
    logs.mkdir(parents=True, exist_ok=True)
    target = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(dict(Label=label, RunAtLoad=True, StartInterval=600,
        LimitLoadToSessionType='Aqua', ProgramArguments=['/usr/bin/caffeinate', '-i', '/usr/bin/python3',
        str(Path(__file__).resolve()), 'refresh', '--config', str(path), '--scheduled'],
        StandardOutPath=str(logs / 'last-check.log'), StandardErrorPath=str(logs / 'last-check.log'))))
    target.chmod(0o600)
    subprocess.run(['/bin/launchctl', 'enable', domain + '/' + label], check=True)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(target)], check=True)
    print('Enabled: installed free apps daily; installed paid apps monthly.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['refresh', 'status', 'install'])
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--wireless', action='store_true')
    parser.add_argument('--scheduled', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if args.scheduled:
        logs = Path(config['logDir'])
        logs.mkdir(parents=True, exist_ok=True)
        fd = os.open(logs / 'last-check.log', os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        os.dup2(fd, 1); os.dup2(fd, 2); os.close(fd)
    print(dt.datetime.now(dt.timezone.utc).isoformat(), flush=True)
    try:
        if args.action == 'install': install(config, args.config.resolve())
        elif args.action == 'status':
            for item in config['apps']:
                app, state = state_for(item)
                print(app['bundleIds'][0], app.get('interval', 'daily'), json.dumps(state))
        else: refresh(config, args.force, args.wireless)
    except Exception as error:
        print('REFRESH FAILED: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
