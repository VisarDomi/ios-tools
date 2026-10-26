"""Use installed Apple component CLIs without Xcode's strict-version installer stubs.

Xcode 26.3's stubs expect CoreDevice506.7/CoreSimulator1051.17.8. Apple's
installed hotfixes can be newer; invoking the stubs repeatedly runs first-launch
setup although the tools are already installed. These are the same exec targets
as the Apple stubs. This module never installs, downgrades or edits Apple code.
"""
from pathlib import Path
import os
import plistlib

FRAMEWORKS = Path('/Library/Developer/PrivateFrameworks')
COMPONENTS = {'devicectl':'CoreDevice', 'simctl':'CoreSimulator'}
MACHO = {b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca',
         b'\xca\xfe\xba\xbf',b'\xbf\xba\xfe\xca'}


def tool_path(name):
    if name not in COMPONENTS:
        raise ValueError('Unsupported Apple component tool: '+name)
    path=FRAMEWORKS/(COMPONENTS[name]+'.framework/Versions/A/Resources/bin')/name
    if not path.is_file() or not os.access(path,os.X_OK):
        raise RuntimeError('Apple component CLI is missing: %s. Initialize Xcode once with no active workload.'%path)
    with path.open('rb') as f:
        if f.read(4) not in MACHO:
            raise RuntimeError('Expected the installed Mach-O CLI, not an installer script: '+str(path))
    return str(path)


def status():
    result={}
    for name,component in COMPONENTS.items():
        resources=FRAMEWORKS/(component+'.framework/Versions/A/Resources')
        try:
            info=plistlib.loads((resources/'Info.plist').read_bytes())
            result[name]=dict(path=tool_path(name),version=info.get('CFBundleVersion'),
                              minimumOS=info.get('LSMinimumSystemVersion'))
        except (OSError,RuntimeError,ValueError) as error:
            result[name]=dict(error=str(error))
    return result
