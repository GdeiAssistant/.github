#!/usr/bin/env python3
"""Tests for controlled artifact secret scanning with Gitleaks 8.30.1."""
from __future__ import annotations

import contextlib
import gzip
import importlib.util
import io
import os
import secrets
import string
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT_PATH = Path(__file__).resolve().parent / "artifact_secret_scan.py"
SPEC = importlib.util.spec_from_file_location("artifact_secret_scan", SCRIPT_PATH)
SCANNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANNER)
BINARY = os.environ.get("GITLEAKS_BIN", "gitleaks")


def fake_value(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class ArtifactSecretScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "payload"
        self.source.mkdir()
        self.report = self.root / "report.json"

    def detect(self, text: str, filename: str = "credentials.properties") -> list[dict]:
        target = self.source / filename
        target.write_text(text, encoding="utf-8")
        return SCANNER.scan(BINARY, target, self.report, SCANNER.DEFAULT_CONFIG)

    def run_cli(self, patterns: str, *extra: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "ARTIFACT_PATHS": patterns}
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--gitleaks", BINARY, *extra],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_mongodb_protocols_are_detected(self) -> None:
        for protocol in ("mongodb", "mongodb+srv"):
            with self.subTest(protocol=protocol):
                findings = self.detect(f"{protocol}://fixture:{fake_value()}@example.invalid/db")
                self.assertIn("mongodb-userinfo-password", {row["RuleID"] for row in findings})

    def test_alibaba_access_key_secret_is_detected_and_id_ignored(self) -> None:
        findings = self.detect("ALIBABA_ACCESS_KEY_SECRET=" + fake_value(30))
        self.assertIn("alibaba-access-key-secret", {row["RuleID"] for row in findings})

        clean = self.detect("ALIBABA_ACCESS_KEY_ID=" + fake_value(30), "id.properties")
        rules = {row["RuleID"] for row in clean}
        self.assertNotIn("alibaba-access-key-secret", rules)
        self.assertNotIn("configuration-secret-value", rules)

    def test_configuration_and_junit_xml_credentials_block_upload(self) -> None:
        value = fake_value()
        (self.source / "TEST-fixture.xml").write_text(
            f"<system-out><![CDATA[password={value}]]></system-out>", encoding="utf-8"
        )
        res = self.run_cli(str(self.source / "*.xml"))
        self.assertEqual(res.returncode, 1, msg=res.stdout + res.stderr)
        self.assertIn("configuration-secret-value", res.stdout)
        self.assertNotIn(value, res.stdout + res.stderr)

    def test_clean_placeholders_pass(self) -> None:
        findings = self.detect(
            "jwt.secret=${JWT_SECRET}\n"
            "password=\n"
            "token=your-token-placeholder\n"
            "password=xxxxxxxxxxxxxxxx\n"
        )
        self.assertEqual(findings, [])

    def test_custom_config_is_supported_and_missing_config_fails_safely(self) -> None:
        custom_cfg = self.root / "custom.toml"
        custom_cfg.write_text(
            'title = "Custom"\n'
            "[[rules]]\n"
            'id = "custom-token"\n'
            'regex = "CUSTOM_TOKEN_[A-Za-z0-9]{16}"\n',
            encoding="utf-8",
        )
        secret = "CUSTOM_TOKEN_" + fake_value(16)
        (self.source / "custom.txt").write_text(secret, encoding="utf-8")

        hit = self.run_cli(str(self.source / "custom.txt"), "--config", str(custom_cfg))
        self.assertEqual(hit.returncode, 1, msg=hit.stdout + hit.stderr)
        self.assertIn("custom-token", hit.stdout)
        self.assertNotIn(secret, hit.stdout + hit.stderr)

        missing = self.run_cli(str(self.source / "custom.txt"), "--config", str(self.root / "absent.toml"))
        self.assertEqual(missing.returncode, 2)
        self.assertIn("during config (FileNotFoundError)", missing.stdout)
        self.assertNotIn("absent.toml", missing.stdout)

    def test_empty_glob_passes_without_scanning_workspace(self) -> None:
        (self.source / "credentials.properties").write_text("jwt.secret=" + fake_value(), encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = SCANNER.run_artifact_scan(BINARY, str(self.source / "*.absent"))
        self.assertEqual(status, 0)
        self.assertIn("0 matching upload path(s)", output.getvalue())

    def test_missing_binary_reports_scan_stage_and_exception_class(self) -> None:
        (self.source / "clean.txt").write_text("clean\n", encoding="utf-8")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = SCANNER.run_artifact_scan(str(self.root / "missing-gitleaks"), str(self.source))
        self.assertEqual(status, 2)
        self.assertIn("during scan (FileNotFoundError)", output.getvalue())

    def test_missing_artifact_paths_env_fails_safely(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "ARTIFACT_PATHS"}
        res = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--gitleaks", BINARY],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("during discover (ValueError)", res.stdout)

    def test_sensitive_filename_and_value_are_suppressed(self) -> None:
        secret = fake_value()
        payload = f"jwt.secret={secret}"
        (self.source / f"{secret}.properties").write_text(payload, encoding="utf-8")
        res = self.run_cli(str(self.source))
        self.assertEqual(res.returncode, 1)
        self.assertIn("RuleIDs:", res.stdout)
        self.assertNotIn(secret, res.stdout + res.stderr)

    def test_cloud_infra_and_personal_disclosure_rules(self) -> None:
        wif = "projects/" + "123456789012" + "/locations/global/workloadIdentityPools/p/providers/gh"
        bucket = "gs://" + "prod-runtime-bucket/data.json"
        public_ip = ".".join(["203", "0", "114", "9"])
        tax_note = "tax " + "residency"
        capital_note = "本人" + "资金"

        self.assertIn("gcp-wif-project-number", {row["RuleID"] for row in self.detect(wif, "wif.txt")})
        self.assertIn("gcs-real-bucket", {row["RuleID"] for row in self.detect(bucket, "bucket.txt")})
        self.assertIn("public-ipv4", {row["RuleID"] for row in self.detect(f"host={public_ip}\n", "host.txt")})
        self.assertIn(
            "personal-tax-or-capital",
            {row["RuleID"] for row in self.detect(f"{tax_note}\n{capital_note}\n", "notes.txt")},
        )

        safe = (
            "gs://example-bucket/data.json\n"
            "gs://<bucket>/data.json\n"
            "10.0.0.1\n172.16.0.1\n192.168.1.1\n127.0.0.1\n192.0.2.1\n"
            "version=1.2.3.4\nv1.2.3.4\n"
        )
        self.assertEqual(self.detect(safe, "safe.txt"), [])


class ArtifactArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.payload = "mongodb://fixture:" + fake_value() + "@example.invalid/db"

    def zip_bytes(self, content: bytes | str, name: str = "0-trace.network") -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, content)
        return buffer.getvalue()

    def run_scan(self) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = SCANNER.run_artifact_scan(BINARY, str(self.root))
        text = output.getvalue()
        self.assertNotIn(self.payload, text)
        return status, text

    def test_compressed_and_nested_zip_credentials_block(self) -> None:
        (self.root / "trace.zip").write_bytes(self.zip_bytes(self.payload))
        status, _ = self.run_scan()
        self.assertEqual(status, 1)

        (self.root / "trace.zip").write_bytes(self.zip_bytes(self.zip_bytes(self.payload), "inner.zip"))
        status, _ = self.run_scan()
        self.assertEqual(status, 1)

    def test_clean_zip_and_path_traversal_name_pass_without_extracting(self) -> None:
        (self.root / "trace.zip").write_bytes(self.zip_bytes("synthetic clean trace", "../escaped.txt"))
        status, _ = self.run_scan()
        self.assertEqual(status, 0)
        self.assertFalse((self.root.parent / "escaped.txt").exists())

    def test_inline_allow_cannot_suppress_artifact_findings(self) -> None:
        (self.root / "trace.zip").write_bytes(self.zip_bytes(self.payload + " # gitleaks:allow"))
        status, _ = self.run_scan()
        self.assertEqual(status, 1)

    def test_depth_entry_and_size_limits_fail_at_stage(self) -> None:
        data = self.zip_bytes("clean")
        for _ in range(2):
            data = self.zip_bytes(data, "inner.zip")
        (self.root / "trace.zip").write_bytes(data)
        status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for index in range(4):
                archive.writestr(str(index), "clean")
        (self.root / "trace.zip").write_bytes(buffer.getvalue())
        with patch.object(SCANNER, "MAX_ARTIFACT_ENTRIES", 3):
            status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)

        (self.root / "trace.zip").write_bytes(self.zip_bytes("x" * 4096))
        with patch.object(SCANNER, "MAX_ARTIFACT_BYTES", 2048):
            status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)

        with patch.object(SCANNER, "MAX_ARTIFACT_FILE_BYTES", 2048):
            status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)

    def test_invalid_encrypted_unsupported_and_symlink_fail_at_stage(self) -> None:
        (self.root / "trace.zip").write_bytes(b"not a zip")
        status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (BadZipFile)", text)
        (self.root / "trace.zip").unlink()

        (self.root / "trace.gz").write_bytes(gzip.compress(self.payload.encode()))
        status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)
        (self.root / "trace.gz").unlink()

        data = bytearray(self.zip_bytes("clean"))
        data[6] |= 1
        offset = data.index(b"PK\x01\x02")
        data[offset + 8] |= 1
        (self.root / "enc.zip").write_bytes(data)
        status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)
        (self.root / "enc.zip").unlink()

        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(self.root / "sym.zip", "w") as archive:
            archive.writestr(info, "elsewhere")
        status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)
        (self.root / "sym.zip").unlink()

        (self.root / "link").symlink_to(self.root / "absent")
        status, text = self.run_scan()
        self.assertEqual(status, 2)
        self.assertIn("during stage (ValueError)", text)


if __name__ == "__main__":
    unittest.main()
