"""Bounded evidence collection. A console flag is not an authentication diagnosis."""
import datetime
import json
import os
from pathlib import Path
import plistlib
import subprocess
import time


def command(argv, timeout=8):
    started = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
        return dict(ok=p.returncode == 0, exitCode=p.returncode,
                    stdout=p.stdout.decode('utf8', 'replace').strip(),
                    stderr=p.stderr.decode('utf8', 'replace').strip(),
                    seconds=round(time.monotonic()-started, 3))
    except (OSError, subprocess.TimeoutExpired) as error:
        return dict(ok=False, error=str(error), seconds=round(time.monotonic()-started, 3))


def console_sessions(data):
    root = plistlib.loads(data)
    users = root[0].get('IOConsoleUsers', [])
    return [dict(user=row.get('kCGSSessionUserNameKey'), uid=row.get('kCGSSessionUserIDKey'),
                 onConsole=row.get('kCGSSessionOnConsoleKey'), loginDone=row.get('kCGSessionLoginDoneKey'),
                 screenShieldFlag=row.get('CGSSessionScreenIsLocked'),
                 authenticationRequired=None) for row in users]


def crash_summary(path):
    with path.open() as stream:
        header = json.loads(stream.readline())
        report = json.load(stream)
    return dict(file=str(path), process=report.get('procName', header.get('app_name')),
                captured=report.get('captureTime', header.get('timestamp')),
                launched=report.get('procLaunch'), parent=report.get('parentProc'),
                coalition=report.get('coalitionName'), exception=report.get('exception'),
                termination=report.get('termination'))


def ui_blockers(rows):
    found = []
    for row in rows:
        for window in row.get('windows', []):
            text = ' '.join(str(x) for x in [window.get('name', ''), *(window.get('texts') or [])])
            dialog = 'AXDialog' in (window.get('role'), window.get('subrole')) or bool(window.get('sheets'))
            if dialog or 'quit unexpectedly' in text.lower():
                found.append(dict(process=row['process'], window=window))
    return found


UI_SCRIPT = '''const se=Application("System Events");
const names=["CoreServicesUIAgent","ReportCrash","Problem Reporter","Xcode","Simulator","loginwindow"];
JSON.stringify(names.map(n=>{try {const p=se.processes.byName(n);return p.exists()?{
process:n,frontmost:p.frontmost(),windows:p.windows().slice(0,8).map(w=>({
name:w.name(),role:w.role(),subrole:w.subrole(),buttons:w.buttons.name(),
texts:w.staticTexts.value(),sheets:w.sheets().map(s=>({name:s.name(),buttons:s.buttons.name()}))
}))}:{process:n,exists:false};}catch(e){return {process:n,error:String(e)}}}));'''


def collect(ui=False):
    result = dict(version=1, collectedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  hostCommandResponded=True, conclusions=[], unknowns=[
                      'Network reachability requires the caller’s authenticated transport check.',
                      'A session screen flag alone cannot establish a password lock or its cause.'])
    queries = dict(power=['/usr/bin/pmset', '-g', 'custom'],
                   network=['/usr/sbin/scutil', '--nwi'],
                   uptime=['/usr/bin/uptime'],
                   crashDialogPreference=['/usr/bin/defaults', 'read', 'com.apple.CrashReporter', 'DialogType'])
    for name, argv in queries.items(): result[name] = command(argv)
    raw = command(['/usr/sbin/ioreg', '-a', '-n', 'Root', '-d', '1'])
    try:
        result['consoleSessions'] = console_sessions(raw['stdout'].encode()) if raw['ok'] else None
    except (ValueError, KeyError, IndexError, plistlib.InvalidFileException) as error:
        result['consoleSessions'] = None; raw['error'] = str(error)
    if result['consoleSessions'] is None: result['consoleProbeError'] = raw.get('error', raw.get('stderr'))
    lease = Path.home()/'Library/Caches/ios-app-refresh/workload-current.json'
    try: result['workloadLease'] = json.loads(lease.read_text())
    except FileNotFoundError: result['workloadLease'] = None
    except (OSError, ValueError) as error: result['workloadLeaseError'] = str(error)
    result['crashes'] = []
    roots = [Path.home()/'Library/Logs/DiagnosticReports', Path('/Library/Logs/DiagnosticReports')]
    for root in roots:
        try: paths = sorted(root.glob('*.ips'), key=lambda p:p.stat().st_mtime, reverse=True)[:12]
        except OSError as error: result['unknowns'].append(str(error)); continue
        for path in paths:
            try: result['crashes'].append(crash_summary(path))
            except (OSError, ValueError) as error:
                result['crashes'].append(dict(file=str(path), readError=str(error)))
    if ui:
        probe = command(['/usr/bin/osascript', '-l', 'JavaScript', '-e', UI_SCRIPT], timeout=12)
        result['ui'] = probe
        if probe['ok']:
            try:
                rows = json.loads(probe.pop('stdout')); probe['processes'] = rows
                probe['blockers'] = ui_blockers(rows)
                probe['complete'] = not any('error' in row for row in rows)
            except ValueError as error: probe['complete'] = False; probe['parseError'] = str(error)
        else: probe['complete'] = False
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def crash_dialogs(mode, receipt):
    previous = command(['/usr/bin/defaults', 'read', 'com.apple.CrashReporter', 'DialogType'])
    if mode == 'status': return previous
    if not previous['ok'] and 'does not exist' not in previous.get('stderr',''):
        raise RuntimeError('Cannot establish the prior crash-dialog preference: '+str(previous))
    if mode == 'noninteractive':
        if not receipt.exists():
            atomic_json(receipt, dict(previous=previous['stdout'] if previous['ok'] else None))
        args = ['/usr/bin/defaults', 'write', 'com.apple.CrashReporter', 'DialogType', '-string', 'none']
    else:
        value = json.loads(receipt.read_text())['previous']
        args = (['/usr/bin/defaults', 'delete', 'com.apple.CrashReporter', 'DialogType'] if value is None else
                ['/usr/bin/defaults', 'write', 'com.apple.CrashReporter', 'DialogType', '-string', value])
    applied = command(args)
    if not applied['ok']: raise RuntimeError(applied)
    observed = command(['/usr/bin/defaults', 'read', 'com.apple.CrashReporter', 'DialogType'])
    expected = 'none' if mode == 'noninteractive' else value
    if (observed['stdout'] if observed['ok'] else None) != expected:
        raise RuntimeError('Crash dialog preference readback failed')
    return dict(mode=mode, observed=observed, rollback=str(receipt),
                crashCaptureDisabled=False, existingDialogsDismissed=False)
