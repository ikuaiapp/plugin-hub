# 私有源码插件同步托管记录（Synced Private-Source Plugins）

本文件记录 `ikuaiapp` 组织下**源码仓库保持 `PRIVATE`、但安装包与图标已通过脱敏审计并同步托管至公开仓库 `ikuaiapp/plugin-hub` Release `v1.0.0` 的插件**。

为避免未登录路由器或中国大陆公开镜像访问私有仓库返回 HTTP `404`，同时支持所有插件源码仓库保持或后续切换为 `PRIVATE`：
- 禁止将任何 `.tar.gz` 压缩包提交进 Git 历史；
- 全部 9 款插件（含以下 3 款私有源码插件及 6 款当前公开源码插件）的 Release `.tar.gz` 与 `.tar.gz.sha256` 经脱敏检查后统一上传至公开仓库 `ikuaiapp/plugin-hub` Release `v1.0.0`；
- `catalog_sources.json` 通过 `"release_repo": "ikuaiapp/plugin-hub"` 与 `"release_tag": "v1.0.0"` 将 `plugins.json` 的 `download_url` 和 `mirror_urls` 全部指向 `https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/...`，同时在 `"repo"` 与 `"source_visibility"` 中保留上游来源元数据。

---

## 1. 已同步托管的私有源码插件清单

| 插件内部名 (`metadata.json.name`) | 上游源码仓库 (`ikuaiapp/*`) | 上游 Tag | 托管 Release (`plugin-hub`) | Release 资产名 | 字节大小 | SHA-256 | 兼容固件 | 托管状态 |
|---|---|---|---|---|---|---|---|---|
| `system-tools` | `ikuaiapp/system-tools` (`PRIVATE`) | `v1.1.9` | `v1.0.0` | `system-tools-1.1.9-ikuai-3.7.x-x64.tar.gz` | `284169` | `c50c5f79ff26b144db52f807e2e2fc5d77f3243547ff575351270e25401e40f6` | `3.7.x` | 已脱敏并同步收录于 `plugins.json` + `icons/` |
| `ikev2-cert` | `ikuaiapp/ikev2-acme` (`PRIVATE`) | `v3.1.7` | `v1.0.0` | `ikev2-acme-3.1.7-ikuai-3.7.x-x64.tar.gz` | `113141` | `dd60e3b0b5cf83a3d32f9f4e859019b6a0d252c85b79da4dc5ac0d5e246fcfa6` | `3.7.x` | 已脱敏并同步收录于 `plugins.json` + `icons/` |
| `Ttyd` | `ikuaiapp/ttyd` (`PRIVATE`) | `v1.7.7` | `v1.0.0` | `ttyd-1.7.7-ikuai-3.7.x-x64.tar.gz` | `930568` | `98da2f68cd5959dedb1c7059d364b00dd54e5997fd0e13a23d5da9665c8a9e2f` | `3.7.x` | 已脱敏并同步收录于 `plugins.json` + `icons/` |

---

## 2. 上游更新与复核同步检查单

当任一插件（无论上游源码仓库为 `PUBLIC` 或 `PRIVATE`）发布新版本时，按以下顺序同步至 `ikuaiapp/plugin-hub`：

1. **通过外置已授权 `gh` CLI 拉取上游最新 Release 资产与元数据**：
   - 使用 `GH_CONFIG_DIR=<workspace-root>/.local-tools/gh/config <workspace-root>/.local-tools/gh/bin/gh release download` 拉取到临时工作目录（禁止放入本仓库），校验 `.sha256`、文件字节大小、`html/metadata.json` 与 `<name>.png` 常规 PNG 文件。
2. **执行上传前脱敏与 `safe_import.sh --check` 审计**：
   - 解包复核内部脚本、配置、压缩 web 资产及二进制字符串，确认无内网测试路由器 IP、测试端口、口令、Token、真实私钥或宿主机绝对路径残留，且 `safe_import.sh --check` 输出 `Validated <name>`。
3. **同步常规 PNG 图标与 `catalog_sources.json`**：
   - 将 `<name>.png`（常规文件、`<= 1 MiB`、禁止软链接）写入 `icons/<name>.png`（或使用 `build_index.py --source-root ../3.7.26 --sync-icons`），并更新 `catalog_sources.json` 中的 `visibility: "public"`、`release_repo: "ikuaiapp/plugin-hub"`、`release_tag`、`tag`、`version`、`asset_name`、`sha256`、`size`。
4. **重新生成并校验索引与脱敏门禁**：
   ```bash
   python3 -B scripts/build_index.py --source-root ../3.7.26
   python3 -B scripts/verify_mirrors.py --offline-test --all-plugins --json
   python3 -B -m unittest discover -s tests -p "test_*.py" -v
   python3 -B scripts/public_audit.py --working-tree
   python3 -B scripts/public_audit.py --history HEAD
   ```
5. **同步 `SOURCES.json` 与文档并发布 Release 资产**：
   - 更新 `SOURCES.json`、`README.md`、`CHANGELOG.md`、`VALIDATION.md`；
   - 经仓库所有者确认后推送 `main` 与目标 Release tag，并将全部 `.tar.gz` + `.tar.gz.sha256` 上传至 `ikuaiapp/plugin-hub` Release，随后执行 `python3 -B scripts/verify_mirrors.py --check-assets --all-plugins --json` 复验。
