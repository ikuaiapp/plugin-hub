"""Catalog integrity and sibling workspace parity tests for plugin-hub."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from scripts import build_index

ROOT = Path(__file__).resolve().parent.parent
SIBLING_3726 = ROOT.parent / "3.7.26"

EXPECTED_PUBLIC_NAMES = [
    "router_backup",
    "fn-knock",
    "docker",
    "MeshCentral",
    "vnt2",
    "vnstat",
    "system-tools",
    "ikev2-cert",
    "Ttyd",
]
EXPECTED_PRIVATE_NAMES: list[str] = []
EXPECTED_PRIVATE_SOURCE_REPOS = {
    "system-tools": "ikuaiapp/system-tools",
    "ikev2-cert": "ikuaiapp/ikev2-acme",
    "Ttyd": "ikuaiapp/ttyd",
}
EXCLUDED_REPOS = {
    "ikuaiapp/reinstall",
    "ikuaiapp/ikuai-plus",
    "ikuaiapp/plugin-store",
    "ikuaiapp/plugin-hub",
}


class CatalogIntegrityTests(unittest.TestCase):
    def test_plugins_json_matches_contract_and_public_set(self) -> None:
        doc = json.loads((ROOT / "plugins.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["hub_repo"], "ikuaiapp/plugin-hub")
        self.assertRegex(doc["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        mirrors = doc["mirrors"]
        for key in ("raw", "release", "jsdelivr", "raw_direct"):
            self.assertIsInstance(mirrors[key], list)
            self.assertTrue(mirrors[key], f"mirrors.{key} must be non-empty")
            for url in mirrors[key]:
                self.assertTrue(url.startswith("https://") and url.endswith("/"))
                self.assertNotIn("github.io", url)

        plugins = doc["plugins"]
        catalog_sources = json.loads((ROOT / "catalog_sources.json").read_text(encoding="utf-8"))
        expected_public_from_sources = [
            s["name"] for s in catalog_sources["sources"] if s.get("visibility") == "public"
        ]
        self.assertEqual([p["name"] for p in plugins], expected_public_from_sources)
        self.assertTrue(set(EXPECTED_PUBLIC_NAMES).issubset(expected_public_from_sources))

        required_keys = {
            "name",
            "alias",
            "repo",
            "tag",
            "version",
            "arch",
            "compat",
            "description",
            "asset_name",
            "download_url",
            "mirror_urls",
            "sha256",
            "size",
            "icon",
        }
        for plugin in plugins:
            self.assertTrue(required_keys.issubset(plugin.keys()))
            self.assertNotIn(plugin["name"], EXPECTED_PRIVATE_NAMES)
            self.assertNotIn(plugin["repo"], EXCLUDED_REPOS)
            self.assertRegex(plugin["name"], build_index.NAME_RE)
            self.assertRegex(plugin["sha256"], build_index.SHA256_RE)
            self.assertGreater(plugin["size"], 0)
            expected_dl = (
                f"https://github.com/ikuaiapp/plugin-hub/releases/download/v1.0.0/{plugin['asset_name']}"
            )
            self.assertEqual(plugin["download_url"], expected_dl)
            self.assertEqual(
                plugin["mirror_urls"],
                [f"{prefix}{expected_dl}" for prefix in mirrors["release"]],
            )
            self.assertFalse(re.search(r"[\ufeff\u200b\u200c\u200d]", plugin["description"]))
            self.assertIsInstance(plugin["only_offline_install"], bool)

    def test_icons_directory_contains_only_valid_public_regular_pngs(self) -> None:
        catalog_sources = json.loads((ROOT / "catalog_sources.json").read_text(encoding="utf-8"))
        public_names = [
            s["name"] for s in catalog_sources["sources"] if s.get("visibility") == "public"
        ]
        icon_files = sorted(p.name for p in (ROOT / "icons").iterdir())
        expected_files = sorted(f"{name}.png" for name in public_names)
        self.assertEqual(icon_files, expected_files)
        for fname in expected_files:
            path = ROOT / "icons" / fname
            self.assertFalse(path.is_symlink(), f"{fname} must not be a symlink")
            build_index.validate_png_file(path, fname)

    def test_repo_metadata_files_are_consistent(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, r"^\d+\.\d+\.\d+$")

        gh_meta = json.loads((ROOT / "GITHUB_METADATA.json").read_text(encoding="utf-8"))
        self.assertEqual(gh_meta["repo"], "ikuaiapp/plugin-hub")
        self.assertEqual(gh_meta["default_branch"], "main")
        self.assertEqual(gh_meta["visibility"], "public")
        self.assertNotIn("github.io", gh_meta["homepage"])
        self.assertLessEqual(len(gh_meta["topics"]), 20)

        catalog_sources = json.loads((ROOT / "catalog_sources.json").read_text(encoding="utf-8"))
        expected_public_from_sources = [
            s["name"] for s in catalog_sources["sources"] if s.get("visibility") == "public"
        ]
        expected_private_from_sources = [
            s["name"] for s in catalog_sources["sources"] if s.get("visibility") == "private_pending"
        ]

        sources_doc = json.loads((ROOT / "SOURCES.json").read_text(encoding="utf-8"))
        self.assertEqual(sources_doc["target"]["catalog_version"], version)
        self.assertEqual(sources_doc["target"]["hosting_branch"], "main")
        self.assertEqual(list(sources_doc["upstream"]["plugins"].keys()), expected_public_from_sources)
        self.assertEqual(
            sources_doc["upstream"]["pending_private_repos"],
            [s["repo"] for s in catalog_sources["sources"] if s.get("visibility") == "private_pending"],
        )
        for pname, expected_repo in EXPECTED_PRIVATE_SOURCE_REPOS.items():
            self.assertEqual(sources_doc["upstream"]["plugins"][pname]["repo"], expected_repo)
            self.assertEqual(sources_doc["upstream"]["plugins"][pname]["source_visibility"], "private")

        self.assertTrue(set(EXPECTED_PUBLIC_NAMES).issubset(expected_public_from_sources))
        self.assertEqual(expected_private_from_sources, EXPECTED_PRIVATE_NAMES)

    def test_jq_parses_plugins_json_when_available(self) -> None:
        jq_bin = shutil.which("jq")
        if jq_bin is None:
            self.skipTest("jq not installed on host")
        proc = subprocess.run(
            [jq_bin, "-e", ".schema_version == 1 and (.plugins | length) >= 9", str(ROOT / "plugins.json")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_cross_check_against_sibling_3726_repos(self) -> None:
        if not SIBLING_3726.is_dir():
            self.skipTest("sibling ../3.7.26 workspace not present")
        catalog_sources = json.loads((ROOT / "catalog_sources.json").read_text(encoding="utf-8"))
        for entry in catalog_sources["sources"]:
            local = entry.get("local_source")
            if not isinstance(local, dict):
                continue
            repo_dir = SIBLING_3726 / local["dir"]
            self.assertTrue(repo_dir.is_dir(), f"missing sibling repo {repo_dir}")

            metadata = json.loads((repo_dir / local["metadata_relpath"]).read_text(encoding="utf-8"))
            self.assertEqual(metadata["name"], entry["name"])
            self.assertEqual(metadata["version"], entry["version"])

            sha_text = (repo_dir / local["sha256_relpath"]).read_text(encoding="utf-8")
            digest, asset = build_index.parse_sha256_sidecar(sha_text, local["sha256_relpath"])
            self.assertEqual(digest, entry["sha256"])
            self.assertEqual(asset, entry["asset_name"])

            tarball = repo_dir / "releases" / entry["asset_name"]
            self.assertTrue(tarball.is_file(), f"missing tarball {tarball}")
            self.assertEqual(tarball.stat().st_size, entry["size"])

            src_icon = repo_dir / local["icon_relpath"]
            self.assertFalse(src_icon.is_symlink(), f"source icon must not be symlink: {src_icon}")
            if entry["visibility"] == "public":
                self.assertEqual(
                    (ROOT / entry["icon"]).read_bytes(),
                    src_icon.read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
