#!/usr/bin/env python3
"""Install the requested durable upload timer and GUI build/install queue."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys
from common import atomic_bytes, ensure_directory, load, save, sync_directory

TOOLS = Path(__file__).resolve().parents[1]


def install_pc():
    home = Path.home(); units = home / '.config/systemd/user'; ensure_directory(units)
    scripts = home / '.local/bin'; ensure_directory(scripts)
    link = scripts / 'ios-push'
    if link.is_symlink():
        if link.resolve() != TOOLS / 'native/scripts/ios-push': raise RuntimeError('An unrelated ios-push command already exists')
        link.unlink()
    if link.exists(): raise RuntimeError('An unrelated ios-push command already exists')
    link.symlink_to(TOOLS / 'native/scripts/ios-push')
    service = f'''[Unit]
Description=Upload frozen iOS push jobs and collect their completion results

[Service]
Type=oneshot
ExecStart={sys.executable} {TOOLS}/native/scripts/ios-push pump
WorkingDirectory={TOOLS}
TimeoutStartSec=900
UMask=0077
'''
    timer = '''[Unit]
Description=Resume pending iOS pushes after login and network recovery

[Timer]
OnStartupSec=15
OnUnitInactiveSec=15
Unit=ios-push.service

[Install]
WantedBy=timers.target
'''
    atomic_bytes(units / 'ios-push.service', service.encode())
    atomic_bytes(units / 'ios-push.timer', timer.encode())
    sync_directory(scripts)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'ios-push.timer'], check=True)
    print('PC durable upload queue installed; command: ios-push <app>')


def install_mac():
    if sys.platform != 'darwin' or os.getuid() == 0: raise RuntimeError('Install the Mac worker as the logged-in GUI user')
    home = Path.home(); store = home / 'Library/Application Support/ios-tools/push'
    for path in [store / 'jobs', home / 'Developer/ios-push/checkpoints', home / 'Library/LaunchAgents', home / '.local/bin']:
        ensure_directory(path)
    link = home / '.local/bin/ios-push'
    if link.is_symlink():
        if link.resolve() != TOOLS / 'native/scripts/ios-push': raise RuntimeError('An unrelated ios-push command already exists')
        link.unlink()
    if link.exists(): raise RuntimeError('An unrelated ios-push command already exists')
    link.symlink_to(TOOLS / 'native/scripts/ios-push')
    global_link = Path('/usr/local/bin/ios-push'); expected = TOOLS / 'native/scripts/ios-push'
    if global_link.is_symlink():
        # Read as root: a link created under this installer's 077 umask hides its target from the user.
        target = subprocess.run(['sudo', '-n', 'readlink', str(global_link)], capture_output=True, text=True, check=True).stdout.strip()
        if Path(target) != expected and Path(target).resolve() != expected.resolve(): raise RuntimeError('An unrelated global ios-push command already exists')
        subprocess.run(['sudo', '-n', 'chmod', '-h', '755', str(global_link)], check=True)
    elif global_link.exists(): raise RuntimeError('An unrelated global ios-push command already exists')
    else: subprocess.run(['sudo', '-n', '/bin/sh', '-c', 'umask 022; exec ln -s "$1" "$2"', 'sh', str(expected), str(global_link)], check=True)
    label = 'com.visar.ios-push'; target = 'gui/' + str(os.getuid())
    plist = home / 'Library/LaunchAgents' / (label + '.plist')
    contents = dict(Label=label, ProgramArguments=['/usr/bin/python3', str(TOOLS / 'push/worker.py'), 'work'],
                    RunAtLoad=True, StartInterval=300, ProcessType='Background',
                    StandardOutPath=str(store / 'worker.log'), StandardErrorPath=str(store / 'worker-errors.log'))
    atomic_bytes(plist, plistlib.dumps(contents))
    loaded = subprocess.run(['launchctl', 'print', target + '/' + label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Never boot out a running queue or its compiler just to refresh its entry point.
    if loaded.returncode: subprocess.run(['launchctl', 'bootstrap', target, str(plist)], check=True)
    subprocess.run(['launchctl', 'print', target + '/' + label], stdout=subprocess.DEVNULL, check=True)
    print('Mac GUI build/install queue installed; pending jobs resume at login')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pc', action='store_true'); parser.add_argument('--mac', action='store_true')
    parser.add_argument('--deploy-mac', action='store_true')
    args = parser.parse_args()
    if args.deploy_mac:
        subprocess.run([str(TOOLS / 'mac-sync')], check=True)
        command = ['sudo', '-n', 'launchctl', 'asuser', '501', 'sudo', '-n', '-H', '-u', 'visar',
                   '/usr/bin/python3', '/Users/visar/Developer/ios-tools/push/install.py', '--mac']
        subprocess.run(['ssh', 'mac', shlex.join(command)], check=True)
    if args.mac: install_mac()
    if args.pc: install_pc()


if __name__ == '__main__': main()
