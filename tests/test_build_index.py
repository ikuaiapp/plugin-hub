"""Unit and integration tests for scripts/build_index.py."""

from __future__ import annotations

import copy
import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_index

ROOT = Path(__file__).resolve().parent.parent
SIBLING_3726 = ROOT.parent / "3.7.26"


def _make_png(width: int = 16, height: int = 16) -> bytes:
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"


class BuildIndexTests(unittest.TestCase):
    def _create_fixture_repo(self, root: Path, *, visibility: str = "private_pending") -> tuple[Path, Path]:
        (root / "icons").mkdir(parents=True, exist_ok=True)
        (root / "icons" / "demo_app.png").write_bytes(_make_png())
        (root / "icons" / "pending_app.png").write_bytes(_make_png())
        sources = {
            "schema_version": 1,
            "hub_repo": "ikuaiapp/plugin-hub",
            "mirrors": {
                "raw": ["https://gh-proxy.org/"],
                "release": ["https://gh-proxy.org/"],
                "jsdelivr": ["https://cdn.jsdelivr.net/gh/ikuaiapp/plugin-hub@main/"],
                "raw_direct": ["https://raw.bgithub.xyz/ikuaiapp/plugin-hub/main/"],
            },
            "sources": [
                {
                    "name": "demo_app",
                    "alias": "Demo App",
                    "repo": "ikuaiapp/demo-repo",
                    "visibility": "public",
                    "tag": "v1.2.3",
                    "version": "1.2.3",
                    "arch": ["x64"],
                    "compat": ["3.7.x"],
                    "description": "\u200c\ufeffClean description\u200b ",
                    "manufacturer": "ikuaiapp",
                    "releasenotes": " \u200dNote ",
                    "only_offline_install": "true",
                    "asset_name": "demo-1.2.3.tar.gz",
                    "sha256": "a" * 64,
                    "size": 1234,
                    "icon": "icons/demo_app.png",
                },
                {
                    "name": "pending_app",
                    "alias": "Pending App",
                    "repo": "ikuaiapp/pending-repo",
                    "visibility": visibility,
                    "tag": "v0.1.0",
                    "version": "0.1.0",
                    "arch": ["x64"],
                    "compat": ["3.7.x"],
                    "description": "Pending plugin",
                    "manufacturer": "ikuaiapp",
                    "releasenotes": "",
                    "only_offline_install": False,
                    "asset_name": "pending-0.1.0.tar.gz",
                    "sha256": "b" * 64,
                    "size": 5678,
                    "icon": "icons/pending_app.png",
                },
            ],
        }
        sources_path = root / "catalog_sources.json"
        sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        return sources_path, root / "plugins.json"

    def test_deterministic_double_build_with_generated_at_and_source_date_epoch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out1 = self._create_fixture_repo(root)
            out2 = root / "plugins2.json"

            build_index.build_index(
                sources_path=sources_path,
                output_path=out1,
                generated_at="2026-11-21T12:00:00Z",
                repo_root=root,
            )
            with mock.patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1795262400"}):
                build_index.build_index(
                    sources_path=sources_path,
                    output_path=out2,
                    repo_root=root,
                )

            self.assertEqual(out1.read_bytes(), out2.read_bytes())
            doc = json.loads(out1.read_text(encoding="utf-8"))
            self.assertEqual(doc["generated_at"], "2026-11-21T12:00:00Z")
            self.assertEqual(len(doc["plugins"]), 1)
            plugin = doc["plugins"][0]
            self.assertEqual(plugin["description"], "Clean description")
            self.assertEqual(plugin["releasenotes"], "Note")
            self.assertIs(plugin["only_offline_install"], True)

    def test_check_mode_passes_and_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root)
            build_index.build_index(
                sources_path=sources_path,
                output_path=out_path,
                generated_at="2026-11-21T12:00:00Z",
                repo_root=root,
            )
            build_index.build_index(
                sources_path=sources_path,
                output_path=out_path,
                check=True,
                repo_root=root,
            )

            tampered = json.loads(out_path.read_text(encoding="utf-8"))
            tampered["plugins"][0]["size"] = 99999
            out_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(
                    sources_path=sources_path,
                    output_path=out_path,
                    check=True,
                    repo_root=root,
                )

    def test_visibility_toggle_includes_or_excludes_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root, visibility="private_pending")
            doc_hidden = build_index.build_index(
                sources_path=sources_path,
                output_path=out_path,
                generated_at="2026-11-21T12:00:00Z",
                repo_root=root,
            )
            self.assertEqual([p["name"] for p in doc_hidden["plugins"]], ["demo_app"])

            raw_sources = json.loads(sources_path.read_text(encoding="utf-8"))
            raw_sources["sources"][1]["visibility"] = "public"
            sources_path.write_text(json.dumps(raw_sources, indent=2), encoding="utf-8")
            doc_public = build_index.build_index(
                sources_path=sources_path,
                output_path=out_path,
                generated_at="2026-11-21T12:00:00Z",
                repo_root=root,
            )
            self.assertEqual([p["name"] for p in doc_public["plugins"]], ["demo_app", "pending_app"])

    def test_rejects_invalid_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root)
            base = json.loads(sources_path.read_text(encoding="utf-8"))

            cases: list[tuple[str, dict]] = []

            bad_name = copy.deepcopy(base)
            bad_name["sources"][0]["name"] = "../evil"
            cases.append(("invalid name", bad_name))

            dup_name = copy.deepcopy(base)
            dup_name["sources"][1]["visibility"] = "public"
            dup_name["sources"][1]["name"] = "demo_app"
            cases.append(("duplicate name", dup_name))

            bad_sha = copy.deepcopy(base)
            bad_sha["sources"][0]["sha256"] = "xyz"
            cases.append(("bad sha256", bad_sha))

            bad_size = copy.deepcopy(base)
            bad_size["sources"][0]["size"] = 0
            cases.append(("zero size", bad_size))

            bool_size = copy.deepcopy(base)
            bool_size["sources"][0]["size"] = True
            cases.append(("bool size", bool_size))

            bad_icon_ref = copy.deepcopy(base)
            bad_icon_ref["sources"][0]["icon"] = "icons/other.png"
            cases.append(("icon mismatch", bad_icon_ref))

            for label, modified in cases:
                with self.subTest(label=label):
                    sources_path.write_text(json.dumps(modified), encoding="utf-8")
                    with self.assertRaises(build_index.BuildIndexError):
                        build_index.build_index(
                            sources_path=sources_path,
                            output_path=out_path,
                            repo_root=root,
                        )

            sources_path.write_text(json.dumps(base), encoding="utf-8")
            (root / "icons" / "demo_app.png").write_bytes(b"NOT_A_PNG")
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(sources_path=sources_path, output_path=out_path, repo_root=root)

            (root / "icons" / "demo_app.png").write_bytes(_make_png() + b"x" * (build_index.MAX_ICON_BYTES + 1))
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(sources_path=sources_path, output_path=out_path, repo_root=root)

            (root / "icons" / "demo_app.png").unlink()
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(sources_path=sources_path, output_path=out_path, repo_root=root)

    def test_verify_remote_and_sync_icons_with_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root)
            (root / "icons" / "demo_app.png").unlink()

            src_root = root / "sibling"
            plugin_dir = src_root / "demo-repo"
            (plugin_dir / "html").mkdir(parents=True)
            (plugin_dir / "releases").mkdir(parents=True)
            (plugin_dir / "html" / "metadata.json").write_text(
                json.dumps(
                    {
                        "name": "demo_app",
                        "alias": "Demo App",
                        "version": "1.2.3",
                        "description": "\u200cClean description",
                        "onlyOfflineInstall": "true",
                    }
                ),
                encoding="utf-8",
            )
            png_bytes = _make_png(32, 32)
            (plugin_dir / "html" / "demo_app.png").write_bytes(png_bytes)
            (plugin_dir / "releases" / "demo-1.2.3.tar.gz.sha256").write_text(
                f"{'a' * 64}  demo-1.2.3.tar.gz\n", encoding="utf-8"
            )
            (plugin_dir / "releases" / "BUILD-MANIFEST.json").write_text(
                json.dumps({"package": "demo-1.2.3.tar.gz", "sha256": "a" * 64, "size_bytes": 1234}),
                encoding="utf-8",
            )

            raw_sources = json.loads(sources_path.read_text(encoding="utf-8"))
            raw_sources["sources"][0]["local_source"] = {
                "dir": "demo-repo",
                "metadata_relpath": "html/metadata.json",
                "icon_relpath": "html/demo_app.png",
                "sha256_relpath": "releases/demo-1.2.3.tar.gz.sha256",
                "manifest_relpath": "releases/BUILD-MANIFEST.json",
            }
            sources_path.write_text(json.dumps(raw_sources), encoding="utf-8")

            build_index.build_index(
                sources_path=sources_path,
                output_path=out_path,
                source_root=src_root,
                generated_at="2026-11-21T12:00:00Z",
                sync_icons=True,
                verify_remote=True,
                remote_fetcher=lambda _url: f"{'a' * 64}  demo-1.2.3.tar.gz\n",
                repo_root=root,
            )
            self.assertEqual((root / "icons" / "demo_app.png").read_bytes(), png_bytes)

            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(
                    sources_path=sources_path,
                    output_path=out_path,
                    source_root=src_root,
                    verify_remote=True,
                    remote_fetcher=lambda _url: f"{'f' * 64}  demo-1.2.3.tar.gz\n",
                    repo_root=root,
                )

    def test_cli_error_exits_nonzero_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_sources = Path(tmp) / "missing.json"
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "build_index.py"), "--sources", str(missing_sources)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("build_index error:", proc.stderr)

    def test_real_repo_check_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_index.py"), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        if SIBLING_3726.is_dir():
            proc_src = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_index.py"),
                    "--source-root",
                    str(SIBLING_3726),
                    "--check",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_src.returncode, 0, proc_src.stderr)


if __name__ == "__main__":
    unittest.main()
