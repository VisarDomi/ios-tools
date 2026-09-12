#!/usr/bin/env python3
"""Check the signed iOS host and extension profiles before physical installation."""
import argparse
import datetime
import fnmatch
import pathlib
import plistlib
import subprocess


def verify(app, team, device, host_id):
    bundles = [app, *sorted((app / 'PlugIns').glob('*.appex'))]
    for bundle in bundles:
        info = plistlib.loads((bundle / 'Info.plist').read_bytes())
        identifier = info['CFBundleIdentifier']
        if identifier != host_id and not identifier.startswith(host_id + '.'):
            raise ValueError('Unexpected bundle identity: ' + identifier)
        profile = plistlib.loads(subprocess.check_output([
            'security', 'cms', '-D', '-i', str(bundle / 'embedded.mobileprovision')]))
        if profile.get('TeamIdentifier') != [team]:
            raise ValueError('Wrong signing team: ' + identifier)
        if device not in profile.get('ProvisionedDevices', []):
            raise ValueError('This iPhone is not included in the provisioning profile: ' + identifier)
        if profile['ExpirationDate'] <= datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None):
            raise ValueError('Expired provisioning profile: ' + identifier)
        entitlement = profile['Entitlements']['application-identifier']
        if not fnmatch.fnmatchcase(team + '.' + identifier, entitlement):
            raise ValueError('Profile does not permit this bundle identity: ' + identifier)
        print(identifier + ': team/device/profile verified; expires ' + profile['ExpirationDate'].isoformat() + 'Z')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=pathlib.Path)
    parser.add_argument('team')
    parser.add_argument('device')
    parser.add_argument('host_id')
    args = parser.parse_args()
    try:
        verify(args.app, args.team, args.device, args.host_id)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, str(error) + '\n')
