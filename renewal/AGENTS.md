This repository owns only the Apple containing app, bundle staging and deployment.
Provider/runtime/manifest/behavior changes belong in the four source repositories.
Read README.md for setup, signing identity and deployment procedures.
Never commit dist, signed apps, access keys, deployment overrides or signing files.
Preserve Apple bundle IDs when updating the existing installation.
For a single-reader update, build/stage that reader only; do not overwrite another
reader's pending experiment. Coordinate before installing the shared app.
Run npm test and npm run verify for packaging changes. Use the configured Mac
build and signature/hash checks for Xcode changes; do not clear phone data.
