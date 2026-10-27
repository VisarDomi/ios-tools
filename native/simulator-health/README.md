# Simulator health checks (Mac only)

A simulator-only native UIKit/WKWebView app, without a game engine, network,
account, provisioning profile or physical-device path. It distinguishes basic
simulator failures from application-specific WebKit/Wasm failures.

Build with all guests off, inside the Mac GUI bootstrap and workload guard:

```sh
python3 ~/Developer/ios-tools/native/scripts/mac-workload build --timeout 300 -- python3 ~/Developer/ios-tools/native/simulator-health/build.py --output ~/Library/Caches/simulator-health
```

The builder explicitly selects the iPhone Simulator SDK and architecture, then
ad-hoc signs and verifies the complete bundle. It never builds an iPhoneOS app.
Run with the exact UUID of a project-owned, shut-down guest:

```sh
python3 ~/Developer/ios-tools/native/scripts/mac-workload simulator --visible --device UUID --timeout 600 -- python3 ~/Developer/ios-tools/native/simulator-health/check.py --device UUID --app ~/Library/Caches/simulator-health/SimulatorHealth.app --mode compare --out ~/Library/Caches/simulator-health/results
```

Use the attached `sudo launchctl asuser … sudo -u … caffeinate` bootstrap from
[MAC-WORKLOADS.md](../MAC-WORKLOADS.md). Never run a build alongside a guest.

The test installs only `com.visar.SimulatorHealth.QA` into the chosen simulator.
Its sandbox-file bridge has no listener or phone transport. Native control
updates, plain JS, a canvas, Wasm return values, load/store, memory growth and
an actual out-of-bounds Wasm load are checked. The latter must be caught as
`WebAssembly.RuntimeError`, not crash WebContent. Native and WebKit screenshots
are captured. Each mode terminates the previous app to ensure a fresh VM.

`compare` runs runtime defaults, checked-memory mode, then another checked-mode
launch. App stdout/stderr, masked WebContent JSC environment values, screenshot
PNGs and `report.json` remain private under the selected output directory. Full
process environments are never logged. This small test is not evidence that a
large Unity module works; test the actual application separately.

## Simulator launch configuration

`mac-workload simulator --checked-wasm` supplies these per-app launch options:

- `useWasmFastMemory=false`
- `useWasmFaultSignalHandler=false`
- `usePollingTraps=true`
- `useSharedArrayBuffer=false`

Both `SIMCTL_CHILD_JSC_…` and `SIMCTL_CHILD___XPC_JSC_…` are required so auxiliary
WebContent receives the options. Three underscores after CHILD are intentional.
The flags apply before the first VM; modifying guest `launchctl` state or an
already-running app is not proof of configuration. The diagnostic adds
`dumpOptions=1` and records the runtime's own modified-options dump.

`native/scripts/sim --checked-wasm … launch` supports the same mode, also honors
the active lease's mode, and terminates the existing selected app before launch.
These are simulator debugging options, not changes to Apple binaries, the host's
global JSC environment, or physical-phone behavior. Checked memory preserves
Wasm bounds traps; it does not disable Wasm. It may change performance and
threading availability; don't use this as an unlabelled performance comparison.

Source rationale: WebKit's [simulator environment plumbing](https://github.com/WebKit/WebKit/blob/main/Tools/Scripts/webkitdirs.pm),
[option dependencies](https://github.com/WebKit/WebKit/blob/main/Source/JavaScriptCore/runtime/Options.cpp),
and [Wasm fault handler](https://github.com/WebKit/WebKit/blob/main/Source/JavaScriptCore/wasm/WasmFaultSignalHandler.cpp).
Upstream source is not an exact symbol match for every shipped runtime.

## Large-Wasm Intel compatibility profile

`mac-workload simulator --wasm-compat` adds the validated baseline compiler mode:
`useJIT=true,useWasmIPInt=false,useBBQJIT=true,useOMGJIT=false`. It retains the
checked-memory settings above. This keeps full Wasm execution available rather
than disabling Wasm or substituting desktop rendering.

The October 27 controlled matrix used the same Unity binary/data in one guest:
JS interpretation failed, explicit Wasm IPInt failed, while baseline Wasm JIT
started the actual game. Complete notation/crafting/shop checks then passed in
two separate cold sessions. The modified-options dumps confirm the effective
runtime settings. This isolates an execution-path difference; it is not proof
that a particular upstream bug report exactly matches this shipped JSC build.

The host's private `simulatorWasmMode` policy can select `compat` for routine
sessions. `--native-wasm`, `--checked-wasm` and `--wasm-compat` provide explicit
controls; build jobs never receive simulator launch overrides. The lease records
the selected mode so PC-side `sim launch` commands use the same configuration.
The health comparator removes inherited tier flags before each control mode.

`tier-matrix.py` is a deliberate diagnostic comparison, requiring an active
`--allow-webcontent-crash` session. Its app checker must stop on the first crash;
ordinary UI sessions abort when a new owned-guest WebContent crash report appears.
No endless reload/boot loop is a repair. Historical reports and other guests'
crashes are excluded from that scoped watcher.
