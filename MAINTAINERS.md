# 维护与构建指南

本仓库维护 **`ikuaiapp/plugin-hub`**（当前版本 **`1.0.0`**），面向 **iKuai `3.7.x` / `3.7.26` x64** 路由器及 `ikuaiapp/plugin-store` 提供公开在线插件索引与图标资源。

---

## 1. 仓库结构

- `VERSION`、`SOURCES.json`、`GITHUB_METADATA.json`：目录版本号、上游插件来源清单、待提交的 GitHub 元数据（Description / Topics）。
- `catalog_sources.json`：目录生成输入源，收录全部 9 个 `ikuaiapp` 已发布插件仓库（统一设置 `visibility: "public"`、`release_repo: "ikuaiapp/plugin-hub"`、`release_tag: "v1.0.0"` 及 `source_visibility`），仅使用相对 `local_source` 提示路径。
- `plugins.json`：由 `scripts/build_index.py` 确定性生成的在线市场索引（`schema_version: 1`，含全部 9 款插件及 `download_url` / `mirror_urls`），直接托管在 `main` 分支根目录。
- `pending_private_plugins.md`：记录 3 个上游源码保持 `PRIVATE` 的插件（`system-tools`、`ikev2-cert`、`Ttyd`）及其脱敏同步托管于 `plugin-hub` Release `v1.0.0` 的检查流程。
- `icons/*.png`：全部 9 个已收录插件的常规 PNG 图标文件（严禁软链接、严禁超过 `1 MiB`、统一取源仓库 `<name>.png`）。
- `scripts/`：
  - `build_index.py`：确定性索引构建与跨仓核验工具。
  - `verify_mirrors.py`：模拟路由器 `OpenSSL 1.0.2u` TLS 1.2 上限的镜像可达性与反 HTML 劫持探测工具。
  - `public_audit.py`：公开发布前的脱敏审计脚本（支持 `--working-tree` 与 `--history`）。
- `tests/`：纯 Python 标准库编写的离线 `unittest` 测试套件。

---

## 2. 构建、索引校验与镜像探测命令

需要 Python `3.11+` 与 `git`。在仓库根目录执行：

```bash
# 1. 独立环境校验 plugins.json 与本地 icons/
python3 scripts/build_index.py --check

# 2. 当存在同级 3.7.26 插件源码目录时，交叉校验 metadata.json / .sha256 / BUILD-MANIFEST.json / PNG 字节一致性
python3 scripts/build_index.py --source-root ../3.7.26 --check

# 3. 离线镜像探测器自检 + 全量单元测试
python3 -B scripts/verify_mirrors.py --offline-test --all-plugins --json
python3 -B -m unittest discover -s tests -p "test_*.py" -v

# 4. 有外网环境时执行真实镜像探测（含全部 9 个插件图标与 Release .tar.gz Range 魔数检查）
python3 -B scripts/verify_mirrors.py --check-assets --all-plugins --json
```

---

## 3. 新增/升级插件与发版检查单

1. **拉取上游 Release 并执行脱敏审计**：
   - 使用外置已授权 `gh` CLI 从上游 `ikuaiapp/<repo>`（无论当前为 `PUBLIC` 或 `PRIVATE`）拉取最新 Release `.tar.gz`、`.sha256`、`metadata.json` 与 `<name>.png` 到宿主机 `/tmp/` 临时目录（切勿放入本仓库）。
   - 执行 `safe_import.sh --check` 与脱敏扫描，确认压缩包内脚本、配置、压缩资源及二进制字符串不含任何敏感凭据或测试路由器信息。
2. **提取并校验常规图标**：
   - 从插件仓库提取 `<name>.png`（不要使用 `logo.png`）覆盖到 `icons/<name>.png`，或执行 `python3 -B scripts/build_index.py --source-root ../3.7.26 --sync-icons` 自动同步校验。
3. **更新 `catalog_sources.json` 并生成 `plugins.json`**：
   - 更新对应插件的 `visibility`、`source_visibility`、`release_repo`（`ikuaiapp/plugin-hub`）、`release_tag`（如 `v1.0.0`）、`tag`、`version`、`asset_name`、`sha256`、`size`（必要时更新 `compat`）。
   - 执行 `python3 -B scripts/build_index.py --source-root ../3.7.26` 重新生成 `plugins.json`。
4. **同步元数据与文档**：
   - 同步更新 `VERSION`、`SOURCES.json`、`README.md`、`CHANGELOG.md`、`VALIDATION.md`（若涉及私有源码插件则更新 `pending_private_plugins.md`）。
5. **实机与镜像回归验证**：
   - 提交并上传 `.tar.gz` + `.tar.gz.sha256` 到 `ikuaiapp/plugin-hub` Release 后，运行 `python3 -B scripts/verify_mirrors.py --check-assets --all-plugins --json`，确认所有插件均至少有 1 个 `raw`/CDN 镜像与 1 个 `release` 镜像正常通过。
   - 在脱敏测试环境确认 `plugin-store` 可从 `plugin-hub` 拉取更新后的索引、图标并完成下载安装与 SHA-256 校验。
6. **脱敏审计与人工确认门禁**：
   - 提交后运行 `python3 scripts/public_audit.py --working-tree` 与 `python3 scripts/public_audit.py --history HEAD`，确认均输出 `public audit passed`。
   - **未经仓库所有者明确确认，严禁执行 `git push`、`gh repo edit` 或发布 GitHub Release。**

---

## 4. 安全与隐私边界

- 公开仓库、提交历史与测试样例严禁包含任何内网网段（包括 `192.168.*`、`10.*`、`172.16-31.*`）、真实路由器端口、账号密码、Token、私钥、数据库或压缩包二进制；示例与测试统一使用 RFC 5737（`192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24`）及 RFC 2606（`example.com`）。
- GitHub CLI OAuth 凭证保存在仓库外持久目录（`<workspace-root>/.local-tools/gh/config`），切勿写入仓库或覆盖该目录。
