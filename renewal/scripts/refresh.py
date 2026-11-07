"""Daily Xcode renewal in a logged-in Mac user session.

Self-contained stdlib runner, also carried by gallery-downloader/apps/ios/scripts.
No source fetch, JavaScript rebuild, certificate revocation or app uninstall.
"""
import argparse
import calendar
import fnmatch
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(value, output, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(parent)
        finally: os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def fingerprint(root, inputs):
    digest = hashlib.sha256()
    for item in sorted(inputs):
        base = root / item
        if not base.exists():
            raise RuntimeError('Missing approved input: ' + item)
        files = sorted(base.rglob('*')) if base.is_dir() else [base]
        for path in files:
            if not path.is_file() or 'xcuserdata' in path.parts or path.name == '.DS_Store':
                continue
            digest.update(str(path.relative_to(root)).encode() + b'\0')
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def prune_completed_caches(config):
    """Caller holds signing.lock. Remove only reproducible mutable build caches.

    Approved/pending checkpoints, input trees, signed app bundles and profile/state
    storage stay intact. Queue checkpoint cleanup belongs to the queue itself.
    """
    root = Path(config['root']).resolve()
    checkpoints = Path.home() / 'Developer/ios-push/checkpoints'
    if root.is_relative_to(checkpoints): return []
    build = root / 'build'
    if not build.is_dir() or build.resolve() != build: return []
    configs = [config]
    registry = Path.home() / 'Library/Application Support/ios-tools/renewal'
    for registration in registry.glob('*/config/*.json'):
        other = json.loads(registration.read_text())
        if Path(other['root']).resolve() == root: configs.append(other)
    protected = []
    for other in configs:
        state_path = root / other.get('stateDir', 'build/refresh') / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get('pendingPush'): return []
        protected.extend((root / item).resolve() for item in [*other['inputs'], other['app']])
        protected.append(state_path.parent.resolve())
        if other.get('profileCache'): protected.append(Path(other['profileCache']).expanduser().resolve())
    candidates = set(build.rglob('DerivedData'))
    # Older Xcode recipes put intermediates directly beside SYMROOT products,
    # rather than inside DerivedData. Their per-provider module copies were
    # retained after every renewal even though the signed app was complete.
    cache_names = {'SwiftExplicitPrecompiledModules', 'ExplicitPrecompiledModules',
                   'XCBuildData', 'EagerLinkingTBDs', 'GeneratedModuleMaps-iphoneos'}
    levels = [build, *(p for p in build.iterdir() if p.is_dir() and not p.is_symlink() and p.suffix != '.app')]
    for folder in levels:
        candidates.update(p for p in folder.iterdir()
                          if p.is_dir() and (p.name in cache_names or p.name.endswith('.build')))
    removed = []
    for path in sorted(candidates, key=lambda p: (len(p.parts), str(p))):
        if not path.is_dir() or path.is_symlink() or path.resolve() != path: continue
        if any(item.is_relative_to(path) or path.is_relative_to(item) for item in protected): continue
        shutil.rmtree(path)
        removed.append(str(path))
    return removed


def preflight_deferral(log):
    """A guard refusal before its 'Guarded build' start marker is no Swift failure."""
    return preflight_deferral_text(log.read_text(errors='replace'))


def preflight_deferral_text(text):
    if 'Guarded build;' in text: return None
    lines = [line for line in text.splitlines() if line.startswith('MAC WORKLOAD STOPPED: ')]
    return lines[-1].removeprefix('MAC WORKLOAD STOPPED: ') if lines else None


def profile(path):
    raw = subprocess.check_output(['/usr/bin/security', 'cms', '-D', '-i', str(path)], stderr=subprocess.PIPE)
    data = plistlib.loads(raw)
    return {
        'id': data['Entitlements']['application-identifier'],
        'uuid': data['UUID'],
        'created': data.get('CreationDate', dt.datetime(1970, 1, 1)).replace(tzinfo=dt.timezone.utc).timestamp(),
        'expires': data['ExpirationDate'].replace(tzinfo=dt.timezone.utc).timestamp(),
    }


def bundle_entries(app):
    return [app, *sorted({path.parent for path in app.rglob('embedded.mobileprovision') if path.parent != app})]


def delivery_targets(config, app):
    targets = [{'device': config['device'], 'app': app, 'bundle': config['bundleIds'][0], 'platform': 'iPhoneOS'}]
    watch = config.get('watch')
    if watch:
        path = Path(watch['app'])
        if (path.is_absolute() or '..' in path.parts or len(path.parts) != 2 or path.parts[0] != 'Watch'
                or path.suffix != '.app' or not isinstance(watch.get('device'), str) or not watch['device'] or watch['device'] == config['device']
                or watch.get('bundleId') not in config['bundleIds'][1:]):
            raise RuntimeError('Invalid paired Watch delivery target')
        targets.append({'device': watch['device'], 'app': app / path, 'bundle': watch['bundleId'], 'platform': 'WatchOS'})
    return targets


def app_profiles(app, expected):
    paths = [entry / 'embedded.mobileprovision' for entry in bundle_entries(app)]
    result = {}
    for path in paths:
        bundle = plistlib.loads((path.parent / 'Info.plist').read_bytes())['CFBundleIdentifier']
        matches = [identity for identity in expected if identity.endswith('.' + bundle)]
        item = profile(path)
        if len(matches) != 1 or not fnmatch.fnmatchcase(matches[0], item['id']) or matches[0] in result:
            raise RuntimeError('App/profile identities differ from the approved configuration')
        result[matches[0]] = item
    if set(result) != set(expected):
        raise RuntimeError('App/profile identities differ from the approved configuration')
    return result


def next_due(config, last_success):
    if config.get('interval') != 'monthly':
        return last_success + 86400
    value = dt.datetime.fromtimestamp(last_success, dt.timezone.utc)
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return value.replace(year=year, month=month,
                         day=min(value.day, calendar.monthrange(year, month)[1])).timestamp()


def approve(config, state_path, state, app, expected, input_hash, keep_schedule=False, initial_install=False):
    """Make the delivered app the renewal baseline. Keeping the schedule leaves the next renewal
    one interval after the last success, unless a delivered profile expires before the renewed one."""
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    profiles = app_profiles(app, expected)
    renewed = state.get('installedProfiles') or {}
    keep = (keep_schedule and bool(state.get('lastSuccess')) and set(renewed) == set(profiles)
            and all(profiles[key]['expires'] >= renewed[key]['expires'] for key in profiles))
    approved = {'inputHash': input_hash, 'installedProfiles': profiles, 'lastSuccess': state['lastSuccess'] if keep else 0}
    # Only a caller that verified the first signed installation on every target
    # may establish this initial clock. An ordinary approval still claims no
    # successful installation/renewal and remains due, as before.
    if initial_install and not state.get('lastSuccess'):
        approved['lastSuccess'] = time.time()
        approved['nextDue'] = next_due(config, approved['lastSuccess'])
    if keep:
        approved['nextDue'] = next_due(config, state['lastSuccess'])
    save(state_path, approved)
    return keep


def advanced(before, after, now):
    return bool(before) and set(before) == set(after) and all(
        after[key]['expires'] > before[key]['expires'] and after[key]['expires'] > now + 6 * 86400
        for key in before
    )


def device_json(config, arguments):
    timeout = 180 if arguments[0] == 'install' else 45
    with tempfile.TemporaryDirectory(prefix='reader-device-') as directory:
        output = Path(directory) / 'result.json'
        subprocess.run([str(Path(__file__).resolve().parents[2]/'native/scripts/apple-tool'), 'devicectl', '--timeout', str(timeout), '--json-output', str(output),
                        'device', *arguments, '--device', config['device']],
                       check=True, timeout=timeout + 15, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        return json.loads(output.read_text())['result']


def companion_apps(config, target, output, install=False):
    """Caller holds signing.lock; use saved trust without mounting a native DDI.

    Installation always sends the actual signed bytes before checking inventory.
    A matching version alone cannot prove a same-version profile renewal.
    """
    tools = Path(__file__).resolve().parents[2]
    python = tools / 'inspector/.venv/bin/python'
    helper = tools / 'native/scripts/watch-apps'
    if not python.exists() or not helper.exists(): return None
    output.unlink(missing_ok=True)
    command = [str(python), str(helper), '--phone', config['device'], '--watch', target['device'],
               '--bundle', target['bundle'], '--json-output', str(output)]
    if install: command += ['--install', str(target['app']), '--team', config['team']]
    try:
        with output.with_suffix('.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=190 if install else 80)
        if result.returncode or not output.exists(): return None
        report = json.loads(output.read_text())
        if (report.get('device') != target['device'] or report.get('transport') != 'companion-lockdown'
                or bool(report.get('installed')) != install or not isinstance(report.get('apps'), list)):
            return None
        return report['apps']
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def restore_cache(stash, cache):
    # A power cut leaves the stash intact. The next run restores it first.
    if not stash.exists():
        return
    for backup in stash.glob('*.mobileprovision'):
        destination = cache / backup.name
        if destination.exists():
            if destination.read_bytes() != backup.read_bytes():
                raise RuntimeError('Profile cache changed; keep backup for manual inspection')
            backup.unlink()
        else:
            os.replace(backup, destination)


def run(config, action, force=False, wireless=False, keep_schedule=False, config_path=None):
    root = Path(config['root']).resolve()
    state_dir = root / config.get('stateDir', 'build/refresh')
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = state_dir / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    app = root / config['app']
    expected = [config['team'] + '.' + identity for identity in config['bundleIds']]
    if action == 'status':
        print(json.dumps(state, indent=2))
        return
    if config_path is not None and json.loads(Path(config_path).read_text()) != config:
        print('App registration changed; retry with its current checkpoint.')
        return
    if action == 'refresh' and state.get('pendingPush'):
        print('A queued push is finalizing this app; renewal will retry after delivery.')
        return
    current_hash = fingerprint(root, config['inputs'])
    if action == 'approve':
        kept = approve(config, state_path, state, app, expected, current_hash, keep_schedule)
        print('Approved current delivered inputs and app IDs. '
              + ('Renewal schedule kept.' if kept else 'No renewal claimed; renewal is due now.'))
        return
    if state.get('inputHash') != current_hash:
        raise RuntimeError('Inputs changed or not approved. Install/review deliberately, then run approve.')
    if not force and state.get('lastSuccess') and time.time() < next_due(config, state['lastSuccess']):
        print('Refresh is current; no build or install needed.')
        return
    lock_dir = Path.home() / 'Library/Caches/ios-app-refresh'
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (lock_dir / 'signing.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another app is signing; retry on the next check.')
            return
        # A push may atomically move this app to a new frozen source checkpoint
        # while this process was reading its configuration before taking the lock.
        if config_path is not None and json.loads(Path(config_path).read_text()) != config:
            print('App registration changed; retry with the new checkpoint on the next check.')
            return
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        if state.get('pendingPush'):
            print('A queued push is finalizing this app; renewal will retry after delivery.')
            return
        if state.get('inputHash') != fingerprint(root, config['inputs']):
            raise RuntimeError('Approved inputs changed before signing')
        cache = Path(config['profileCache'])
        stash = state_dir / 'profile-cache-backup'
        stash.mkdir(exist_ok=True)
        restore_cache(stash, cache)
        if subprocess.run(['/usr/bin/pgrep', '-x', 'xcodebuild'], stdout=subprocess.DEVNULL).returncode == 0:
            print('An Xcode build is already running; retry on the next check.')
            return
        info = device_json(config, ['info', 'details'])
        transport = info['connectionProperties']['transportType']
        if wireless and transport != 'localNetwork':
            raise RuntimeError('Wireless test requires USB disconnected; transport=' + transport)
        print('Connection: ' + transport, flush=True)
        lock_state = device_json(config, ['info', 'lockState'])
        if lock_state.get('passcodeRequired') is not False or lock_state.get('unlockedSinceBoot') is not True:
            print('Phone locked; no build. Daily renewal remains due for the next check.', flush=True)
            return
        targets = delivery_targets(config, app)
        for target in targets[1:]:
            # An unavailable Watch must not provoke a paid-profile rebuild.
            try:
                catalog = device_json(dict(config, device=target['device']), ['info', 'apps'])
            except (RuntimeError, subprocess.SubprocessError):
                actual = companion_apps(config, target, state_dir / 'watch-companion-before.json')
                if actual is None: raise
                catalog = {'apps': actual}
            if not isinstance(catalog.get('apps'), list): raise RuntimeError('Watch app service is unavailable; no renewal build started')
        before = state['installedProfiles']
        try:
            # Renew profiles once, then reuse a profile already renewed by this batch.
            # This avoids Xcode replacing a shared wildcard separately for each target.
            cached_profiles = [(path, profile(path)) for path in cache.glob('*.mobileprovision')]
            reusable = set()
            if config.get('interval') == 'monthly':
                for identity in expected:
                    fresh = [path for path, item in cached_profiles
                             if fnmatch.fnmatchcase(identity, item['id'])
                             and item['expires'] > before[identity]['expires']
                             and item.get('created', 0) > state.get('lastSuccess', 0)]
                    if not fresh:
                        reusable.clear()
                        break
                    reusable.update(fresh)
            for cached, item in cached_profiles:
                if cached not in reusable and any(fnmatch.fnmatchcase(identity, item['id']) for identity in expected):
                    os.replace(cached, stash / cached.name)
            environment = {**os.environ, **config.get('environment', {}), 'IOS_REFRESH_LOCK_FD': str(lock.fileno())}
            command = config['build']
            guard = Path(__file__).resolve().parents[2] / 'native/scripts/mac-workload'
            if sys.platform == 'darwin':
                if not guard.exists():
                    raise RuntimeError('Shared Mac workload guard is missing; sync ios-tools before renewal')
                checkpoints = Path.home() / 'Developer/ios-push/checkpoints'
                if config_path is not None and root.name == 'source' and root.parent.parent == checkpoints:
                    command = [sys.executable, str(guard.parents[2] / 'push/worker.py'),
                               'renewal-build', '--config', str(config_path)]
                command = [sys.executable, str(guard), 'build', '--timeout', '900', '--', *command]
            with (state_dir / 'build.log').open('w') as log:
                result = subprocess.run(command, cwd=root, env=environment,
                                        stdout=log, stderr=subprocess.STDOUT, timeout=900, pass_fds=(lock.fileno(),))
            if result.returncode:
                log_path = state_dir / 'build.log'
                deferred = preflight_deferral(log_path) if sys.platform == 'darwin' else None
                if deferred:
                    restore_cache(stash, cache)
                    state.update(lastError=None, lastDeferred=deferred, lastDeferredAt=time.time(), lastAttempt=time.time())
                    save(state_path, state)
                    print('Refresh deferred by Mac workload preflight: ' + deferred + '; still due on the next check.', flush=True)
                    return
                raise RuntimeError('Xcode build failed; see ' + str(log_path))
            if fingerprint(root, config['inputs']) != current_hash:
                raise RuntimeError('Build inputs changed during renewal; refusing installation')
            after = app_profiles(app, expected)
            if config.get('interval') == 'monthly':
                if (not advanced(before, after, time.time())
                        or any(item['expires'] < time.time() + 45 * 86400 for item in after.values())):
                    raise RuntimeError('Paid profiles did not receive later deadlines; no renewal claimed')
            elif not advanced(before, after, time.time()):
                raise RuntimeError('Profiles did not ALL receive later seven-day deadlines; no renewal claimed')
            subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
            for target in targets:
                target_config = dict(config, device=target['device'])
                companion = None
                try:
                    device_json(target_config, ['install', 'app', str(target['app'])])
                except (RuntimeError, subprocess.SubprocessError):
                    if target['platform'] != 'WatchOS': raise
                    companion = companion_apps(config, target, state_dir / 'watch-companion-install.json', install=True)
                    if companion is None: raise
                if config.get('watch'):
                    try:
                        actual = companion if companion is not None else device_json(target_config, ['info', 'apps']).get('apps', [])
                    except (RuntimeError, subprocess.SubprocessError):
                        if target['platform'] != 'WatchOS': raise
                        actual = companion_apps(config, target, state_dir / 'watch-companion-after.json')
                        if actual is None: raise
                    expected_version = str(plistlib.loads((target['app'] / 'Info.plist').read_bytes())['CFBundleVersion'])
                    if not any(row.get('bundleIdentifier') == target['bundle'] and str(row.get('bundleVersion')) == expected_version for row in actual):
                        raise RuntimeError('Renewal installation version was not verified on every target device')
            completed = time.time()
            state.update(lastSuccess=completed, nextDue=next_due(config, completed), installedProfiles=after, transport=transport, lastError=None, lastDeferred=None)
            save(state_path, state)
            # Successful replacement: retain no unbounded archive of old profiles.
            for backup in stash.glob('*.mobileprovision'):
                backup.unlink()
            for identity in sorted(after):
                print(identity + ': ' + dt.datetime.fromtimestamp(before[identity]['expires'], dt.timezone.utc).isoformat()
                      + ' -> ' + dt.datetime.fromtimestamp(after[identity]['expires'], dt.timezone.utc).isoformat())
            print('Refresh installed successfully; existing app data retained.', flush=True)
            try:
                removed = prune_completed_caches(config)
                if removed: print('Removed completed compiler caches: ' + ', '.join(removed), flush=True)
            except (OSError, ValueError, KeyError) as error:
                print('Compiler cache cleanup deferred: ' + str(error), flush=True)
        except BaseException:
            restore_cache(stash, cache)
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['approve', 'refresh', 'status'])
    parser.add_argument('--config', required=True)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--wireless', action='store_true')
    parser.add_argument('--keep-schedule', action='store_true',
                        help='approve: keep the next renewal date unless a delivered profile expires earlier')
    parser.add_argument('--scheduled', action='store_true', help='Keep only the latest check log')
    args = parser.parse_args()
    settings = json.loads(Path(args.config).read_text())
    if args.scheduled:
        log_dir = Path(settings['root']) / settings.get('stateDir', 'build/refresh')
        log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Bound diagnostics: one check log and one overwritten Xcode build log.
        log_fd = os.open(log_dir / 'last-check.log', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        os.close(log_fd)
        print(dt.datetime.now(dt.timezone.utc).isoformat(), flush=True)
    try:
        run(settings, args.action, args.force, args.wireless, args.keep_schedule, config_path=args.config)
    except Exception as error:
        state_path = Path(settings['root']) / settings.get('stateDir', 'build/refresh') / 'state.json'
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state.update(lastError=str(error), lastAttempt=time.time())
        save(state_path, state)
        print('REFRESH FAILED: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
