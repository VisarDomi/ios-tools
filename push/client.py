"""One-line PC submission and durable asynchronous upload/status collection."""
from __future__ import annotations
import argparse
import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

from common import TERMINAL, ensure_directory, identity, load, locked, save, source_hash, update, verify
from snapshot import capture

TOOLS = Path(__file__).resolve().parents[1]
ON_MAC = sys.platform == 'darwin'
STORE = Path(os.environ.get('IOS_PUSH_STORE', Path.home() / ('Library/Application Support/ios-tools/push' if ON_MAC else '.local/share/ios-tools/push')))
REMOTE = '/Users/visar/Library/Application Support/ios-tools/push'
RUNNER = '/Users/visar/Developer/ios-tools/push/worker.py'
LABEL = 'com.visar.ios-push'


def projects():
    result = load(TOOLS / 'push/projects.json')
    base = Path(os.environ.get('IOS_PUSH_WORKSPACE', Path.home() / ('Developer' if ON_MAC else 'Documents/work')))
    for name, item in result.items(): item['root'] = str(base / (name if ON_MAC else item['path']))
    return result


def declaration(project):
    script = Path(project['root']) / 'apps/ios/scripts/renewal.py'
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
            if (candidate / 'apps/ios/scripts/renewal.py').exists():
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


def enqueue(selector, project_name=None, source=None, validate_only=False, force=False):
    repo, project, app = choose(selector, project_name, source)
    prepare(project, app)
    repo_root = Path(project['root']).resolve(); root = Path(app['root']).resolve()
    suffix = root.relative_to(repo_root)
    overlays = {}
    for src, dst in project.get('copies', {}).items():
        target = Path(dst)
        if target.is_relative_to(suffix): overlays[str(target.relative_to(suffix))] = repo_root / src
    job_id = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:10]
    directory = STORE / 'jobs' / job_id
    ensure_directory(directory)
    captured = Path.home() / 'Developer/ios-push/checkpoints' / job_id / 'source' if ON_MAC else directory / 'source'
    try:
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
                   'validateOnly': validate_only, 'force': force, 'neverLaunch': True}
        update(directory / 'state.json', 'queued', id=job_id, repo=repo, app=app['name'], createdAt=request['createdAt'])
        save(directory / 'request.json', request)  # Publish last; uploader cannot race the initial state.
    except BaseException:
        import shutil
        shutil.rmtree(directory, ignore_errors=True)
        if ON_MAC: shutil.rmtree(captured.parent, ignore_errors=True)
        raise
    if ON_MAC:
        import worker
        worker.ready(job_id)
        subprocess.run(['launchctl', 'kickstart', 'gui/' + str(os.getuid()) + '/' + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        started = subprocess.run(['systemctl', '--user', 'start', '--no-block', 'ios-push.service'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if started.returncode: raise RuntimeError('Job ' + job_id + ' is saved; install the shared ios-push worker before delivery')
    return job_id


def remote(arguments, timeout=90, check=True):
    command = shlex.join(['/usr/bin/python3', RUNNER, *arguments])
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', 'mac', command], capture_output=True, text=True, timeout=timeout, check=check)


def transfer(directory):
    request = load(directory / 'request.json'); job_id = identity(request['id'])
    verify(directory / 'source', request['files'])
    target = json.loads(remote(['receive', '--id', job_id, '--repo', request['repo'], '--app', request['app']]).stdout)
    if target.get('ready'): return
    args = ['rsync', '-az', '--delete', '--checksum', '-e', 'ssh -o BatchMode=yes', str(directory / 'source') + '/',
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
            if not request or state.get('transportNextAttempt', 0) > time.time(): continue
            try:
                if not state.get('uploadComplete'):
                    update(directory / 'state.json', 'uploading')
                    transfer(directory)
                    update(directory / 'state.json', 'submitted', uploadComplete=True)
                result = remote(['status', '--id', request['id']], timeout=45)
                current = json.loads(result.stdout)
                # A transfer acknowledgement is not an installation success.
                if current: save(directory / 'state.json', current)
            except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
                attempts = state.get('transportAttempts', 0) + 1
                detail = (getattr(error, 'stderr', None) or str(error)).strip()[-400:]
                update(directory / 'state.json', state.get('phase', 'queued'), transportAttempts=attempts,
                       transportError=detail, message='Waiting for Mac transfer: ' + detail,
                       transportNextAttempt=time.time() + min(300, 10 * 2 ** min(5, attempts - 1)))


def show(job_id=None, follow=False, as_json=False):
    directories = [STORE / 'jobs' / identity(job_id)] if job_id else sorted((STORE / 'jobs').glob('*'))[-20:]
    while True:
        values = [load(path / 'state.json', {'id': path.name, 'phase': 'unknown'}) for path in directories]
        if as_json: print(json.dumps(values[0] if job_id else values, indent=2), flush=True)
        else:
            for value in values: print(value.get('id', ''), value.get('repo', ''), value.get('app', ''), value.get('phase'), value.get('message', ''), flush=True)
        if not follow: return
        if all(value.get('phase') in TERMINAL or value.get('phase') == 'awaiting_ota' for value in values):
            if any(value.get('phase') == 'failed' for value in values): raise SystemExit(1)
            if any(value.get('phase') == 'awaiting_ota' for value in values): raise SystemExit(10)
            return
        time.sleep(5)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='status', help='app, project:app, list, status, logs, or pump')
    parser.add_argument('job', nargs='?')
    parser.add_argument('--project'); parser.add_argument('--source')
    parser.add_argument('--follow', action='store_true'); parser.add_argument('--json', action='store_true')
    parser.add_argument('--validate-only', action='store_true'); parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    if args.action == 'pump':
        try: pump()
        except BlockingIOError: pass
    elif args.action == 'status': show(args.job, args.follow, args.json)
    elif args.action == 'logs':
        if ON_MAC:
            import worker
            metadata, _ = worker.paths(identity(args.job))
            for name in ['build.log', 'install.log']:
                path = metadata / name
                if path.exists(): print(path.read_text(errors='replace')[-16000:])
        else:
            result = remote(['logs', '--id', identity(args.job)], timeout=30)
            print(result.stdout, end='')
    elif args.action in {'cancel', 'retry'}:
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
    elif args.action == 'list':
        for name, project in projects().items():
            try:
                listing = declaration(project)
                print(name + ': ' + ', '.join(app['name'] for app in listing['apps']))
            except (OSError, subprocess.SubprocessError): continue
    else:
        job_id = enqueue(args.action, args.project, args.source, args.validate_only, args.force)
        print('Queued ' + job_id + '; source is frozen. ios-push status ' + job_id, flush=True)
        if args.follow: show(job_id, True, args.json)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error: raise SystemExit(str(error))
