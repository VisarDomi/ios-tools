# iOS tools

Agent owns repo. Read README.md, native/README.md and ../../environment/mac-access.md.

- Test, then `native/scripts/ios-push APP` (`ios-push APP`); see push/README.md.
  Wait for captured/Queued, continue independent work, verify `ios-push status JOB`
  before claiming installed. Guarded build/sign/install never launches the app.
  Approval binds delivered frozen checkpoints, never newer mutable mirrors.
- mac-sync/ios-tools-mac-sync.timer publishes committed HEAD: commit tested tool
  changes before deployment. App snapshots still include caller working edits.
- Before compilation/virtual devices read native/MAC-WORKLOADS.md; use
  native/scripts/mac-workload, explicit guest UUIDs, guests shut down while building.
  Never overlap compilation/simulator tests or bypass recorded Intel graphics policy.
  Simulator refusal never permits physical-phone UI; finish independent checks.
- Inspect exact job logs: load/disk/lock preflight refusal precedes Swift compilation,
  proves neither app failure nor renewal success. Preserve guards/checkpoints;
  reconcile durable state/partial effects before retries or duplicate jobs.
- Survive reboot without agents/temporary helpers. Preserve existing sleep prevention;
  no caffeinate, wake helpers, extra startup jobs or power changes without a request.
- Child briefs bind app/bundle, source, writes, devices, guards, tests and delivery proof.
  Keep diagnostic identity during a session; finally remove owned temporary apps/
  controllers and verify absence. Preserve products, BLE/trust identities and data.
- Mac backup: private VisarDomi/ios-tools-private; public VisarDomi/ios-tools is
  upstream. Inspect remote URLs/visibility, not names; never publish private incidents.
