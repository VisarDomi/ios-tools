#!/usr/bin/env python3
"""Copies NativeKit (ios-tools/native/Kit) into an app repository as apps/ios/Kit.

Renewal fingerprints only files inside a repository, so each repository builds its own
copy; a changed copy is a changed renewal input, deployed and approved like any other.

  vendor-kit.py <repository> [<repository> ...]          copy (replacing the old copy)
  vendor-kit.py --check <repository> [<repository> ...]  exit 1 if a copy differs
"""
import filecmp
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / 'Kit'
IGNORE = shutil.ignore_patterns('.build', '.swiftpm', '*.xcworkspace', 'xcuserdata', '.DS_Store')


def files(root):
    skip = {'.build', '.swiftpm', 'xcuserdata'}
    return sorted(str(path.relative_to(root)) for path in root.rglob('*')
                  if path.is_file() and not skip.intersection(path.relative_to(root).parts) and path.name != '.DS_Store')


def differs(target):
    if not target.is_dir():
        return ['(missing)']
    ours, theirs = files(KIT), files(target)
    changed = sorted(set(ours) ^ set(theirs))
    changed += [name for name in set(ours) & set(theirs) if not filecmp.cmp(KIT / name, target / name, shallow=False)]
    return sorted(changed)


def main(args):
    check = '--check' in args
    repositories = [Path(arg).resolve() for arg in args if arg != '--check']
    if not repositories:
        sys.exit(__doc__)
    drift = False
    for repository in repositories:
        target = repository / 'apps' / 'ios' / 'Kit'
        if check:
            changed = differs(target)
            if changed:
                drift = True
                print(f'{target}: differs from NativeKit: ' + ', '.join(changed[:10]) + (' …' if len(changed) > 10 else ''))
            else:
                print(f'{target}: matches NativeKit')
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(KIT, target, ignore=IGNORE)
        print(f'Vendored NativeKit into {target}')
    sys.exit(1 if drift else 0)


if __name__ == '__main__':
    main(sys.argv[1:])
