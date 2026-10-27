"""Opt-in JSC compatibility flags for simulator app launches, never host/phone JSC."""
CHECKED_WASM = {'useWasmFastMemory':'false','useWasmFaultSignalHandler':'false',
                'usePollingTraps':'true','useSharedArrayBuffer':'false'}


INTEL_WASM_COMPAT = dict(CHECKED_WASM, useJIT='true', useWasmIPInt='false', useBBQJIT='true', useOMGJIT='false')

def intel_wasm_overrides():
    return {'SIMCTL_CHILD_'+prefix+name:value
            for name,value in INTEL_WASM_COMPAT.items() for prefix in ('JSC_','__XPC_JSC_')}

def checked_wasm_overrides():
    # WebKit's simulator launch plumbing uses SIMCTL_CHILD_; auxiliary XPC
    # processes additionally need __XPC_ mirrors. Three underscores are intended.
    return {'SIMCTL_CHILD_'+prefix+name:value
            for name,value in CHECKED_WASM.items() for prefix in ('JSC_','__XPC_JSC_')}


def operation_timeout(action):
    # Even the tiny native diagnostic app took 70s to install on this host.
    return 240 if action=='install' else 45
