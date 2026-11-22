"""One-line PC submission and durable asynchronous upload/status collection."""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import uuid

from common import OTA_PAGE, TERMINAL, install_note, ensure_directory, identity, load, locked, save, source_hash, update, verify
from snapshot import capture

TOOLS = Path(__file__).resolve().parents[1]
ON_MAC = sys.platform == 'darwin'
STORE = Path(os.environ.get('IOS_PUSH_STORE', Path.home() / ('Library/Application Support/ios-tools/push' if ON_MAC else '.local/share/ios-tools/push')))
REMOTE = '/Users/visar/Library/Application Support/ios-tools/push'
RUNNER = '/Users/visar/Developer/ios-tools/push/worker.py'
LABEL = 'com.visar.ios-push'


# What a project may say about itself, in ios-push.json at its root: its short names, its
# compiler-cache policy, how it is prepared and tested. Merged over the registry entry, so a
# project's own (possibly private) app names never need to be in this repository.
PROJECT_SETTINGS = ('aliases', 'persistentBuildCache', 'prepare', 'tests', 'testScope', 'carry', 'declaration')


def projects():
    result = load(TOOLS / 'push/projects.json')
    base = Path(os.environ.get('IOS_PUSH_WORKSPACE', Path.home() / ('Developer' if ON_MAC else 'Documents/work')))
    for name, item in result.items():
        item['root'] = str(base / (name if ON_MAC else item['path']))
        own = load(Path(item['root']) / 'ios-push.json', {})
        item.update({key: value for key, value in own.items() if key in PROJECT_SETTINGS})
    return result


def declaration(project):
    root = Path(project['root'])
    name = project.get('declaration') or next((name for name in
        ['apps/ios/scripts/renewal.py', 'tools/renewal.py', 'scripts/renewal.py'] if (root / name).is_file()), 'apps/ios/scripts/renewal.py')
    script = root / name
    result = subprocess.run([sys.executable, str(script), '--team', '__IOS_PUSH_TEAM__', '--device', '__IOS_PUSH_DEVICE__'],
                            capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout)


def choose(selector, project_name=None, source=None):
    registry = projects(); choices = []
    if ':' in selector: project_name, selector = selector.split(':', 1)
    local = None
    if source:
        local_project = {'root': str(Path(source).expanduser().resolve())}
        local = declaration(local_project)
    else:
        for candidate in [Path.cwd(), *Path.cwd().parents]:
            if any((candidate / name).is_file() for name in ['apps/ios/scripts/renewal.py', 'tools/renewal.py', 'scripts/renewal.py']):
                local_project = {'root': str(candidate)}; local = declaration(local_project); break
    for name, project in registry.items():
        if project_name and name != project_name: continue
        if local and local['repo'] == name: project = dict(project, root=local_project['root'])
        try: listing = local if local and local['repo'] == name else declaration(project)
        except (OSError, subprocess.CalledProcessError): continue
        selected = project.get('aliases', {}).get(selector, selector)
        for app in listing['apps']:
            if app['name'] == selected or (selector == name and len(listing['apps']) == 1): choices.append((name, project, app))
    if len(choices) != 1:
        raise ValueError('Choose an unambiguous project:app; see ios-push list')
    return choices[0]


def prepare(project, app):
    root = Path(project['root']); ios = root / 'apps/ios'
    if ON_MAC: return  # Mac checkouts already contain the prepared resources; no Node/auth flows here.
    if project.get('prepare') == 'video':
        provider = app['build'][-1]
        # The repository exposes the same preparation used by its normal sync,
        # without contacting the Mac or mutating a delivery mirror.
        subprocess.run([sys.executable, str(ios / 'scripts/deploy.py'), provider, 'prepare'], cwd=root, check=True)
    elif project.get('prepare') == 'gallery':
        subprocess.run(['node', str(ios / 'scripts/build.mjs'), app['name'], '--prepare-only'], cwd=root, check=True)


