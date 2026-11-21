"""Unit tests for scripts/verify_mirrors.py (100% offline using mock ProbeClient)."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
