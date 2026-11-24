"""Offline tests for scripts/sync_hub.py auto-discovery, audit, and Release sync."""

from __future__ import annotations

import io
import json
import shutil
import struct
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts import build_index, sync_hub

ROOT = Path(__file__).resolve().parent.parent


def _make_png(width: int = 16, height: int = 16) -> bytes:
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"


def _add_file(tf: tarfile.TarFile, arcname: str, data: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mode = mode
    tf.addfile(info, io.BytesIO(data))


def _make_plugin_tarball(
    dest: Path,
    *,
    top_dir: str,
    name: str,
    alias: str,
    version: str,
    description: str = "Clean test plugin",
    extra_files: dict[str, bytes] | None = None,
    traversal_member: str | None = None,
) -> tuple[Path, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest, "w:gz") as tf:
        _add_file(tf, f"{top_dir}/install.sh", b"#!/bin/bash\nexit 0\n", 0o755)
        meta = json.dumps(
            {
                "name": name,
                "alias": alias,
                "version": version,
                "description": description,
                "manufacturer": "ikuaiapp",
                "releasenotes": f"Release {version}",
                "onlyOfflineInstall": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        _add_file(tf, f"{top_dir}/html/metadata.json", meta)
        _add_file(tf, f"{top_dir}/html/{name}.png", _make_png(24, 24))
        for rel, body in (extra_files or {}).items():
            _add_file(tf, f"{top_dir}/{rel}", body)
        if traversal_member:
            _add_file(tf, traversal_member, b"bad")
    return dest, build_index.sha256_file(dest)


class SyncHubTests(unittest.TestCase):
    def _setup_hub_copy(self, dest: Path) -> None:
        for fname in ("VERSION", "catalog_sources.json", "SOURCES.json", "plugins.json", "README.md", ".gitignore"):
            shutil.copy2(ROOT / fname, dest / fname)
        shutil.copytree(ROOT / "icons", dest / "icons")

    def test_auto_discovers_new_plugin_and_upgrades_existing_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hub = tmp_path / "hub"
            hub.mkdir()
            self._setup_hub_copy(hub)

            offline = tmp_path / "offline"
            (offline / "releases").mkdir(parents=True)

            # Existing plugin unchanged except new_plugin added and config-backup upgraded to v3.8
            repos = [
                {"name": "plugin-hub", "nameWithOwner": "ikuaiapp/plugin-hub", "visibility": "PUBLIC", "isArchived": False},
                {"name": "plugin-store", "nameWithOwner": "ikuaiapp/plugin-store", "visibility": "PRIVATE", "isArchived": False},
                {"name": "reinstall", "nameWithOwner": "ikuaiapp/reinstall", "visibility": "PUBLIC", "isArchived": False},
                {"name": "config-backup", "nameWithOwner": "ikuaiapp/config-backup", "visibility": "PRIVATE", "isArchived": False},
                {"name": "new-demo", "nameWithOwner": "ikuaiapp/new-demo", "visibility": "PRIVATE", "isArchived": False},
                {"name": "no-release-repo", "nameWithOwner": "ikuaiapp/no-release-repo", "visibility": "PUBLIC", "isArchived": False},
            ]
            (offline / "repos.json").write_text(json.dumps(repos), encoding="utf-8")

            # Upgrade config-backup to v3.8
            cb_asset = "config-backup-3.8-ikuai-3.7.x-x64.tar.gz"
            cb_path, cb_sha = _make_plugin_tarball(
                offline / "assets" / "config-backup" / cb_asset,
                top_dir="router_backup",
                name="router_backup",
                alias="路由远程备份",
                version="3.8",
            )
            (offline / "assets" / "config-backup" / f"{cb_asset}.sha256").write_text(
                f"{cb_sha}  {cb_asset}\n", encoding="utf-8"
            )
            (offline / "releases" / "config-backup.json").write_text(
                json.dumps(
                    {
                        "tagName": "v3.8",
                        "isDraft": False,
                        "isPrerelease": False,
                        "assets": [
                            {"name": cb_asset, "size": cb_path.stat().st_size},
                            {"name": f"{cb_asset}.sha256", "size": 90},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            # Brand-new private plugin repo new-demo -> plugin name new_demo
            nd_asset = "new-demo-1.0.0-ikuai-3.7.26-x64.tar.gz"
            nd_path, nd_sha = _make_plugin_tarball(
                offline / "assets" / "new-demo" / nd_asset,
                top_dir="new_demo",
                name="new_demo",
                alias="示例新插件",
                version="1.0.0",
            )
            (offline / "assets" / "new-demo" / f"{nd_asset}.sha256").write_text(
                f"{nd_sha}  {nd_asset}\n", encoding="utf-8"
            )
            (offline / "releases" / "new-demo.json").write_text(
                json.dumps(
                    {
                        "tagName": "v1.0.0",
                        "isDraft": False,
                        "isPrerelease": False,
                        "assets": [
                            {"name": nd_asset, "size": nd_path.stat().st_size},
                            {"name": f"{nd_asset}.sha256", "size": 90},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            initial_ver = (hub / "VERSION").read_text(encoding="utf-8").strip()
            expected_ver = sync_hub._bump_patch_version(initial_ver)
            initial_count = len(json.loads((hub / "plugins.json").read_text(encoding="utf-8"))["plugins"])
            expected_count = initial_count + 1

            summary = sync_hub.sync_hub(
                repo_root=hub,
                upload_release=True,
                bump_version=True,
                offline_dir=offline,
            )
            self.assertTrue(summary["changed"])
            self.assertEqual([x["name"] for x in summary["added"]], ["new_demo"])
            self.assertEqual([x["name"] for x in summary["updated"]], ["router_backup"])

            self.assertEqual((hub / "VERSION").read_text(encoding="utf-8").strip(), expected_ver)
            self.assertTrue((hub / "icons" / "new_demo.png").is_file())
            doc = json.loads((hub / "plugins.json").read_text(encoding="utf-8"))
            names = [p["name"] for p in doc["plugins"]]
            self.assertIn("new_demo", names)
            self.assertEqual(len(names), expected_count)
            new_entry = next(p for p in doc["plugins"] if p["name"] == "new_demo")
            self.assertEqual(
                new_entry["download_url"],
                f"https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/{nd_asset}",
            )
            self.assertEqual(new_entry["compat"], ["3.7.26"])
            readme_text = (hub / "README.md").read_text(encoding="utf-8")
            self.assertIn(f"全部 {expected_count} 款 `ikuaiapp` 插件", readme_text)
            self.assertIn(f"全部 {expected_count} 款插件", readme_text)
            self.assertIn("`new_demo` | 示例新插件 | `ikuaiapp/new-demo` | `PRIVATE`（Release 同步收录） | `1.0.0` / `v1.0.0`", readme_text)
            self.assertIn("`router_backup` | 路由远程备份 | `ikuaiapp/config-backup` | `PRIVATE`（Release 同步收录） | `3.8` / `v3.8`", readme_text)
            build_index.build_index(
                sources_path=hub / "catalog_sources.json",
                output_path=hub / "plugins.json",
                check=True,
                repo_root=hub,
            )

            # Second run with identical releases is a clean no-op
            second = sync_hub.sync_hub(
                repo_root=hub,
                upload_release=True,
                bump_version=True,
                offline_dir=offline,
            )
            self.assertFalse(second["changed"])
            self.assertEqual((hub / "VERSION").read_text(encoding="utf-8").strip(), expected_ver)

    def test_rejects_sensitive_or_traversal_tarballs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hub = tmp_path / "hub"
            hub.mkdir()
            self._setup_hub_copy(hub)

            offline = tmp_path / "offline"
            (offline / "releases").mkdir(parents=True)
            repos = [
                {"name": "bad-leak", "nameWithOwner": "ikuaiapp/bad-leak", "visibility": "PRIVATE", "isArchived": False},
            ]
            (offline / "repos.json").write_text(json.dumps(repos), encoding="utf-8")

            bad_asset = "bad-leak-1.0.0-ikuai-3.7.x-x64.tar.gz"
            bad_path, _ = _make_plugin_tarball(
                offline / "assets" / "bad-leak" / bad_asset,
                top_dir="bad_leak",
                name="bad_leak",
                alias="Leaky",
                version="1.0.0",
                extra_files={"script/test.sh": ("TOKEN=gho_" + "1234567890abcdef\n").encode("utf-8")},
            )
            (offline / "releases" / "bad-leak.json").write_text(
                json.dumps(
                    {
                        "tagName": "v1.0.0",
                        "isDraft": False,
                        "isPrerelease": False,
                        "assets": [{"name": bad_asset, "size": bad_path.stat().st_size}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(sync_hub.SyncHubError):
                sync_hub.sync_hub(repo_root=hub, offline_dir=offline)

            # Real multi-line PEM private key material is rejected, while standard LAN CIDR
            # defaults and one-line JS library PEM header strings in bundled UI are allowed.
            ok_ui_path, _ = _make_plugin_tarball(
                tmp_path / "ok_ui.tar.gz",
                top_dir="lan_app",
                name="lan_app",
                alias="LAN App",
                version="1.0.0",
                extra_files={
                    "bin/ui/app.js": (
                        "const lan=['192." + "168.0.0/16','10." + "0.0.0/8','172." + "16.0.0/12'];\n"
                        "const hdr='-----BEGIN " + "PRIVATE KEY-----';\n"
                    ).encode("utf-8"),
                    "certs/ca.pem": b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n",
                },
            )
            inspected_ok = sync_hub.inspect_plugin_tarball(ok_ui_path, asset_name="ok_ui.tar.gz")
            self.assertEqual(inspected_ok.name, "lan_app")

            real_key_path, _ = _make_plugin_tarball(
                tmp_path / "real_key.tar.gz",
                top_dir="key_leak",
                name="key_leak",
                alias="Key Leak",
                version="1.0.0",
                extra_files={
                    "certs/server.pem": (
                        "-----BEGIN RSA " + "PRIVATE KEY-----\n"
                        + ("A" * 64 + "\n") * 2
                        + "-----END RSA " + "PRIVATE KEY-----\n"
                    ).encode("utf-8"),
                },
            )
            with self.assertRaises(sync_hub.SyncHubError):
                sync_hub.inspect_plugin_tarball(real_key_path, asset_name="real_key.tar.gz")

            trav_path, _ = _make_plugin_tarball(
                tmp_path / "trav.tar.gz",
                top_dir="bad_leak",
                name="bad_leak",
                alias="Trav",
                version="1.0.0",
                traversal_member="../../etc/evil",
            )
            with self.assertRaises(sync_hub.SyncHubError):
                sync_hub.inspect_plugin_tarball(trav_path, asset_name="trav.tar.gz")


if __name__ == "__main__":
    unittest.main()
