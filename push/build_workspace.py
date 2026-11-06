"""Regenerable, stable compiler paths; frozen checkpoints remain the authority."""
from pathlib import Path
import os
import shutil
import tempfile
from common import digest, ensure_directory, relative

GENERATED = {'build', '.build', '.swiftpm', 'xcuserdata', '__pycache__'}


def prepare(source, files, destination):
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
    return destination


def trim(source, current_app, maximum=2 << 30):
    """Bound regenerable compiler data; never remove sources or signed checkpoints."""
    source = Path(source)
    derived = source / 'build/DerivedData'
    if not derived.is_dir() or derived.is_symlink(): return
    def size():
        total = 0
        for folder, directories, files in os.walk(source, followlinks=False):
            directories[:] = [name for name in directories if not (Path(folder) / name).is_symlink()]
            for name in files:
                try: total += (Path(folder) / name).lstat().st_size
                except FileNotFoundError: pass
        return total
    if size() <= maximum: return
    candidates = sorted((p for p in derived.iterdir() if p.is_dir() and not p.is_symlink()),
                        key=lambda p: (p.name == current_app, p.stat().st_mtime))
    for path in candidates:
        shutil.rmtree(path)
        if size() <= maximum: break
