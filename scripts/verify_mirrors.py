#!/usr/bin/env python3
"""Mirror reachability, TLS 1.2 compatibility, anti-portal, and asset integrity prober."""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import re
import socket
import ssl
import sys
import time
import urllib.parse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INDEX = REPO_ROOT / "plugins.json"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GZIP_MAGIC = b"\x1f\x8b\x08"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ProbeResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes
    tls_version: str = ""
    latency_ms: float = 0.0


@dataclass(frozen=True)
class ProbeResult:
    url: str
    role: str
    mirror: str
    ok: bool
    status_code: int
    tls_version: str
    latency_ms: float
    content_type: str
    bytes_read: int
    error: str = ""


class ProbeClient(Protocol):
    def fetch(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
        max_bytes: int = 1048576,
    ) -> ProbeResponse:
        ...


def _validate_public_ip(ip_str: str, host: str) -> None:
    addr = ipaddress.ip_address(ip_str)
    if (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    ):
        raise ValueError(f"blocked non-public host {host!r} ({ip_str})")


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection preferring IPv4 (matching curl -4 on dual-stack routers)."""

    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        timeout: float,
        context: ssl.SSLContext,
        allow_private_hosts: bool = False,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self.negotiated_tls_version: str = ""
        self.allow_private_hosts = allow_private_hosts

    def connect(self) -> None:
        port = self.port or 443
        last_exc: OSError | None = None
        addrinfo = socket.getaddrinfo(self.host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not self.allow_private_hosts:
            for _, _, _, _, sockaddr in addrinfo:
                _validate_public_ip(sockaddr[0], self.host)
        for family, socktype, proto, _, sockaddr in addrinfo:
            raw_sock: socket.socket | None = None
            try:
                raw_sock = socket.socket(family, socktype, proto)
                raw_sock.settimeout(self.timeout)
                raw_sock.connect(sockaddr)
                wrapped = self._context.wrap_socket(raw_sock, server_hostname=self.host)
                self.sock = wrapped
                self.negotiated_tls_version = wrapped.version() or ""
                return
            except OSError as exc:
                last_exc = exc
                if raw_sock is not None:
                    try:
                        raw_sock.close()
                    except OSError:
                        pass
        if last_exc is not None:
            raise last_exc
        raise OSError(f"no IPv4 address resolved for {self.host}")


class UrllibProbeClient:
    """Stdlib HTTPS probe client bounded to TLS 1.2 (OpenSSL 1.0.2u router parity)."""

    def __init__(
        self,
        *,
        max_redirects: int = 5,
        allow_private_hosts: bool = False,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self.max_redirects = max_redirects
        self.allow_private_hosts = allow_private_hosts
        if ssl_context is not None:
            self.ssl_context = ssl_context
        else:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            self.ssl_context.load_default_certs()
            self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2

    def fetch(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
        max_bytes: int = 1048576,
    ) -> ProbeResponse:
        current_url = url
        req_headers = {"User-Agent": "ikuai-plugin-hub-probe/1.0", "Accept": "*/*"}
        if headers:
            req_headers.update(headers)

        started = time.monotonic()
        for _ in range(self.max_redirects + 1):
            parsed = urllib.parse.urlsplit(current_url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or "@" in parsed.netloc
            ):
                raise ValueError(f"only https:// URLs without userinfo are supported: {current_url!r}")
            if not self.allow_private_hosts:
                try:
                    _validate_public_ip(parsed.hostname, parsed.hostname)
                except ValueError as exc:
                    if "does not appear to be an IPv4 or IPv6 address" not in str(exc):
                        raise
            path = parsed.path or "/"
            if parsed.query:
                path = f"{path}?{parsed.query}"
            conn = _IPv4HTTPSConnection(
                parsed.hostname,
                parsed.port,
                timeout=timeout,
                context=self.ssl_context,
                allow_private_hosts=self.allow_private_hosts,
            )
            try:
                conn.request("GET", path, headers=req_headers)
                resp = conn.getresponse()
                resp_headers = {k.lower(): v for k, v in resp.getheaders()}
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp_headers.get("location", "")
                    resp.read(1024)
                    if not location:
                        elapsed = round((time.monotonic() - started) * 1000.0, 2)
                        return ProbeResponse(
                            status_code=resp.status,
                            headers=resp_headers,
                            body=b"",
                            tls_version=conn.negotiated_tls_version,
                            latency_ms=elapsed,
                        )
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue
                body = resp.read(max_bytes)
                elapsed = round((time.monotonic() - started) * 1000.0, 2)
                return ProbeResponse(
                    status_code=resp.status,
                    headers=resp_headers,
                    body=body,
                    tls_version=conn.negotiated_tls_version,
                    latency_ms=elapsed,
                )
            finally:
                conn.close()
        raise RuntimeError(f"too many redirects (> {self.max_redirects}) for {url}")


def is_html_portal(headers: dict[str, str], body: bytes) -> bool:
    ctype = headers.get("content-type", "").lower()
    if "text/html" in ctype or "application/xhtml" in ctype:
        return True
    head = body[:256].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def build_raw_targets(index: dict[str, Any], relpath: str) -> list[tuple[str, str, str]]:
    hub_repo = str(index["hub_repo"])
    mirrors = index["mirrors"]
    canonical = f"https://raw.githubusercontent.com/{hub_repo}/main/{relpath}"
    targets: list[tuple[str, str, str]] = []
    for prefix in mirrors.get("raw", []):
        targets.append(("raw", prefix, f"{prefix}{canonical}"))
    for base in mirrors.get("jsdelivr", []):
        targets.append(("jsdelivr", base, f"{base}{relpath}"))
    for base in mirrors.get("raw_direct", []):
        targets.append(("raw_direct", base, f"{base}{relpath}"))
    targets.append(("raw_canonical", canonical, canonical))
    return targets


def build_release_targets(index: dict[str, Any], release_url: str) -> list[tuple[str, str, str]]:
    mirrors = index["mirrors"]
    targets: list[tuple[str, str, str]] = []
    for prefix in mirrors.get("release", []):
        targets.append(("release", prefix, f"{prefix}{release_url}"))
    targets.append(("release_canonical", "https://github.com/", release_url))
    return targets


def _probe_single(
    client: ProbeClient,
    *,
    role: str,
    mirror: str,
    url: str,
    timeout: float,
    validator: Any,
    headers: dict[str, str] | None = None,
    max_bytes: int = 1048576,
    expected_statuses: tuple[int, ...] = (200,),
) -> ProbeResult:
    started = time.monotonic()
    try:
        resp = client.fetch(url, timeout=timeout, headers=headers, max_bytes=max_bytes)
        latency_ms = resp.latency_ms if resp.latency_ms > 0 else round((time.monotonic() - started) * 1000.0, 2)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code not in expected_statuses:
            return ProbeResult(
                url=url,
                role=role,
                mirror=mirror,
                ok=False,
                status_code=resp.status_code,
                tls_version=resp.tls_version,
                latency_ms=latency_ms,
                content_type=ctype,
                bytes_read=len(resp.body),
                error=f"unexpected HTTP status {resp.status_code}",
            )
        if is_html_portal(resp.headers, resp.body):
            return ProbeResult(
                url=url,
                role=role,
                mirror=mirror,
                ok=False,
                status_code=resp.status_code,
                tls_version=resp.tls_version,
                latency_ms=latency_ms,
                content_type=ctype,
                bytes_read=len(resp.body),
                error="rejected HTML portal response on HTTP 200",
            )
        err = validator(resp.body)
        return ProbeResult(
            url=url,
            role=role,
            mirror=mirror,
            ok=err == "",
            status_code=resp.status_code,
            tls_version=resp.tls_version,
            latency_ms=latency_ms,
            content_type=ctype,
            bytes_read=len(resp.body),
            error=err,
        )
    except Exception as exc:
        latency_ms = round((time.monotonic() - started) * 1000.0, 2)
        return ProbeResult(
            url=url,
            role=role,
            mirror=mirror,
            ok=False,
            status_code=0,
            tls_version="",
            latency_ms=latency_ms,
            content_type="",
            bytes_read=0,
            error=str(exc),
        )


def _validate_index_json(body: bytes, expected_hub_repo: str) -> str:
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return f"invalid JSON payload: {exc}"
    if not isinstance(doc, dict):
        return "JSON root must be an object"
    if doc.get("schema_version") != 1:
        return f"unexpected schema_version: {doc.get('schema_version')!r}"
    if doc.get("hub_repo") != expected_hub_repo:
        return f"unexpected hub_repo: {doc.get('hub_repo')!r}"
    if not isinstance(doc.get("plugins"), list) or not doc["plugins"]:
        return "plugins array must be non-empty"
    return ""


def _validate_non_empty(body: bytes) -> str:
    return "" if body.strip() else "empty response body"


def _validate_png(body: bytes) -> str:
    return "" if body.startswith(PNG_MAGIC) else "missing PNG magic header"


def _validate_sha256_sidecar(body: bytes, expected_sha256: str, expected_asset: str) -> str:
    text = body.decode("utf-8", errors="replace")
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            digest = parts[0].lower()
            filename = Path(parts[-1].lstrip("*")).name
            if not SHA256_RE.match(digest):
                return f"invalid sha256 syntax: {digest!r}"
            if digest != expected_sha256:
                return f"sha256 mismatch: {digest} != {expected_sha256}"
            if filename != expected_asset:
                return f"asset filename mismatch: {filename!r} != {expected_asset!r}"
            return ""
    return "empty .sha256 sidecar"


def _validate_gzip_magic(body: bytes) -> str:
    return "" if body.startswith(GZIP_MAGIC) else "missing gzip magic header (\\x1f\\x8b\\x08)"


def _validate_plugin_entry(plugin: Any, idx: int) -> dict[str, Any]:
    if not isinstance(plugin, dict):
        raise ValueError(f"plugin entry [{idx}] must be an object")
    for req_key in ("name", "icon", "download_url", "sha256", "asset_name"):
        val = plugin.get(req_key)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(f"plugin entry [{idx}] missing or invalid {req_key!r}")
    return plugin


def load_index(index_path: Path) -> dict[str, Any]:
    if not index_path.is_file():
        raise ValueError(f"index file not found: {index_path}")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"invalid plugin index schema in {index_path}")
    if not isinstance(data.get("hub_repo"), str) or not data["hub_repo"].strip():
        raise ValueError(f"missing hub_repo in {index_path}")
    if not isinstance(data.get("mirrors"), dict) or not isinstance(data.get("plugins"), list) or not data["plugins"]:
        raise ValueError(f"missing mirrors or plugins in {index_path}")
    for idx, plugin in enumerate(data["plugins"]):
        _validate_plugin_entry(plugin, idx)
    return data


def verify_all(
    index: dict[str, Any],
    *,
    client: ProbeClient,
    timeout: float = 8.0,
    probe_relpath: str = "plugins.json",
    check_assets: bool = False,
    all_plugins: bool = False,
    min_raw: int = 1,
    min_release: int = 1,
) -> dict[str, Any]:
    if not isinstance(index, dict) or not isinstance(index.get("plugins"), list) or not index["plugins"]:
        raise ValueError("index must include non-empty plugins list")
    hub_repo = str(index.get("hub_repo", ""))
    if not hub_repo:
        raise ValueError("index missing hub_repo")
    plugins_to_check = index["plugins"] if all_plugins else [index["plugins"][0]]
    validated_plugins = [_validate_plugin_entry(p, idx) for idx, p in enumerate(plugins_to_check)]

    results: list[ProbeResult] = []

    raw_validator = (
        (lambda body: _validate_index_json(body, hub_repo))
        if probe_relpath == "plugins.json"
        else _validate_non_empty
    )

    for role, mirror, url in build_raw_targets(index, probe_relpath):
        res = _probe_single(
            client,
            role=role,
            mirror=mirror,
            url=url,
            timeout=timeout,
            validator=raw_validator,
        )
        results.append(res)

    for plugin in validated_plugins:
        sample_icon = str(plugin["icon"])
        sample_url = str(plugin["download_url"])
        sample_sha256 = str(plugin["sha256"])
        sample_asset = str(plugin["asset_name"])

        if check_assets:
            for role, mirror, url in build_raw_targets(index, sample_icon):
                res = _probe_single(
                    client,
                    role=f"{role}_icon",
                    mirror=mirror,
                    url=url,
                    timeout=timeout,
                    validator=_validate_png,
                )
                results.append(res)

        for role, mirror, sidecar_url in build_release_targets(index, f"{sample_url}.sha256"):
            res = _probe_single(
                client,
                role=role,
                mirror=mirror,
                url=sidecar_url,
                timeout=timeout,
                validator=lambda body, s=sample_sha256, a=sample_asset: _validate_sha256_sidecar(body, s, a),
                max_bytes=4096,
            )
            results.append(res)

        if check_assets:
            for role, mirror, asset_url in build_release_targets(index, sample_url):
                res = _probe_single(
                    client,
                    role=f"{role}_range",
                    mirror=mirror,
                    url=asset_url,
                    timeout=timeout,
                    validator=_validate_gzip_magic,
                    headers={"Range": "bytes=0-511"},
                    max_bytes=512,
                    expected_statuses=(200, 206),
                )
                results.append(res)

    raw_ok = sum(1 for r in results if r.role in {"raw", "jsdelivr", "raw_direct", "raw_canonical"} and r.ok)
    release_ok = sum(1 for r in results if r.role in {"release", "release_canonical"} and r.ok)
    icon_ok = sum(1 for r in results if r.role.endswith("_icon") and r.ok)
    range_ok = sum(1 for r in results if r.role.endswith("_range") and r.ok)

    assets_ok = True
    if check_assets:
        assets_ok = icon_ok >= min_raw and range_ok >= min_release

    passed = raw_ok >= min_raw and release_ok >= min_release and assets_ok
    return {
        "passed": passed,
        "probe_relpath": probe_relpath,
        "check_assets": check_assets,
        "all_plugins": all_plugins,
        "summary": {
            "raw_ok": raw_ok,
            "release_ok": release_ok,
            "icon_ok": icon_ok,
            "range_ok": range_ok,
            "min_raw": min_raw,
            "min_release": min_release,
            "plugins_checked": len(validated_plugins),
            "total_probes": len(results),
        },
        "results": [asdict(r) for r in results],
    }


class _OfflineMockProbeClient:
    """Deterministic fixture client for offline --offline-test verification."""

    def __init__(self, index: dict[str, Any]) -> None:
        self.index = index
        self.plugins = index["plugins"]
        self.sidecars_by_suffix = {
            f"{p['download_url']}.sha256": f"{p['sha256']}  {p['asset_name']}\n".encode("utf-8")
            for p in self.plugins
        }
        self.index_bytes = json.dumps(index, ensure_ascii=False).encode("utf-8")
        self.png_bytes = PNG_MAGIC + b"\x00\x00\x00\x0dIHDR" + b"\x00" * 16
        self.gzip_bytes = GZIP_MAGIC + b"\x00" * 64

    def _sidecar_for_url(self, url: str) -> bytes:
        for suffix, payload in self.sidecars_by_suffix.items():
            if url.endswith(suffix):
                return payload
        p0 = self.plugins[0]
        return f"{p0['sha256']}  {p0['asset_name']}\n".encode("utf-8")

    def fetch(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
        max_bytes: int = 1048576,
    ) -> ProbeResponse:
        if "wget.la" in url:
            return ProbeResponse(
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=b"<!DOCTYPE html><html><body>proxy portal</body></html>",
                tls_version="TLSv1.2",
                latency_ms=12.5,
            )
        if "gcore.jsdelivr.net" in url:
            raise TimeoutError("simulated cold DNS timeout")
        if url.endswith(".sha256"):
            return ProbeResponse(
                status_code=200,
                headers={"content-type": "text/plain"},
                body=self._sidecar_for_url(url),
                tls_version="TLSv1.2",
                latency_ms=8.1,
            )
        if url.endswith(".png"):
            return ProbeResponse(
                status_code=200,
                headers={"content-type": "image/png"},
                body=self.png_bytes,
                tls_version="TLSv1.2",
                latency_ms=6.4,
            )
        if url.endswith(".tar.gz"):
            return ProbeResponse(
                status_code=206,
                headers={"content-type": "application/octet-stream"},
                body=self.gzip_bytes,
                tls_version="TLSv1.2",
                latency_ms=15.0,
            )
        if url.endswith("plugins.json"):
            return ProbeResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=self.index_bytes,
                tls_version="TLSv1.2",
                latency_ms=9.3,
            )
        return ProbeResponse(
            status_code=200,
            headers={"content-type": "text/plain"},
            body=b"ok\n",
            tls_version="TLSv1.2",
            latency_ms=5.0,
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="Path to plugins.json")
    parser.add_argument("--timeout", type=float, default=8.0, help="Per-probe HTTP timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--check-assets", action="store_true", help="Also probe PNG icons and tarball Range gzip magic")
    parser.add_argument("--all-plugins", action="store_true", help="Probe every plugin entry instead of only plugins[0]")
    parser.add_argument("--probe-relpath", default="plugins.json", help="Relative repo path to probe on raw/CDN mirrors")
    parser.add_argument("--min-raw", type=int, default=1, help="Minimum healthy raw/CDN mirrors required")
    parser.add_argument("--min-release", type=int, default=1, help="Minimum healthy release mirrors required")
    parser.add_argument(
        "--offline-test",
        action="store_true",
        help="Run built-in simulated mirror/anti-portal checks without network access",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.timeout <= 0 or args.min_raw < 0 or args.min_release < 0:
        print("verify_mirrors error: invalid numeric threshold/timeout", file=sys.stderr)
        return 2
    try:
        index = load_index(args.index.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify_mirrors error: {exc}", file=sys.stderr)
        return 2

    client: ProbeClient = _OfflineMockProbeClient(index) if args.offline_test else UrllibProbeClient()
    report = verify_all(
        index,
        client=client,
        timeout=args.timeout,
        probe_relpath=args.probe_relpath,
        check_assets=args.check_assets or args.offline_test,
        all_plugins=args.all_plugins,
        min_raw=args.min_raw,
        min_release=args.min_release,
    )
    report["mode"] = "offline_test" if args.offline_test else "live"

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print(
            f"mode={report['mode']} passed={report['passed']} "
            f"raw_ok={summary['raw_ok']}>={summary['min_raw']} "
            f"release_ok={summary['release_ok']}>={summary['min_release']}"
        )
        for item in report["results"]:
            status = "OK" if item["ok"] else "FAIL"
            detail = f" ({item['error']})" if item["error"] else ""
            print(f"[{status}] {item['role']} {item['url']} http={item['status_code']} tls={item['tls_version'] or '-'} {item['latency_ms']}ms{detail}")

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
