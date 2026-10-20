# Pet Hunter G Offline Project

Private, local-only work to assess and prototype offline play for the discontinued Android game Pet Hunter G.

## Current status

- The AIR 3.4 client failed on Android 16 while loading its old native runtime.
- A test APK repackaged with AIR SDK 51 launches on the connected Android 16 phone.
- The game reaches its own `Connection Timeout` screen because the original service is unavailable.
- Static inspection found the original HTTP endpoint and several server-list addresses. The request/response schema is not yet fully recovered.
- No local server implementation or server-side protocol patch has been written yet.

See [docs/progress-v1.md](docs/progress-v1.md) and [docs/network-recon.md](docs/network-recon.md).

## Project files

- `client/air51-repack/` contains the AIR 51 packaging descriptor and extracted SWF/data/icon inputs used for the test build.
- Build outputs and device captures remain outside this repository at `C:\Users\ssm\Documents\Codex\2026-10-20\ban\outputs`.

## Local-only handling

Do not publish or distribute the game APK or extracted game assets. Do not configure a public server or commercial service. APKs, signatures, build outputs, and captures are excluded by `.gitignore`. This repository has no remote configured; review contents before adding a remote.

Build tools and generated APKs currently live outside this repository in the surrounding workspace and `D:\Tool`.
