"""Xcode's bounded content-addressed cache survives per-delivery DerivedData cleanup."""
from pathlib import Path
import json
from common import atomic_bytes, ensure_directory


def build_environment(environment, metadata, source, cache_root):
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
    lines += [
        'COMPILATION_CACHE_ENABLE_CACHING = YES',
        'COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS = YES',
        'COMPILATION_CACHE_CAS_PATH = ' + str(cache_root),
        'COMPILATION_CACHE_KEEP_CAS_DIRECTORY = YES',
        'COMPILATION_CACHE_LIMIT_SIZE = 2G',
        'SWIFT_ENABLE_PREFIX_MAPPING = YES',
        'CLANG_ENABLE_PREFIX_MAPPING = YES',
        'SWIFT_OTHER_PREFIX_MAPPINGS = $(inherited) ' + quoted(str(source.resolve()) + '=/^src'),
        'CLANG_OTHER_PREFIX_MAPPINGS = $(inherited) ' + quoted(str(source.resolve()) + '=/^src'),
        'COMPILER_INDEX_STORE_ENABLE = NO',
    ]
    atomic_bytes(config, ('\n'.join(lines) + '\n').encode())
    result['XCODE_XCCONFIG_FILE'] = str(config)
    return result
