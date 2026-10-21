# Pet Hunter G Offline Project

Private, local-only work to assess and prototype offline play for the discontinued Android game Pet Hunter G.

## Current status

- The AIR 3.4 client failed on Android 16 while loading its old native runtime.
- A test APK repackaged with AIR SDK 51 launches on the connected Android 16 phone.
- The game reaches its own `Connection Timeout` screen because the original service is unavailable.
- Static inspection found the original HTTP endpoint and several server-list addresses. The request/response schema is not yet fully recovered.
- A first Flask LAN prototype exists. It serves captured server-list XML verbatim when provided and observes `flash.do` requests without inventing success responses.
- The AIR 51 client still points at hard-coded retired server IPs; client redirection remains a separate next step.

See [docs/progress-v1.md](docs/progress-v1.md) and [docs/network-recon.md](docs/network-recon.md).

## Project files

- `client/air51-repack/` contains the AIR 51 packaging descriptor and extracted SWF/data/icon inputs used for the test build.
- Build outputs and device captures remain outside this repository at `C:\Users\ssm\Documents\Codex\2026-10-20\ban\outputs`.
- The Flask prototype and run instructions are under `server/`.

## Local-only handling

Do not publish or distribute game APKs. Do not expose a public server or commercialize the project. APKs, signatures, build outputs, and captures are excluded by `.gitignore`. A GitHub remote is configured; changes are not pushed automatically.

Build tools and generated APKs currently live outside this repository in the surrounding workspace and `D:\Tool`.
