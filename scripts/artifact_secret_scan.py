#!/usr/bin/env python3
"""Scan controlled build artifact paths with Gitleaks 8.30.1 before upload."""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

DEFAULT_CONFIG = (
    Path(__file__).resolve().parent.parent / "actions" / "artifact-secret-scan" / "gitleaks.toml"
)

MAX_ARCHIVE_DEPTH = 2
MAX_ARTIFACT_ENTRIES = 10000
MAX_ARTIFACT_FILE_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024

ARCHIVE_SUFFIXES = (".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar", ".zst")
ARCHIVE_MAGIC = (
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!",
    b"\x28\xb5\x2f\xfd",
)


def resolve_config(config_path: Path | None) -> Path:
    """Resolve and verify the Gitleaks configuration file path."""
    target = config_path if config_path is not None else DEFAULT_CONFIG
    if not target.is_file():
        raise FileNotFoundError("Gitleaks config file does not exist")
    return target


def discover_paths(patterns: str) -> list[Path]:
    """Expand newline-separated path/glob patterns into deduplicated paths."""
    matched: set[Path] = set()
    for raw in patterns.splitlines():
        pattern = raw.strip()
        if not pattern:
            continue
        for hit in glob.glob(pattern, recursive=True):
            matched.add(Path(hit))
    return sorted(matched)


def stage_artifacts(paths: list[Path], destination: Path) -> None:
    """Stage artifact files and bounded ZIP contents under neutral .txt names."""
    entries = 0
    total = 0

    def count_entry() -> int:
        nonlocal entries
        entries += 1
        if entries > MAX_ARTIFACT_ENTRIES:
            raise ValueError("Artifact entry limit exceeded")
        return entries

    def read_bounded(stream: io.BufferedIOBase | zipfile.ZipExtFile) -> bytes:
        nonlocal total
        limit = min(MAX_ARTIFACT_FILE_BYTES, MAX_ARTIFACT_BYTES - total)
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Artifact size limit exceeded")
        total += len(data)
        return data

    def inspect(data: bytes, name: str, depth: int) -> None:
        stream = io.BytesIO(data)
        if zipfile.is_zipfile(stream) or name.lower().endswith(".zip"):
            if depth >= MAX_ARCHIVE_DEPTH:
                raise ValueError("Artifact archive depth exceeded")
            with zipfile.ZipFile(stream) as archive:
                for member in archive.infolist():
                    count_entry()
                    if member.flag_bits & 1 or stat.S_ISLNK(member.external_attr >> 16):
                        raise ValueError("Encrypted or linked artifact member")
                    if member.is_dir() and member.file_size == 0:
                        continue
                    if (
                        member.file_size > MAX_ARTIFACT_FILE_BYTES
                        or member.file_size > MAX_ARTIFACT_BYTES - total
                    ):
                        raise ValueError("Artifact member size limit exceeded")
                    with archive.open(member) as source:
                        content = read_bounded(source)
                    inspect(content, member.filename, depth + 1)
            return
        if (
            name.lower().endswith(ARCHIVE_SUFFIXES)
            or data.startswith(b"PK")
            or data.startswith(ARCHIVE_MAGIC)
            or data[257:262] == b"ustar"
        ):
            raise ValueError("Unsupported or invalid artifact archive")
        # Neutral .txt paths prevent Zip Slip and source-path allowlist bypasses.
        (destination / f"{entries}.txt").write_bytes(data)

    pending = list(paths)
    seen_files: set[Path] = set()
    while pending:
        path = pending.pop()
        if path.is_symlink():
            raise ValueError("Unsupported artifact symlink")
        if path.is_dir():
            count_entry()
            with os.scandir(path) as children:
                for child in children:
                    if child.is_symlink():
                        raise ValueError("Unsupported artifact symlink")
                    if len(pending) + entries >= MAX_ARTIFACT_ENTRIES:
                        raise ValueError("Artifact entry limit exceeded")
                    pending.append(Path(child.path))
        elif path.is_file():
            resolved = path.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            count_entry()
            with path.open("rb") as source:
                inspect(read_bounded(source), path.name, 0)
        else:
            raise ValueError("Unsupported artifact file type")


def scan(binary: str, target: Path, report: Path, config: Path) -> list[dict]:
    """Run Gitleaks directory scan with inline-allow and source ignore disabled."""
    command = [
        binary,
        "dir",
        str(target),
        "--config",
        str(config),
        "--redact",
        "--no-banner",
        "--ignore-gitleaks-allow",
        "--gitleaks-ignore-path",
        os.devnull,
        "--report-format",
        "json",
        "--report-path",
        str(report),
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode not in (0, 1) or not report.is_file():
        raise RuntimeError("Gitleaks failed; no artifact may be uploaded")
    findings = json.loads(report.read_text(encoding="utf-8"))
    if not isinstance(findings, list) or bool(findings) != bool(result.returncode):
        raise RuntimeError("Gitleaks returned an inconsistent result")
    return findings


def run_artifact_scan(binary: str, patterns: str, config_path: Path | None = None) -> int:
    """Execute bounded staging and secret scan, logging only safe metadata on error."""
    stage = "config"
    try:
        config = resolve_config(config_path)
        stage = "discover"
        paths = discover_paths(patterns)
        if not paths:
            print("Artifact scan passed: 0 matching upload path(s)")
            return 0

        with tempfile.TemporaryDirectory(
            prefix="gitleaks-", dir=os.environ.get("RUNNER_TEMP")
        ) as directory:
            stage = "stage"
            staged = Path(directory) / "payload"
            staged.mkdir()
            stage_artifacts(paths, staged)

            stage = "scan"
            findings = scan(binary, staged, Path(directory) / "report.json", config)

        if findings:
            rules = ", ".join(sorted({str(row.get("RuleID", "unknown")) for row in findings}))
            print(
                f"Artifact scan blocked upload: {len(findings)} credential finding(s) "
                f"(RuleIDs: {rules}); file paths and secret values suppressed"
            )
            return 1

        print(f"Artifact scan passed: {len(paths)} matching upload path(s)")
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        zipfile.BadZipFile,
        NotImplementedError,
        EOFError,
        zlib.error,
    ) as exc:
        print(
            f"Artifact secret scan failed during {stage} ({type(exc).__name__}); "
            "values and raw reports suppressed"
        )
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitleaks", default="gitleaks", help="path to gitleaks binary")
    parser.add_argument("--config", default=None, help="optional Gitleaks config path")
    parser.add_argument("--paths", default=None, help="newline-separated artifact patterns")
    args = parser.parse_args(argv)

    patterns = args.paths if args.paths is not None else os.environ.get("ARTIFACT_PATHS")
    if patterns is None:
        print(
            "Artifact secret scan failed during discover (ValueError); "
            "values and raw reports suppressed"
        )
        return 2
    config_path = Path(args.config) if args.config else None
    return run_artifact_scan(args.gitleaks, patterns, config_path)


if __name__ == "__main__":
    sys.exit(main())
