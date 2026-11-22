#!/usr/bin/env python3
"""Auto-discover ikuaiapp plugin releases, audit them, sync to plugin-hub Release, and rebuild plugins.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_index, public_audit  # noqa: E402

DEFAULT_ORG = "ikuaiapp"
DEFAULT_RELEASE_REPO = "ikuaiapp/plugin-hub"
DEFAULT_RELEASE_TAG = "v1.0.0"
DEFAULT_EXCLUDED_REPOS = frozenset(
    {
        "ikuaiapp/plugin-hub",
        "ikuaiapp/plugin-store",
        "ikuaiapp/reinstall",
        "ikuaiapp/ikuai-plus",
    }
)
INNER_SENSITIVE_FILENAMES = frozenset({"hosts.yml", ".env", ".netrc", "id_rsa", "id_ed25519", "id_ecdsa"})
INNER_SENSITIVE_SUFFIXES = frozenset(
    {
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
        ".env",
        ".bak",
        ".backup",
    }
)


class SyncHubError(Exception):
    """Raised when syncing plugin-hub fails due to security, audit, or command errors."""


class NonPluginReleaseError(Exception):
    """Raised when a repository release is not an installable iKuai plugin package."""


@dataclass
class InspectedPlugin:
    name: str
    alias: str
    version: str
    description: str
    manufacturer: str
    releasenotes: str
    only_offline_install: bool
    arch: list[str]
    compat: list[str]
    icon_bytes: bytes
    sha256: str
    size: int


def _validate_png_bytes(data: bytes, label: str) -> None:
    if not data:
        raise SyncHubError(f"{label}: icon file is empty")
    if len(data) > build_index.MAX_ICON_BYTES:
        raise SyncHubError(f"{label}: icon exceeds {build_index.MAX_ICON_BYTES} bytes ({len(data)} bytes)")
    if not data.startswith(build_index.PNG_MAGIC):
        raise SyncHubError(f"{label}: invalid PNG magic header")
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise SyncHubError(f"{label}: missing PNG IHDR chunk")
    ihdr_len = struct.unpack(">I", data[8:12])[0]
    if ihdr_len != 13:
        raise SyncHubError(f"{label}: invalid PNG IHDR length {ihdr_len}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise SyncHubError(f"{label}: invalid PNG dimensions {width}x{height}")


def _infer_arch_compat(asset_name: str, metadata: dict[str, Any], existing: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    arch_val = metadata.get("arch")
    if isinstance(arch_val, list) and arch_val:
        arch = [str(x).strip() for x in arch_val if str(x).strip()]
    elif isinstance(arch_val, str) and arch_val.strip():
        arch = [arch_val.strip()]
    elif existing and isinstance(existing.get("arch"), list) and existing["arch"]:
        arch = list(existing["arch"])
    else:
        arch = ["x64"]

    compat_val = metadata.get("compat")
    if isinstance(compat_val, list) and compat_val:
        compat = [str(x).strip() for x in compat_val if str(x).strip()]
    elif isinstance(compat_val, str) and compat_val.strip():
        compat = [compat_val.strip()]
    elif existing and isinstance(existing.get("compat"), list) and existing["compat"]:
        compat = list(existing["compat"])
    elif "3.7.26" in asset_name:
        compat = ["3.7.26"]
    else:
        compat = ["3.7.x"]
    return arch, compat


def _check_safe_member_path(name: str, *, is_link: bool = False, linkname: str = "") -> str:
    if not name or "\x00" in name or "\\" in name:
        raise SyncHubError(f"unsafe tar member path: {name!r}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise SyncHubError(f"control character in tar member path: {name!r}")
    cleaned = name
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if cleaned.startswith("/") or ".." in cleaned.split("/"):
        raise SyncHubError(f"path traversal in tar member: {name!r}")
    norm = posixpath.normpath(cleaned)
    if norm == "." and cleaned in ("", ".", "./"):
        return "."
    if norm.startswith("/") or norm == ".." or norm.startswith("../"):
        raise SyncHubError(f"path escapes package root: {name!r}")

    if is_link:
        if not linkname or "\x00" in linkname or linkname.startswith("/"):
            raise SyncHubError(f"unsafe link target in {name!r}: {linkname!r}")
        parent = posixpath.dirname(norm)
        joined = posixpath.normpath(posixpath.join(parent, linkname)) if parent else posixpath.normpath(linkname)
        if joined.startswith("/") or joined == ".." or joined.startswith("../"):
            raise SyncHubError(f"link target escapes package root in {name!r}: {linkname!r}")
    return norm


def _inner_filename_findings(norm_path: str) -> list[str]:
    findings: list[str] = []
    p = Path(norm_path)
    lower = p.name.lower()
    if (
        lower in INNER_SENSITIVE_FILENAMES
        or lower.startswith(".env.")
        or any(s.lower() in INNER_SENSITIVE_SUFFIXES for s in p.suffixes)
    ):
        findings.append(f"{norm_path}: sensitive filename inside plugin archive")
    for rule_name, pattern in public_audit.CONTENT_RULES:
        if pattern.search(norm_path):
            findings.append(f"{norm_path}: sensitive filename ({rule_name})")
    return findings


def inspect_plugin_tarball(
    tar_path: Path,
    *,
    asset_name: str,
    existing: dict[str, Any] | None = None,
) -> InspectedPlugin:
    if tar_path.is_symlink() or not tar_path.is_file():
        raise SyncHubError(f"tarball missing or symlinked: {tar_path}")

    actual_size = tar_path.stat().st_size
    if actual_size <= 0:
        raise SyncHubError(f"tarball is empty: {tar_path}")
    actual_sha = build_index.sha256_file(tar_path)

    has_install_sh = False
    metadata_members: list[tuple[str, tarfile.TarInfo]] = []
    reg_members: dict[str, tarfile.TarInfo] = {}
    audit_findings: list[str] = []

    try:
        with tarfile.open(tar_path, "r:gz") as tf:
            for member in tf.getmembers():
                is_link = member.issym() or member.islnk()
                norm = _check_safe_member_path(member.name, is_link=is_link, linkname=member.linkname)
                if norm == ".":
                    continue
                if member.isdev() or member.ischr() or member.isblk() or member.isfifo():
                    raise SyncHubError(f"forbidden special file in archive: {norm}")
                parts = norm.split("/")
                if norm == "install.sh" or (len(parts) == 2 and parts[1] == "install.sh"):
                    if member.isreg():
                        has_install_sh = True
                if (len(parts) == 2 and parts == ["html", "metadata.json"]) or (
                    len(parts) == 3 and parts[1:] == ["html", "metadata.json"]
                ):
                    if member.isreg():
                        metadata_members.append((norm, member))
                if member.isreg():
                    reg_members[norm] = member
                    audit_findings.extend(_inner_filename_findings(norm))
                    if member.size <= public_audit.MAX_FILE_BYTES:
                        extracted = tf.extractfile(member)
                        if extracted is not None:
                            data = extracted.read(public_audit.MAX_FILE_BYTES + 1)
                            if not data.startswith(public_audit.ELF_MAGIC):
                                audit_findings.extend(public_audit.bytes_findings(norm, data))

            if not has_install_sh or len(metadata_members) != 1:
                raise NonPluginReleaseError(
                    f"{asset_name}: not a valid iKuai plugin package (install.sh={has_install_sh}, metadata_count={len(metadata_members)})"
                )

            meta_norm, meta_member = metadata_members[0]
            meta_file = tf.extractfile(meta_member)
            if meta_file is None:
                raise SyncHubError(f"unable to read {meta_norm} from {asset_name}")
            try:
                metadata = json.loads(meta_file.read(public_audit.MAX_FILE_BYTES).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise SyncHubError(f"invalid metadata.json in {asset_name}: {exc}") from exc
            if not isinstance(metadata, dict):
                raise SyncHubError(f"metadata.json must be a JSON object in {asset_name}")

            name = build_index.strip_invisible(str(metadata.get("name", "")))
            if not build_index.NAME_RE.match(name):
                raise SyncHubError(f"invalid metadata.json name {name!r} in {asset_name}")
            version = build_index.strip_invisible(str(metadata.get("version", "")))
            if not version:
                raise SyncHubError(f"empty metadata.json version in {asset_name}")
            alias = build_index.strip_invisible(str(metadata.get("alias") or name))
            description = build_index.strip_invisible(str(metadata.get("description") or alias))
            manufacturer = build_index.strip_invisible(str(metadata.get("manufacturer", "")))
            releasenotes = build_index.strip_invisible(str(metadata.get("releasenotes", "")))
            if "onlyOfflineInstall" in metadata:
                only_offline = build_index.normalize_bool(
                    metadata["onlyOfflineInstall"], f"{name}.onlyOfflineInstall"
                )
            elif "only_offline_install" in metadata:
                only_offline = build_index.normalize_bool(
                    metadata["only_offline_install"], f"{name}.only_offline_install"
                )
            elif existing and "only_offline_install" in existing:
                only_offline = build_index.normalize_bool(
                    existing["only_offline_install"], f"{name}.only_offline_install"
                )
            else:
                only_offline = False

            html_dir = posixpath.dirname(meta_norm)
            icon_norm = posixpath.join(html_dir, f"{name}.png")
            icon_member = reg_members.get(icon_norm)
            if icon_member is None:
                raise SyncHubError(f"{asset_name}: missing regular icon file {icon_norm}")
            icon_file = tf.extractfile(icon_member)
            if icon_file is None:
                raise SyncHubError(f"{asset_name}: unable to extract {icon_norm}")
            icon_bytes = icon_file.read(build_index.MAX_ICON_BYTES + 1)
            _validate_png_bytes(icon_bytes, f"{asset_name}:{icon_norm}")

    except (tarfile.TarError, EOFError, OSError) as exc:
        raise SyncHubError(f"failed reading tarball {tar_path}: {exc}") from exc

    audit_findings.extend(
        public_audit.text_findings(
            f"{asset_name}:metadata.json",
            json.dumps(
                {
                    "name": name,
                    "alias": alias,
                    "description": description,
                    "manufacturer": manufacturer,
                    "releasenotes": releasenotes,
                },
                ensure_ascii=False,
            ),
        )
    )
    if audit_findings:
        joined = "; ".join(audit_findings[:10])
        raise SyncHubError(f"desensitization audit failed for {asset_name}: {joined}")

    arch, compat = _infer_arch_compat(asset_name, metadata, existing)
    return InspectedPlugin(
        name=name,
        alias=alias,
        version=version,
        description=description,
        manufacturer=manufacturer,
        releasenotes=releasenotes,
        only_offline_install=only_offline,
        arch=arch,
        compat=compat,
        icon_bytes=icon_bytes,
        sha256=actual_sha,
        size=actual_size,
    )


def _choose_release_asset(assets: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    tarballs = [
        a
        for a in assets
        if isinstance(a.get("name"), str)
        and a["name"].endswith(".tar.gz")
        and build_index.ASSET_RE.match(a["name"])
        and ".." not in a["name"]
    ]
    if not tarballs:
        return None
    tarballs.sort(key=lambda a: (0 if "-ikuai-" in a["name"] else 1, a["name"]))
    chosen = tarballs[0]
    sidecar_name = f"{chosen['name']}.sha256"
    sidecar = next((a for a in assets if a.get("name") == sidecar_name), None)
    return chosen, sidecar


def _bump_patch_version(version: str) -> str:
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)\Z", version.strip())
    if not m:
        raise SyncHubError(f"invalid SemVer VERSION: {version!r}")
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{major}.{minor}.{patch + 1}"


def _run_gh(gh_bin: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run([gh_bin, *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise SyncHubError(f"gh {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return proc


class _LiveProvider:
    def __init__(self, gh_bin: str) -> None:
        self.gh_bin = gh_bin

    def list_repos(self, org: str) -> list[dict[str, Any]]:
        proc = _run_gh(
            self.gh_bin,
            ["repo", "list", org, "--limit", "200", "--json", "name,nameWithOwner,visibility,isArchived"],
        )
        data = json.loads(proc.stdout)
        if not isinstance(data, list):
            raise SyncHubError("unexpected output from gh repo list")
        return data

    def get_latest_release(self, repo: str) -> dict[str, Any] | None:
        proc = _run_gh(
            self.gh_bin,
            ["release", "view", "--repo", repo, "--json", "tagName,isDraft,isPrerelease,assets"],
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").lower()
            if "release not found" in err or "not found" in err:
                return None
            raise SyncHubError(f"gh release view --repo {repo} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        doc = json.loads(proc.stdout)
        if doc.get("isDraft") or doc.get("isPrerelease"):
            return None
        return doc

    def download_asset(self, repo: str, tag: str, asset_name: str, dest_dir: Path) -> Path:
        _run_gh(
            self.gh_bin,
            [
                "release",
                "download",
                tag,
                "--repo",
                repo,
                "--pattern",
                asset_name,
                "--dir",
                str(dest_dir),
                "--clobber",
            ],
        )
        target = dest_dir / asset_name
        if not target.is_file():
            raise SyncHubError(f"downloaded asset missing: {target}")
        return target

    def upload_release_assets(self, release_repo: str, release_tag: str, files: list[Path]) -> None:
        _run_gh(
            self.gh_bin,
            [
                "release",
                "upload",
                release_tag,
                *[str(f) for f in files],
                "--repo",
                release_repo,
                "--clobber",
            ],
        )


class _OfflineProvider:
    def __init__(self, offline_dir: Path) -> None:
        self.offline_dir = offline_dir.resolve()
        self.uploaded: list[tuple[str, str, list[str]]] = []

    def list_repos(self, org: str) -> list[dict[str, Any]]:
        repos_file = self.offline_dir / "repos.json"
        if not repos_file.is_file():
            raise SyncHubError(f"missing offline repos.json: {repos_file}")
        return json.loads(repos_file.read_text(encoding="utf-8"))

    def get_latest_release(self, repo: str) -> dict[str, Any] | None:
        short_name = repo.split("/", 1)[-1]
        rel_file = self.offline_dir / "releases" / f"{short_name}.json"
        if not rel_file.is_file():
            return None
        doc = json.loads(rel_file.read_text(encoding="utf-8"))
        if doc.get("isDraft") or doc.get("isPrerelease"):
            return None
        return doc

    def download_asset(self, repo: str, tag: str, asset_name: str, dest_dir: Path) -> Path:
        short_name = repo.split("/", 1)[-1]
        src = self.offline_dir / "assets" / short_name / asset_name
        if not src.is_file():
            raise SyncHubError(f"missing offline asset: {src}")
        dst = dest_dir / asset_name
        shutil.copy2(src, dst)
        return dst

    def upload_release_assets(self, release_repo: str, release_tag: str, files: list[Path]) -> None:
        self.uploaded.append((release_repo, release_tag, [f.name for f in files]))


def _update_sources_manifest(
    manifest_path: Path,
    *,
    catalog_sources: dict[str, Any],
    catalog_version: str,
    release_repo: str,
    release_tag: str,
    icon_hashes: dict[str, str],
) -> None:
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {"target": {}, "upstream": {"plugins": {}, "mirrors": {}, "pending_private_repos": []}}

    manifest.setdefault("target", {})["catalog_version"] = catalog_version
    upstream = manifest.setdefault("upstream", {})
    plugins_map: dict[str, Any] = upstream.get("plugins", {})
    if not isinstance(plugins_map, dict):
        plugins_map = {}

    new_plugins_map: dict[str, Any] = {}
    for entry in catalog_sources["sources"]:
        if entry.get("visibility") != "public":
            continue
        pname = entry["name"]
        prev = plugins_map.get(pname, {})
        record = {
            "repo": entry["repo"],
            "source_visibility": entry.get("source_visibility", "public"),
            "release_repo": entry.get("release_repo", release_repo),
            "release_tag": entry.get("release_tag", release_tag),
            "tag": entry["tag"],
            "version": entry["version"],
            "asset_name": entry["asset_name"],
            "download_url": (
                f"https://github.com/{entry.get('release_repo', release_repo)}"
                f"/releases/download/{entry.get('release_tag', release_tag)}/{entry['asset_name']}"
            ),
            "sha256": entry["sha256"],
            "size": entry["size"],
        }
        if isinstance(prev.get("icon_source_relpath"), str):
            record["icon_source_relpath"] = prev["icon_source_relpath"]
        record["icon_sha256"] = icon_hashes.get(pname, prev.get("icon_sha256", ""))
        new_plugins_map[pname] = record

    upstream["plugins"] = new_plugins_map
    upstream["mirrors"] = catalog_sources["mirrors"]
    upstream["pending_private_repos"] = [
        entry["repo"] for entry in catalog_sources["sources"] if entry.get("visibility") == "private_pending"
    ]
    build_index._atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")


def sync_hub(
    *,
    repo_root: Path = REPO_ROOT,
    org: str = DEFAULT_ORG,
    release_repo: str = DEFAULT_RELEASE_REPO,
    release_tag: str = DEFAULT_RELEASE_TAG,
    dry_run: bool = False,
    force: bool = False,
    upload_release: bool = False,
    bump_version: bool = False,
    offline_dir: Path | None = None,
    gh_bin: str | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    sources_path = repo_root / "catalog_sources.json"
    output_path = repo_root / "plugins.json"
    manifest_path = repo_root / "SOURCES.json"
    version_path = repo_root / "VERSION"
    icons_dir = repo_root / "icons"

    catalog = build_index._load_json(sources_path, "catalog_sources.json")
    sources = catalog.get("sources")
    if not isinstance(sources, list):
        raise SyncHubError("catalog_sources.json 'sources' must be a list")

    excluded = set(DEFAULT_EXCLUDED_REPOS)
    extra_excluded = catalog.get("excluded_repos")
    if isinstance(extra_excluded, list):
        excluded.update(str(item).strip() for item in extra_excluded if str(item).strip())

    if offline_dir is not None:
        provider: _LiveProvider | _OfflineProvider = _OfflineProvider(offline_dir)
    else:
        resolved_gh = gh_bin or os.environ.get("GH_BIN", "").strip() or shutil.which("gh")
        if not resolved_gh:
            raise SyncHubError("gh CLI binary not found in PATH or GH_BIN")
        provider = _LiveProvider(resolved_gh)

    by_repo: dict[str, int] = {
        str(entry["repo"]).lower(): idx for idx, entry in enumerate(sources) if isinstance(entry, dict) and entry.get("repo")
    }

    repos = provider.list_repos(org)
    repos_sorted = sorted(
        (r for r in repos if isinstance(r, dict) and isinstance(r.get("nameWithOwner"), str)),
        key=lambda r: r["nameWithOwner"].lower(),
    )

    added: list[dict[str, str]] = []
    updated: list[dict[str, str]] = []
    visibility_updated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    metadata_changed = False

    with tempfile.TemporaryDirectory(prefix="plugin-hub-sync-") as td:
        tmp_dir = Path(td)
        for repo_info in repos_sorted:
            full_name = repo_info["nameWithOwner"]
            if full_name.lower() in {x.lower() for x in excluded}:
                skipped.append({"repo": full_name, "reason": "excluded"})
                continue
            if repo_info.get("isArchived"):
                skipped.append({"repo": full_name, "reason": "archived"})
                continue

            src_vis = "public" if str(repo_info.get("visibility", "")).upper() == "PUBLIC" else "private"
            existing_idx = by_repo.get(full_name.lower())
            existing = sources[existing_idx] if existing_idx is not None else None
            if existing is not None and existing.get("visibility") == "disabled":
                skipped.append({"repo": full_name, "reason": "disabled"})
                continue

            rel = provider.get_latest_release(full_name)
            if rel is None:
                skipped.append({"repo": full_name, "reason": "no_published_release"})
                continue

            tag_name = str(rel.get("tagName", "")).strip()
            if not tag_name or not build_index.TAG_RE.match(tag_name) or ".." in tag_name:
                skipped.append({"repo": full_name, "reason": f"invalid_tag:{tag_name}"})
                continue

            assets = rel.get("assets")
            if not isinstance(assets, list):
                skipped.append({"repo": full_name, "reason": "no_assets"})
                continue

            picked = _choose_release_asset(assets)
            if picked is None:
                skipped.append({"repo": full_name, "reason": "no_tar_gz_asset"})
                continue
            asset_info, sidecar_info = picked
            asset_name = str(asset_info["name"])
            asset_size = int(asset_info.get("size", 0))

            if existing is not None and not force:
                same_coords = (
                    existing.get("tag") == tag_name
                    and existing.get("asset_name") == asset_name
                    and existing.get("size") == asset_size
                )
                if same_coords:
                    sidecar_match = True
                    if sidecar_info is not None:
                        sidecar_file = provider.download_asset(full_name, tag_name, str(sidecar_info["name"]), tmp_dir)
                        sidecar_digest, sidecar_target = build_index.parse_sha256_sidecar(
                            sidecar_file.read_text(encoding="utf-8"), str(sidecar_file)
                        )
                        sidecar_match = (sidecar_digest == existing.get("sha256") and sidecar_target == asset_name)
                    if sidecar_match:
                        if existing.get("source_visibility") != src_vis:
                            if not dry_run:
                                existing["source_visibility"] = src_vis
                                metadata_changed = True
                            visibility_updated.append({"repo": full_name, "name": existing["name"], "source_visibility": src_vis})
                        else:
                            skipped.append({"repo": full_name, "reason": "up_to_date"})
                        continue

            tar_path = provider.download_asset(full_name, tag_name, asset_name, tmp_dir)
            if sidecar_info is not None:
                sidecar_file = provider.download_asset(full_name, tag_name, str(sidecar_info["name"]), tmp_dir)
                sidecar_digest, sidecar_target = build_index.parse_sha256_sidecar(
                    sidecar_file.read_text(encoding="utf-8"), str(sidecar_file)
                )
                if sidecar_target != asset_name or sidecar_digest != build_index.sha256_file(tar_path):
                    raise SyncHubError(f"{full_name}: upstream .sha256 verification failed for {asset_name}")

            try:
                inspected = inspect_plugin_tarball(tar_path, asset_name=asset_name, existing=existing)
            except NonPluginReleaseError as exc:
                skipped.append({"repo": full_name, "reason": f"non_plugin:{exc}"})
                continue

            if existing is None and any(
                isinstance(e, dict) and e.get("name") == inspected.name for e in sources
            ):
                raise SyncHubError(
                    f"{full_name}: plugin name {inspected.name!r} collides with existing catalog entry"
                )

            if upload_release and not dry_run:
                sha_sidecar_path = tmp_dir / f"{asset_name}.sha256"
                sha_sidecar_path.write_text(f"{inspected.sha256}  {asset_name}\n", encoding="utf-8")
                provider.upload_release_assets(release_repo, release_tag, [tar_path, sha_sidecar_path])

            new_entry: dict[str, Any] = {
                "name": inspected.name,
                "alias": inspected.alias,
                "repo": full_name,
                "visibility": "public",
                "tag": tag_name,
                "version": inspected.version,
                "arch": inspected.arch,
                "compat": inspected.compat,
                "description": inspected.description,
                "manufacturer": inspected.manufacturer,
                "releasenotes": inspected.releasenotes,
                "only_offline_install": inspected.only_offline_install,
                "asset_name": asset_name,
                "sha256": inspected.sha256,
                "size": inspected.size,
                "icon": f"icons/{inspected.name}.png",
            }
            if existing is not None and isinstance(existing.get("local_source"), dict):
                if existing.get("sha256") == inspected.sha256:
                    new_entry["local_source"] = existing["local_source"]
            new_entry["source_visibility"] = src_vis
            new_entry["release_repo"] = release_repo
            new_entry["release_tag"] = release_tag

            if existing is None:
                added.append({"repo": full_name, "name": inspected.name, "tag": tag_name, "version": inspected.version})
            else:
                updated.append({"repo": full_name, "name": inspected.name, "tag": tag_name, "version": inspected.version})

            if not dry_run:
                if icons_dir.is_symlink():
                    raise SyncHubError(f"refusing symlinked icons directory: {icons_dir}")
                icon_dest = icons_dir / f"{inspected.name}.png"
                build_index._atomic_write_bytes(icon_dest, inspected.icon_bytes)
                if existing_idx is not None:
                    sources[existing_idx] = new_entry
                else:
                    by_repo[full_name.lower()] = len(sources)
                    sources.append(new_entry)
                metadata_changed = True

        plugins_changed = bool(added or updated)
        if not dry_run and metadata_changed:
            current_ver = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else "1.0.0"
            if bump_version and plugins_changed:
                current_ver = _bump_patch_version(current_ver)
                build_index._atomic_write_text(version_path, f"{current_ver}\n")

            build_index._atomic_write_text(
                sources_path, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n"
            )
            icon_hashes = {
                entry["name"]: hashlib.sha256((icons_dir / f"{entry['name']}.png").read_bytes()).hexdigest()
                for entry in sources
                if entry.get("visibility") == "public" and (icons_dir / f"{entry['name']}.png").is_file()
            }
            _update_sources_manifest(
                manifest_path,
                catalog_sources=catalog,
                catalog_version=current_ver,
                release_repo=release_repo,
                release_tag=release_tag,
                icon_hashes=icon_hashes,
            )
            build_index.build_index(
                sources_path=sources_path,
                output_path=output_path,
                repo_root=repo_root,
            )

    return {
        "changed": bool(added or updated or visibility_updated),
        "plugins_changed": bool(added or updated),
        "dry_run": dry_run,
        "added": added,
        "updated": updated,
        "visibility_updated": visibility_updated,
        "skipped": skipped,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="Path to plugin-hub repository root")
    parser.add_argument("--org", default=DEFAULT_ORG, help="GitHub organization/owner to scan")
    parser.add_argument("--release-repo", default=DEFAULT_RELEASE_REPO, help="Target repository hosting plugin assets")
    parser.add_argument("--release-tag", default=DEFAULT_RELEASE_TAG, help="Target release tag hosting plugin assets")
    parser.add_argument("--dry-run", action="store_true", help="Inspect and report changes without modifying files or releases")
    parser.add_argument("--force", action="store_true", help="Force re-download and re-index even when tag/asset/sha256 match")
    parser.add_argument("--upload-release", action="store_true", help="Upload new/updated plugin tarballs and .sha256 to hub release")
    parser.add_argument("--bump-version", action="store_true", help="Increment VERSION patch number when plugins are added/updated")
    parser.add_argument("--offline-dir", type=Path, default=None, help="Offline fixture directory for deterministic tests")
    parser.add_argument("--gh-bin", default=None, help="Explicit path to gh CLI binary")
    parser.add_argument("--json", action="store_true", help="Print JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = sync_hub(
            repo_root=args.root,
            org=args.org,
            release_repo=args.release_repo,
            release_tag=args.release_tag,
            dry_run=args.dry_run,
            force=args.force,
            upload_release=args.upload_release,
            bump_version=args.bump_version,
            offline_dir=args.offline_dir,
            gh_bin=args.gh_bin,
        )
    except (SyncHubError, build_index.BuildIndexError, OSError, json.JSONDecodeError) as exc:
        print(f"sync_hub error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(
            f"sync_hub complete: changed={summary['changed']}, "
            f"added={len(summary['added'])}, updated={len(summary['updated'])}, "
            f"visibility_updated={len(summary['visibility_updated'])}, skipped={len(summary['skipped'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
