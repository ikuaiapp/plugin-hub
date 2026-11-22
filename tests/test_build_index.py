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

    def test_rejects_traversal_bad_mirrors_bad_png_ihdr_and_sync_icons_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root)
            base = json.loads(sources_path.read_text(encoding="utf-8"))

            cases: list[tuple[str, dict]] = []
            for label, field, bad_val in (
                ("repo traversal", "repo", "ikuaiapp/../../evil"),
                ("repo empty slug", "repo", "ikuaiapp/"),
                ("tag traversal", "tag", "../v1"),
                ("asset traversal", "asset_name", "../../evil.tar.gz"),
            ):
                mut = copy.deepcopy(base)
                mut["sources"][0][field] = bad_val
                cases.append((label, mut))

            for label, bad_mirror in (
                ("github.io mirror", "https://evil.github.io/"),
                ("hostless mirror", "https:///"),
                ("space in mirror", "https://evil.com/a b/"),
                ("userinfo in mirror", "https://user:pass@evil.com/"),
            ):
                mut = copy.deepcopy(base)
                mut["mirrors"]["raw"] = [bad_mirror]
                cases.append((label, mut))

            for label, mut in cases:
                with self.subTest(label=label):
                    sources_path.write_text(json.dumps(mut), encoding="utf-8")
                    with self.assertRaises(build_index.BuildIndexError):
                        build_index.build_index(sources_path=sources_path, output_path=out_path, repo_root=root)

            # Malformed PNG: 24-byte truncated and IHDR length=0
            sources_path.write_text(json.dumps(base), encoding="utf-8")
            (root / "icons" / "demo_app.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 16, 16)
            )
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(sources_path=sources_path, output_path=out_path, repo_root=root)

            (root / "icons" / "demo_app.png").write_bytes(
                b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 0) + b"IHDR" + struct.pack(">IIBBBBB", 16, 16, 8, 6, 0, 0, 0) + b"\x00" * 4
            )
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(sources_path=sources_path, output_path=out_path, repo_root=root)

            # local_source traversal and --sync-icons symlink refusal
            src_root = root / "sibling"
            outside_dir = root / "outside_repo"
            outside_dir.mkdir(parents=True)
            plugin_dir = src_root / "demo-repo"
            (plugin_dir / "html").mkdir(parents=True)
            (plugin_dir / "releases").mkdir(parents=True)
            (plugin_dir / "html" / "metadata.json").write_text(
                json.dumps({"name": "demo_app", "alias": "Demo App", "version": "1.2.3"}),
                encoding="utf-8",
            )
            (plugin_dir / "html" / "demo_app.png").write_bytes(_make_png(16, 16))
            (plugin_dir / "releases" / "demo-1.2.3.tar.gz.sha256").write_text(
                f"{'a' * 64}  demo-1.2.3.tar.gz\n", encoding="utf-8"
            )

            trav_dir = copy.deepcopy(base)
            trav_dir["sources"][0]["local_source"] = {
                "dir": "../outside_repo",
                "metadata_relpath": "html/metadata.json",
                "icon_relpath": "html/demo_app.png",
                "sha256_relpath": "releases/demo-1.2.3.tar.gz.sha256",
            }
            sources_path.write_text(json.dumps(trav_dir), encoding="utf-8")
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(
                    sources_path=sources_path,
                    output_path=out_path,
                    source_root=src_root,
                    sync_icons=True,
                    repo_root=root,
                )

            good_src = copy.deepcopy(base)
            good_src["sources"][0]["local_source"] = {
                "dir": "demo-repo",
                "metadata_relpath": "html/metadata.json",
                "icon_relpath": "html/demo_app.png",
                "sha256_relpath": "releases/demo-1.2.3.tar.gz.sha256",
            }
            sources_path.write_text(json.dumps(good_src), encoding="utf-8")
            victim = root / "victim.txt"
            victim.write_text("KEEP", encoding="utf-8")
            icon_dest = root / "icons" / "demo_app.png"
            icon_dest.unlink()
            icon_dest.symlink_to(victim)
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(
                    sources_path=sources_path,
                    output_path=out_path,
                    source_root=src_root,
                    sync_icons=True,
                    repo_root=root,
                )
            self.assertEqual(victim.read_text(encoding="utf-8"), "KEEP")

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

    def test_release_repo_and_release_tag_override_download_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root, visibility="public")
            raw_sources = json.loads(sources_path.read_text(encoding="utf-8"))
            for entry in raw_sources["sources"]:
                entry["release_repo"] = "ikuaiapp/plugin-hub"
                entry["release_tag"] = "v1.0.0"
            sources_path.write_text(json.dumps(raw_sources), encoding="utf-8")

            requested_urls: list[str] = []

            def _fake_fetch(url: str) -> str:
                requested_urls.append(url)
                if "demo-1.2.3" in url:
                    return f"{'a' * 64}  demo-1.2.3.tar.gz\n"
                return f"{'b' * 64}  pending-0.1.0.tar.gz\n"

            doc = build_index.build_index(
                sources_path=sources_path,
                output_path=out_path,
                generated_at="2026-11-22T08:00:00Z",
                verify_remote=True,
                remote_fetcher=_fake_fetch,
                repo_root=root,
            )
            self.assertEqual(len(doc["plugins"]), 2)
            self.assertEqual(doc["plugins"][0]["repo"], "ikuaiapp/demo-repo")
            self.assertEqual(doc["plugins"][0]["tag"], "v1.2.3")
            self.assertEqual(
                doc["plugins"][0]["download_url"],
                "https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/demo-1.2.3.tar.gz",
            )
            self.assertEqual(
                doc["plugins"][0]["mirror_urls"],
                [
                    "https://gh-proxy.org/https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/demo-1.2.3.tar.gz"
                ],
            )
            self.assertEqual(doc["plugins"][1]["repo"], "ikuaiapp/pending-repo")
            self.assertEqual(doc["plugins"][1]["tag"], "v0.1.0")
            self.assertEqual(
                doc["plugins"][1]["download_url"],
                "https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/pending-0.1.0.tar.gz",
            )
            self.assertEqual(
                requested_urls,
                [
                    "https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/demo-1.2.3.tar.gz.sha256",
                    "https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/pending-0.1.0.tar.gz.sha256",
                ],
            )

    def test_rejects_invalid_release_repo_release_tag_and_symlinked_icons_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root)
            base = json.loads(sources_path.read_text(encoding="utf-8"))

            for label, field, bad_val in (
                ("non-ikuaiapp release_repo", "release_repo", "otherorg/plugin-hub"),
                ("traversal release_repo", "release_repo", "ikuaiapp/../../evil"),
                ("empty slug release_repo", "release_repo", "ikuaiapp/"),
                ("non-string release_repo", "release_repo", None),
                ("traversal release_tag", "release_tag", "../v1.0.0"),
                ("empty release_tag", "release_tag", ""),
                ("non-string release_tag", "release_tag", 123),
            ):
                mut = copy.deepcopy(base)
                mut["sources"][0][field] = bad_val
                sources_path.write_text(json.dumps(mut), encoding="utf-8")
                with self.subTest(label=label):
                    with self.assertRaises(build_index.BuildIndexError):
                        build_index.build_index(
                            sources_path=sources_path,
                            output_path=out_path,
                            repo_root=root,
                        )

            # Symlinked icons/ parent directory must be refused by --sync-icons
            sources_path.write_text(json.dumps(base), encoding="utf-8")
            src_root = root / "sibling"
            plugin_dir = src_root / "demo-repo"
            (plugin_dir / "html").mkdir(parents=True)
            (plugin_dir / "releases").mkdir(parents=True)
            (plugin_dir / "html" / "metadata.json").write_text(
                json.dumps({"name": "demo_app", "alias": "Demo App", "version": "1.2.3"}),
                encoding="utf-8",
            )
            (plugin_dir / "html" / "demo_app.png").write_bytes(_make_png(16, 16))
            (plugin_dir / "releases" / "demo-1.2.3.tar.gz.sha256").write_text(
                f"{'a' * 64}  demo-1.2.3.tar.gz\n", encoding="utf-8"
            )
            mut_src = copy.deepcopy(base)
            mut_src["sources"][0]["local_source"] = {
                "dir": "demo-repo",
                "metadata_relpath": "html/metadata.json",
                "icon_relpath": "html/demo_app.png",
                "sha256_relpath": "releases/demo-1.2.3.tar.gz.sha256",
            }
            sources_path.write_text(json.dumps(mut_src), encoding="utf-8")
            evil_dir = root / "evil_icons_dir"
            evil_dir.mkdir()
            import shutil as _shutil

            _shutil.rmtree(root / "icons")
            (root / "icons").symlink_to(evil_dir)
            with self.assertRaises(build_index.BuildIndexError):
                build_index.build_index(
                    sources_path=sources_path,
                    output_path=out_path,
                    source_root=src_root,
                    sync_icons=True,
                    repo_root=root,
                )

    def test_rejects_trailing_newline_in_regex_validated_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sources_path, out_path = self._create_fixture_repo(root)
            base = json.loads(sources_path.read_text(encoding="utf-8"))
            base["sources"][0]["release_repo"] = "ikuaiapp/plugin-hub"
            base["sources"][0]["release_tag"] = "v1.0.0"

            newline_cases = (
                ("name", "demo_app\n"),
                ("repo", "ikuaiapp/demo-repo\n"),
                ("release_repo", "ikuaiapp/plugin-hub\n"),
                ("tag", "v1.2.3\n"),
                ("release_tag", "v1.0.0\n"),
                ("asset_name", "demo-1.2.3.tar.gz\n"),
                ("sha256", ("a" * 64) + "\n"),
            )
            for field, bad_val in newline_cases:
                with self.subTest(field=field):
                    mut = copy.deepcopy(base)
                    mut["sources"][0][field] = bad_val
                    sources_path.write_text(json.dumps(mut), encoding="utf-8")
                    with self.assertRaises(build_index.BuildIndexError):
                        build_index.build_index(
                            sources_path=sources_path,
                            output_path=out_path,
                            repo_root=root,
                        )


if __name__ == "__main__":
    unittest.main()
