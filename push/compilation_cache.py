"""Xcode's bounded content-addressed cache survives per-delivery DerivedData cleanup."""
from pathlib import Path
import json
import os
import re
from common import atomic_bytes, ensure_directory


def requires_swift_source_paths(source):
    # Apple's App Intents extractor matches compiler constant values against
    # real source files and has no option to reverse our virtual prefix maps.
    for folder, directories, files in os.walk(source):
        directories[:] = [name for name in directories if name not in {'.git', '.local', '.build', 'build', 'DerivedData', 'node_modules'}]
        for name in files:
            if name.endswith('.swift'):
                text = (Path(folder) / name).read_text(errors='replace')
                if re.search(r'(?m)^\s*(?:@\w+\s+)*import\s+(?:\w+\s+)?AppIntents\b', text):
                    return True
    return False


def build_environment(environment, metadata, source, cache_root, *, product=None, app_name=None):
    result = dict(environment)
    metadata, source, cache_root = map(Path, (metadata, source, cache_root))
    ensure_directory(cache_root)
    config = metadata / 'compilation-cache.xcconfig'
    def quoted(path):
        path = str(path)
        if any(c in path for c in '\r\n\0'): raise ValueError('Invalid xcconfig path')
        return json.dumps(path)
    lines = []
    if original := result.get('XCODE_XCCONFIG_FILE'):
        original = Path(original)
        if not original.is_absolute(): original = source / original
        if original.resolve() == config.resolve(): raise ValueError('Recursive xcconfig include')
        lines.append('#include ' + quoted(original))
    mappings = [(source.resolve(), '/^src')]
    if product is not None:
        mappings.append(((source / Path(product).parent).resolve(), '/^products'))
    if app_name:
        mappings.append(((source / 'build/DerivedData' / app_name).resolve(), '/^derived'))
    # More-specific paths must be considered before the frozen source root.
    mappings.sort(key=lambda pair: len(str(pair[0])), reverse=True)
    prefix_maps = ' '.join(quoted(str(path) + '=' + virtual) for path, virtual in mappings)
    preserve_swift_paths = requires_swift_source_paths(source)
    lines += [
        'COMPILATION_CACHE_ENABLE_CACHING = YES',
        'COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS = YES',
        'COMPILATION_CACHE_CAS_PATH = ' + str(cache_root),
        'COMPILATION_CACHE_KEEP_CAS_DIRECTORY = YES',
        'COMPILATION_CACHE_LIMIT_SIZE = 2G',
        'SWIFT_ENABLE_PREFIX_MAPPING = ' + ('NO' if preserve_swift_paths else 'YES'),
        'CLANG_ENABLE_PREFIX_MAPPING = YES',
        'SWIFT_OTHER_PREFIX_MAPPINGS = $(inherited)' + ('' if preserve_swift_paths else ' ' + prefix_maps),
        'CLANG_OTHER_PREFIX_MAPPINGS = $(inherited) ' + prefix_maps,
        'COMPILER_INDEX_STORE_ENABLE = NO',
    ]
    atomic_bytes(config, ('\n'.join(lines) + '\n').encode())
    result['XCODE_XCCONFIG_FILE'] = str(config)
    return result
