"""Tests for scripts/public_audit.py desensitization rules."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import public_audit

ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_temp_repo(repo: Path) -> None:
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "--local", "user.name", "ikuaiapp")
    _git(repo, "config", "--local", "user.email", "ikuaiapp@users.noreply.github.com")


class PublicAuditTests(unittest.TestCase):
    def test_detects_all_sensitive_content_rules(self) -> None:
        self.assertTrue(public_audit.text_findings("doc.md", "host 192." + "168.2.252"))
        self.assertTrue(public_audit.text_findings("doc.md", "host 10." + "0.0.1"))
        self.assertTrue(public_audit.text_findings("doc.md", "host 172." + "16.10.1"))
        self.assertTrue(public_audit.text_findings("doc.md", "host 172." + "31.255.1"))
        self.assertEqual(public_audit.text_findings("doc.md", "host 172." + "15.10.1"), [])
        self.assertEqual(public_audit.text_findings("doc.md", "host 172." + "32.10.1"), [])
        self.assertTrue(public_audit.text_findings("doc.md", "ssh -p 321" + "23 user@198.51.100.1"))
        self.assertTrue(public_audit.text_findings("doc.md", "ip 13.213." + "45.152"))
        self.assertTrue(public_audit.text_findings("doc.md", "ip 47.84." + "83.155"))
        self.assertTrue(public_audit.text_findings("doc.md", "https://sub.host.150" + "99.net"))
        self.assertTrue(public_audit.text_findings("doc.md", "https://150" + "99.net"))
        self.assertTrue(public_audit.text_findings("doc.md", "pass sanjin" + "168"))
        self.assertTrue(public_audit.text_findings("doc.md", "user iks" + "shd"))
        self.assertTrue(public_audit.text_findings("doc.md", "user lihx" + "linux"))
        self.assertTrue(public_audit.text_findings("doc.md", "user lihai" + "xin"))
        self.assertTrue(public_audit.text_findings("doc.md", "path /vol" + "1/1000/4.0"))
        self.assertTrue(public_audit.text_findings("doc.md", "path /home/" + "li/work"))
        self.assertTrue(public_audit.text_findings("doc.md", "-----BEGIN RSA " + "PRIVATE KEY-----"))
        self.assertTrue(public_audit.text_findings("doc.md", "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"))
        self.assertTrue(public_audit.text_findings("doc.md", "gho_" + "1234567890"))
        self.assertTrue(public_audit.text_findings("doc.md", "github_pat_" + "1234567890"))

    def test_detects_sensitive_filenames_and_suffixes(self) -> None:
        for name in (
            "hosts.yml",
            ".env",
            "server.key",
            "cert.pem",
            "store.p12",
            "store.pfx",
            "app.sqlite",
            "app.sqlite-wal",
            "app.sqlite-shm",
            "app.sqlite-journal",
            "config.db",
            "config.db-wal",
            "config.db-shm",
            "config.db-journal",
            "data.bak",
            "data.backup",
            "bundle.tar.gz",
            "archive.tgz",
            "archive.tar",
            "archive.zip",
            "pkg.fpk",
            "pkg.ipk",
            "pkg.apk",
            "firmware.bin",
            "pgstore.bin.pkg",
            "disk.iso",
            "rootfs.xz",
            "bundle.7z",
            "bundle.rar",
            "192." + "168.2.252.txt",
            "iks" + "shd_notes.md",
            "port-321" + "23.txt",
        ):
            self.assertTrue(public_audit.filename_findings(name), f"expected sensitive filename match for {name}")

    def test_allows_rfc5737_and_example_domains(self) -> None:
        sample = "192.0.2.10 and 198.51.100.1 and 203.0.113.5 via example.com and example.org"
        self.assertEqual(public_audit.text_findings("README.md", sample), [])

    def test_worktree_and_history_scan_and_non_utf8_handling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _init_temp_repo(repo)
            shutil.copy2(ROOT / ".gitignore", repo / ".gitignore")
            (repo / "README.md").write_text("# Clean\n198.51.100.1\n", encoding="utf-8")
            self.assertEqual(public_audit.scan_worktree(repo), [])

            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "public_audit.py"), "--history", "HEAD"],
                cwd=repo,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)

            _git(repo, "add", "README.md", ".gitignore")
            _git(repo, "commit", "-m", "clean initial commit")
            self.assertEqual(public_audit.scan_history(repo, "HEAD"), [])

            (repo / "badbin").write_bytes(b"\x7fELF\x02\x01\x01\x00")
            (repo / "huge.txt").write_bytes(b"a" * (public_audit.MAX_FILE_BYTES + 1))
            (repo / "utf16.dat").write_bytes(("router 192." + "168.2.252\n").encode("utf-16"))
            (repo / "link_leak").symlink_to("/vol" + "1/1000/4.0/secret")
            wt_findings = public_audit.scan_worktree(repo)
            self.assertTrue(any("badbin: unexpected ELF binary" in item for item in wt_findings))
            self.assertTrue(any("huge.txt: oversized file" in item for item in wt_findings))
            self.assertTrue(any("utf16.dat:" in item for item in wt_findings))
            self.assertTrue(any("link_leak: local host path" in item for item in wt_findings))

            _git(repo, "add", "utf16.dat", "link_leak")
            _git(repo, "commit", "-m", "leak user iks" + "shd")
            hist_findings = public_audit.scan_history(repo, "HEAD")
            self.assertTrue(any("commit message: test credential or user" in item for item in hist_findings))
            self.assertTrue(any("utf16.dat:" in item for item in hist_findings))

    def test_icons_and_docs_pass_audit(self) -> None:
        for png in sorted((ROOT / "icons").glob("*.png")):
            raw = png.read_bytes()
            self.assertEqual(public_audit.bytes_findings(str(png.name), raw), [])
            self.assertEqual(public_audit.binary_and_size_findings(str(png.name), raw), [])

    def test_current_working_tree_passes_public_audit(self) -> None:
        if not (ROOT / ".git").exists():
            self.skipTest("git repository not initialized yet")
        self.assertEqual(public_audit.scan_worktree(ROOT), [])


if __name__ == "__main__":
    unittest.main()
