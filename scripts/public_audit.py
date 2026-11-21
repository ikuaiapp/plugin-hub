#!/usr/bin/env python3
"""Block accidental publication of router-specific data, secrets, binaries, archives, and local paths."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024
ELF_MAGIC = b"\x7fELF"

CONTENT_RULES = (
    ("private RFC1918 192.168 IP", re.compile(r"\b192[.]168[.]\d{1,3}[.]\d{1,3}\b", re.ASCII)),
    ("private RFC1918 10.x IP", re.compile(r"\b10[.]\d{1,3}[.]\d{1,3}[.]\d{1,3}\b", re.ASCII)),
    ("private RFC1918 172.16-31 IP", re.compile(r"\b172[.](?:1[6-9]|2\d|3[01])[.]\d{1,3}[.]\d{1,3}\b", re.ASCII)),
    ("test router SSH port", re.compile(r"\b321" + r"23\b", re.ASCII)),
    (
        "legacy incident IP",
        re.compile(r"\b(?:13[.]213" + r"[.]45[.]152|47[.]84" + r"[.]83[.]155)\b", re.ASCII),
    ),
    ("private domain", re.compile(r"(?:[A-Za-z0-9-]+[.])*150" + r"99[.]net", re.IGNORECASE | re.ASCII)),
    (
        "test credential or user",
        re.compile(
            r"(?:sanjin" + r"168|iks" + r"shd|lihx" + r"linux|lihai" + r"xin)",
            re.IGNORECASE | re.ASCII,
        ),
    ),
    ("local host path", re.compile(r"(?:/vol" + r"1/1000|/home/" + r"li\b)", re.ASCII)),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z ]+ )?" + r"PRIVATE KEY(?: BLOCK)?-----", re.ASCII)),
    ("GitHub token", re.compile(r"(?:gh[opsu]|github_pat)_[A-Za-z0-9_]{8,}", re.ASCII)),
)
SENSITIVE_FILENAMES = {"hosts.yml", ".env"}
SENSITIVE_SUFFIXES = {
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite-journal",
    ".sqlite3",
    ".sqlite3-wal",
    ".sqlite3-shm",
    ".sqlite3-journal",
    ".db",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".bak",
    ".backup",
    ".env",
    ".tgz",
    ".gz",
    ".tar",
    ".zip",
    ".fpk",
    ".ipk",
    ".apk",
    ".bin",
    ".pkg",
    ".iso",
    ".xz",
    ".7z",
    ".rar",
}


def _display_safe(text: str) -> str:
    return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")


def run_git_bytes(root: Path, *args: str | bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True)


def find_root(path: Path | None = None) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=path,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError("must be run inside a Git repository")
    return Path(os.fsdecode(result.stdout.rstrip(b"\r\n")))


def text_findings(label: str, text: str) -> list[str]:
    safe_label = _display_safe(label)
    return [safe_label + ": " + name for name, pattern in CONTENT_RULES if pattern.search(text)]


def filename_findings(label: str, *, rel_path: str | None = None) -> list[str]:
    safe_label = _display_safe(label)
    rel = safe_label if rel_path is None else _display_safe(rel_path)
    path = Path(rel)
    findings: list[str] = []
    if path.name.lower() in SENSITIVE_FILENAMES or path.suffix.lower() in SENSITIVE_SUFFIXES:
        findings.append(safe_label + ": sensitive filename")
    for name, pattern in CONTENT_RULES:
        if pattern.search(rel):
            findings.append(f"{safe_label}: sensitive filename ({name})")
    return findings


def bytes_findings(label: str, raw_bytes: bytes) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()

    def _record(items: list[str]) -> None:
        for item in items:
            if item not in seen:
                seen.add(item)
                findings.append(item)

    _record(text_findings(label, raw_bytes.decode("utf-8", errors="replace")))
    if b"\x00" in raw_bytes:
        _record(text_findings(label, raw_bytes.decode("utf-16-le", errors="ignore")))
        _record(text_findings(label, raw_bytes.decode("utf-16-be", errors="ignore")))
        _record(text_findings(label, raw_bytes[1:].decode("utf-16-le", errors="ignore")))
        _record(text_findings(label, raw_bytes[1:].decode("utf-16-be", errors="ignore")))
        _record(text_findings(label, raw_bytes.replace(b"\x00", b"").decode("latin-1", errors="replace")))
    return findings


def binary_and_size_findings(label: str, raw_bytes: bytes, *, size: int | None = None) -> list[str]:
    safe_label = _display_safe(label)
    findings: list[str] = []
    actual_size = len(raw_bytes) if size is None else size
    if actual_size > MAX_FILE_BYTES:
        findings.append(f"{safe_label}: oversized file ({actual_size} bytes > {MAX_FILE_BYTES})")
    if raw_bytes.startswith(ELF_MAGIC):
        findings.append(f"{safe_label}: unexpected ELF binary")
    return findings


def scan_worktree(root: Path) -> list[str]:
    result = run_git_bytes(root, "-c", "core.quotePath=false", "ls-files", "-co", "--exclude-standard", "-z")
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    findings: list[str] = []
    for raw_path in result.stdout.split(b"\x00"):
        if not raw_path:
            continue
        fs_relative = os.fsdecode(raw_path)
        display_relative = _display_safe(raw_path.decode("utf-8", errors="surrogateescape"))
        findings.extend(filename_findings(display_relative, rel_path=display_relative))
        path = root / fs_relative
        if path.is_symlink():
            findings.extend(text_findings(display_relative, os.readlink(path)))
            continue
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            findings.append(f"{display_relative}: oversized file ({size} bytes > {MAX_FILE_BYTES})")
            with path.open("rb") as stream:
                if stream.read(len(ELF_MAGIC)) == ELF_MAGIC:
                    findings.append(f"{display_relative}: unexpected ELF binary")
            continue
        raw_bytes = path.read_bytes()
        if raw_bytes.startswith(ELF_MAGIC):
            findings.append(f"{display_relative}: unexpected ELF binary")
            continue
        findings.extend(bytes_findings(display_relative, raw_bytes))
    return findings


def scan_history(root: Path, revision: str) -> list[str]:
    commits = run_git_bytes(root, "rev-list", revision)
    if commits.returncode != 0:
        raise RuntimeError(commits.stderr.decode("utf-8", errors="replace").strip())
    findings: list[str] = []
    for commit_bytes in commits.stdout.splitlines():
        if not commit_bytes:
            continue
        commit = commit_bytes.decode("ascii")
        message = run_git_bytes(root, "show", "-s", "--format=%B", commit)
        if message.returncode != 0:
            raise RuntimeError(message.stderr.decode("utf-8", errors="replace").strip())
        findings.extend(bytes_findings(commit + ": commit message", message.stdout))
        listing = run_git_bytes(
            root, "-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", "-z", commit
        )
        if listing.returncode != 0:
            raise RuntimeError(listing.stderr.decode("utf-8", errors="replace").strip())
        for raw_path in listing.stdout.split(b"\x00"):
            if not raw_path:
                continue
            display_relative = _display_safe(raw_path.decode("utf-8", errors="surrogateescape"))
            label = commit[:12] + ":" + display_relative
            findings.extend(filename_findings(label, rel_path=display_relative))
            blob = run_git_bytes(root, "show", commit_bytes + b":" + raw_path)
            if blob.returncode != 0:
                raise RuntimeError(blob.stderr.decode("utf-8", errors="replace").strip())
            raw_bytes = blob.stdout
            findings.extend(binary_and_size_findings(label, raw_bytes))
            if raw_bytes.startswith(ELF_MAGIC) or len(raw_bytes) > MAX_FILE_BYTES:
                continue
            findings.extend(bytes_findings(label, raw_bytes))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working-tree", action="store_true", help="scan tracked and non-ignored worktree files")
    parser.add_argument("--history", metavar="REVISION", help="scan a revision and all of its ancestors")
    args = parser.parse_args()
    if not args.working_tree and not args.history:
        args.working_tree = True
    try:
        root = find_root()
        findings = []
        if args.working_tree:
            findings.extend(scan_worktree(root))
        if args.history:
            findings.extend(scan_history(root, args.history))
    except RuntimeError as exc:
        print("public audit error: " + _display_safe(str(exc)), file=sys.stderr)
        return 2
    if findings:
        print("public audit failed; do not publish:", file=sys.stderr)
        for finding in findings:
            print("- " + _display_safe(finding), file=sys.stderr)
        return 1
    print("public audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