def test_files(repo_root, scope):
    """Tracked and untracked, non-ignored files under scope. A linked directory in it (a
    deployment's `engine` link to a public checkout's apps/ios) contributes the files its own
    repository lists there, so the frozen copy carries what the link points at."""
    listed = subprocess.run(['git', '-C', str(repo_root), 'ls-files', '-co', '--exclude-standard', '-z', '--', scope],
                            capture_output=True, check=True).stdout.split(b'\0')
    for name in (item for item in listed if item):
        path = Path(repo_root) / name.decode()
        if path.is_symlink() and path.is_dir():
            inner = subprocess.run(['git', '-C', str(path.resolve()), 'ls-files', '-co', '--exclude-standard', '-z'],
                                   capture_output=True, check=True).stdout.split(b'\0')
            yield from (name + b'/' + item for item in inner if item)
        else: yield name


def tests_key(repo_root, project, copy_to=None):
    """The exact test inputs: every tracked and untracked, non-ignored file under the test scope
    (default apps/ios), with the test command. Ignored build outputs are not part of it.
    With copy_to, the same bytes are also written there (the job's frozen test source)."""
    scope = project.get('testScope', 'apps/ios')
    digest = hashlib.sha256(json.dumps(project['tests']).encode())
    for name in sorted(test_files(repo_root, scope)):
        path = repo_root / name.decode()
        if not path.is_file(): continue
        data = path.read_bytes()
        digest.update(name + b'\0'); digest.update(hashlib.sha256(data).digest())
        if copy_to:
            target = Path(copy_to) / name.decode(); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data); os.chmod(target, path.stat().st_mode & 0o777)
    return digest.hexdigest()


def tests_passed(repo, key):
    return load(STORE / 'test-results.json', {}).get(repo, {}).get('key') == key


