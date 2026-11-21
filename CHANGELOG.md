# Changelog

All notable changes to `ikuaiapp/plugin-hub` are documented in this file.

## [1.0.0] - 2026-11-21

### Added
- Initialized `ikuaiapp/plugin-hub` public online plugin catalog (`schema_version: 1`) on `main` branch.
- Indexed the 6 public `ikuaiapp` iKuai `3.7.x` / `3.7.26` x64 plugins (`router_backup`, `fn-knock`, `docker`, `MeshCentral`, `vnt2`, `vnstat`) in `plugins.json` with exact `metadata.json.name` keys, SHA-256 checksums, byte sizes, and regular-file PNG icons under `icons/`.
- Added `catalog_sources.json` and `pending_private_plugins.md` tracking all 9 released `ikuaiapp` plugin repositories (6 `public` + 3 `private_pending`: `system-tools`, `ikev2-cert`, `Ttyd`).
- Configured ordered Mainland China mirror templates (`mirrors.raw`, `mirrors.release`, `mirrors.jsdelivr`, `mirrors.raw_direct`) targeting `main` branch assets (excluding `*.github.io`).
- Added deterministic index generator/validator `scripts/build_index.py`, TLS 1.2 mirror prober `scripts/verify_mirrors.py` (with anti-HTML-portal rejection and `--offline-test`), desensitization scanner `scripts/public_audit.py`, and pure-stdlib `unittest` suite under `tests/`.
- Added repo metadata and AI Agent handover documentation (`VERSION`, `GITHUB_METADATA.json`, `SOURCES.json`, `README.md`, `AGENTS.md`, `MAINTAINERS.md`, `VALIDATION.md`).
