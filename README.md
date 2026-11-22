# ikuaiapp/plugin-hub

**爱快（iKuai）`3.7.x` / `3.7.26` x64 公开在线插件市场索引仓库**，配合 [`ikuaiapp/plugin-store`](https://github.com/ikuaiapp/plugin-store) 使用，为中国大陆及海外路由器提供带 SHA-256 校验与多镜像回退的在线插件目录。

---

## 1. 收录范围与去重原则

本仓库**仅收录 `ikuaiapp` 名下已公开发布且可直接通过在线市场安装运行的插件**，严格避免与其它构建目录或非插件仓库重复收录：

- **已收录的插件（全部 9 款 `ikuaiapp` 插件，统一托管于 `ikuaiapp/plugin-hub` Release `v1.0.0`）**：

| 插件内部名 (`name`) | 显示名称 (`alias`) | 上游源码仓库 (`repo`) | 源码可见性 | 当前版本 / Tag | 兼容固件 | 安装包大小 | 说明 |
|---|---|---|---|---|---|---|---|
| `router_backup` | 路由远程备份 | `ikuaiapp/config-backup` | `PUBLIC` | `3.7` / `v3.7` | `3.7.x` | `47,239 B` (~46 KiB) | 定时原生配置备份与 FTP/FTPS 远程管理 |
| `fn-knock` | fn-knock | `ikuaiapp/knock` | `PUBLIC` | `2.5.11` / `v2.5.11` | `3.7.x` | `32,157,989 B` (~30.7 MiB) | 端口敲门与远程安全管理 |
| `docker` | Docker容器 | `ikuaiapp/docker` | `PUBLIC` | `28.5.2` / `v28.5.2` | `3.7.x` | `100,046,010 B` (~95.4 MiB) | 原生 Docker 28.5.2 与 Compose 2.39.2 |
| `MeshCentral` | MeshCentral 远程管理 | `ikuaiapp/MeshCentral` | `PUBLIC` | `3.7.26` / `v3.7.26` | `3.7.26` | `125,786,787 B` (~120.0 MiB) | 路由器本机运行 MeshCentral 1.3.1 + Node 24 |
| `vnt2` | VNT 套件 | `ikuaiapp/vnt` | `PUBLIC` | `3.7.26` / `v3.7.26` | `3.7.26` | `11,940,298 B` (~11.4 MiB) | VNT 2.0.11 客户端与 VNTS 2.0.9 服务端 |
| `vnstat` | vnStat 流量统计 | `ikuaiapp/vnstat` | `PUBLIC` | `3.7.26` / `v3.7.26` | `3.7.26+` | `1,395,719 B` (~1.3 MiB) | WAN 出口与多接口独立账期流量统计 |
| `system-tools` | 系统工具 | `ikuaiapp/system-tools` | `PRIVATE`（Release 同步收录） | `1.1.9` / `v1.1.9` | `3.7.x` | `284,169 B` (~278 KiB) | 系统安全加固、官方外联屏蔽、体验企业版切换与路由 ID 管理 |
| `ikev2-cert` | IKEv2证书申请 | `ikuaiapp/ikev2-acme` | `PRIVATE`（Release 同步收录） | `3.1.7` / `v3.1.7` | `3.7.x` | `113,141 B` (~110 KiB) | 腾讯云 DNSPod / Cloudflare DNS 验证 IKEv2 证书申请与续期 |
| `Ttyd` | Ttyd终端 | `ikuaiapp/ttyd` | `PRIVATE`（Release 同步收录） | `1.7.7` / `v1.7.7` | `3.7.x` | `930,568 B` (~909 KiB) | 基于路由器会话鉴权与 Unix Socket 隔离的 Web TTY 终端 |

> **大体积插件提示**：`docker`（~95.4 MiB）与 `MeshCentral`（~120.0 MiB）超过原厂 iKuai `3.7.26` 的 50 MiB 默认上传限制，需配合 `plugin-store` 提供的 `128 MiB` 上传放行守护、在线安装链路或 `safe_import.sh` 使用，并确保 `/etc/log` 与 `/tmp` 拥有充足可用空间。

- **统一公开分发与明确排除项**：
  - 全部 9 款插件的 `.tar.gz` 与 `.tar.gz.sha256` 均经脱敏及 `safe_import.sh --check` 审计后统一托管于公开仓库 **`ikuaiapp/plugin-hub` Release `v1.0.0`**（不提交大体积压缩包到 Git 历史）；`plugins.json` 中全部 9 条 `download_url` 与 `mirror_urls` 均指向 `https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/...`，即使上游源码仓库全部保持或后续切换为 `PRIVATE`，路由器及中国大陆加速镜像仍可正常下载安装。
  - 明确排除非插件仓库：`ikuaiapp/reinstall`、`ikuaiapp/ikuai-plus`（VPS 刷机/重装镜像工具），以及早期无 Release 的历史归档与本地未发布构建中间产物。详细信息见 [`pending_private_plugins.md`](pending_private_plugins.md)。

---

## 2. 中国大陆加速与分支规范

- **严禁使用 `gh-pages` / `*.github.io`**：所有中国大陆公开 GitHub 代理均会拦截或不支持 `github.io` 站点，因此本仓库将 `plugins.json` 与 `icons/*.png` 直接托管在 **`main` 分支根目录**。
- **多通道镜像回退顺序**（由 `plugins.json` 中的 `mirrors` 字段下发）：
  1. **索引 JSON (`plugins.json`)**：优先遍历 `mirrors.raw` 前缀代理（`gh-proxy.org`、`ghfast.top`、`gh-proxy.com`、`wget.la`，保证实时更新无 CDN 延迟）→ `mirrors.jsdelivr`（`cdn.jsdelivr.net` / `fastly.jsdelivr.net` / `gcore.jsdelivr.net`）→ `mirrors.raw_direct`（`raw.bgithub.xyz`）→ 官方 `raw.githubusercontent.com`。
  2. **图标资源 (`icons/<name>.png`)**：优先 `mirrors.jsdelivr` → `mirrors.raw` → `mirrors.raw_direct` → 官方 `raw.githubusercontent.com`。
  3. **Release 压缩包 (`.tar.gz`)**：全部 9 款插件统一托管于 `ikuaiapp/plugin-hub` Release `v1.0.0`，依次遍历 `mirrors.release` 前缀代理（`gh-proxy.org`、`ghfast.top`、`gh-proxy.com`、`cdn.gh-proxy.com`、`edgeone.gh-proxy.com`、`wget.la`，对应每个插件的 `mirror_urls`）→ 官方 `github.com` 直连。
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
      "download_url": "https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/config-backup-3.7-ikuai-3.7.x-x64.tar.gz",
      "mirror_urls": [
        "https://gh-proxy.org/https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/config-backup-3.7-ikuai-3.7.x-x64.tar.gz",
        "..."
      ],
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
python3 -B scripts/build_index.py --check
python3 -B scripts/verify_mirrors.py --offline-test --all-plugins --json
python3 -B -m unittest discover -s tests -p "test_*.py" -v
python3 -B scripts/public_audit.py --working-tree
python3 -B scripts/public_audit.py --history HEAD
```

---

## 5. 云端自动定时抓取与更新（GitHub Actions）

本仓库已配置云端自动巡检工作流 [`.github/workflows/sync-hub.yml`](.github/workflows/sync-hub.yml) 与同步脚本 [`scripts/sync_hub.py`](scripts/sync_hub.py)：

- **触发方式**：
  - 每 6 小时自动定时巡检（`cron: "0 */6 * * *"`）；
  - 支持在 GitHub Actions 页面点击 **`Run workflow`**（`workflow_dispatch`）手动触发，或通过 `repository_dispatch` (`plugin-release`) 立即触发。
- **自动闭环流程**：
  1. 扫描 `ikuaiapp` 名下所有未归档仓库（支持公开与私有插件仓库，自动跳过 `plugin-hub`、`plugin-store`、`reinstall`、`ikuai-plus` 及无 Release 的仓库）；
  2. 检查每个插件仓库最新 Release 的 `.tar.gz`（比对 `tag` / `asset_name` / `.sha256` 避免重复下载）；
  3. 发现新插件或新版本后自动安全解包：校验证书/路径穿越/符号链接安全、提取 `html/metadata.json` 与 `<name>.png` 图标、并执行 `public_audit.py` 脱敏扫描；
  4. 自动上传 `.tar.gz` 与 `.sha256` 到 `ikuaiapp/plugin-hub` Release `v1.0.0`，更新 `VERSION`、`catalog_sources.json`、`SOURCES.json`、`icons/` 与 `plugins.json`，跑通全部校验与单元测试后自动提交推送至 `main` 并实测国内加速镜像。
- **Token 配置说明**：
  - 如需自动拉取您新建的**私有**插件仓库，需在 `ikuaiapp/plugin-hub` 仓库 `Settings -> Secrets and variables -> Actions` 中配置具备 `repo` 权限的 `HUB_SYNC_TOKEN` Secret（未配置时回退为 `GITHUB_TOKEN`，仅可扫描公开仓库）。

---

## 6. 仓库文档导航

- [`AGENTS.md`](AGENTS.md) — 面向 AI Agent 的架构规范、平台约束、测试与脱敏发布门禁（英文）
- [`MAINTAINERS.md`](MAINTAINERS.md) — 维护者构建、探测、升级与发版检查单（中文）
- [`pending_private_plugins.md`](pending_private_plugins.md) — 私有源码插件同步记录及统一托管说明
- [`CHANGELOG.md`](CHANGELOG.md) — 版本变更记录
- [`VALIDATION.md`](VALIDATION.md) — 脱敏验证报告与环境覆盖说明
