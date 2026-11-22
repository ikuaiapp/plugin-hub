#!/usr/bin/env python3
"""Deterministic generator and validator for ikuaiapp/plugin-hub plugins.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES = REPO_ROOT / "catalog_sources.json"
DEFAULT_OUTPUT = REPO_ROOT / "plugins.json"

MAX_ICON_BYTES = 1024 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REPO_RE = re.compile(r"^ikuaiapp/[A-Za-z0-9._-]+$")
TAG_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
ASSET_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
INVISIBLE_CHARS_RE = re.compile(r"[\ufeff\u200b\u200c\u200d]")
VALID_VISIBILITIES = {"public", "private_pending", "disabled"}
REQUIRED_MIRROR_GROUPS = ("raw", "release", "jsdelivr")


class BuildIndexError(Exception):
    """Raised when catalog inputs, metadata, icons, or contracts fail validation."""


def strip_invisible(text: str) -> str:
    return INVISIBLE_CHARS_RE.sub("", text).strip()


def normalize_bool(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise BuildIndexError(f"{field_name} must be a boolean or 'true'/'false' string")


def validate_iso_utc(value: str, label: str = "generated_at") -> str:
    if not isinstance(value, str) or not ISO_UTC_RE.match(value):
        raise BuildIndexError(f"{label} must match YYYY-MM-DDTHH:MM:SSZ: {value!r}")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise BuildIndexError(f"{label} is not a valid UTC timestamp: {value!r}") from exc
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def validate_png_file(path: Path, label: str) -> bytes:
    if path.is_symlink():
        raise BuildIndexError(f"{label}: icon must be a regular file, not a symlink: {path}")
    if not path.is_file():
        raise BuildIndexError(f"{label}: missing icon file: {path}")
    data = path.read_bytes()
    if len(data) == 0:
        raise BuildIndexError(f"{label}: icon file is empty: {path}")
    if len(data) > MAX_ICON_BYTES:
        raise BuildIndexError(f"{label}: icon exceeds {MAX_ICON_BYTES} bytes ({len(data)} bytes): {path}")
    if not data.startswith(PNG_MAGIC):
        raise BuildIndexError(f"{label}: invalid PNG magic header: {path}")
    if len(data) < 33 or data[12:16] != b"IHDR":
        raise BuildIndexError(f"{label}: missing PNG IHDR chunk: {path}")
    ihdr_len = struct.unpack(">I", data[8:12])[0]
    if ihdr_len != 13:
        raise BuildIndexError(f"{label}: invalid PNG IHDR length {ihdr_len}: {path}")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise BuildIndexError(f"{label}: invalid PNG dimensions {width}x{height}: {path}")
    return data


def parse_sha256_sidecar(text: str, path_label: str) -> tuple[str, str]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            raise BuildIndexError(f"{path_label}: malformed sha256 sidecar line: {line!r}")
        digest = parts[0].lower()
        filename = parts[-1].lstrip("*")
        if not SHA256_RE.match(digest):
            raise BuildIndexError(f"{path_label}: invalid sha256 digest in sidecar: {digest!r}")
        return digest, Path(filename).name
    raise BuildIndexError(f"{path_label}: empty sha256 sidecar")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise BuildIndexError(f"missing {label}: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildIndexError(f"invalid JSON in {label} ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise BuildIndexError(f"{label} must be a JSON object: {path}")
    return data


def _validate_mirrors(mirrors: Any) -> dict[str, list[str]]:
    if not isinstance(mirrors, dict):
        raise BuildIndexError("mirrors must be an object")
    for key in REQUIRED_MIRROR_GROUPS:
        if key not in mirrors:
            raise BuildIndexError(f"mirrors missing required group {key!r}")
    normalized: dict[str, list[str]] = {}
    for key, entries in mirrors.items():
        if not isinstance(entries, list) or not entries:
            raise BuildIndexError(f"mirrors.{key} must be a non-empty list")
        cleaned_list: list[str] = []
        for idx, url in enumerate(entries):
            if not isinstance(url, str) or not url.endswith("/"):
                raise BuildIndexError(
                    f"mirrors.{key}[{idx}] must be an https:// URL ending with '/': {url!r}"
                )
            if any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in url):
                raise BuildIndexError(
                    f"mirrors.{key}[{idx}] contains invalid whitespace or control characters: {url!r}"
                )
            parsed = urllib.parse.urlsplit(url)
            host = (parsed.hostname or "").lower()
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or not host
                or parsed.username is not None
                or parsed.password is not None
                or "@" in parsed.netloc
                or "github.io" in host
            ):
                raise BuildIndexError(
                    f"mirrors.{key}[{idx}] must be a valid https:// mirror URL without userinfo or github.io: {url!r}"
                )
            cleaned_list.append(url)
        normalized[key] = cleaned_list
    return normalized


def _validate_str_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise BuildIndexError(f"{label} must be a non-empty list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BuildIndexError(f"{label} contains empty/non-string item: {item!r}")
        out.append(item.strip())
    return out


def _default_remote_sha256_fetcher(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ikuaiapp-plugin-hub-builder/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                raise BuildIndexError(f"remote sha256 fetch failed ({resp.status}): {url}")
            return resp.read(4096).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BuildIndexError(f"remote sha256 fetch failed for {url}: {exc}") from exc


def _resolve_generated_at(
    generated_at: str | None,
    output_path: Path,
    new_plugins: list[dict[str, Any]],
    new_mirrors: dict[str, list[str]],
    schema_version: int,
    hub_repo: str,
) -> tuple[str, bool]:
    if generated_at is not None:
        return validate_iso_utc(generated_at, "--generated-at"), True
    env_epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if env_epoch:
        try:
            epoch_int = int(env_epoch)
        except ValueError as exc:
            raise BuildIndexError(f"SOURCE_DATE_EPOCH must be an integer: {env_epoch!r}") from exc
        if epoch_int < 0:
            raise BuildIndexError(f"SOURCE_DATE_EPOCH must be non-negative: {epoch_int}")
        ts = datetime.fromtimestamp(epoch_int, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return ts, True

    if output_path.is_file():
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict) and isinstance(existing.get("generated_at"), str):
            try:
                existing_ts = validate_iso_utc(existing["generated_at"], "existing generated_at")
            except BuildIndexError:
                existing_ts = ""
            if (
                existing_ts
                and existing.get("schema_version") == schema_version
                and existing.get("hub_repo") == hub_repo
                and existing.get("mirrors") == new_mirrors
                and existing.get("plugins") == new_plugins
            ):
                return existing_ts, False

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), False


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    if target.is_symlink():
        raise BuildIndexError(f"refusing to write through symlink: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _atomic_write_text(target: Path, content: str) -> None:
    _atomic_write_bytes(target, content.encode("utf-8"))


def _resolve_contained_path(base_dir: Path, rel_val: Any, label: str) -> Path:
    if not isinstance(rel_val, str) or not rel_val or rel_val.strip() != rel_val:
        raise BuildIndexError(f"{label} must be a non-empty relative path")
    rel_path = Path(rel_val)
    if rel_path.is_absolute():
        raise BuildIndexError(f"{label} must be a relative path, got {rel_val!r}")
    base_resolved = base_dir.resolve()
    candidate = (base_resolved / rel_path).resolve()
    if candidate == base_resolved or not candidate.is_relative_to(base_resolved):
        raise BuildIndexError(f"{label} escapes base directory: {rel_val!r}")
    return candidate


def build_index(
    *,
    sources_path: Path = DEFAULT_SOURCES,
    output_path: Path = DEFAULT_OUTPUT,
    source_root: Path | None = None,
    generated_at: str | None = None,
    check: bool = False,
    sync_icons: bool = False,
    verify_remote: bool = False,
    remote_fetcher: Callable[[str], str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    if sync_icons and source_root is None:
        raise BuildIndexError("--sync-icons requires --source-root")

    effective_repo_root = repo_root if repo_root is not None else sources_path.resolve().parent
    catalog = _load_json(sources_path, "catalog_sources.json")

    schema_version = catalog.get("schema_version")
    if schema_version != 1:
        raise BuildIndexError(f"schema_version must be 1, got {schema_version!r}")

    hub_repo = catalog.get("hub_repo")
    if hub_repo != "ikuaiapp/plugin-hub":
        raise BuildIndexError(f"hub_repo must be 'ikuaiapp/plugin-hub', got {hub_repo!r}")

    mirrors = _validate_mirrors(catalog.get("mirrors"))

    raw_sources = catalog.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise BuildIndexError("catalog_sources.json 'sources' must be a non-empty list")

    seen_names: set[str] = set()
    seen_repos: set[str] = set()
    plugins: list[dict[str, Any]] = []

    fetcher = remote_fetcher if remote_fetcher is not None else _default_remote_sha256_fetcher

    for idx, entry in enumerate(raw_sources):
        if not isinstance(entry, dict):
            raise BuildIndexError(f"sources[{idx}] must be a JSON object")
        visibility = entry.get("visibility")
        if visibility not in VALID_VISIBILITIES:
            raise BuildIndexError(f"sources[{idx}] invalid visibility {visibility!r}")

        name = entry.get("name")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise BuildIndexError(f"sources[{idx}] invalid plugin name {name!r}")
        if name in seen_names:
            raise BuildIndexError(f"duplicate plugin name: {name!r}")
        seen_names.add(name)

        repo = entry.get("repo")
        if not isinstance(repo, str) or not REPO_RE.match(repo) or ".." in repo:
            raise BuildIndexError(f"{name}: repo must match '^ikuaiapp/[A-Za-z0-9._-]+$' without '..', got {repo!r}")
        if repo in seen_repos:
            raise BuildIndexError(f"duplicate plugin repo: {repo!r}")
        seen_repos.add(repo)

        if visibility != "public":
            continue

        tag = entry.get("tag")
        version = entry.get("version")
        asset_name = entry.get("asset_name")
        sha256 = entry.get("sha256")
        size = entry.get("size")
        icon_rel = entry.get("icon")

        if not isinstance(tag, str) or not TAG_RE.match(tag) or ".." in tag:
            raise BuildIndexError(f"{name}: invalid tag {tag!r}")
        release_repo = entry["release_repo"] if "release_repo" in entry else repo
        if not isinstance(release_repo, str) or not REPO_RE.match(release_repo) or ".." in release_repo:
            raise BuildIndexError(
                f"{name}: release_repo must match '^ikuaiapp/[A-Za-z0-9._-]+$' without '..', got {release_repo!r}"
            )
        release_tag = entry["release_tag"] if "release_tag" in entry else tag
        if not isinstance(release_tag, str) or not TAG_RE.match(release_tag) or ".." in release_tag:
            raise BuildIndexError(f"{name}: invalid release_tag {release_tag!r}")
        if not isinstance(version, str) or not version.strip():
            raise BuildIndexError(f"{name}: version must be a non-empty string")
        if not isinstance(asset_name, str) or not ASSET_RE.match(asset_name) or ".." in asset_name:
            raise BuildIndexError(f"{name}: invalid asset_name {asset_name!r}")
        if not isinstance(sha256, str) or not SHA256_RE.match(sha256):
            raise BuildIndexError(f"{name}: sha256 must be 64 lowercase hex characters, got {sha256!r}")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise BuildIndexError(f"{name}: size must be a positive integer, got {size!r}")

        arch = _validate_str_list(entry.get("arch"), f"{name}.arch")
        compat = _validate_str_list(entry.get("compat"), f"{name}.compat")

        expected_icon = f"icons/{name}.png"
        if icon_rel != expected_icon:
            raise BuildIndexError(f"{name}: icon must be {expected_icon!r}, got {icon_rel!r}")

        download_url = f"https://github.com/{release_repo}/releases/download/{release_tag}/{asset_name}"
        mirror_urls = [f"{prefix}{download_url}" for prefix in mirrors["release"]]

        alias = strip_invisible(str(entry.get("alias", "")))
        description = strip_invisible(str(entry.get("description", "")))
        manufacturer = strip_invisible(str(entry.get("manufacturer", "")))
        releasenotes = strip_invisible(str(entry.get("releasenotes", "")))
        only_offline_install = normalize_bool(
            entry.get("only_offline_install", False), f"{name}.only_offline_install"
        )

        dest_icon_path = effective_repo_root / expected_icon

        if source_root is not None:
            local_source = entry.get("local_source")
            if not isinstance(local_source, dict):
                raise BuildIndexError(f"{name}: missing local_source object for --source-root validation")
            local_dir = _resolve_contained_path(
                source_root, local_source.get("dir"), f"{name}.local_source.dir"
            )
            if not local_dir.is_dir():
                raise BuildIndexError(f"{name}: source repo directory not found: {local_dir}")

            meta_path = _resolve_contained_path(
                local_dir, local_source.get("metadata_relpath"), f"{name}.local_source.metadata_relpath"
            )
            metadata = _load_json(meta_path, f"{name} metadata.json")
            if metadata.get("name") != name:
                raise BuildIndexError(
                    f"{name}: metadata.json name {metadata.get('name')!r} != {name!r}"
                )
            if metadata.get("version") != version:
                raise BuildIndexError(
                    f"{name}: metadata.json version {metadata.get('version')!r} != {version!r}"
                )

            alias = strip_invisible(str(metadata.get("alias") or alias))
            description = strip_invisible(str(metadata.get("description") or description))
            manufacturer = strip_invisible(str(metadata.get("manufacturer", manufacturer)))
            releasenotes = strip_invisible(str(metadata.get("releasenotes", releasenotes)))
            if "onlyOfflineInstall" in metadata:
                only_offline_install = normalize_bool(
                    metadata["onlyOfflineInstall"], f"{name}.metadata.onlyOfflineInstall"
                )
            elif "only_offline_install" in metadata:
                only_offline_install = normalize_bool(
                    metadata["only_offline_install"], f"{name}.metadata.only_offline_install"
                )

            sha_path = _resolve_contained_path(
                local_dir, local_source.get("sha256_relpath"), f"{name}.local_source.sha256_relpath"
            )
            if not sha_path.is_file():
                raise BuildIndexError(f"{name}: missing .sha256 sidecar: {sha_path}")
            sidecar_digest, sidecar_file = parse_sha256_sidecar(
                sha_path.read_text(encoding="utf-8"), str(sha_path)
            )
            if sidecar_digest != sha256:
                raise BuildIndexError(
                    f"{name}: .sha256 digest mismatch ({sidecar_digest} != {sha256})"
                )
            if sidecar_file != asset_name:
                raise BuildIndexError(
                    f"{name}: .sha256 filename mismatch ({sidecar_file!r} != {asset_name!r})"
                )

            tarball_path = local_dir / "releases" / asset_name
            if tarball_path.is_file():
                actual_size = tarball_path.stat().st_size
                if actual_size != size:
                    raise BuildIndexError(
                        f"{name}: local tarball size mismatch ({actual_size} != {size})"
                    )
                actual_sha = sha256_file(tarball_path)
                if actual_sha != sha256:
                    raise BuildIndexError(
                        f"{name}: local tarball sha256 mismatch ({actual_sha} != {sha256})"
                    )

            manifest_rel = local_source.get("manifest_relpath")
            if manifest_rel:
                manifest_path = _resolve_contained_path(
                    local_dir, manifest_rel, f"{name}.local_source.manifest_relpath"
                )
                manifest = _load_json(manifest_path, f"{name} BUILD-MANIFEST.json")
                if manifest.get("package") != asset_name:
                    raise BuildIndexError(
                        f"{name}: BUILD-MANIFEST package {manifest.get('package')!r} != {asset_name!r}"
                    )
                if manifest.get("sha256") != sha256:
                    raise BuildIndexError(
                        f"{name}: BUILD-MANIFEST sha256 mismatch"
                    )
                if "size_bytes" in manifest and manifest["size_bytes"] != size:
                    raise BuildIndexError(
                        f"{name}: BUILD-MANIFEST size_bytes {manifest['size_bytes']} != {size}"
                    )

            src_icon_path = _resolve_contained_path(
                local_dir, local_source.get("icon_relpath"), f"{name}.local_source.icon_relpath"
            )
            src_icon_bytes = validate_png_file(src_icon_path, f"{name} source icon")
            if sync_icons:
                if dest_icon_path.parent.is_symlink():
                    raise BuildIndexError(
                        f"{name}: refusing symlinked destination icon directory: {dest_icon_path.parent}"
                    )
                if dest_icon_path.is_symlink():
                    raise BuildIndexError(f"{name}: refusing symlinked destination icon: {dest_icon_path}")
                _atomic_write_bytes(dest_icon_path, src_icon_bytes)
            else:
                if dest_icon_path.parent.is_symlink():
                    raise BuildIndexError(
                        f"{name}: refusing symlinked repo icon directory: {dest_icon_path.parent}"
                    )
                dest_icon_bytes = validate_png_file(dest_icon_path, f"{name} repo icon")
                if dest_icon_bytes != src_icon_bytes:
                    raise BuildIndexError(
                        f"{name}: {expected_icon} differs from {src_icon_path} (run with --sync-icons)"
                    )
        else:
            if dest_icon_path.parent.is_symlink():
                raise BuildIndexError(
                    f"{name}: refusing symlinked repo icon directory: {dest_icon_path.parent}"
                )
            validate_png_file(dest_icon_path, f"{name} repo icon")

        if not alias:
            raise BuildIndexError(f"{name}: alias must be non-empty")
        if not description:
            raise BuildIndexError(f"{name}: description must be non-empty")

        if verify_remote:
            remote_body = fetcher(f"{download_url}.sha256")
            remote_digest, remote_file = parse_sha256_sidecar(
                remote_body, f"{download_url}.sha256"
            )
            if remote_digest != sha256 or remote_file != asset_name:
                raise BuildIndexError(
                    f"{name}: remote .sha256 mismatch ({remote_digest} {remote_file!r})"
                )

        plugins.append(
            {
                "name": name,
                "alias": alias,
                "repo": repo,
                "tag": tag,
                "version": version,
                "arch": arch,
                "compat": compat,
                "description": description,
                "asset_name": asset_name,
                "download_url": download_url,
                "mirror_urls": mirror_urls,
                "sha256": sha256,
                "size": size,
                "icon": expected_icon,
                "manufacturer": manufacturer,
                "releasenotes": releasenotes,
                "only_offline_install": only_offline_install,
            }
        )

    if not plugins:
        raise BuildIndexError("no public plugins found in catalog_sources.json")

    resolved_ts, strict_ts = _resolve_generated_at(
        generated_at, output_path, plugins, mirrors, schema_version, hub_repo
    )
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "generated_at": resolved_ts,
        "hub_repo": hub_repo,
        "mirrors": mirrors,
        "plugins": plugins,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if check:
        if not output_path.is_file():
            raise BuildIndexError(f"output file does not exist for --check: {output_path}")
        existing_text = output_path.read_text(encoding="utf-8")
        if strict_ts:
            if existing_text != serialized:
                raise BuildIndexError(f"{output_path} differs from generated index (strict check)")
        else:
            existing_obj = _load_json(output_path, str(output_path))
            validate_iso_utc(str(existing_obj.get("generated_at", "")), "plugins.json generated_at")
            if existing_text != serialized:
                raise BuildIndexError(f"{output_path} is out of date or formatting differs; rebuild plugins.json")
        return payload

    _atomic_write_text(output_path, serialized)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, default=DEFAULT_SOURCES, help="Path to catalog_sources.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Path to plugins.json")
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Optional local 3.7.26 workspace root containing sibling plugin repositories",
    )
    parser.add_argument(
        "--generated-at",
        default=None,
        help="Explicit UTC timestamp override (YYYY-MM-DDTHH:MM:SSZ)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate inputs and verify output matches without modifying files",
    )
    parser.add_argument(
        "--sync-icons",
        action="store_true",
        help="Copy validated regular-file PNG icons from --source-root into icons/",
    )
    parser.add_argument(
        "--verify-remote",
        action="store_true",
        help="Fetch remote .sha256 release sidecars and verify digests",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build_index(
            sources_path=args.sources.resolve(),
            output_path=args.output.resolve(),
            source_root=args.source_root.resolve() if args.source_root is not None else None,
            generated_at=args.generated_at,
            check=args.check,
            sync_icons=args.sync_icons,
            verify_remote=args.verify_remote,
        )
    except BuildIndexError as exc:
        print(f"build_index error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"build_index io error: {exc}", file=sys.stderr)
        return 2
    action = "verified" if args.check else "generated"
    print(f"plugins.json {action} successfully ({args.output})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
