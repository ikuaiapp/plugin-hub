# 验证报告（Validation Report）

- **目标仓库**：`ikuaiapp/plugin-hub`（`VERSION = 1.0.0`，`schema_version = 1`）
- **验证环境**：Linux x86_64 构建主机（Python `3.11.2`、Git、无外网 DNS 的离线沙箱）；全部路径与示例已脱敏，不含任何真实路由器 IP、端口、凭据或本机绝对路径。

---

## 1. 索引构建与确定性校验

1. **目录一致性校验**：
   - `python3 -B scripts/build_index.py --check`：通过（`plugins.json` 完整收录全部 9 款 `ikuaiapp` 插件，所有 `download_url` 与 `mirror_urls` 均指向 `ikuaiapp/plugin-hub` Release `v1.0.0`，字段、正则名称、64 位十六进制 SHA-256、字节大小与 PNG 图标全部合法）。
   - `python3 -B scripts/build_index.py --source-root ../3.7.26 --check`：通过（逐一比对同级上游仓库的 `metadata.json`、`.sha256`、`BUILD-MANIFEST.json`、`.tar.gz` 字节大小与 SHA-256、以及常规文件 `<name>.png` 字节一致性）。
2. **双次构建字节级可复现性**：
   - 使用 `--generated-at 2026-11-21T12:00:00Z` 与 `SOURCE_DATE_EPOCH=1795262400` 分别生成 `/tmp/ph1.json` 与 `/tmp/ph2.json`，`cmp` 比对字节完全一致（退出码 `0`）。
3. **字符清洗与字段归一化**：
   - `docker` 上游 `metadata.json` 描述中的前导 `\u200c` 零宽字符已清洗；`"onlyOfflineInstall": "true"` 已归一化为 JSON 布尔值 `true`。

---

## 2. 图标与 9 插件统一托管清单核对

| 插件名 (`name`) | 图标路径 | 字节大小 | 规范校验 | SHA-256 |
|---|---|---|---|---|
| `router_backup` | `icons/router_backup.png` | `274` | 常规 PNG（96x96），`<= 1 MiB` | `6e36f984ed7cc3dc2efaceef60c7062c22af2c42dd2fa99c5388472206a5ca23` |
| `fn-knock` | `icons/fn-knock.png` | `415` | 常规 PNG（128x128），`<= 1 MiB` | `ab54cf8316515f214b4f62959116648a88afe4c3f9e96e6d9b8da8a1914b7131` |
| `docker` | `icons/docker.png` | `21316` | 常规 PNG（256x256），`<= 1 MiB` | `c0637cce45c67407705a21f45698611b8f393a686ede4fd63519ebdf093a0538` |
| `MeshCentral` | `icons/MeshCentral.png` | `112227` | 常规 PNG（303x303），`<= 1 MiB` | `1b7d9724b4636be4ab88c373af21d5278b9f951acabcc6678c15c9b9ad7bc394` |
| `vnt2` | `icons/vnt2.png` | `16855` | 常规 PNG（128x128），`<= 1 MiB` | `25946dbb92b7dba836681c376ff47ffe58f7efbe7cfa00cc3b92f13575fdd82c` |
| `vnstat` | `icons/vnstat.png` | `394` | 常规 PNG（128x128），`<= 1 MiB` | `6c15449d945bbe91f948cca53fab7daf7162206e6c7d9b1f0c30eff225a875dc` |
| `system-tools` | `icons/system-tools.png` | `116399` | 常规 PNG（447x358），`<= 1 MiB` | `ced3fb18c2654fe6dafd4b1a59b43857bdd0421586963b8381ecad421cc0b907` |
| `ikev2-cert` | `icons/ikev2-cert.png` | `604` | 常规 PNG（128x128），`<= 1 MiB` | `a8dd1989ce0979b13cbda66e1be96e184676897ad8d6ce2626c7d3acd7df3742` |
| `Ttyd` | `icons/Ttyd.png` | `81715` | 常规 PNG（627x627），`<= 1 MiB` | `21964f858474fce7d828ab9986f2c9df2b555ffa9d2057608af32c14a116c9b7` |

- `system-tools`、`ikev2-cert`（`ikev2-acme`）、`Ttyd`（`ttyd`）上游源码仓库保持 `PRIVATE`，其余 6 款上游源码仓库当前为 `PUBLIC`；全部 9 款插件的 `.tar.gz` 与 `.tar.gz.sha256` 经上传前脱敏与 `safe_import.sh --check` 审计后统一托管至 `ikuaiapp/plugin-hub` Release `v1.0.0`，`plugins.json` 中全部 `download_url` 与 `mirror_urls` 均指向 `https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/...`。

