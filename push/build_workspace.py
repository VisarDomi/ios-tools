"""Regenerable, stable compiler paths; frozen checkpoints remain the authority."""
from pathlib import Path
import os
import shutil
import tempfile
from common import digest, ensure_directory, relative

GENERATED = {'build', '.build', '.swiftpm', 'xcuserdata', '__pycache__'}


def cache_path(name):
    part = relative(name)
    if part.parts[0] != 'build' and part.parts[:3] != ('apps', 'ios', 'build'):
        raise ValueError('Compiler cache must be under generated build/')
    return part


def policy(project, app):
    """Resolve opt-in compiler retention.

    True: one workspace for all of the project's apps (generated DerivedData under build/DerivedData).
    A dict: `apps` get their own per-app workspace; `shared.apps` build in one workspace, for
    providers that compile the same target (identical compiler inputs at one stable path).
    Dict entries name their generated cache roots explicitly."""
    value = project.get('persistentBuildCache')
    if not value: return None
    if value is True:
        return {'perApp': False, 'maximumBytes': 2 << 30, 'cacheRoots': None}
    if not isinstance(value, dict): raise ValueError('Invalid persistent compiler-cache policy')
    shared = value.get('shared')
    if shared is not None and not isinstance(shared, dict): raise ValueError('Invalid shared compiler-cache policy')
    if shared and app in shared.get('apps', []):
        if app in value.get('apps', []): raise ValueError('An app cannot use both a shared and its own compiler workspace')
        return {'perApp': False, **bounds(shared)}
    if app not in value.get('apps', []): return None
    return {'perApp': True, **bounds(value)}


def bounds(value):
    maximum = value.get('maximumBytes', 2 << 30)
    if not isinstance(maximum, int) or maximum <= 0: raise ValueError('Invalid compiler-cache budget')
    roots = value.get('cacheRoots')
    if not roots: raise ValueError('Compiler-cache roots must be explicit')
    for name in roots:
        cache_path(name)
    return {'maximumBytes': maximum, 'cacheRoots': roots}


def prepare(source, files, destination, input_directories=()):
    source, destination = Path(source), Path(destination)
    ensure_directory(destination)
    if destination.is_symlink(): raise RuntimeError('Build workspace cannot be a symlink')
    names = set(files)
    # An interrupted copy/build can leave extra files. Reconcile only this private
    # disposable workspace, retaining generated compiler directories.
    for folder, directories, entries in os.walk(destination, topdown=True, followlinks=False):
        base = Path(folder)
        for name in list(directories):
            path = base / name
            if path.is_symlink():
                path.unlink(); directories.remove(name)
            elif name in GENERATED:
                directories.remove(name)
        for name in entries:
            path = base / name
            if str(path.relative_to(destination)) not in names: path.unlink()
    for name, expected in files.items():
        part = relative(name)
        target = destination / part
        if target.is_file() and not target.is_symlink() and digest(target) == expected:
            continue  # Preserve unchanged source timestamps for Xcode's build database.
        if target.is_symlink(): target.unlink()
        if target.is_dir(): shutil.rmtree(target)
        ensure_directory(target.parent)
        descriptor, temporary = tempfile.mkstemp(prefix='.source-', dir=target.parent)
        os.close(descriptor)
        try:
            shutil.copyfile(source / part, temporary)
            shutil.copymode(source / part, temporary)
            if digest(temporary) != expected: raise RuntimeError('Source changed during workspace preparation: ' + name)
            # Keep a fresh timestamp for changed bytes, even if the captured file
            # carries its previous timestamp. This invalidates incremental tasks.
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    for name in input_directories:
        ensure_directory(destination / relative(name))
    return destination


def trim(source, current_app, maximum=2 << 30, cache_roots=None):
    """Bound generated compiler data only; sources and frozen artifacts are excluded."""
    source = Path(source)
    if cache_roots is None:
        derived = source / 'build/DerivedData'
        candidates = list(derived.iterdir()) if derived.is_dir() and not derived.is_symlink() else []
        candidates = sorted((p for p in candidates if p.is_dir() and not p.is_symlink()),
                            key=lambda p: (p.name == current_app, p.stat().st_mtime))
    else:
        candidates = []
        for name in cache_roots:
            part = cache_path(name)
            path = source / part
            if not path.resolve().is_relative_to(source.resolve()): raise ValueError('Compiler cache leaves its workspace')
            if path.is_dir() and not path.is_symlink(): candidates.append(path)
    def size():
        total = 0
        for candidate in candidates:
            if not candidate.exists(): continue
            for folder, directories, files in os.walk(candidate, followlinks=False):
                directories[:] = [name for name in directories if not (Path(folder) / name).is_symlink()]
                for name in files:
                    try: total += (Path(folder) / name).lstat().st_size
                    except FileNotFoundError: pass
        return total
    removed = []
    for path in candidates:
        if size() <= maximum: break
        shutil.rmtree(path); removed.append(str(path.relative_to(source)))
    return removed
