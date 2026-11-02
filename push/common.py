"""Private, durable queue records shared by the PC client and the Mac runner."""
from __future__ import annotations
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

TERMINAL = {'installed', 'failed', 'cancelled', 'superseded', 'validated'}
IDENTITY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$')


def identity(value):
    if not IDENTITY.fullmatch(str(value)):
        raise ValueError('Invalid queue identity')
    return str(value)


def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def ensure_directory(path):
    path = Path(path)
    if path.exists(): return
    missing = []; current = path
    while not current.exists(): missing.append(current); current = current.parent
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    for created in missing: sync_directory(created.parent)


def atomic_bytes(path, value):
    path = Path(path)
    ensure_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def save(path, value):
    atomic_bytes(path, (json.dumps(value, indent=2) + '\n').encode())


def relative(value):
    path = Path(value)
    if path.is_absolute() or not path.parts or any(part in {'.', '..'} for part in path.parts):
        raise ValueError('Expected a relative source path: ' + str(value))
    return path


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block: break
            result.update(block)
    return result.hexdigest()


def manifest(root):
    root = Path(root).resolve(); result = {}
    for folder, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in {'__pycache__', '.git', '.DS_Store'})
        for name in sorted(files):
            path = Path(folder) / name
            if name == '.DS_Store': continue
            if not path.resolve().is_relative_to(root):
                raise ValueError('Source link leaves its frozen checkpoint: ' + str(path.relative_to(root)))
            result[str(path.relative_to(root))] = digest(path)
        for name in list(directories):
            path = Path(folder) / name
            if path.is_symlink():
                raise ValueError('Directory links must be captured as directories: ' + str(path.relative_to(root)))
    return result


def verify(root, expected):
    actual = manifest(root)
    if actual != expected:
        raise RuntimeError('Frozen source checkpoint changed or upload is incomplete')


def source_hash(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@contextlib.contextmanager
def locked(path, wait=0):
    path = Path(path); ensure_directory(path.parent)
    with path.open('a') as stream:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise
                time.sleep(.1)
        yield stream


def update(path, phase, **fields):
    value = load(path, {})
    value.update(phase=phase, updatedAt=time.time(), **fields)
    save(path, value)
    return value
