from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


class IntegrityError(RuntimeError):
    """Raised when generated output does not match its manifest."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_domain_lines(path: Path) -> list[str]:
    content = path.read_bytes()
    if b"\r" in content:
        raise IntegrityError(f"{path.name} must use LF line endings")
    lines = content.decode("utf-8").splitlines()
    if any(not line or line != line.lower() or line.strip() != line for line in lines):
        raise IntegrityError(f"{path.name} contains a blank, mixed-case, or padded domain")
    if len(lines) != len(set(lines)):
        raise IntegrityError(f"{path.name} contains duplicate domains")
    return lines


def _checked_file(root: Path, filename: object) -> Path:
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise IntegrityError("manifest contains an unsafe file name")
    path = root / filename
    if not path.is_file():
        raise IntegrityError(f"missing generated file: {filename}")
    return path


def _check_hash(path: Path, expected: object) -> None:
    if not isinstance(expected, str) or sha256_file(path) != expected:
        raise IntegrityError(f"SHA-256 mismatch: {path.name}")


def verify_output_directory(output_dir: Path) -> dict[str, Any]:
    manifest_path = output_dir / "manifest.json"
    try:
        manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise IntegrityError(f"cannot read manifest.json: {exc}") from exc

    if manifest.get("schema_version") != 1:
        raise IntegrityError("unsupported manifest schema")
    source_update_dates = manifest.get("source_update_dates")
    if (
        not isinstance(source_update_dates, list)
        or not source_update_dates
        or any(not isinstance(value, str) for value in source_update_dates)
        or manifest.get("source_updated_at") not in source_update_dates
    ):
        raise IntegrityError("invalid source update date metadata")
    source_entries = manifest.get("source_entries")
    parsed_source_entries = manifest.get("parsed_source_entries")
    filtered_source_entries = manifest.get("filtered_source_entries")
    if (
        not isinstance(source_entries, int)
        or not isinstance(parsed_source_entries, int)
        or not isinstance(filtered_source_entries, list)
        or source_entries - parsed_source_entries != len(filtered_source_entries)
    ):
        raise IntegrityError("invalid filtered source entry metadata")

    all_details = manifest.get("all")
    ranking_details = manifest.get("ranking")
    snapshots = manifest.get("snapshots")
    if not isinstance(all_details, dict) or not isinstance(ranking_details, dict):
        raise IntegrityError("manifest is missing all or ranking metadata")
    if not isinstance(snapshots, dict):
        raise IntegrityError("manifest is missing snapshot metadata")

    all_path = _checked_file(output_dir, all_details.get("file"))
    _check_hash(all_path, all_details.get("sha256"))
    all_domains = _read_domain_lines(all_path)
    if all_details.get("actual") != len(all_domains):
        raise IntegrityError("all.txt line count does not match manifest")
    if manifest.get("unique_domains") != len(all_domains):
        raise IntegrityError("unique domain count does not match manifest")

    for filename, details in snapshots.items():
        if not isinstance(details, dict):
            raise IntegrityError(f"invalid snapshot metadata: {filename}")
        path = _checked_file(output_dir, filename)
        _check_hash(path, details.get("sha256"))
        domains = _read_domain_lines(path)
        if details.get("actual") != len(domains):
            raise IntegrityError(f"{filename} line count does not match manifest")
        if domains != all_domains[: len(domains)]:
            raise IntegrityError(f"{filename} is not a prefix of all.txt")
        requested = details.get("requested")
        if not isinstance(requested, int) or requested < 1 or len(domains) > requested:
            raise IntegrityError(f"invalid requested count for {filename}")
        if details.get("complete") is not (len(domains) == requested):
            raise IntegrityError(f"invalid completeness flag for {filename}")

    ranking_path = _checked_file(output_dir, ranking_details.get("file"))
    _check_hash(ranking_path, ranking_details.get("sha256"))
    if b"\r" in ranking_path.read_bytes():
        raise IntegrityError("ranking.csv must use LF line endings")
    with ranking_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if ranking_details.get("rows") != len(rows) or len(rows) != len(all_domains):
        raise IntegrityError("ranking.csv row count does not match manifest")
    if [row.get("domain") for row in rows] != all_domains:
        raise IntegrityError("ranking.csv domain order does not match all.txt")

    return manifest
