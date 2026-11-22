"""Unit tests for scripts/verify_mirrors.py (100% offline using mock ProbeClient)."""

from __future__ import annotations

import json
import socket
import ssl
import subprocess
import sys
import threading
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scripts import verify_mirrors

ROOT = Path(__file__).resolve().parent.parent


class _DictProbeClient:
    def __init__(self, responses: dict[str, verify_mirrors.ProbeResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def fetch(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str] | None = None,
        max_bytes: int = 1048576,
    ) -> verify_mirrors.ProbeResponse:
        self.calls.append((url, headers))
        item = self.responses[url]
        if isinstance(item, Exception):
            raise item
        return item


def _sample_index() -> dict:
    return {
        "schema_version": 1,
        "generated_at": "2026-11-21T12:00:00Z",
        "hub_repo": "ikuaiapp/plugin-hub",
        "mirrors": {
            "raw": ["https://gh-proxy.org/"],
            "release": ["https://gh-proxy.org/"],
            "jsdelivr": ["https://cdn.jsdelivr.net/gh/ikuaiapp/plugin-hub@main/"],
            "raw_direct": ["https://raw.bgithub.xyz/ikuaiapp/plugin-hub/main/"],
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
                "description": "backup",
                "asset_name": "config-backup-3.7-ikuai-3.7.x-x64.tar.gz",
                "download_url": "https://github.com/ikuaiapp/config-backup/releases/download/v3.7/config-backup-3.7-ikuai-3.7.x-x64.tar.gz",
                "sha256": "d6a6a0216f9a6f8f923fdc918422bc225f205bc0bc6c4261e8cdf17ca91012d9",
                "size": 47239,
                "icon": "icons/router_backup.png",
            }
        ],
    }


