# 待公开私有插件记录（Pending Private Plugins）

本文件记录 `ikuaiapp` 组织下**已存在可用 Release、但当前 GitHub 仓库可见性仍为 `PRIVATE` 的插件**。

由于未登录的路由器与中国大陆公开镜像无法下载私有仓库的 Release 资产（会返回 HTTP `404`），`catalog_sources.json` 将以下条目标记为 `"visibility": "private_pending"`，在仓库未正式公开前**禁止写入 `plugins.json`，也不在 `icons/` 中提前暴露图标资源**。

---

## 1. 待公开插件清单

| 插件内部名 (`metadata.json.name`) | 仓库 (`ikuaiapp/*`) | 最新 Tag | Release 资产名 | 字节大小 | SHA-256 | 兼容固件 | 阻塞原因 |
|---|---|---|---|---|---|---|---|
| `system-tools` | `ikuaiapp/system-tools` | `v1.1.9` | `system-tools-1.1.9-ikuai-3.7.x-x64.tar.gz` | `284169` | `c50c5f79ff26b144db52f807e2e2fc5d77f3243547ff575351270e25401e40f6` | `3.7.x` | 仓库当前为 `PRIVATE`，公开镜像不可访问 |
| `ikev2-cert` | `ikuaiapp/ikev2-acme` | `v3.1.7` | `ikev2-acme-3.1.7-ikuai-3.7.x-x64.tar.gz` | `113141` | `dd60e3b0b5cf83a3d32f9f4e859019b6a0d252c85b79da4dc5ac0d5e246fcfa6` | `3.7.x` | 仓库当前为 `PRIVATE`，公开镜像不可访问 |
| `Ttyd` | `ikuaiapp/ttyd` | `v1.7.7` | `ttyd-1.7.7-ikuai-3.7.x-x64.tar.gz` | `930568` | `98da2f68cd5959dedb1c7059d364b00dd54e5997fd0e13a23d5da9665c8a9e2f` | `3.7.x` | 仓库当前为 `PRIVATE`，公开镜像不可访问 |

---

## 2. 转正上架检查单（仓库转为 `PUBLIC` 后执行）

当仓库所有者明确将上述任意仓库切换为 `PUBLIC` 后，按以下顺序操作：

1. **确认远程公开可达**：
   - 使用匿名 `curl -4 -fSLI --tlsv1.2` 或 `gh repo view ikuaiapp/<repo> --json visibility` 确认仓库及对应 Release `.tar.gz` / `.sha256` 无需认证即可下载。
2. **拷贝常规 PNG 图标**：
   - 从上游仓库提取 `<name>.png`（必须为常规文件，禁止软链接，大小 `<= 1 MiB`）复制到 `icons/<name>.png`（或在运行 `build_index.py` 时附带 `--source-root <sibling-3.7.26-dir> --sync-icons`）。
3. **切换 `catalog_sources.json` 可见性**：
   - 将对应条目的 `"visibility"` 从 `"private_pending"` 修改为 `"public"`，并核对 `tag`、`version`、`asset_name`、`sha256`、`size` 与最新公开 Release 一致。
4. **重新生成并校验索引**：
   ```bash
   python3 scripts/build_index.py --source-root ../3.7.26
   python3 scripts/verify_mirrors.py --check-assets --json
   python3 -m unittest discover -s tests -p "test_*.py" -v
   python3 scripts/public_audit.py --working-tree
   ```
5. **同步元数据与文档**：
   - 更新 `SOURCES.json`、`README.md`、`CHANGELOG.md`、`VALIDATION.md` 及 `VERSION`，并将已转正条目从本文件移除。
   - 经所有者明确确认后再提交并推送至 `main`。
