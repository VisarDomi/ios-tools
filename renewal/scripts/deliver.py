#!/usr/bin/env python3
"""Approve a deliberate deployment as its app's renewal baseline.

A repository's deploy runs `begin` before its build, `built` after a successful build and
`installed` after a successful install. The installed app is approved, keeping its renewal
schedule, only if its inputs did not change during the build or before the install and the
built app was not replaced. Otherwise nothing is approved and the reason is printed.
"""
import argparse
import fcntl
import json
from pathlib import Path
import re
import sys
import time

import refresh

STORE = Path.home() / 'Library/Application Support/ios-tools/renewal'
LOCK_TIMEOUT = 1800


def skip(record, reason):
    if record.exists():
        record.unlink()
    print('Renewal approval skipped: ' + reason, flush=True)


def wait_for_lock(lock):
    # A renewal or another deploy may be signing; approval must not interleave with it.
    deadline = time.monotonic() + LOCK_TIMEOUT
    waiting = False
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() > deadline:
                raise RuntimeError('Another app is still signing; rerun this step to approve')
            if not waiting:
                print('Waiting for another app to finish signing before approval…', flush=True)
                waiting = True
            time.sleep(10)


def deliver(config, step, bundle):
    if bundle != config['bundleIds'][0]:
        # Another identity (e.g. an unsuffixed build) is not the app this registration renews.
        print('Renewal approval skipped: ' + bundle + ' is not the renewed app ' + config['bundleIds'][0], flush=True)
        return
    root = Path(config['root']).resolve()
    state_dir = root / config.get('stateDir', 'build/refresh')
    record = state_dir / 'delivery.json'
    app = root / config['app']
    inputs = refresh.fingerprint(root, config['inputs'])
    if step == 'begin':
        refresh.save(record, {'inputHash': inputs})
        return
    delivered = json.loads(record.read_text()) if record.exists() else {}
    if not delivered:
        return skip(record, 'this deploy recorded no build')
    if step == 'built':
        if delivered.get('inputHash') != inputs:
            return skip(record, 'build inputs changed during the build')
        refresh.save(record, {'inputHash': inputs, 'appHash': refresh.fingerprint(app.parent, [app.name])})
        return
    if 'appHash' not in delivered:
        return skip(record, 'the recorded build did not finish')
    lock_path = Path.home() / 'Library/Caches/ios-app-refresh/signing.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with lock_path.open('a') as lock:
        wait_for_lock(lock)
        # Checked under the lock: a renewal may have rebuilt the app while this step waited.
        if refresh.fingerprint(root, config['inputs']) != delivered['inputHash']:
            return skip(record, 'build inputs changed after the build')
        if refresh.fingerprint(app.parent, [app.name]) != delivered['appHash']:
            return skip(record, 'the app was rebuilt after this deploy built it')
        state_path = state_dir / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        expected = [config['team'] + '.' + identity for identity in config['bundleIds']]
        kept = refresh.approve(config, state_path, state, app, expected, delivered['inputHash'], keep_schedule=True)
        record.unlink()
    approved = json.loads(state_path.read_text())
    print('Approved ' + config['bundleIds'][0] + ' as its renewal baseline; '
          + ('next renewal ' + time.strftime('%Y-%m-%d', time.gmtime(approved['nextDue'])) if kept
             else 'its renewal is due at the next scheduler check'), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=['begin', 'built', 'installed'])
    parser.add_argument('--repo', required=True)
    parser.add_argument('--app', required=True, help="The app's renewal name in the repository's renewal.py")
    parser.add_argument('--bundle', required=True, help='The bundle ID this deploy builds and installs')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*', args.repo) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', args.app):
        parser.error('Invalid repository or app name')
    path = STORE / args.repo / 'config' / (args.app + '.json')
    if not path.exists():
        print('Renewal approval skipped: ' + args.repo + '/' + args.app + ' is not registered for renewal', flush=True)
        sys.exit(0)
    try:
        deliver(json.loads(path.read_text()), args.step, args.bundle)
    except Exception as error:
        print('RENEWAL APPROVAL FAILED: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
