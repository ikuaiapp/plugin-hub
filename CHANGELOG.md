# Changelog

All notable changes to `ikuaiapp/plugin-hub` are documented in this file.

## [1.0.0] - 2026-11-22

### Added
- Initialized `ikuaiapp/plugin-hub` public online plugin catalog (`schema_version: 1`) on `main` branch.
- Indexed all 9 `ikuaiapp` iKuai `3.7.x` / `3.7.26` x64 plugins (`router_backup`, `fn-knock`, `docker`, `MeshCentral`, `vnt2`, `vnstat`, `system-tools`, `ikev2-cert`, `Ttyd`) in `plugins.json` with exact `metadata.json.name` keys, SHA-256 checksums, byte sizes, and regular-file PNG icons under `icons/`.
- Unified release asset hosting under `ikuaiapp/plugin-hub` Release `v1.0.0` (18 assets: 9 `.tar.gz` + 9 `.tar.gz.sha256`) via `release_repo` / `release_tag` in `catalog_sources.json` and `scripts/build_index.py`, emitting both `download_url` and `mirror_urls` targeting `https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/...` while preserving upstream `repo` / `tag` / `source_visibility` provenance (allowing upstream source repos, including `system-tools`, `ikev2-acme`, `ttyd`, to remain or become `PRIVATE`).
- Configured ordered Mainland China mirror templates (`mirrors.raw`, `mirrors.release`, `mirrors.jsdelivr`, `mirrors.raw_direct`) targeting `main` branch assets (excluding `*.github.io`).
- Added deterministic index generator/validator `scripts/build_index.py` (including symlinked `icons/` directory refusal), TLS 1.2 mirror prober `scripts/verify_mirrors.py` (with anti-HTML-portal rejection, `--offline-test --all-plugins`, and `--check-assets --all-plugins`), desensitization scanner `scripts/public_audit.py`, and pure-stdlib `unittest` suite under `tests/`.
- Added repo metadata and AI Agent handover documentation (`VERSION`, `GITHUB_METADATA.json`, `SOURCES.json`, `pending_private_plugins.md`, `README.md`, `AGENTS.md`, `MAINTAINERS.md`, `VALIDATION.md`).
