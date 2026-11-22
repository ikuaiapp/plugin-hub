# 验证报告（Validation Report）

- **目标仓库**：`ikuaiapp/plugin-hub`（`VERSION = 1.0.0`，`schema_version = 1`）
- **验证环境**：Linux x86_64 构建主机（Python `3.11.2`、Git、无外网 DNS 的离线沙箱）；全部路径与示例已脱敏，不含任何真实路由器 IP、端口、凭据或本机绝对路径。

---

## 1. 索引构建与确定性校验

1. **目录一致性校验**：
   - `python3 scripts/build_index.py --check`：通过（`plugins.json` 仅包含 6 个公开插件，字段、正则名称、64 位十六进制 SHA-256、字节大小与 PNG 图标全部合法）。
   - `python3 scripts/build_index.py --source-root ../3.7.26 --check`：通过（逐一比对同级上游仓库的 `metadata.json`、`.sha256`、`BUILD-MANIFEST.json`、`.tar.gz` 字节大小与 SHA-256、以及常规文件 `<name>.png` 字节一致性）。
2. **双次构建字节级可复现性**：
   - 使用 `--generated-at 2026-11-21T12:00:00Z` 与 `SOURCE_DATE_EPOCH=1795262400` 分别生成 `/tmp/ph1.json` 与 `/tmp/ph2.json`，`cmp` 比对字节完全一致（退出码 `0`）。
3. **字符清洗与字段归一化**：
   - `docker` 上游 `metadata.json` 描述中的前导 `\u200c` 零宽字符已清洗；`"onlyOfflineInstall": "true"` 已归一化为 JSON 布尔值 `true`。

---

## 2. 图标与公开清单核对

| 插件名 (`name`) | 图标路径 | 字节大小 | 规范校验 | SHA-256 |
|---|---|---|---|---|
| `router_backup` | `icons/router_backup.png` | `274` | 常规 PNG（96x96），`<= 1 MiB` | `6e36f984ed7cc3dc2efaceef60c7062c22af2c42dd2fa99c5388472206a5ca23` |
| `fn-knock` | `icons/fn-knock.png` | `415` | 常规 PNG（128x128），`<= 1 MiB` | `ab54cf8316515f214b4f62959116648a88afe4c3f9e96e6d9b8da8a1914b7131` |
| `docker` | `icons/docker.png` | `21316` | 常规 PNG（256x256），`<= 1 MiB` | `c0637cce45c67407705a21f45698611b8f393a686ede4fd63519ebdf093a0538` |
| `MeshCentral` | `icons/MeshCentral.png` | `112227` | 常规 PNG（303x303），`<= 1 MiB` | `1b7d9724b4636be4ab88c373af21d5278b9f951acabcc6678c15c9b9ad7bc394` |
| `vnt2` | `icons/vnt2.png` | `16855` | 常规 PNG（128x128），`<= 1 MiB` | `25946dbb92b7dba836681c376ff47ffe58f7efbe7cfa00cc3b92f13575fdd82c` |
| `vnstat` | `icons/vnstat.png` | `394` | 常规 PNG（128x128），`<= 1 MiB` | `6c15449d945bbe91f948cca53fab7daf7162206e6c7d9b1f0c30eff225a875dc` |

- `system-tools`、`ikev2-cert`（`ikev2-acme`）、`Ttyd`（`ttyd`）因仓库仍为 `PRIVATE`，已在 `catalog_sources.json` 中标记为 `"visibility": "private_pending"`，未写入 `plugins.json` 及 `icons/`。

---

## 3. 自动化测试与脱敏审计

- **离线镜像探测自检**：`python3 scripts/verify_mirrors.py --offline-test --json` 通过（`passed: true`，`raw_ok: 7 >= 1`，`release_ok: 6 >= 1`，`icon_ok: 7`，`range_ok: 6`，正确拦截模拟 HTTP `200` HTML 门户页并验证 TLS 1.2 / PNG / `.sha256` / gzip 魔数）。
- **单元测试与完整性套件**：`python3 -m unittest discover -s tests -p "test_*.py" -v` 共 **21** 项用例全部通过（`OK`，0 失败，0 错误）。
- **脱敏审计**：
  - `python3 scripts/public_audit.py --working-tree`：输出 `public audit passed`（退出码 `0`）。
  - `python3 scripts/public_audit.py --history HEAD`：输出 `public audit passed`（退出码 `0`）。

---

## 4. 实时镜像连通性与实机端到端验证（M4，2026-11-22）

- **构建主机外网镜像探测**（`python3 scripts/verify_mirrors.py --check-assets --json`）：
  - 在 `ikuaiapp/plugin-hub` 尚未推送至 GitHub `main`（按发布确认门控保持未推送）时，`plugins.json` 与 `icons/router_backup.png` 的 `raw`/`jsdelivr` 探测按预期返回 `404`/`403`（`raw_ok: 0`、`icon_ok: 0`）。
  - 公开 Release 资产（`config-backup`）探测：`release_ok: 4`（`gh-proxy.org`、`ghfast.top`、`cdn.gh-proxy.com`、`edgeone.gh-proxy.com` 返回 `HTTP 200` `TLSv1.2`）与 `range_ok: 4`（`cdn.gh-proxy.com`、`edgeone.gh-proxy.com`、`wget.la`、`github.com` 返回 `HTTP 206` `512` 字节 `TLSv1.2`）。
- **测试路由器实机镜像探活（6 个公开插件发布包）**：
  - 在 `iKuai 3.7.26 x64` 测试路由器上使用 `curl -4 -fSL --tlsv1.2 -r 0-511` 实测所有 6 个收录插件（`router_backup`、`fn-knock`、`docker`、`MeshCentral`、`vnt2`、`vnstat`）：每个插件均有 `3`–`4` 个中国大陆镜像节点返回 `HTTP 206` 与 gzip 魔数 `1f8b`（`ghfast.top`、`wget.la`、`cdn.gh-proxy.com`、`edgeone.gh-proxy.com`、`gh-proxy.org`），个别镜像 DNS 超时或返回 `403` 时可正常触发故障转移。
- **测试路由器实机索引拉取与安装/卸载联动**：
  - 通过局域网临时 HTTP 索引服务向路由器下发 `plugins.json` 并调用 `plugin-store v2.1.0` 的 `set_hub_url` / `refresh_hub` / `uninstall` / `install_online`：卸载 `router_backup` 后其自动进入 `online` 列表，触发 `install_online` 后由路由器经 `ghfast.top` 拉取真实 GitHub Release 压缩包（`14.52s`）、完成 SHA-256 校验与安装并从 `online` 移除、回到 `installed` 列表；随后恢复默认 `plugins.json` 源地址。
  - **推送后待补复核**：`main` 分支经仓库所有者确认并推送至 GitHub 后，需再执行一次 `python3 scripts/verify_mirrors.py --check-assets --json` 验证 `raw_ok >= 1`。
- **远程推送门控**：依据安全规则，尚未向 `origin`（`https://github.com/ikuaiapp/plugin-hub.git`）执行 `git push` 或修改 GitHub 仓库元数据，等待仓库所有者确认。
