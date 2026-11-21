# ikuaiapp/plugin-hub

**爱快（iKuai）`3.7.x` / `3.7.26` x64 公开在线插件市场索引仓库**，配合 [`ikuaiapp/plugin-store`](https://github.com/ikuaiapp/plugin-store) 使用，为中国大陆及海外路由器提供带 SHA-256 校验与多镜像回退的在线插件目录。

---

## 1. 收录范围与去重原则

本仓库**仅收录 `ikuaiapp` 名下已公开发布且可直接通过在线市场安装运行的插件**，严格避免与其它构建目录或非插件仓库重复收录：

- **已收录的公开插件（6 款）**：

| 插件内部名 (`name`) | 显示名称 (`alias`) | GitHub 仓库 | 当前版本 / Tag | 兼容固件 | 安装包大小 | 说明 |
|---|---|---|---|---|---|---|
| `router_backup` | 路由远程备份 | `ikuaiapp/config-backup` | `3.7` / `v3.7` | `3.7.x` | `47,239 B` (~46 KiB) | 定时原生配置备份与 FTP/FTPS 远程管理 |
| `fn-knock` | fn-knock | `ikuaiapp/knock` | `2.5.11` / `v2.5.11` | `3.7.x` | `32,157,989 B` (~30.7 MiB) | 端口敲门与远程安全管理 |
| `docker` | Docker容器 | `ikuaiapp/docker` | `28.5.2` / `v28.5.2` | `3.7.x` | `100,046,010 B` (~95.4 MiB) | 原生 Docker 28.5.2 与 Compose 2.39.2 |
| `MeshCentral` | MeshCentral 远程管理 | `ikuaiapp/MeshCentral` | `3.7.26` / `v3.7.26` | `3.7.26` | `125,786,787 B` (~120.0 MiB) | 路由器本机运行 MeshCentral 1.3.1 + Node 24 |
| `vnt2` | VNT 套件 | `ikuaiapp/vnt` | `3.7.26` / `v3.7.26` | `3.7.26` | `11,940,298 B` (~11.4 MiB) | VNT 2.0.11 客户端与 VNTS 2.0.9 服务端 |
| `vnstat` | vnStat 流量统计 | `ikuaiapp/vnstat` | `3.7.26` / `v3.7.26` | `3.7.26+` | `1,395,719 B` (~1.3 MiB) | WAN 出口与多接口独立账期流量统计 |

> **大体积插件提示**：`docker`（~95.4 MiB）与 `MeshCentral`（~120.0 MiB）超过原厂 iKuai `3.7.26` 的 50 MiB 默认上传限制，需配合 `plugin-store` 提供的 `128 MiB` 上传放行守护、在线安装链路或 `safe_import.sh` 使用，并确保 `/etc/log` 与 `/tmp` 拥有充足可用空间。

- **明确排除项**：
  - `ikuaiapp/reinstall`、`ikuaiapp/ikuai-plus`（VPS 刷机/重装镜像工具，非市场插件）。
  - 早期无 Release 的历史归档仓库与本地未发布构建中间产物。
  - 当前仍为 `PRIVATE` 的 3 个仓库（`system-tools`、`ikev2-acme`、`ttyd`）暂记录于 [`pending_private_plugins.md`](pending_private_plugins.md) 与 `catalog_sources.json`（`"visibility": "private_pending"`），在正式转为公开前不写入 `plugins.json`，避免未授权路由器下载出现 HTTP `404`。

---

## 2. 中国大陆加速与分支规范

- **严禁使用 `gh-pages` / `*.github.io`**：所有中国大陆公开 GitHub 代理均会拦截或不支持 `github.io` 站点，因此本仓库将 `plugins.json` 与 `icons/*.png` 直接托管在 **`main` 分支根目录**。
- **多通道镜像回退顺序**（由 `plugins.json` 中的 `mirrors` 字段下发）：
  1. **索引 JSON (`plugins.json`)**：优先遍历 `mirrors.raw` 前缀代理（`gh-proxy.org`、`ghfast.top`、`gh-proxy.com`、`wget.la`，保证实时更新无 CDN 延迟）→ `mirrors.jsdelivr`（`cdn.jsdelivr.net` / `fastly.jsdelivr.net` / `gcore.jsdelivr.net`）→ `mirrors.raw_direct`（`raw.bgithub.xyz`）→ 官方 `raw.githubusercontent.com`。
  2. **图标资源 (`icons/<name>.png`)**：优先 `mirrors.jsdelivr` → `mirrors.raw` → `mirrors.raw_direct` → 官方 `raw.githubusercontent.com`。
  3. **Release 压缩包 (`.tar.gz`)**：依次遍历 `mirrors.release` 前缀代理（`gh-proxy.org`、`ghfast.top`、`gh-proxy.com`、`cdn.gh-proxy.com`、`edgeone.gh-proxy.com`、`wget.la`）→ 官方 `github.com` 直连。
- **强制完整性校验**：下载的索引 JSON 必须通过结构化解析并拒绝代理返回的 HTTP `200` HTML 门户页；下载的 `.tar.gz` 压缩包必须严格匹配 `plugins.json` 中的 `sha256` 摘要并经 `safe_import.sh` 安全检查后方可安装。

---

## 3. 索引格式 (`plugins.json`)

```json
{
  "schema_version": 1,
  "generated_at": "2026-11-21T12:00:00Z",
  "hub_repo": "ikuaiapp/plugin-hub",
  "mirrors": {
    "raw": ["https://gh-proxy.org/", "..."],
    "release": ["https://gh-proxy.org/", "..."],
    "jsdelivr": ["https://cdn.jsdelivr.net/gh/ikuaiapp/plugin-hub@main/"],
    "raw_direct": ["https://raw.bgithub.xyz/ikuaiapp/plugin-hub/main/"]
  },
  "plugins": [
    {
      "name": "router_backup",
      "alias": "路由远程备份",
      "repo": "ikuaiapp/config-backup",
      "tag": "v3.7",
      "version": "3.7",
      "arch": ["x64"],
      "compat": ["3.7.x"],
      "description": "...",
      "asset_name": "config-backup-3.7-ikuai-3.7.x-x64.tar.gz",
      "download_url": "https://github.com/ikuaiapp/config-backup/releases/download/v3.7/config-backup-3.7-ikuai-3.7.x-x64.tar.gz",
      "sha256": "<64-hex>",
      "size": 47239,
      "icon": "icons/router_backup.png",
      "manufacturer": "ikuaiapp",
      "releasenotes": "",
      "only_offline_install": false
    }
  ]
}
```

其中 `name` 必须与插件压缩包内 `html/metadata.json` 的 `.name` 字段**逐字一致**，以便 `plugin-store` 实现“已安装插件 ↔ 在线市场列表”的准确隐藏与卸载还原联动。

---

## 4. 快速校验

```bash
python3 scripts/build_index.py --check
python3 scripts/verify_mirrors.py --offline-test --json
python3 -m unittest discover -s tests -p "test_*.py" -v
python3 scripts/public_audit.py --working-tree
python3 scripts/public_audit.py --history HEAD
```

---

## 5. 仓库文档导航

- [`AGENTS.md`](AGENTS.md) — 面向 AI Agent 的架构规范、平台约束、测试与脱敏发布门禁（英文）
- [`MAINTAINERS.md`](MAINTAINERS.md) — 维护者构建、探测、升级与发版检查单（中文）
- [`pending_private_plugins.md`](pending_private_plugins.md) — 待公开私有插件追踪及转正上架流程
- [`CHANGELOG.md`](CHANGELOG.md) — 版本变更记录
- [`VALIDATION.md`](VALIDATION.md) — 脱敏验证报告与环境覆盖说明
