#!/usr/bin/env python3
"""GUI-session Mac worker: frozen inputs, guarded build, in-place install, approval."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time
from compilation_cache import build_environment

from common import IDENTITY, TERMINAL, digest, ensure_directory, identity, load, locked, manifest, relative, save, source_hash, sync_directory, update, verify

TOOLS = Path(__file__).resolve().parents[1]
MAC_HOME = Path.home()
STORE = Path(os.environ.get('IOS_PUSH_MAC_STORE', MAC_HOME / 'Library/Application Support/ios-tools/push'))
CHECKPOINTS = Path(os.environ.get('IOS_PUSH_CHECKPOINTS', MAC_HOME / 'Developer/ios-push/checkpoints'))
RENEWAL = MAC_HOME / 'Library/Application Support/ios-tools/renewal'
SIGNING_LOCK = MAC_HOME / 'Library/Caches/ios-app-refresh/signing.lock'
sys.path.insert(0, str(TOOLS / 'renewal/scripts'))
import refresh


class Retry(Exception):
    pass


class Rebuild(Retry):
    pass


class RecoverTransport(Exception):
    pass


def paths(job_id):
    job_id = identity(job_id)
    return STORE / 'jobs' / job_id, CHECKPOINTS / job_id / 'source'


def config_path(repo, app):
    return RENEWAL / identity(repo) / 'config' / (identity(app) + '.json')


def clone(source, destination):
    """Distinct APFS inodes share unchanged blocks; never hardlink mutable builds."""
    source, destination = Path(source), Path(destination)
    ensure_directory(destination.parent)
    if destination.exists(): return
    result = subprocess.run(['/bin/cp', '-cRp', str(source), str(destination)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        if destination.exists():
            if destination.is_dir(): shutil.rmtree(destination)
            else: destination.unlink()
        if source.is_dir(): shutil.copytree(source, destination, symlinks=False)
        else: shutil.copy2(source, destination)


def receive(job_id, repo, app):
    metadata, source = paths(job_id)
    if (metadata / 'cancelled.json').exists(): return {'ready': True, 'source': str(source), 'metadata': str(metadata)}
    if (metadata / 'ready.json').exists(): return {'ready': True, 'source': str(source), 'metadata': str(metadata)}
    ensure_directory(metadata)
    save(metadata / 'incoming.json', {'at': time.time(), 'repo': repo, 'app': app})
    with locked(SIGNING_LOCK):
        status = subprocess.run([sys.executable, str(TOOLS / 'native/scripts/mac-workload'), 'status'], capture_output=True, text=True, timeout=30, check=True)
        status = json.loads(status.stdout)
        if status.get('booted'): raise Retry('Waiting for the booted simulator to shut down')
        if status['metrics'].get('pressure', 1) != 1: raise Retry('Waiting for normal Mac memory pressure')
        if status['metrics']['diskGiB'] < 12: raise Retry('Mac disk admission requires 12 GiB free')
        ensure_directory(metadata)
        ensure_directory(source)
        previous = load(config_path(repo, app))
        if previous:
            root = Path(previous['root'])
            for item in previous['inputs']:
                item = relative(item)
                if (root / item).exists(): clone(root / item, source / item)
        # A resumed transfer may need to replace entries from an older checkpoint.
        for folder, directories, _files in os.walk(source):
            os.chmod(folder, os.stat(folder).st_mode | 0o700)
        update(metadata / 'state.json', 'receiving', id=job_id, repo=identity(repo), app=identity(app))
    return {'ready': False, 'source': str(source), 'metadata': str(metadata)}


def ready(job_id):
    metadata, source = paths(job_id); request = load(metadata / 'request.json')
    if (metadata / 'cancelled.json').exists():
        update(metadata / 'state.json', 'cancelled', id=job_id); return
    if not request or request['id'] != job_id or request.get('version') != 1 or request.get('neverLaunch') is not True:
        raise ValueError('Invalid push request')
    existing = load(metadata / 'ready.json')
    if existing:
        if existing['requestHash'] != digest(metadata / 'request.json'): raise RuntimeError('Queued request changed')
        verify_files(source, existing['files']); return
    repo, app = identity(request['repo']), identity(request['app'])
    if request['config']['name'] != app: raise ValueError('Requested app differs from its build registration')
    carry = [str(relative(item)) for item in request.get('carry', [])]
    actual = manifest(source)
    provided = {name: value for name, value in actual.items() if not any(Path(name).is_relative_to(Path(item)) for item in carry)}
    if provided != request['files'] or source_hash(request['files']) != request['sourceHash']:
        raise RuntimeError('Incomplete or changed source upload')
    if carry:
        previous = load(config_path(repo, app)); state = load(Path(previous['stateDir']) / 'state.json', {}) if previous else {}
        if not previous or refresh.fingerprint(Path(previous['root']), previous['inputs']) != state.get('inputHash'):
            raise RuntimeError('Cannot inherit an unapproved generated input')
        for item in carry:
            if refresh.fingerprint(source, [item]) != refresh.fingerprint(Path(previous['root']), [item]):
                raise RuntimeError('Inherited input does not match its approved checkpoint')
    # rsync/scp close their outputs, but closing alone does not make an accepted
    # job survive a hard power cut. Publish ready only after data and directories.
    for name in actual:
        with (source / name).open('rb') as stream: os.fsync(stream.fileno())
    with (metadata / 'request.json').open('rb') as stream: os.fsync(stream.fileno())
    for folder, _directories, _files in os.walk(source, topdown=False): sync_directory(folder)
    config = configuration(request, source)
    with locked(STORE / 'order.lock', wait=10):
        sequence = load(STORE / 'order.json', {}).get('sequence', 0) + 1
        save(STORE / 'order.json', {'sequence': sequence})
        save(metadata / 'ready.json', {'files': actual, 'sourceHash': source_hash(actual),
                                       'requestHash': digest(metadata / 'request.json'), 'inputHash': input_hash(config), 'sequence': sequence})
    update(metadata / 'state.json', 'queued', id=job_id, repo=repo, app=app, createdAt=request['createdAt'], uploadComplete=True)


def request_for(metadata):
    request = load(metadata / 'request.json')
    request['queueSequence'] = load(metadata / 'ready.json')['sequence']
    return request


def expand(value, old_root, new_root, settings):
    if isinstance(value, dict): return {key: expand(item, old_root, new_root, settings) for key, item in value.items()}
    if isinstance(value, list): return [expand(item, old_root, new_root, settings) for item in value]
    if isinstance(value, str):
        value = value.replace('__IOS_PUSH_TEAM__', settings['team']).replace('__IOS_PUSH_DEVICE__', settings['device'])
        if '__IOS_PUSH_WATCH_DEVICE__' in value:
            if not settings.get('watchDevice'): raise RuntimeError('Set watchDevice in the Mac private ios-tools.local.json before pushing a Watch app')
            value = value.replace('__IOS_PUSH_WATCH_DEVICE__', settings['watchDevice'])
        if value == old_root or value.startswith(old_root + '/'):
            value = str(new_root) + value[len(old_root):]
    return value


def configuration(request, source):
    settings = load(TOOLS / 'ios-tools.local.json')
    config = expand(request['config'], request['sourceRoot'], source, settings)
    config.update(root=str(source), team=settings['team'], device=settings['device'], interval='monthly',
                  profileCache=str(MAC_HOME / 'Library/Developer/Xcode/UserData/Provisioning Profiles'),
                  stateDir=str(RENEWAL / request['repo'] / request['app']))
    relative(config['app'])
    for item in config['inputs']: relative(item)
    refresh.delivery_targets(config, source / config['app'])
    if not config['bundleIds'] or len(set(config['bundleIds'])) != len(config['bundleIds']): raise ValueError('Invalid app identities')
    for forbidden in ['HOME', 'CODEX_HOME', 'SIMULATOR', 'DECODER_PROBE', 'ORIGINAL_CODEC_PROBE']:
        if config.get('environment', {}).get(forbidden): raise ValueError('Diagnostic builds cannot be pushed')
    for index in RENEWAL.glob('*/config/*.json'):
        other = load(index)
        if index != config_path(request['repo'], request['app']) and set(other['bundleIds']) & set(config['bundleIds']):
            raise ValueError('An app identity belongs to another registration')
    return config


def input_hash(config): return refresh.fingerprint(Path(config['root']), config['inputs'])


def recipe_hash(config):
    recipe = {name: config.get(name) for name in ['name', 'app', 'bundleIds', 'inputs', 'build', 'environment', 'team', 'device', 'watch']}
    def normalise(value):
        if isinstance(value, dict): return {key: normalise(item) for key, item in value.items()}
        if isinstance(value, list): return [normalise(item) for item in value]
        return value.replace(config['root'], '{ROOT}') if isinstance(value, str) else value
    return hashlib.sha256(json.dumps(normalise(recipe), sort_keys=True).encode()).hexdigest()


def profiles_current(details, config):
    state = load(Path(config['stateDir']) / 'state.json', {})
    return all(name not in details['profiles'] or details['profiles'][name]['expires'] >= profile['expires']
               for name, profile in state.get('installedProfiles', {}).items())


def verify_files(source, files):
    # Build outputs are allowed outside the frozen source file set. Input-tree
    # fingerprints additionally catch newly inserted sources inside build inputs.
    for name, expected in files.items():
        if digest(Path(source) / relative(name)) != expected: raise RuntimeError('Frozen source changed: ' + name)


def verify_checkpoint(config, frozen):
    source = Path(config['root']); verify_files(source, frozen['files'])
    if input_hash(config) != frozen['inputHash']: raise RuntimeError('Frozen input tree changed')
    # Catch a newly inserted helper/source without hashing generated build outputs.
    for folder, directories, files in os.walk(source):
        directories[:] = [name for name in directories if name not in {'__pycache__', 'xcuserdata', '.swiftpm', '.build', 'build'}]
        for name in files:
            path = str((Path(folder) / name).relative_to(source))
            if name != '.DS_Store' and path not in frozen['files']: raise RuntimeError('Unexpected source file in checkpoint: ' + path)


def verify_app(config, app):
    app = Path(app); info = plistlib.loads((app / 'Info.plist').read_bytes())
    if info['CFBundleIdentifier'] != config['bundleIds'][0] or info.get('CFBundleSupportedPlatforms') != ['iPhoneOS']:
        raise RuntimeError('Wrong app identity or simulator artifact')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True, stdout=subprocess.DEVNULL)
    expected = [config['team'] + '.' + item for item in config['bundleIds']]
    profiles = refresh.app_profiles(app, expected)
    now = time.time()
    for identity_name, profile in profiles.items():
        if profile['expires'] < now + 45 * 86400: raise RuntimeError('Provisioning profile expires too soon')
    targets = refresh.delivery_targets(config, app)
    for entry in refresh.bundle_entries(app):
        target = next((target for target in reversed(targets) if entry.is_relative_to(target['app'])), None)
        if target is None or not entry.resolve().is_relative_to(app.resolve()): raise RuntimeError('Embedded bundle is outside its signed app')
        profile = plistlib.loads(subprocess.check_output(['security', 'cms', '-D', '-i', str(entry / 'embedded.mobileprovision')], stderr=subprocess.DEVNULL))
        if profile['TeamIdentifier'] != [config['team']] or target['device'] not in profile.get('ProvisionedDevices', []):
            raise RuntimeError('Profile does not authorise the paid team and target device')
        embedded = plistlib.loads((entry / 'Info.plist').read_bytes())
        bundle = embedded['CFBundleIdentifier']
        if embedded.get('CFBundleSupportedPlatforms') != [target['platform']]: raise RuntimeError('Embedded bundle has the wrong device platform')
        if config.get('watch') and str(embedded['CFBundleVersion']) != str(info['CFBundleVersion']):
            raise RuntimeError('Companion, Watch and complication build versions differ')
        entitlement = plistlib.loads(subprocess.check_output(['codesign', '-d', '--entitlements', ':-', str(entry)], stderr=subprocess.DEVNULL))
        if entitlement.get('application-identifier') != config['team'] + '.' + bundle: raise RuntimeError('Signing entitlement differs from the app identity')
        if target['platform'] == 'WatchOS':
            required = set(config['watch'].get('appGroups', []))
            if not required.issubset(entitlement.get('com.apple.security.application-groups', [])) or not required.issubset(profile['Entitlements'].get('com.apple.security.application-groups', [])):
                raise RuntimeError('Watch app or complication is missing its provisioned App Group')
    binary = (app / info['CFBundleExecutable']).read_bytes()
    arches = subprocess.check_output(['lipo', '-archs', str(app / info['CFBundleExecutable'])], text=True).split()
    if 'arm64' not in arches or any(item.startswith('x86') for item in arches): raise RuntimeError('Product is not an arm64 phone build')
    for marker in [b'zoom-fixture', b'navigation-state', b'feed-scroll', b'reader-check-state', b'original-codec-probe', b'decoder-probe.json', b'qa-command.json']:
        if marker in binary: raise RuntimeError('Diagnostic code in a product build')
    if info['CFBundleIdentifier'] == 'com.visar.MaidHeroes':
        wasm = app / 'Web/Build/MaidHeroes.wasm'
        if not wasm.exists() or any(marker in wasm.read_bytes() for marker in [b'_qa_', b'_test_']): raise RuntimeError('Unverified Maid Heroes Web payload')
    return {'bundle': info['CFBundleIdentifier'], 'version': str(info['CFBundleVersion']), 'profiles': profiles}


def build_one(job_id):
    if not os.environ.get('IOS_WORKLOAD_ACTIVE') or not os.environ.get('IOS_REFRESH_LOCK_FD'):
        raise RuntimeError('The shared workload guard must own a push build')
    metadata, source = paths(job_id); request = request_for(metadata); frozen = load(metadata / 'ready.json')
    if digest(metadata / 'request.json') != frozen['requestHash']: raise RuntimeError('Queued build request changed')
    config = configuration(request, source); before = input_hash(config)
    verify_checkpoint(config, frozen)
    # Retain the validated output/input layout even if a builder fails before
    # producing its receipt, so completed compiler caches can still be cleaned.
    save(metadata / 'config.json', config)
    save(metadata / 'build-receipt.json', {'inputHash': before, 'complete': False})
    app = source / config['app']
    previous = load(config_path(request['repo'], request['app']))
    reused = False
    compile_seconds = 0.0
    # Reuse an identical validated queue build, including validation-only runs.
    if not request.get('force'):
        for candidate in sorted((STORE / 'jobs').glob('*'), reverse=True):
            if candidate == metadata: continue
            built = load(candidate / 'build-receipt.json', {})
            captured = load(candidate / 'ready.json', {})
            older = load(candidate / 'config.json')
            if not older or not built.get('complete') or built.get('inputHash') != before: continue
            if captured.get('sourceHash') != frozen['sourceHash'] or recipe_hash(older) != recipe_hash(config): continue
            cached = Path(older['root']) / older['app']
            try:
                verify_checkpoint(older, captured)
                if refresh.fingerprint(cached.parent, [cached.name]) != built['appHash']: continue
                if not profiles_current(verify_app(config, cached), config): continue
                if app.exists(): shutil.rmtree(app)
                clone(cached, app); reused = True; break
            except (OSError, RuntimeError, subprocess.SubprocessError): continue
    if previous and not reused and not request.get('force'):
        state = load(Path(previous['stateDir']) / 'state.json', {})
        old_app = Path(previous['root']) / previous['app']
        if before == state.get('inputHash') and input_hash(previous) == before and old_app.exists():
            try:
                details = verify_app(config, old_app)
                if not profiles_current(details, config): raise RuntimeError('Cached provisioning is older than the installed app')
                if old_app.resolve() != app.resolve():
                    if app.exists(): shutil.rmtree(app)
                    clone(old_app, app)
                reused = True
            except (OSError, subprocess.SubprocessError, RuntimeError): reused = False
    if not reused:
        update(metadata / 'state.json', 'building', message='Compiling the frozen source checkpoint')
        if any(app.is_relative_to(source / item) for item in config['inputs']): raise RuntimeError('Build output overlaps its frozen inputs')
        if app.exists(): shutil.rmtree(app)
        environment = dict(os.environ)
        for item in ['SIMULATOR', 'DECODER_PROBE', 'ORIGINAL_CODEC_PROBE']: environment.pop(item, None)
        environment.update(config.get('environment', {}), SIGNING_DESTINATION='generic/platform=iOS')
        environment = build_environment(environment, metadata, source, MAC_HOME / 'Library/Caches/ios-tools/CompilationCache.noindex',
                                        product=config['app'], app_name=config['name'])
        print('Using shared Xcode compilation cache (2 GiB per CAS store)', flush=True)
        compile_started = time.monotonic()
        subprocess.run(config['build'], cwd=source, env=environment, pass_fds=(int(os.environ['IOS_REFRESH_LOCK_FD']),), check=True)
        compile_seconds = time.monotonic() - compile_started
    if input_hash(config) != before: raise RuntimeError('Build changed its approved input tree')
    verify_checkpoint(config, frozen)
    details = verify_app(config, app)
    save(metadata / 'build-receipt.json', {'inputHash': before, 'appHash': refresh.fingerprint(app.parent, [app.name]),
                                         'sourceHash': frozen['sourceHash'], 'recipeHash': recipe_hash(config),
                                         'complete': True, 'reused': reused, 'compileSeconds': compile_seconds, **details})
    save(metadata / 'config.json', config)
    cleanup_intermediates(config)


def cleanup_intermediates(config):
    root = Path(config['root'])
    if not root.is_relative_to(CHECKPOINTS): return
    def protected(path):
        return any((root / item).is_relative_to(path) or path.is_relative_to(root / item) for item in config['inputs'])
    for directory in [*(root / 'build').glob('**/DerivedData'), *(root / 'build').glob('**/Intermediates')]:
        if protected(directory): continue
        shutil.rmtree(directory)
    app = root / config['app']
    if app.parent.exists():
        for path in list(app.parent.iterdir()):
            if path.suffix == '.app' or protected(path): continue
            if path.is_dir(): shutil.rmtree(path)
            else: path.unlink()


def validate_receipt(config, receipt, app):
    if input_hash(config) != receipt['inputHash']: raise RuntimeError('Frozen build inputs changed')
    if not app.exists() or refresh.fingerprint(app.parent, [app.name]) != receipt['appHash']:
        raise Rebuild('Interrupted or changed signed artifact needs rebuilding')
    details = verify_app(config, app)
    state = load(Path(config['stateDir']) / 'state.json', {})
    for name, previous in state.get('installedProfiles', {}).items():
        if name in details['profiles'] and details['profiles'][name]['expires'] < previous['expires']:
            raise Rebuild('Installed provisioning is newer than this queued artifact')
    return details


def pending_state(request, config):
    path = Path(config['stateDir']) / 'state.json'
    state = load(path, {})
    pending = state.get('pendingPush')
    if pending and pending.get('sequence', 0) > request['queueSequence']: raise RuntimeError('A newer push owns this app')
    if pending and pending.get('id') != request['id']:
        old, _ = paths(pending['id'])
        update(old / 'state.json', 'superseded', message='Replaced by ' + request['id'])
    state['pendingPush'] = {'id': request['id'], 'createdAt': request['createdAt'], 'sequence': request['queueSequence']}
    save(path, state)
    return path, state


def catalog(config, output):
    output.unlink(missing_ok=True)
    try:
        result = subprocess.run([str(TOOLS / 'native/scripts/apple-tool'), 'devicectl', 'device', 'info', 'apps',
                                 '--device', config['device'], '--json-output', str(output), '--timeout', '20', '--quiet'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    except (OSError, subprocess.SubprocessError): return None
    if result.returncode: return None
    return load(output, {}).get('result', {}).get('apps')


def ensure_initial_scheduler(request, index, metadata):
    if not load(metadata / 'state.json', {}).get('renewalSchedulerPending'): return
    label = 'com.visar.renewal.' + request['repo']; domain = 'gui/' + str(os.getuid())
    plist = MAC_HOME / 'Library/LaunchAgents' / (label + '.plist')
    runner = TOOLS / 'renewal/scripts/refresh-installed.py'
    check = ['/bin/launchctl', 'print', domain + '/' + label]
    try:
        if subprocess.run(check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode:
            if plist.exists():
                data = plistlib.loads(plist.read_bytes())
                expected = ['/usr/bin/python3', str(runner), 'refresh', '--config', str(index), '--scheduled']
                if data.get('Label') != label or data.get('ProgramArguments') != expected:
                    raise RuntimeError('Existing renewal scheduler differs from the new project registration')
                subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(plist)], check=True, timeout=20)
            else:
                subprocess.run([sys.executable, str(runner), 'install', '--repo', request['repo']],
                               check=True, timeout=30, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if subprocess.run(check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10).returncode:
                raise Retry('Apps installed; initial renewal scheduler is not yet loaded')
    except subprocess.SubprocessError as error:
        raise Retry('Apps installed; initial renewal scheduler setup will retry') from error
    update(metadata / 'state.json', 'installing', renewalSchedulerPending=False)


def approve(request, config, receipt):
    state_path, state = pending_state(request, config)
    destination = config_path(request['repo'], request['app'])
    metadata, _ = paths(request['id'])
    index = RENEWAL / request['repo'] / 'apps.json'
    previous = load(destination, {})
    if not destination.exists():
        update(metadata / 'state.json', 'installing', initialRegistration=True)
    initial = load(metadata / 'state.json', {}).get('initialRegistration', False)
    managed_scheduler = previous.get('pushManagedScheduler', False) or (initial and not index.exists())
    if managed_scheduler:
        config['pushManagedScheduler'] = True
        plist = MAC_HOME / 'Library/LaunchAgents' / ('com.visar.renewal.' + request['repo'] + '.plist')
        if not plist.exists(): update(metadata / 'state.json', 'installing', renewalSchedulerPending=True)
    config.update(pushJob=request['id'], pushCreatedAt=request['createdAt'], pushSequence=request['queueSequence'])
    save(destination, config)
    listing = load(index, {'repo': request['repo'], 'device': config['device'], 'logDir': str(RENEWAL / request['repo']), 'apps': []})
    if not any(item['config'] == str(destination) for item in listing['apps']):
        listing['apps'].append({'config': str(destination), 'runner': str(TOOLS / 'renewal/scripts/refresh.py')})
    save(index, listing)
    expected = [config['team'] + '.' + item for item in config['bundleIds']]
    refresh.approve(config, state_path, state, Path(config['root']) / config['app'], expected, receipt['inputHash'],
                    keep_schedule=True, initial_install=initial)
    if load(state_path)['inputHash'] != receipt['inputHash']: raise RuntimeError('Renewal approval did not commit')
    ensure_initial_scheduler(request, index, metadata)


def wait_for_watch(metadata, message):
    attempts = load(metadata / 'state.json', {}).get('watchAttempts', 0) + 1
    update(metadata / 'state.json', 'awaiting_watch', watchAttempts=attempts,
           nextAttempt=time.time() + min(300, 30 * 2 ** min(attempts, 4)),
           message=message)


def deliver_watch(config, receipt, app, metadata):
    target = refresh.delivery_targets(config, app)[1]
    state = load(metadata / 'state.json', {})
    proof = {'appHash': receipt['appHash'], 'device': target['device'], 'version': receipt['version']}
    if state.get('watchDelivery') == proof: return True
    def companion_install():
        actual = refresh.companion_apps(config, target, metadata / 'watch-companion-install.json', install=True)
        if not any(row.get('bundleIdentifier') == target['bundle'] and str(row.get('bundleVersion')) == receipt['version'] for row in actual or []):
            return False
        update(metadata / 'state.json', 'installing', watchDelivery=proof, watchTransport='companion-lockdown')
        return True
    watch_config = dict(config, device=target['device'])
    if catalog(watch_config, metadata / 'watch-before.json') is None:
        if companion_install(): return True
        wait_for_watch(metadata, 'Phone updated; waiting for paired Watch delivery access')
        return False
    log_path = metadata / 'watch-install.log'
    command = [str(TOOLS / 'native/scripts/apple-tool'), 'devicectl', 'device', 'install', 'app',
               '--device', target['device'], str(target['app']), '--timeout', '120']
    with log_path.open('w') as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=140)
    if result.returncode:
        detail = log_path.read_text(errors='replace').lower()
        if any(marker in detail for marker in ['remote.installcoordination_proxy', 'coredeviceerror error 4000', 'remotepairingerror error 1001']):
            # One cold-DDI preparation/retry, with the same signed bytes. A
            # sleeping/offline Watch normally fails the app-service check above.
            with log_path.open('a') as stream:
                subprocess.run([str(TOOLS / 'native/scripts/apple-tool'), 'devicectl', 'device', 'info', 'ddiServices',
                                '--device', target['device'], '--timeout', '30'],
                               stdout=stream, stderr=subprocess.STDOUT, timeout=45)
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=140)
        if result.returncode:
            if companion_install(): return True
            wait_for_watch(metadata, 'Phone updated; Watch install is pending. See watch-install.log')
            return False
    actual = catalog(watch_config, metadata / 'watch-after.json')
    if not any(row.get('bundleIdentifier') == target['bundle'] and str(row.get('bundleVersion')) == receipt['version'] for row in actual or []):
        # The native installer acknowledged these exact bytes; a separate live
        # companion inventory can confirm them if only direct discovery drops.
        actual = refresh.companion_apps(config, target, metadata / 'watch-companion-after.json')
    if not any(row.get('bundleIdentifier') == target['bundle'] and str(row.get('bundleVersion')) == receipt['version'] for row in actual or []):
        wait_for_watch(metadata, 'Watch install acknowledged; actual installed-version confirmation is pending')
        return False
    update(metadata / 'state.json', 'installing', watchDelivery=proof)
    return True


def deliver(job_id, allow_ota=False):
    metadata, source = paths(job_id); request = request_for(metadata); config = load(metadata / 'config.json')
    receipt = load(metadata / 'build-receipt.json'); app = source / config['app']
    frozen = load(metadata / 'ready.json')
    if digest(metadata / 'request.json') != frozen['requestHash'] or configuration(request, source) != config:
        raise RuntimeError('Queued build registration changed')
    with locked(SIGNING_LOCK):
        if (metadata / 'cancelled.json').exists(): update(metadata / 'state.json', 'cancelled'); return
        current = load(config_path(request['repo'], request['app']), {})
        if current.get('pushSequence', 0) > request['queueSequence']:
            update(metadata / 'state.json', 'superseded', message='A newer source checkpoint is installed'); return
        pending = load(Path(config['stateDir']) / 'state.json', {}).get('pendingPush', {})
        if pending.get('sequence', 0) > request['queueSequence']:
            update(metadata / 'state.json', 'superseded', message='A newer push owns this app'); return
        verify_checkpoint(config, frozen)
        validate_receipt(config, receipt, app)
        phone_proof = {'appHash': receipt['appHash'], 'device': config['device'], 'version': receipt['version']}
        phone_done = bool(config.get('watch') and load(metadata / 'state.json', {}).get('phoneDelivery') == phone_proof)
        ota_requested = load(metadata / 'delivery-mode.json', {}).get('mode') == 'ota'
        unpublished_ota = ota_requested and not load(metadata / 'state.json', {}).get('otaPublished')
        before = [] if phone_done else (None if unpublished_ota else catalog(config, metadata / 'phone-before.json'))
        if before is None and not allow_ota and not ota_requested: raise RecoverTransport()
        with locked(metadata / 'control.lock', wait=5):
            if (metadata / 'cancelled.json').exists(): update(metadata / 'state.json', 'cancelled'); return
            state_path, state = pending_state(request, config)
            update(metadata / 'state.json', 'publishing' if before is None else 'installing',
                   installAttempted=True, deliveryAttempts=load(metadata / 'state.json', {}).get('deliveryAttempts', 0) + 1)
        if before is None:
            if not load(metadata / 'state.json', {}).get('otaPublished'):
                with (metadata / 'install.log').open('w') as stream:
                    result = subprocess.run([str(TOOLS / 'native/scripts/phone-install'), '--ota', '--device', config['device'], str(app)],
                                            env=dict(os.environ, IOS_PUSH_JOB_ID=request['id']), stdout=stream, stderr=subprocess.STDOUT, timeout=180)
                if result.returncode != 10: raise RuntimeError('OTA publication failed; see the private install log')
            update(metadata / 'state.json', 'awaiting_ota', otaPublished=True, nextAttempt=time.time() + 300,
                   message='Signed update published; direct installation will retry when the phone returns')
            return
        if not phone_done:
            with (metadata / 'install.log').open('w') as stream:
                result = subprocess.run([str(TOOLS / 'native/scripts/apple-tool'), 'devicectl', 'device', 'install', 'app',
                                         '--device', config['device'], str(app), '--timeout', '180'],
                                        stdout=stream, stderr=subprocess.STDOUT, timeout=200)
            if result.returncode: raise Retry('Installation interrupted or rejected; see private install.log')
            after = catalog(config, metadata / 'phone-after.json')
            installed = next((item for item in after or [] if item['bundleIdentifier'] == config['bundleIds'][0]), None)
            if not installed or str(installed.get('bundleVersion')) != receipt['version']: raise Retry('Install acknowledgement received; version confirmation is pending')
            if config.get('watch'): update(metadata / 'state.json', 'installing', phoneDelivery=phone_proof)
        if config.get('watch') and not deliver_watch(config, receipt, app, metadata): return
        # These checks run under the same lock as installation and approval.
        if input_hash(config) != receipt['inputHash'] or refresh.fingerprint(app.parent, [app.name]) != receipt['appHash']:
            raise RuntimeError('Inputs changed before approval')
        approve(request, config, receipt)
        watch_result = ({'watchBundle': config['watch']['bundleId'], 'watchVersion': receipt['version']}
                        if config.get('watch') else {})
        update(metadata / 'state.json', 'installed', bundle=receipt['bundle'], version=receipt['version'],
               inputHash=receipt['inputHash'], appHash=receipt['appHash'], sourceRevision=request.get('sourceRevision'),
               checkpoint=str(source), launched=False, nextAttempt=0,
               message='Phone and Watch installed in place and approved for renewal' if config.get('watch') else 'Installed in place and approved for renewal',
               **watch_result)


def build_errors(output):
    """Keep the compiler's cause even when Xcode's traceback fills the log tail."""
    markers = ('error:', 'Undefined symbols', 'ld: ', 'BUILD FAILED')
    errors = []
    for line in output.splitlines():
        line = line.strip()
        if 'warning:' in line and 'error:' not in line: continue
        if any(marker in line for marker in markers) and line not in errors:
            errors.append(line[:500])
            if len(errors) == 5: break
    return errors


def log_excerpt(output):
    tail = [line[:500] for line in output.splitlines()[-20:]]
    return '\n'.join([line for line in build_errors(output) if line not in tail] + tail)


def run_job(job_id):
    metadata, source = paths(job_id); request = request_for(metadata); state = load(metadata / 'state.json', {})
    if state.get('phase') in TERMINAL or (metadata / 'cancelled.json').exists(): return
    frozen = load(metadata / 'ready.json')
    if digest(metadata / 'request.json') != frozen['requestHash']: raise RuntimeError('Queued build request changed')
    current = load(config_path(request['repo'], request['app']), {})
    if not request.get('validateOnly') and current.get('pushSequence', 0) > request['queueSequence']:
        update(metadata / 'state.json', 'superseded', message='A newer source checkpoint is installed'); return
    receipt = load(metadata / 'build-receipt.json', {})
    if not receipt.get('complete'):
        update(metadata / 'state.json', 'building', message='Waiting for guarded Mac build admission')
        log_path = metadata / 'build.log'
        offset = log_path.stat().st_size if log_path.exists() else 0
        with log_path.open('a') as stream:
            result = subprocess.run([sys.executable, str(TOOLS / 'native/scripts/mac-workload'), 'build', '--wait-for-idle', '300',
                                     '--timeout', '900', '--', sys.executable, str(Path(__file__).resolve()), 'build-one', '--id', job_id],
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=1250)
        if result.returncode:
            with log_path.open('rb') as stream:
                stream.seek(offset); text = stream.read().decode(errors='replace')
            reason = refresh.preflight_deferral_text(text)
            if reason: raise Retry('Waiting for shared Mac resources: ' + reason)
            errors = build_errors(text)
            detail = errors[0] if errors else 'see private build.log'
            raise RuntimeError('Build failed: ' + detail)
    if (metadata / 'cancelled.json').exists(): update(metadata / 'state.json', 'cancelled'); return
    if request.get('validateOnly'):
        with locked(SIGNING_LOCK):
            config = load(metadata / 'config.json'); receipt = load(metadata / 'build-receipt.json')
            verify_checkpoint(config, frozen)
            validate_receipt(config, receipt, source / config['app'])
        update(metadata / 'state.json', 'validated', message='Signed source checkpoint verified; no phone operation', nextAttempt=0)
        return
    try: deliver(job_id)
    except RecoverTransport:
        # Pairing recovery uses the same global lock itself. Never call it while
        # retaining the installation lock, and never change trust or phone UI.
        if (metadata / 'cancelled.json').exists(): update(metadata / 'state.json', 'cancelled'); return
        subprocess.run([str(TOOLS / 'native/scripts/phone-pairing'), '--now'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        deliver(job_id, allow_ota=True)


def prune():
    """Keep every approved/pending source root, plus two recent unreferenced trials."""
    try:
        with locked(SIGNING_LOCK):
            keep = set()
            for path in RENEWAL.glob('*/config/*.json'):
                config = load(path); root = Path(config['root'])
                if root.is_relative_to(CHECKPOINTS): keep.add(root.relative_to(CHECKPOINTS).parts[0])
                state = load(root / config.get('stateDir', 'build/refresh') / 'state.json', {})
                if state.get('pendingPush'): keep.add(state['pendingPush']['id'])
            jobs = sorted((STORE / 'jobs').glob('*'), reverse=True)
            recent = 0
            for metadata in jobs:
                state = load(metadata / 'state.json', {})
                if state.get('phase') not in TERMINAL: keep.add(metadata.name)
                elif recent < 2: keep.add(metadata.name); recent += 1
                config = load(metadata / 'config.json')
                if not config and state.get('phase') in TERMINAL:
                    frozen = load(metadata / 'ready.json', {})
                    request = load(metadata / 'request.json')
                    if request and frozen.get('requestHash') == digest(metadata / 'request.json'):
                        try: config = configuration(request, paths(metadata.name)[1])
                        except (KeyError, ValueError, RuntimeError): pass
                if config and (state.get('phase') in TERMINAL or load(metadata / 'build-receipt.json', {}).get('complete')):
                    cleanup_intermediates(config)
            for directory in CHECKPOINTS.glob('*'):
                if directory.name not in keep and IDENTITY.fullmatch(directory.name):
                    shutil.rmtree(directory)
    except BlockingIOError: pass


def control(job_id, action):
    metadata, source = paths(job_id); state = load(metadata / 'state.json', {})
    if action == 'ota':
        ensure_directory(metadata)
        with locked(metadata / 'control.lock', wait=5):
            state = load(metadata / 'state.json', {})
            if state.get('phase') in TERMINAL: raise RuntimeError('This delivery is already closed')
            save(metadata / 'delivery-mode.json', {'mode': 'ota', 'at': time.time()})
            update(metadata / 'state.json', state.get('phase', 'receiving'), id=job_id,
                   nextAttempt=state.get('nextAttempt', 0) if state.get('otaPublished') else 0,
                   message='OTA publication requested for this delivery')
    elif action == 'cancel':
        metadata.mkdir(parents=True, exist_ok=True, mode=0o700)
        with locked(metadata / 'control.lock', wait=5):
            state = load(metadata / 'state.json', {})
            request = load(metadata / 'request.json')
            if request:
                registration = load(config_path(request['repo'], request['app']), {})
                pending = load(RENEWAL / request['repo'] / request['app'] / 'state.json', {}).get('pendingPush', {})
                if pending.get('id') == job_id or registration.get('pushJob') == job_id:
                    raise RuntimeError('Delivery may already be applied; finish it or supersede it with a newer push')
            if state.get('installAttempted') or state.get('otaPublished') or state.get('phase') == 'installed':
                raise RuntimeError('Delivery may already be applied; finish it or supersede it with a newer push')
            save(metadata / 'cancelled.json', {'at': time.time()})
            update(metadata / 'state.json', 'cancelled', id=job_id, nextAttempt=0)
    else:
        if not (metadata / 'ready.json').exists(): raise RuntimeError('Source upload is not complete')
        if not source.exists(): raise RuntimeError('Old checkpoint was pruned; enqueue the current source again')
        frozen = load(metadata / 'ready.json')
        if digest(metadata / 'request.json') != frozen['requestHash']: raise RuntimeError('Queued request changed; enqueue a new checkpoint')
        verify_files(source, frozen['files'])
        (metadata / 'cancelled.json').unlink(missing_ok=True)
        update(metadata / 'state.json', 'queued', nextAttempt=0, message='Retry requested')


def work():
    with locked(STORE / 'worker.lock'):
        due = []
        for metadata in sorted((STORE / 'jobs').glob('*')):
            try: state = load(metadata / 'state.json', {})
            except (OSError, ValueError):
                save(metadata / 'state.json', {'id': metadata.name, 'phase': 'failed', 'message': 'Unreadable queue state; inspect and retry the frozen checkpoint'})
                continue
            if not (metadata / 'ready.json').exists() or state.get('phase') in TERMINAL or state.get('nextAttempt', 0) > time.time(): continue
            due.append((bool(state.get('otaPublished') or state.get('phase') == 'awaiting_watch'), metadata, state))
        # Fresh source/build/publication work precedes retries for packages already sent.
        for _retry, metadata, state in sorted(due, key=lambda item: (item[0], item[1].name)):
            try: run_job(metadata.name)
            except Rebuild as error:
                attempts = state.get('rebuildAttempts', 0) + 1
                if attempts > 2:
                    update(metadata / 'state.json', 'failed', message=str(error)[:300]); continue
                receipt = load(metadata / 'build-receipt.json', {})
                receipt['complete'] = False; save(metadata / 'build-receipt.json', receipt)
                update(metadata / 'state.json', 'waiting_mac', rebuildAttempts=attempts, nextAttempt=time.time() + 30, message=str(error)[:300])
            except (Retry, BlockingIOError, subprocess.TimeoutExpired) as error:
                update(metadata / 'state.json', 'waiting_mac', nextAttempt=time.time() + 30, message=str(error)[:300])
            except Exception as error:
                update(metadata / 'state.json', 'failed', message=str(error)[:400], nextAttempt=0)
        prune()


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['receive', 'ready', 'work', 'build-one', 'status', 'logs', 'install-authority', 'retry', 'cancel', 'ota'])
    parser.add_argument('--id'); parser.add_argument('--repo'); parser.add_argument('--app'); parser.add_argument('--bundle')
    args = parser.parse_args()
    if args.action == 'receive': print(json.dumps(receive(identity(args.id), identity(args.repo), identity(args.app))))
    elif args.action == 'ready': ready(identity(args.id)); print('ready')
    elif args.action == 'build-one': build_one(identity(args.id))
    elif args.action in {'retry', 'cancel', 'ota'}: control(identity(args.id), args.action)
    elif args.action == 'work':
        try: work()
        except BlockingIOError: pass
    elif args.action == 'install-authority':
        for path in RENEWAL.glob('*/config/*.json'):
            config = load(path)
            if args.bundle not in config['bundleIds']: continue
            pending = load(Path(config['root']) / config.get('stateDir', 'build/refresh') / 'state.json', {}).get('pendingPush')
            if pending and pending['id'] != os.environ.get('IOS_PUSH_JOB_ID'):
                raise Retry('Queued push ' + pending['id'] + ' owns this app; use ios-push status')
    elif args.action == 'status': print(json.dumps(load(paths(args.id)[0] / 'state.json', {})))
    elif args.action == 'logs':
        metadata, _ = paths(args.id)
        for name in ['build.log', 'install.log', 'watch-install.log', 'watch-companion-install.log', 'watch-companion-after.log']:
            path = metadata / name
            if path.exists(): print(name + '\n' + log_excerpt(path.read_text(errors='replace')))


if __name__ == '__main__':
    try: main()
    except (Retry, BlockingIOError) as error:
        print('Waiting for the shared Mac build/install lock' if isinstance(error, BlockingIOError) else str(error), file=sys.stderr)
        raise SystemExit(75)
