import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { root, readers, verifyStaged } from './suite.mjs';

const command = process.argv[2];
if (!['sync', 'build', 'status', 'check', 'install', 'finish'].includes(command)) throw new Error('Use npm run mac -- sync|build|status|check|install|finish');
const config = JSON.parse(readFileSync(resolve(root, 'deploy.local.json'), 'utf8'));
const { host, knownHosts, remoteRoot, guiUid, signingTeam, device } = config;
const hostBundleId = config.hostBundleId ?? "com.visar.galleryreader.extensiontest";
if (!/^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/.test(hostBundleId)) throw new Error("Invalid hostBundleId");
if (!/^[\w.-]+@[\w.-]+$/.test(host) || !/^\/Users\/[^/]+\/Developer\/reader-extensions$/.test(remoteRoot)
    || !Number.isSafeInteger(guiUid) || !/^[A-Z0-9]+$/.test(signingTeam)) throw new Error('Invalid deployment configuration');
const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
const sshArgs = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=yes', '-o', `UserKnownHostsFile=${knownHosts}`];
const ssh = script => execFileSync('ssh', [...sshArgs, host, script], { stdio: 'inherit' });
const label = 'com.visar.reader-extensions-build';
const plist = `${remoteRoot}/dist/deploy/build.plist`;
const app = `${remoteRoot}/build/Debug-iphoneos/Reader Extensions.app`;
if (command === 'sync') {
    verifyStaged();
    const xml = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
    mkdirSync(resolve(root, 'dist/deploy'), { recursive: true });
    writeFileSync(resolve(root, 'dist/deploy/build.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>/bin/bash</string><string>${xml(remoteRoot)}/scripts/build-on-mac.sh</string></array>
<key>EnvironmentVariables</key><dict><key>SIGNING_TEAM</key><string>${xml(signingTeam)}</string><key>READER_HOST_BUNDLE_ID</key><string>${xml(hostBundleId)}</string><key>SIGNING_DEVICE</key><string>${config.registerDevice ? xml(device) : ''}</string></dict>
<key>RunAtLoad</key><true/>
<key>StandardOutPath</key><string>${xml(remoteRoot)}/gui-build.log</string>
<key>StandardErrorPath</key><string>${xml(remoteRoot)}/gui-build.log</string>
</dict></plist>\n`);
    ssh(`mkdir -p ${quote(remoteRoot)}/scripts`);
    execFileSync('rsync', ['-a', '--exclude=xcuserdata', '-e', ['ssh', ...sshArgs].map(quote).join(' '),
        resolve(root, 'apple'), resolve(root, 'dist'), `${host}:${remoteRoot}/`], { stdio: 'inherit' });
    execFileSync('rsync', ['-a', '-e', ['ssh', ...sshArgs].map(quote).join(' '),
        resolve(root, 'scripts/build-on-mac.sh'), resolve(root, 'scripts/verify-provisioning.py'), `${host}:${remoteRoot}/scripts/`], { stdio: 'inherit' });
} else if (command === 'build') {
    ssh(`launchctl bootstrap gui/${guiUid} ${quote(plist)}`);
} else if (command === 'status') {
    ssh(`launchctl list ${quote(label)}; tail -25 ${quote(remoteRoot + '/gui-build.log')}`);
} else if (command === 'finish') {
    ssh(`launchctl bootout gui/${guiUid}/${label}`);
} else {
    if (command === 'install' && !/^[A-Fa-f0-9-]+$/.test(device)) throw new Error('Set device UDID in deploy.local.json');
    const hashes = verifyStaged();
    // Refuse a stale/different build: every embedded bundle must match staging.
    const checks = Object.entries(readers).flatMap(([name, reader]) => Object.entries(hashes[name]).map(([file, hash]) =>
        `test "$(shasum -a 256 ${quote(`${app}/PlugIns/${reader.product}/${file}`)} | cut -d ' ' -f 1)" = ${quote(hash)}`));
    ssh(['set -eu', `test "$(/usr/libexec/PlistBuddy -c "Print CFBundleIdentifier" ${quote(app + "/Info.plist")})" = ${quote(hostBundleId)}`, ...checks, `codesign --verify --deep --strict ${quote(app)}`,
        `python3 ${quote(remoteRoot + '/scripts/verify-provisioning.py')} ${quote(app)} ${quote(signingTeam)} ${quote(device)} ${quote(hostBundleId)}`,
        ...(command === 'install' ? [`xcrun devicectl device install app --device ${quote(device)} ${quote(app)}`] : []),
    ].join('\n'));
    console.log(command === 'install' ? 'Matching signed app installed.' : 'All embedded web files match staging; complete app signature verified. No installation performed.');
}
