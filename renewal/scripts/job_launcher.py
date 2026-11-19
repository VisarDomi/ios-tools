"""Named programs for this repository's launchd jobs.

System Settings > General > Login Items lists a LaunchAgent under the file name of
the program it starts. Jobs that started /usr/bin/python3 directly therefore all
showed up as "python3 - Item from unidentified developer": a dozen identical rows
that look like spam and cannot be told apart. Each job now starts a tiny launcher
named after the job (for example "manga-reader renewal") that execs python3 with
the job's arguments. The running process is still /usr/bin/python3 with the same
command line, so process-based checks (mac-workload) are unaffected.
"""
import os
import tempfile
from pathlib import Path

LAUNCHERS = Path.home() / 'Library/Application Support/ios-tools/launchers'
PYTHON = '/usr/bin/python3'


def body(python=PYTHON):
    return ('#!/bin/sh\n'
            '# launchd job program, named so System Settings > Login Items shows the job.\n'
            'exec ' + python + ' "$@"\n').encode()


def python_launcher(name, directory=LAUNCHERS, python=PYTHON):
    """Path of an executable called NAME that runs python with its arguments; created or repaired as needed."""
    if not name.strip() or '/' in name or name.startswith('.'):
        raise ValueError('launcher name must be a plain file name: %r' % name)
    path = Path(directory) / name
    data = body(python)
    if path.is_file() and path.read_bytes() == data and os.access(path, os.X_OK):
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.launcher-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        os.chmod(temporary, 0o755)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return str(path)


def renewal_name(repo):
    return repo + ' renewal'
