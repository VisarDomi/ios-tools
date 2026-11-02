"""Freeze the declared build inputs before the caller continues editing."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from common import ensure_directory, relative, sync_directory


def stamp(path):
    stat = Path(path).stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def capture(root, destination, inputs, extras=(), overlays=None, allow_missing=()):
    root = Path(root).resolve(); destination = Path(destination)
    ensure_directory(destination.parent)
    destination.mkdir(exist_ok=False, mode=0o700); sync_directory(destination.parent)
    files = {}; observed = {}; directories = {}; missing = []

    def copy(source, target, ancestors=()):
        source = Path(source)
        if not source.exists(): raise FileNotFoundError(source)
        resolved = source.resolve()
        if resolved in ancestors: raise ValueError('Recursive source link')
        if resolved.is_dir():
            names = sorted(p.name for p in resolved.iterdir() if p.name not in {'__pycache__', '.DS_Store', '.git', '.build', '.swiftpm'})
            directories[str(resolved)] = names
            ensure_directory(target)
            for name in names: copy(resolved / name, target / name, (*ancestors, resolved))
            descriptor = os.open(target, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
            return
        if not resolved.is_file(): raise ValueError('Unsupported source entry: ' + str(source))
        before = stamp(resolved); ensure_directory(target.parent)
        value = hashlib.sha256()
        cloned = sys.platform == 'darwin' and subprocess.run(['/bin/cp', '-c', str(resolved), str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        with resolved.open('rb') as source_stream:
            if cloned:
                while True:
                    block = source_stream.read(1024 * 1024)
                    if not block: break
                    value.update(block)
                with target.open('rb') as output: os.fsync(output.fileno())
            else:
                with target.open('wb') as output:
                    while True:
                        block = source_stream.read(1024 * 1024)
                        if not block: break
                        output.write(block); value.update(block)
                    output.flush(); os.fsync(output.fileno())
        shutil.copystat(resolved, target)
        if stamp(resolved) != before: raise RuntimeError('Source changed during capture: ' + str(source))
        observed[str(resolved)] = before
        files[str(target.relative_to(destination))] = value.hexdigest()

    try:
        selected = []
        overlays = {str(relative(key)): Path(value) for key, value in (overlays or {}).items()}
        for item in [*inputs, *extras]:
            item = str(relative(item))
            if any(Path(item).is_relative_to(Path(parent)) for parent in selected): continue
            selected = [parent for parent in selected if not Path(parent).is_relative_to(Path(item))]
            selected.append(item)
        for item in selected:
            source = overlays.get(item, root / item)
            if not source.exists():
                if item in allow_missing: missing.append(item); continue
                raise FileNotFoundError('Prepare this build input before pushing: ' + str(source))
            copy(source, destination / item)
        for item, source in overlays.items():
            target = destination / item
            if target.exists():
                if target.is_dir(): shutil.rmtree(target)
                else: target.unlink()
                files = {name: value for name, value in files.items() if not Path(name).is_relative_to(Path(item))}
            copy(source, destination / item)
        for name, before in observed.items():
            if stamp(name) != before: raise RuntimeError('Source changed during capture; enqueue again: ' + name)
        for name, names in directories.items():
            after = sorted(p.name for p in Path(name).iterdir() if p.name not in {'__pycache__', '.DS_Store', '.git', '.build', '.swiftpm'})
            if after != names: raise RuntimeError('Source directory changed during capture; enqueue again: ' + name)
        descriptor = os.open(destination, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
        return files, missing
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
