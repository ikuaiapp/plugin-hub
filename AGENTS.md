# ikuaiapp/plugin-hub — Agent Engineering & Handover Guide

This repository (`https://github.com/ikuaiapp/plugin-hub`) hosts the public online plugin catalog (`plugins.json`), plugin icons (`icons/*.png`), and deterministic catalog/mirror/audit tooling consumed by [`ikuaiapp/plugin-store`](https://github.com/ikuaiapp/plugin-store) on **iKuai 3.7.x / 3.7.26 x64** routers.

All autonomous and cooperating AI agents working in this repository MUST follow the catalog policy, repository layout, router/mirror invariants, validation commands, desensitization rules, and out-of-repo GitHub auth gate below.

---

## 1. Version & Catalog Policy

- **Catalog version (`VERSION`)**: SemVer catalog/tooling version starting at **`1.0.0`** (independent of individual plugin release versions, paired with `plugins.json` `schema_version: 1`).
  - Bump PATCH (`1.0.1`) or MINOR (`1.1.0`) when updating indexed plugin versions, adding newly public plugins, adjusting mirrors, or updating scripts/docs.
  - Bump MAJOR (`2.0.0`) only when making breaking changes to the `plugins.json` `schema_version` contract.
- **`ikuaiapp`-Only & Unified `plugin-hub` Release Hosting Rule**:
  - Index ONLY usable released plugin repositories under `ikuaiapp/*`. Never duplicate local build leftovers or index non-plugin VPS installers (`reinstall`, `ikuai-plus`).
  - Host all 9 audited plugin `.tar.gz` + `.tar.gz.sha256` assets in public `ikuaiapp/plugin-hub` GitHub Releases (e.g., `v1.0.0`) via `release_repo` / `release_tag` in `catalog_sources.json` so all `download_url` and `mirror_urls` fields in `plugins.json` resolve against `https://github.com/ikuaiapp/plugin-hub/releases/download/...` while keeping upstream `repo` / `tag` provenance intact (allowing `system-tools`, `ikev2-acme`, `ttyd`, or any other upstream source repo to remain or become `PRIVATE` without causing HTTP `404` on routers). NEVER commit `.tar.gz` blobs into Git history.
  - Never emit an unhosted `PRIVATE` upstream URL directly into `plugins.json`: any entry marked `"visibility": "private_pending"` or `"disabled"` is excluded from `plugins.json`.
- **`metadata.json.name` Invariant**:
  - Every `plugins[].name` MUST match the exact `name` inside the plugin's `html/metadata.json` (`^[A-Za-z0-9][A-Za-z0-9._-]*$`), even when it differs from the GitHub repository name (`router_backup` for `config-backup`, `fn-knock` for `knock`, `vnt2` for `vnt`, `ikev2-cert` for `ikev2-acme`, `Ttyd` for `ttyd`). `plugin-store` relies on exact `name` parity to hide installed plugins from the online list and restore them upon uninstall.
- **Synchronization Checklist**: Keep these files aligned when bumping `VERSION` or updating catalog entries:
  - `VERSION`, `SOURCES.json`, `GITHUB_METADATA.json`
  - `catalog_sources.json`, `plugins.json`, `icons/*.png`
  - `pending_private_plugins.md`, `README.md`, `MAINTAINERS.md`, `CHANGELOG.md`, `VALIDATION.md`, `tests/`

---

## 2. Repository Layout & Architecture

- `VERSION`: Single-line catalog SemVer (`1.0.0`).
- `GITHUB_METADATA.json`: Offline-staged GitHub repository Description, Homepage, and Topics for post-confirmation `gh repo edit`.
- `SOURCES.json`: Provenance manifest pinning all 9 indexed `ikuaiapp/*` plugin release coordinates, `source_visibility`, `release_repo`/`release_tag`, SHA-256 checksums, icon source paths/hashes, and mirror lists.
- `catalog_sources.json`: Authoritative generator input containing `mirrors` and all 9 `ikuaiapp` plugin records (`release_repo: "ikuaiapp/plugin-hub"`, `release_tag: "v1.0.0"`, `source_visibility`) with relative `local_source` hints (never absolute host paths).
- `plugins.json`: Deterministic generated catalog (`schema_version: 1`, 9 entries) consumed directly from the `main` branch by `plugin-store`.
- `pending_private_plugins.md`: Sync record and pre-upload audit checklist for private-source plugins (`system-tools`, `ikev2-cert`, `Ttyd`) hosted via `plugin-hub` Release `v1.0.0`.
- `icons/<name>.png`: Regular-file PNG icons (`<= 1 MiB`, valid `IHDR`, **zero symlinks**) extracted from each indexed plugin's `<name>.png` (never `logo.png`, because `MeshCentral` lacks `logo.png` and `vnt2/html/logo.png` is a symlink).
- `scripts/`:
  - `build_index.py`: Deterministic catalog builder/validator (`--sources`, `--output`, `--source-root`, `--generated-at`, `SOURCE_DATE_EPOCH`, `--check`, `--sync-icons`, `--verify-remote`), supporting `release_repo`/`release_tag` overrides, generating per-plugin `mirror_urls`, refusing symlinked `icons/` directories/files, sanitizing invisible Unicode characters (`\ufeff\u200b\u200c\u200d`), and normalizing `onlyOfflineInstall` to boolean `only_offline_install`.
  - `verify_mirrors.py`: Mirror probe tool enforcing TLS 1.2 bounds (`ssl.TLSVersion.TLSv1_2`), IPv4 connection preference, HTTP `200` HTML-portal rejection, JSON/PNG/`.sha256`/Range-gzip checks, `--all-plugins`, and `--offline-test` / injectable `ProbeClient`.
  - `public_audit.py`: Mandatory desensitization scanner (`--working-tree` and `--history <REVISION>`).
- `tests/`: Pure Python stdlib `unittest` suite (`test_build_index.py`, `test_verify_mirrors.py`, `test_catalog_integrity.py`, `test_public_audit.py`) runnable offline with zero network calls.

---

## 3. Critical Platform & Mirror Invariants

1. **`main` Branch Hosting (Never `gh-pages` / `*.github.io`)**:
   - Mainland China GitHub mirrors (`gh-proxy.org`, `ghfast.top`, `gh-proxy.com`, `wget.la`, `raw.bgithub.xyz`, jsDelivr `@main`) do NOT proxy `*.github.io`. All raw catalog files (`plugins.json`, `icons/*.png`) MUST live on `main`.
2. **Mirror URL Semantics (`mirrors` Object)**:
   - `mirrors.raw`: Prefix proxies expecting `<prefix>https://raw.githubusercontent.com/ikuaiapp/plugin-hub/main/<relpath>`.
   - `mirrors.release`: Prefix proxies expecting `<prefix><download_url>`.
   - `mirrors.jsdelivr`: Branch-root CDN bases expecting `<base><relpath>`.
   - `mirrors.raw_direct`: Host-replacement base expecting `<base><relpath>` (do NOT prepend `https://raw.githubusercontent.com/` to `raw.bgithub.xyz`).
3. **Router Client Constraints (`iKuai 3.7.x / 3.7.26`)**:
   - Routers run `curl 7.70.0` compiled against `OpenSSL 1.0.2u` (**TLS 1.2 maximum**, no TLS 1.3), BusyBox `1.23.2`, `jq 1.4` (avoid `jq -er` assumptions; prefer `luajit` + `libjansson` / `json_tool.lua`), and IPv4-first (`curl -4 -fSL --tlsv1.2`).
   - Always reject HTTP `200` HTML portals (`<!DOCTYPE html>` / `text/html`) returned by broken proxies, and verify every downloaded `.tar.gz` with `sha256sum` and `safe_import.sh`.
   - `plugin-store` runtime state lives strictly under `/etc/log/pgstore` and `/tmp/iktmp/online_install` — never `/etc/mnt`. Note that stock `3.7.26` enforces a `50 MiB` upload limit unless patched to `128 MiB`, affecting `docker` (~95.4 MiB) and `MeshCentral` (~120.0 MiB), and official `pmd` can overwrite `pgstore.bin.pkg` via `pkgmanager.ikuai8.com` if unguarded.

---

## 4. Build, Test & Verification Commands

Run all commands from the `plugin-hub` repository root using Python `3.11+` standard library:

```bash
# 1. Verify plugins.json determinism & schema (standalone CI mode)
python3 scripts/build_index.py --check

# 2. Cross-verify against sibling 3.7.26 plugin repos (when present)
python3 scripts/build_index.py --source-root ../3.7.26 --check

# 3. Deterministic reproducible output test
python3 scripts/build_index.py --generated-at 2026-11-21T12:00:00Z --output /tmp/p1.json
SOURCE_DATE_EPOCH=1795262400 python3 scripts/build_index.py --output /tmp/p2.json
cmp /tmp/p1.json /tmp/p2.json && rm -f /tmp/p1.json /tmp/p2.json

# 4. Run full offline unit & catalog integrity tests
python3 -m unittest discover -s tests -p "test_*.py" -v

# 5. Run offline mirror probe self-test (and live probe when online)
python3 scripts/verify_mirrors.py --offline-test --json
# When online:
python3 scripts/verify_mirrors.py --check-assets --json
```

---

## 5. Privacy, Desensitization & Out-of-Repo GitHub Auth

- **Zero Sensitive Artifacts**: NEVER commit RFC1918 IPs (`192.168.*`, `10.*`, `172.16-31.*`), test SSH ports, credentials, GitHub tokens, private keys, `.db`/`.sqlite`/`.bak` files, `.tar.gz`/`.bin`/`.pkg` archives, ELF binaries, files `> 1 MiB`, or local workspace paths. Use ONLY RFC 5737 (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`) and RFC 2606 (`example.com`, `example.org`) in examples and tests.
- **Test Literal Splitting**: In `scripts/public_audit.py` and `tests/test_public_audit.py`, split any synthetic sensitive test tokens via Python `+` concatenation so the audit scanner never triggers false positives on the test suite itself.
- **Persistent Out-of-Repo GitHub Auth**:
  - Do NOT store `gh` credentials inside this repository. Keep OAuth state in `<workspace-root>/.local-tools/gh/{bin,config}`:
    ```bash
    GH_CONFIG_DIR=<workspace-root>/.local-tools/gh/config <workspace-root>/.local-tools/gh/bin/gh <command>
    ```
- **Mandatory Pre-Commit / Pre-Push Audit**:
  ```bash
  python3 scripts/public_audit.py --working-tree
  python3 scripts/public_audit.py --history HEAD
  ```
  Both MUST print `public audit passed` and exit `0`.

---

## 6. Git & Release Workflow

- Local Git identity: `user.name = ikuaiapp`, `user.email = ikuaiapp@users.noreply.github.com`.
- Branch: `main`; remote `origin = https://github.com/ikuaiapp/plugin-hub.git`.
- Commit style: Conventional Commits (e.g., `feat(plugin-hub): ...`). Tag releases as `v<VERSION>` when ready.
- **Hard Gate**: **Never push to `origin`, alter GitHub repository metadata (`gh repo edit`), or publish a GitHub Release without the repository owner's explicit confirmation.**