class VerifyMirrorsTests(unittest.TestCase):
    def test_url_rewriting_separates_prefix_and_base_syntax(self) -> None:
        index = _sample_index()
        targets = verify_mirrors.build_raw_targets(index, "plugins.json")
        urls = {role: url for role, _mirror, url in targets}
        self.assertEqual(
            urls["raw"],
            "https://gh-proxy.org/https://raw.githubusercontent.com/ikuaiapp/plugin-hub/main/plugins.json",
        )
        self.assertEqual(
            urls["jsdelivr"],
            "https://cdn.jsdelivr.net/gh/ikuaiapp/plugin-hub@main/plugins.json",
        )
        self.assertEqual(
            urls["raw_direct"],
            "https://raw.bgithub.xyz/ikuaiapp/plugin-hub/main/plugins.json",
        )
        self.assertNotIn("raw.githubusercontent.com", urls["raw_direct"])

    def test_rejects_html_portal_bad_digest_bad_magic_and_http_errors(self) -> None:
        index = _sample_index()
        plugin = index["plugins"][0]
        raw_targets = dict((role, url) for role, _, url in verify_mirrors.build_raw_targets(index, "plugins.json"))
        icon_targets = dict((role, url) for role, _, url in verify_mirrors.build_raw_targets(index, plugin["icon"]))
        rel_targets = dict(
            (role, url)
            for role, _, url in verify_mirrors.build_release_targets(index, plugin["download_url"] + ".sha256")
        )
        asset_targets = dict(
            (role, url)
            for role, _, url in verify_mirrors.build_release_targets(index, plugin["download_url"])
        )

        responses: dict[str, verify_mirrors.ProbeResponse | Exception] = {
            # HTML 200 portal on raw proxy
            raw_targets["raw"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "text/html"},
                body=b"<!DOCTYPE html><html>portal</html>",
                tls_version="TLSv1.2",
                latency_ms=11.0,
            ),
            # Invalid JSON on jsdelivr
            raw_targets["jsdelivr"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=b"{not-json",
                tls_version="TLSv1.2",
                latency_ms=7.5,
            ),
            # Valid JSON on raw_direct
            raw_targets["raw_direct"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "application/json"},
                body=json.dumps(index).encode("utf-8"),
                tls_version="TLSv1.2",
                latency_ms=15.2,
            ),
            # Timeout on canonical raw
            raw_targets["raw_canonical"]: TimeoutError("timed out"),
            # Icon invalid magic vs valid PNG
            icon_targets["raw"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "image/png"},
                body=b"GIF89a",
                tls_version="TLSv1.2",
            ),
            icon_targets["jsdelivr"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "image/png"},
                body=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
                tls_version="TLSv1.2",
            ),
            icon_targets["raw_direct"]: verify_mirrors.ProbeResponse(
                status_code=403, headers={}, body=b"forbidden"
            ),
            icon_targets["raw_canonical"]: verify_mirrors.ProbeResponse(
                status_code=500, headers={}, body=b"error"
            ),
            # Release .sha256: mismatch on proxy, valid on canonical
            rel_targets["release"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "text/plain"},
                body=f"{'0' * 64}  {plugin['asset_name']}\n".encode("utf-8"),
                tls_version="TLSv1.2",
            ),
            rel_targets["release_canonical"]: verify_mirrors.ProbeResponse(
                status_code=200,
                headers={"content-type": "text/plain"},
                body=f"{plugin['sha256']}  {plugin['asset_name']}\n".encode("utf-8"),
                tls_version="TLSv1.2",
            ),
            # Range gzip check: bad header on proxy, valid 206 on canonical
            asset_targets["release"]: verify_mirrors.ProbeResponse(
                status_code=206,
                headers={"content-type": "application/octet-stream"},
                body=b"PK\x03\x04",
                tls_version="TLSv1.2",
            ),
            asset_targets["release_canonical"]: verify_mirrors.ProbeResponse(
                status_code=206,
                headers={"content-type": "application/octet-stream"},
                body=b"\x1f\x8b\x08\x00",
                tls_version="TLSv1.2",
            ),
        }

        client = _DictProbeClient(responses)
        report = verify_mirrors.verify_all(
            index,
            client=client,
            check_assets=True,
            min_raw=1,
            min_release=1,
        )
        self.assertTrue(report["passed"])
        by_url = {r["url"]: r for r in report["results"]}
        self.assertFalse(by_url[raw_targets["raw"]]["ok"])
        self.assertIn("HTML portal", by_url[raw_targets["raw"]]["error"])
        self.assertFalse(by_url[raw_targets["jsdelivr"]]["ok"])
        self.assertTrue(by_url[raw_targets["raw_direct"]]["ok"])
        self.assertFalse(by_url[rel_targets["release"]]["ok"])
        self.assertIn("sha256 mismatch", by_url[rel_targets["release"]]["error"])
        self.assertTrue(by_url[rel_targets["release_canonical"]]["ok"])
        self.assertFalse(by_url[asset_targets["release"]]["ok"])
        self.assertTrue(by_url[asset_targets["release_canonical"]]["ok"])

        strict_fail = verify_mirrors.verify_all(
            index,
            client=client,
            check_assets=False,
            min_raw=2,
            min_release=1,
        )
        self.assertFalse(strict_fail["passed"])

    def test_cli_offline_test_json_output(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_mirrors.py"), "--offline-test", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["passed"])
        self.assertEqual(doc["mode"], "offline_test")
        self.assertGreaterEqual(doc["summary"]["raw_ok"], 1)
        self.assertGreaterEqual(doc["summary"]["release_ok"], 1)

    def test_incomplete_plugin_entry_exits_2_without_traceback_and_all_plugins_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_idx = Path(tmp) / "bad_plugins.json"
            bad_idx.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "hub_repo": "ikuaiapp/plugin-hub",
                        "mirrors": {"raw": ["https://gh-proxy.org/"], "release": ["https://gh-proxy.org/"]},
                        "plugins": [{"name": "incomplete"}],
                    }
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "verify_mirrors.py"), "--index", str(bad_idx)],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertNotIn("Traceback", proc.stderr)
            self.assertIn("verify_mirrors error:", proc.stderr)

        idx = _sample_index()
        p2 = dict(idx["plugins"][0])
        p2["name"] = "second_plugin"
        p2["icon"] = "icons/second_plugin.png"
        p2["asset_name"] = "second-1.0.tar.gz"
        p2["download_url"] = "https://github.com/ikuaiapp/second/releases/download/v1.0/second-1.0.tar.gz"
        idx["plugins"].append(p2)

        hits: list[str] = []

        class _AllOkClient:
            def fetch(self, url: str, *, timeout: float, headers: dict[str, str] | None = None, max_bytes: int = 1048576):
                hits.append(url)
                if url.endswith("plugins.json"):
                    return verify_mirrors.ProbeResponse(200, {"content-type": "application/json"}, json.dumps(idx).encode(), "TLSv1.2")
                if url.endswith(".sha256"):
                    asset = p2["asset_name"] if "second" in url else idx["plugins"][0]["asset_name"]
                    sha = idx["plugins"][0]["sha256"]
                    return verify_mirrors.ProbeResponse(200, {"content-type": "text/plain"}, f"{sha}  {asset}\n".encode(), "TLSv1.2")
                return verify_mirrors.ProbeResponse(200, {}, b"ok", "TLSv1.2")

        rep = verify_mirrors.verify_all(idx, client=_AllOkClient(), all_plugins=True)
        self.assertTrue(rep["passed"])
        self.assertEqual(rep["summary"]["plugins_checked"], 2)
        self.assertTrue(any("second-1.0.tar.gz.sha256" in u for u in hits))

    def test_urllib_probe_client_tls12_redirects_http_downgrade_and_ssrf_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            cert = td / "cert.pem"
            key = td / "key.pem"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=127.0.0.1",
                    "-addext",
                    "subjectAltName=IP:127.0.0.1,DNS:localhost",
                ],
                check=True,
                capture_output=True,
            )

            seen_paths: list[str] = []

            class _TLSHandler(BaseHTTPRequestHandler):
                def log_message(self, fmt: str, *args: object) -> None:
                    return

                def do_GET(self) -> None:
                    seen_paths.append(self.path)
                    if self.path == "/ok":
                        self.send_response(200)
                        self.send_header("Content-Type", "text/plain")
                        self.end_headers()
                        self.wfile.write(b"tls12-ok")
                    elif self.path == "/redir-ok":
                        self.send_response(302)
                        self.send_header("Location", "/ok")
                        self.end_headers()
                    elif self.path == "/redir-http":
                        self.send_response(302)
                        self.send_header("Location", "http://127.0.0.1/downgraded")
                        self.end_headers()
                    elif self.path == "/redir-loop":
                        self.send_response(302)
                        self.send_header("Location", "/redir-loop")
                        self.end_headers()
                    else:
                        self.send_response(404)
                        self.end_headers()

            srv = ThreadingHTTPServer(("127.0.0.1", 0), _TLSHandler)
            srv_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            srv_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            srv_ctx.maximum_version = ssl.TLSVersion.TLSv1_2
            srv_ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
            srv.socket = srv_ctx.wrap_socket(srv.socket, server_side=True)
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            self.addCleanup(srv.shutdown)
            self.addCleanup(srv.server_close)
            port = srv.server_address[1]

            cli_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            cli_ctx.load_verify_locations(cafile=str(cert))
            cli_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            cli_ctx.maximum_version = ssl.TLSVersion.TLSv1_2

            # Default allow_private_hosts=False blocks loopback/private IP targets before connecting
            ssrf_client = verify_mirrors.UrllibProbeClient(ssl_context=cli_ctx)
            with self.assertRaises(ValueError):
                ssrf_client.fetch(f"https://127.0.0.1:{port}/ok", timeout=2.0)
            with self.assertRaises(ValueError):
                ssrf_client.fetch("https://" + "10." + "0.0.1/secret", timeout=2.0)
            with mock.patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]):
                with self.assertRaises(ValueError):
                    ssrf_client.fetch(f"https://ssrf.example.test:{port}/ok", timeout=2.0)
            self.assertEqual(seen_paths, [])

            # Redirect from an allowed connection to loopback must also be blocked
            local_client = verify_mirrors.UrllibProbeClient(max_redirects=2, allow_private_hosts=True, ssl_context=cli_ctx)
            resp_ok = local_client.fetch(f"https://127.0.0.1:{port}/redir-ok", timeout=2.0)
            self.assertEqual(resp_ok.status_code, 200)
            self.assertEqual(resp_ok.body, b"tls12-ok")
            self.assertEqual(resp_ok.tls_version, "TLSv1.2")

            with self.assertRaises(ValueError):
                local_client.fetch(f"https://127.0.0.1:{port}/redir-http", timeout=2.0)
            with self.assertRaises(RuntimeError):
                local_client.fetch(f"https://127.0.0.1:{port}/redir-loop", timeout=2.0)


if __name__ == "__main__":
    unittest.main()
