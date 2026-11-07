"""Durable, per-build compiler-cache evidence; runs in the existing queue worker."""
from pathlib import Path
import hashlib
import json
import re
import time
from common import load, save, source_hash


def toolchain_signature(environment):
    developer = Path(environment.get('DEVELOPER_DIR', '/Applications/Xcode.app/Contents/Developer'))
    paths = [developer / 'Toolchains/XcodeDefault.xctoolchain/usr/bin/swift-frontend',
             developer / 'Platforms/iPhoneOS.platform/Developer/SDKs/iPhoneOS.sdk/SDKSettings.plist']
    values = []
    for path in paths:
        try:
            actual = path.resolve(); stamp = actual.stat()
            values.append((str(actual), stamp.st_size, stamp.st_mtime_ns))
        except FileNotFoundError: values.append((str(path), None, None))
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def module_inputs(module, files):
    if module == 'AetherEngine':
        prefixes = ['ThirdParty/AetherCore/', 'ThirdParty/FFmpegBuild/', 'ThirdParty/LibDovi/']
        names = {'FileHost/build-provider.py', 'FileHost/project.py', 'scripts/build-provider.py', 'scripts/project.py'}
    elif module == 'AetherFFmpegBuild':
        prefixes = ['ThirdParty/FFmpegBuild/']
        names = {'FileHost/build-provider.py', 'FileHost/project.py', 'scripts/build-provider.py', 'scripts/project.py'}
    elif module.startswith('Kit'):
        # Conservative dependency coverage: any NativeKit change may invalidate a module.
        prefixes, names = ['Kit/Sources/'], {'Kit/Package.swift'}
    else:
        return source_hash(files)
    return source_hash({n: h for n, h in files.items() if n in names or any(n.startswith(p) for p in prefixes)})


def analyse(output, files):
    totals = re.findall(r'note:\s*(\d+) hits / (\d+) cacheable tasks', output)
    modules = set(re.findall(r"(?:SwiftCompile|CompileSwift|SwiftEmitModule)[^\n]*\(in target '([^']+)'", output))
    misses = {}
    for key, target in re.findall(r"(?im)^note: local cache miss for key:\s*(\S+)\s+\(in target '([^']+)'", output):
        modules.add(target); misses.setdefault(target, set()).add(key)
    return {'hits': sum(int(a) for a, _ in totals), 'cacheableTasks': sum(int(b) for _, b in totals),
            'modules': {name: {'inputHash': module_inputs(name, files), 'misses': len(misses.get(name, [])), 'scheduled': True}
                        for name in sorted(modules)}}


def record(store, metadata, request, files, output, *, seconds, strategy, toolchain, success, reused=False, evicted=()):
    """Source snapshots remain authoritative; diagnostics never approve an artifact."""
    path = Path(store) / 'cache-health' / request['repo'] / (request['app'] + '.json')
    state = load(path, {})
    previous = state.get('baseline', state)
    metrics = analyse(output, files)
    # Skipped modules are the strongest cache hit. Keep their comparison
    # fingerprints so a later regression cannot disappear from the baseline.
    for name in previous.get('modules', {}):
        metrics['modules'].setdefault(name, {'inputHash': module_inputs(name, files), 'misses': 0, 'scheduled': False})
    compatible = previous.get('toolchain') == toolchain and previous.get('strategy') == strategy
    warnings = []
    if success and compatible and not previous.get('evicted'):
        for module, current in metrics['modules'].items():
            old = previous.get('modules', {}).get(module)
            if old and old['inputHash'] == current['inputHash'] and current['misses']:
                warnings.append('Unchanged module recompiled: ' + module)
    report = dict(metrics, job=request['id'], repo=request['repo'], app=request['app'], at=time.time(),
                  buildKind=request.get('kind', 'push'),
                  compileSeconds=seconds, strategy=strategy, toolchain=toolchain, success=success,
                  artifactReused=reused, evicted=list(evicted), warnings=warnings,
                  health='regression' if warnings else ('ok' if success else 'build-failed'))
    save(Path(metadata) / 'cache-report.json', report)
    history = state.get('recent', []) + [{k: report[k] for k in ['job', 'at', 'health', 'compileSeconds', 'artifactReused', 'warnings']}]
    baseline = report if success and not reused else previous
    save(path, {'latest': report, 'baseline': baseline, 'recent': history[-20:]})
    return report


def status(store):
    rows = []
    for path in sorted((Path(store) / 'cache-health').glob('*/*.json')):
        state = load(path); rows.append(dict(state.get('latest', state), recent=state.get('recent', [])))
    return {'apps': rows}