def test_job(job_id):
    """Run a queued job's PC tests on its frozen test source, while the Mac builds it. The Mac
    installs nothing until the uploader reports a pass. Pushes of one repository take turns,
    so a batch runs identical tests once."""
    directory = STORE / 'jobs' / identity(job_id); request = load(directory / 'request.json')
    if not request or not request.get('testsRequired'): return
    try: runner = locked(directory / 'tests.lock'); runner.__enter__()
    except BlockingIOError: return   # already running
    try:
        if load(directory / 'tests.json', {}).get('result') or load(directory / 'state.json', {}).get('phase') in TERMINAL: return
        repo = request['repo']; key = request['testsKey']
        log = STORE / 'test-logs' / (identity(job_id) + '.log'); ensure_directory(log.parent)
        with locked(STORE / ('tests-' + identity(repo) + '.lock'), wait=900):
            started = time.time()
            if tests_passed(repo, key):
                result = 'passed'; log.write_text('Passed earlier for identical test inputs.\n')
            else:
                with log.open('w') as stream:
                    try: code = subprocess.run(request['testsCommand'], cwd=directory / 'tests-source', stdout=stream,
                                               stderr=subprocess.STDOUT, timeout=900).returncode
                    except subprocess.TimeoutExpired: code = 'timeout'
                result = 'passed' if code == 0 else 'failed'
                if result == 'passed':
                    results = load(STORE / 'test-results.json', {})
                    results[repo] = {'key': key, 'seconds': round(time.time() - started, 1), 'at': time.time()}
                    save(STORE / 'test-results.json', results)
        save(directory / 'tests.json', {'result': result, 'key': key, 'seconds': round(time.time() - started, 1),
                                        'log': str(log), 'reported': False})
    finally: runner.__exit__(None, None, None)
    # The uploader reports the result to the Mac (or fails a job that never left the PC).
    subprocess.run(['systemctl', '--user', 'start', '--no-block', 'ios-push.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_tests(job_id):
    """Run test_job detached in its own user unit, so it outlives the shell that queued the push.
    The uploader starts it again if it never finished (for example after a reboot)."""
    command = [sys.executable, str(TOOLS / 'native/scripts/ios-push'), 'test-job', job_id]
    try:
        started = subprocess.run(['systemd-run', '--user', '--collect', '--quiet', '--unit', 'ios-push-tests-' + identity(job_id).lower().replace('_', '-'),
                                  '--property', 'UMask=0077', *command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if started.returncode == 0: return
    except (OSError, subprocess.SubprocessError): pass
    subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def tests_due(directory, request, state):
    """Start the job's tests if they have no result and nothing is running them."""
    if not request.get('testsRequired') or load(directory / 'tests.json', {}).get('result') or state.get('phase') in TERMINAL: return
    try:
        with locked(directory / 'tests.lock'): pass
    except BlockingIOError: return
    start_tests(directory.name)


def enqueue(selector, project_name=None, source=None, validate_only=False, force=False, skip_tests=False):
    repo, project, app = choose(selector, project_name, source)
    repo_root = Path(project['root']).resolve(); root = Path(app['root']).resolve()
    job_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:10]
    directory = STORE / 'jobs' / job_id
    ensure_directory(directory)
    captured = Path.home() / 'Developer/ios-push/checkpoints' / job_id / 'source' if ON_MAC else directory / 'source'
    tests = None
    try:
        # The PC tests run on a frozen copy of their inputs while the Mac builds (no longer before
        # queueing); the Mac installs only after a pass. A pass for identical inputs is reused.
        if not skip_tests and project.get('tests') and not ON_MAC:
            key = tests_key(repo_root, project, copy_to=directory / 'tests-source')
            if tests_passed(repo, key):
                shutil.rmtree(directory / 'tests-source'); print(repo + ' tests already passed for this source on this PC.', flush=True)
            else: tests = {'testsRequired': True, 'testsKey': key, 'testsCommand': project['tests']}
        prepare(project, app)
        suffix = root.relative_to(repo_root)
        overlays = {}
        for src, dst in project.get('copies', {}).items():
            target = Path(dst)
            if target.is_relative_to(suffix): overlays[str(target.relative_to(suffix))] = repo_root / src
        extra = []
        for candidate in ['scripts', 'apps/ios/scripts']:
            if (root / candidate).is_dir(): extra.append(candidate)
        files, missing = capture(root, captured, app['inputs'], extra, overlays, project.get('carry', []))
        # Git identifies the review checkpoint; actual bytes include working edits
        # and ignored production resources, frozen before enqueue returns.
        revision = subprocess.run(['git', '-C', str(repo_root), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        request = {'version': 1, 'id': job_id, 'repo': identity(repo), 'app': identity(app['name']),
                   'createdAt': time.time(), 'sourceRevision': revision, 'sourceHash': source_hash(files),
                   'files': files, 'carry': missing, 'config': app, 'sourceRoot': str(root),
                   'validateOnly': validate_only, 'force': force, 'neverLaunch': True, **(tests or {}),
                   # The Mac worker (and every renewal of this checkpoint) reads the cache policy here.
                   **({'persistentBuildCache': project['persistentBuildCache']} if project.get('persistentBuildCache') else {})}
        update(directory / 'state.json', 'queued', id=job_id, repo=repo, app=app['name'], createdAt=request['createdAt'])
        save(directory / 'request.json', request)  # Publish last; uploader cannot race the initial state.
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        if ON_MAC: shutil.rmtree(captured.parent, ignore_errors=True)
        raise
    if ON_MAC:
        import worker
        worker.ready(job_id)
        subprocess.run(['launchctl', 'kickstart', 'gui/' + str(os.getuid()) + '/' + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        started = subprocess.run(['systemctl', '--user', 'start', '--no-block', 'ios-push.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if tests:
            start_tests(job_id)
            print('Running ' + repo + ' tests on this PC while the Mac builds; it installs only if they pass.', flush=True)
        if started.returncode: raise RuntimeError('Job ' + job_id + ' is saved; install the shared ios-push worker before delivery')
    return job_id


def remote(arguments, timeout=90, check=True):
    command = shlex.join(['/usr/bin/python3', RUNNER, *arguments])
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', 'mac', command], capture_output=True, text=True, timeout=timeout, check=check)


def transfer(directory, checksum=False):
    request = load(directory / 'request.json'); job_id = identity(request['id'])
    verify(directory / 'source', request['files'])
    target = json.loads(remote(['receive', '--id', job_id, '--repo', request['repo'], '--app', request['app']]).stdout)
    if target.get('ready'): return
    # Size/mtime quick check: the Mac's `ready` hashes every file and refuses a mismatch, after which
    # the retry compares checksums (reading all files on both machines, as every upload used to).
    args = ['rsync', '-az', '--delete', *(['--checksum'] if checksum else []), '-e', 'ssh -o BatchMode=yes', str(directory / 'source') + '/',
            'mac:' + shlex.quote(target['source']) + '/']
    for item in request.get('carry', []): args.insert(1, '--exclude=/' + str(item))
    subprocess.run(args, check=True, timeout=600, stdout=subprocess.DEVNULL)
    # Ready is written on the Mac only after all bytes and the complete request
    # arrive and their hashes agree. An interrupted upload remains unbuildable.
    metadata = target['metadata']
    subprocess.run(['scp', '-q', str(directory / 'request.json'), 'mac:' + metadata + '/request.json'], check=True, timeout=60)
    remote(['ready', '--id', job_id], timeout=120)
    subprocess.run(['ssh', 'mac', 'launchctl kickstart gui/501/' + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)


def pump():
    with locked(STORE / 'uploader.lock'):
        for directory in sorted((STORE / 'jobs').glob('*')):
            try:
                state = load(directory / 'state.json', {})
                if state.get('phase') in TERMINAL: continue
                request = load(directory / 'request.json')
            except (OSError, ValueError):
                save(directory / 'state.json', {'id': directory.name, 'phase': 'failed', 'message': 'Unreadable queue record; enqueue a fresh checkpoint'})
                continue
            if not request: continue
            tests = load(directory / 'tests.json', {}) if request.get('testsRequired') else {}
            uploaded = state.get('uploadComplete') or (directory / 'uploaded.json').exists()
            if tests.get('result') == 'failed' and not uploaded and not tests.get('reported'):
                # Failed before it reached the Mac: nothing to upload or build.
                update(directory / 'state.json', 'failed', message='PC tests failed; nothing was queued on the Mac. Log: ' + tests.get('log', ''))
                continue
            tests_due(directory, request, state)
            if state.get('transportNextAttempt', 0) > time.time(): continue
            try:
                if not uploaded:
                    update(directory / 'state.json', 'uploading', message='Transferring the frozen source checkpoint')
                    transfer(directory, checksum=state.get('checksumTransfer', False))
                    update(directory / 'state.json', 'submitted', uploadComplete=True, message='Source transferred; waiting for guarded build')
                    save(directory / 'uploaded.json', {'at': time.time()})   # state.json is replaced by the Mac's
                if tests.get('result') and not tests.get('reported'):
                    remote(['tests', '--id', request['id'], '--result', tests['result'], '--key', request['testsKey']], timeout=45)
                    tests['reported'] = True; save(directory / 'tests.json', tests)
                result = remote(['status', '--id', request['id']], timeout=45)
                current = json.loads(result.stdout)
                # A transfer acknowledgement is not an installation success.
                if current: save(directory / 'state.json', current)
            except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
                attempts = state.get('transportAttempts', 0) + 1
                detail = getattr(error, 'stderr', None) or str(error)
                if isinstance(detail, bytes): detail = detail.decode(errors='replace')   # TimeoutExpired ignores text=True
                detail = detail.strip()[-400:]
                busy = isinstance(error, subprocess.CalledProcessError) and error.returncode == 75
                if 'Incomplete or changed source upload' in detail: state['checksumTransfer'] = True
                update(directory / 'state.json', state.get('phase', 'queued'), transportAttempts=attempts,
                       checksumTransfer=state.get('checksumTransfer', False),
                       transportError=detail, message='Waiting for Mac transfer: ' + detail,
                       transportNextAttempt=time.time() + (15 if busy else min(300, 10 * 2 ** min(5, attempts - 1))))


def show(job_id=None, follow=False, as_json=False):
    directories = [STORE / 'jobs' / identity(job_id)] if job_id else sorted((STORE / 'jobs').glob('*'))[-20:]
    while True:
        values = []
        for path in directories:
            value = load(path / 'state.json', {'id': path.name, 'phase': 'unknown'})
            if load(path / 'request.json', {}).get('testsRequired') and value.get('phase') not in TERMINAL - {'failed'}:
                tests = load(path / 'tests.json', {})
                if not tests.get('result'): value['message'] = (value.get('message', '') + ' · PC tests running').lstrip(' ·')
                elif tests['result'] == 'failed': value['message'] = value.get('message', '') + ' · PC test log: ' + tests.get('log', '')
            # Published is not installed: an away delivery names the page the owner installs it from.
            if install_note(value): value.update(installed=False, installUrl=OTA_PAGE, action=install_note(value))
            values.append(value)
        if as_json: print(json.dumps(values[0] if job_id else values, indent=2), flush=True)
        else:
            for value in values:
                print(value.get('id', ''), value.get('repo', ''), value.get('app', ''), value.get('phase'), value.get('message', ''), flush=True)
                if value.get('action'): print('  ' + value['action'], flush=True)
        if not follow: return
        if all(value.get('phase') in TERMINAL or value.get('phase') in {'awaiting_ota', 'awaiting_watch'} for value in values):
            if any(value.get('phase') == 'failed' for value in values): raise SystemExit(1)
            if any(value.get('phase') in {'awaiting_ota', 'awaiting_watch'} for value in values): raise SystemExit(10)
            return
        time.sleep(5)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='status', help='app, project:app, list, status, logs, cache, or pump')
    parser.add_argument('job', nargs='?')
    parser.add_argument('--project'); parser.add_argument('--source')
    parser.add_argument('--follow', action='store_true'); parser.add_argument('--json', action='store_true')
    parser.add_argument('--validate-only', action='store_true'); parser.add_argument('--force', action='store_true')
    parser.add_argument('--skip-tests', action='store_true', help="don't run the project's PC tests first")
    args = parser.parse_args()
    if args.action == 'pump':
        try: pump()
        except BlockingIOError: pass
    elif args.action == 'test-job': test_job(args.job)
    elif args.action == 'status': show(args.job, args.follow, args.json)
    elif args.action == 'logs':
        if ON_MAC:
            import worker
            metadata, _ = worker.paths(identity(args.job))
            for name in ['build.log', 'install.log', 'watch-install.log', 'watch-companion-install.log', 'watch-companion-after.log']:
                path = metadata / name
                if path.exists(): print(path.read_text(errors='replace')[-16000:])
        else:
            result = remote(['logs', '--id', identity(args.job)], timeout=30)
            print(result.stdout, end='')
    elif args.action in {'cancel', 'retry', 'ota'}:
        job_id = identity(args.job)
        if ON_MAC:
            import worker
            worker.control(job_id, args.action)
        else:
            state = load(STORE / 'jobs' / job_id / 'state.json', {})
            if args.action == 'cancel' and not state.get('uploadComplete'):
                update(STORE / 'jobs' / job_id / 'state.json', 'cancelled')
            remote([args.action, '--id', job_id])
            current = json.loads(remote(['status', '--id', job_id]).stdout)
            if current: save(STORE / 'jobs' / job_id / 'state.json', current)
    elif args.action == 'cache':
        if ON_MAC:
            import worker
            data = worker.cache_health.status(worker.STORE)
        else: data = json.loads(remote(['cache-status'], timeout=30).stdout)
        if args.json: print(json.dumps(data, indent=2))
        else:
            for row in data['apps']:
                modules = row.get('modules', {})
                scheduled = sum(value['scheduled'] for value in modules.values())
                detail = ('verified artifact reused' if row.get('artifactReused') else
                          str(scheduled)+' modules scheduled; '+str(len(modules)-scheduled)+' skipped')
                if row['cacheableTasks']:
                    detail += '; '+str(row['hits'])+'/'+str(row['cacheableTasks'])+' task hits'
                misses = sum(value['misses'] for value in modules.values())
                if misses: detail += '; '+str(misses)+' cache misses'
                print(row['repo']+':'+row['app'], row['health'], str(round(row['compileSeconds'], 1))+'s',
                      detail, '; '.join(row['warnings']))
    elif args.action == 'list':
        for name, project in projects().items():
            try:
                listing = declaration(project)
                print(name + ': ' + ', '.join(app['name'] for app in listing['apps']))
            except (OSError, subprocess.SubprocessError): continue
    else:
        job_id = enqueue(args.action, args.project, args.source, args.validate_only, args.force, args.skip_tests)
        print('Queued ' + job_id + '; source is frozen. ios-push status ' + job_id, flush=True)
        if args.follow: show(job_id, True, args.json)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: raise SystemExit(str(error))
