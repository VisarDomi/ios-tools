"""Xcode's bounded content-addressed cache survives per-delivery DerivedData cleanup."""
from pathlib import Path
import json
from common import atomic_bytes, ensure_directory


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
    lines += [
        'COMPILATION_CACHE_ENABLE_CACHING = YES',
        'COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS = YES',
        'COMPILATION_CACHE_CAS_PATH = ' + str(cache_root),
        'COMPILATION_CACHE_KEEP_CAS_DIRECTORY = YES',
        'COMPILATION_CACHE_LIMIT_SIZE = 2G',
        'SWIFT_ENABLE_PREFIX_MAPPING = YES',
        'CLANG_ENABLE_PREFIX_MAPPING = YES',
        'SWIFT_OTHER_PREFIX_MAPPINGS = $(inherited) ' + prefix_maps,
        'CLANG_OTHER_PREFIX_MAPPINGS = $(inherited) ' + prefix_maps,
        'COMPILER_INDEX_STORE_ENABLE = NO',
    ]
    atomic_bytes(config, ('\n'.join(lines) + '\n').encode())
    result['XCODE_XCCONFIG_FILE'] = str(config)
    return result