---

## 3. 自动化测试与脱敏审计

- **离线镜像探测自检**：`python3 -B scripts/verify_mirrors.py --offline-test --all-plugins --json` 通过（`passed: true`，`plugins_checked: 9`，`raw_ok >= 1`，`release_ok >= 1`，`icon_ok >= 1`，`range_ok >= 1`，正确拦截模拟 HTTP `200` HTML 门户页并验证 TLS 1.2 / PNG / `.sha256` / gzip 魔数）。
- **单元测试与完整性套件**：`python3 -B -m unittest discover -s tests -p "test_*.py" -v` 共 **27** 项用例全部通过（`OK`，0 失败，0 错误）。
- **9 插件发布包上传前脱敏审计（M6）**：
  - 9/9 远程 Release `.tar.gz` 与 `.sha256` 均与 GitHub API `digest` / `size` 及本地 `3.7.26/*/releases/` 完全一致；
  - 9/9 压缩包通过 `safe_import.sh --check`（输出 `Validated <name>`）及 `html/metadata.json` / `<name>.png` 一致性校验；
  - 深度扫描全部包内脚本、配置、压缩 Web 资源（`*.js.gz`/`*.css.gz`/`manifest.json.gz`）、`MeshCentral/runtime.tar.gz`（7,344 成员）及 ELF 可打印字符串，确认 0 例敏感 IP/端口/口令/Token/真实私钥/本地绝对路径残留。
- **仓库脱敏审计**：
  - `python3 -B scripts/public_audit.py --working-tree`：输出 `public audit passed`（退出码 `0`）。
  - `python3 -B scripts/public_audit.py --history HEAD`：输出 `public audit passed`（退出码 `0`）。

---

## 4. 实时镜像连通性与实机端到端验证（M4，2026-11-22）

- **构建主机外网镜像探测**（`python3 scripts/verify_mirrors.py --check-assets --json`）：
  - 在 `ikuaiapp/plugin-hub` 尚未推送至 GitHub `main`（按发布确认门控保持未推送）时，`plugins.json` 与 `icons/router_backup.png` 的 `raw`/`jsdelivr` 探测按预期返回 `404`/`403`（`raw_ok: 0`、`icon_ok: 0`）。
  - 公开 Release 资产（`config-backup`）探测：`release_ok: 4`（`gh-proxy.org`、`ghfast.top`、`cdn.gh-proxy.com`、`edgeone.gh-proxy.com` 返回 `HTTP 200` `TLSv1.2`）与 `range_ok: 4`（`cdn.gh-proxy.com`、`edgeone.gh-proxy.com`、`wget.la`、`github.com` 返回 `HTTP 206` `512` 字节 `TLSv1.2`）。
- **测试路由器实机镜像探活（6 个公开插件发布包）**：
  - 在 `iKuai 3.7.26 x64` 测试路由器上使用 `curl -4 -fSL --tlsv1.2 -r 0-511` 实测所有 6 个收录插件（`router_backup`、`fn-knock`、`docker`、`MeshCentral`、`vnt2`、`vnstat`）：每个插件均有 `3`–`4` 个中国大陆镜像节点返回 `HTTP 206` 与 gzip 魔数 `1f8b`（`ghfast.top`、`wget.la`、`cdn.gh-proxy.com`、`edgeone.gh-proxy.com`、`gh-proxy.org`），个别镜像 DNS 超时或返回 `403` 时可正常触发故障转移。
- **测试路由器实机索引拉取与安装/卸载联动**：
  - 通过局域网临时 HTTP 索引服务向路由器下发 `plugins.json` 并调用 `plugin-store v2.1.0` 的 `set_hub_url` / `refresh_hub` / `uninstall` / `install_online`：卸载 `router_backup` 后其自动进入 `online` 列表，触发 `install_online` 后由路由器经 `ghfast.top` 拉取真实 GitHub Release 压缩包（`14.52s`）、完成 SHA-256 校验与安装并从 `online` 移除、回到 `installed` 列表；随后恢复默认 `plugins.json` 源地址。
  - **M6 发布后复验命令**：`main` 分支与 Release `v1.0.0`（18 个资产：`9 .tar.gz + 9 .tar.gz.sha256`）推送上传完成后，执行 `python3 -B scripts/build_index.py --verify-remote --check` 与 `python3 -B scripts/verify_mirrors.py --check-assets --all-plugins --json` 验证全部 9 款插件直连与大陆镜像均可正常下载。
