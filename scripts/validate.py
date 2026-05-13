#!/usr/bin/env python3
"""
Validate every v1/modules/<uuid>/versions/<version>/ entry:
  - manifest.json carries every required field and types match the
    host's Manifest binding,
  - manifest.uuid == directory name; manifest.version == directory name,
  - payload.zip hashes to manifest.payload_sha256,
  - v1/modules/<uuid>/manifest.json (the "latest" pointer) equals one
    of the per-version manifests,
  - v1/index.json is byte-coherent with the per-version manifests.

Runs from .github/workflows/validate.yml on every push + pull_request.
Exits non-zero on any failure with a clear pointer to the offending
file / field. Touches no files.

No Ed25519 signature verification: this registry is a curated mirror,
so trust is administrative ("the repo owner chose to mirror this")
rather than cryptographic. SHA-256 catches transport corruption + lets
the host refuse a payload whose bytes do not match what was signed off
on at publish time.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REQUIRED_MANIFEST_FIELDS = {
    "uuid": str,
    "name": str,
    "vendor": str,
    "version": str,
    "sdk_version": str,
    "min_host_version": str,
    "supported_hmds": list,
    "capabilities": list,
    "platforms": list,
    "entry_assembly": str,
    "entry_type": str,
    "payload_sha256": str,
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def fail(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def validate_manifest(path: Path, expected_uuid: str, expected_version: str) -> dict:
    with path.open("r", encoding="utf-8") as f:
        try:
            m = json.load(f)
        except json.JSONDecodeError as e:
            fail(f"{path}: invalid JSON ({e})")

    for field, ty in REQUIRED_MANIFEST_FIELDS.items():
        if field not in m:
            fail(f"{path}: missing required field '{field}'")
        if not isinstance(m[field], ty):
            fail(
                f"{path}: field '{field}' is {type(m[field]).__name__}, "
                f"expected {ty.__name__}"
            )

    if m["uuid"] != expected_uuid:
        fail(
            f"{path}: uuid '{m['uuid']}' does not match directory "
            f"name '{expected_uuid}'."
        )
    if m["version"] != expected_version:
        fail(
            f"{path}: version '{m['version']}' does not match directory "
            f"name '{expected_version}'."
        )

    sha = m["payload_sha256"]
    if len(sha) != 64 or sha != sha.lower():
        fail(
            f"{path}: payload_sha256 must be 64 lowercase hex characters "
            f"(got {sha!r})"
        )
    try:
        bytes.fromhex(sha)
    except ValueError:
        fail(f"{path}: payload_sha256 is not valid hex ({sha!r}).")

    return m


def validate_version_dir(version_dir: Path, uuid: str) -> dict:
    manifest_path = version_dir / "manifest.json"
    payload_path = version_dir / "payload.zip"

    for p in (manifest_path, payload_path):
        if not p.exists():
            fail(f"{version_dir}: missing required file {p.name}")

    manifest = validate_manifest(manifest_path, uuid, version_dir.name)

    payload_bytes = payload_path.read_bytes()
    actual_hash = hashlib.sha256(payload_bytes).hexdigest()
    if actual_hash != manifest["payload_sha256"]:
        fail(
            f"{payload_path}: SHA-256 mismatch "
            f"(actual {actual_hash} vs manifest {manifest['payload_sha256']})"
        )
    if "payload_size" in manifest and manifest["payload_size"] != len(payload_bytes):
        fail(
            f"{payload_path}: payload_size mismatch "
            f"(actual {len(payload_bytes)} vs manifest {manifest['payload_size']})"
        )

    return manifest


def validate_latest_pointer(uuid_dir: Path, per_version: dict[str, dict]) -> None:
    latest_path = uuid_dir / "manifest.json"
    if not latest_path.exists():
        if per_version:
            fail(
                f"{uuid_dir}: latest manifest.json is missing but there are "
                f"published versions."
            )
        return
    with latest_path.open("r", encoding="utf-8") as f:
        latest = json.load(f)
    matching = [v for v, m in per_version.items() if m == latest]
    if not matching:
        fail(
            f"{latest_path}: contents do not match any version manifest under "
            f"versions/. The publish workflow copies a specific version's "
            f"manifest into this slot; if a version was removed, refresh this "
            f"pointer."
        )


def validate_index(modules_dir: Path, expected_modules: list[dict]) -> None:
    index_path = repo_root() / "v1" / "index.json"
    if not index_path.exists():
        fail(f"{index_path}: missing")
    with index_path.open("r", encoding="utf-8") as f:
        idx = json.load(f)
    if not isinstance(idx.get("modules"), list):
        fail(f"{index_path}: 'modules' is not an array")
    expected_by_uuid = {m["uuid"]: m for m in expected_modules}
    actual_by_uuid = {m["uuid"]: m for m in idx["modules"]}
    if expected_by_uuid.keys() != actual_by_uuid.keys():
        missing = expected_by_uuid.keys() - actual_by_uuid.keys()
        extra = actual_by_uuid.keys() - expected_by_uuid.keys()
        fail(
            f"{index_path}: module set drifted from v1/modules/. "
            f"missing={sorted(missing)} extra={sorted(extra)}. "
            f"Run scripts/publish.py to refresh."
        )
    for uuid, expected in expected_by_uuid.items():
        actual = actual_by_uuid[uuid]
        for k in ("name", "vendor", "version", "capabilities"):
            if actual.get(k) != expected.get(k):
                fail(
                    f"{index_path}: module {uuid} field '{k}' drifted "
                    f"(index={actual.get(k)!r} latest_manifest={expected.get(k)!r})"
                )


def main() -> int:
    root = repo_root()

    # Forbid incoming/ from carrying unprocessed files after a publish run. An
    # author drops files there, the publish workflow signs and removes the
    # directory in the same run; a trailing file is a red flag.
    incoming = root / "incoming"
    if incoming.exists():
        leftover = [
            p
            for p in incoming.rglob("*")
            if p.is_file() and p.name not in (".gitkeep",)
        ]
        if leftover:
            fail(
                "incoming/ contains unprocessed files after a publish run: "
                + ", ".join(str(p.relative_to(root)) for p in leftover)
                + ". The publish workflow consumes these; if you see them in "
                "main, the workflow failed mid-run."
            )

    modules_dir = root / "v1" / "modules"
    expected_index_entries: list[dict] = []

    if modules_dir.exists():
        for uuid_dir in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
            versions_dir = uuid_dir / "versions"
            if not versions_dir.exists():
                fail(f"{uuid_dir}: missing versions/ subdirectory")
            per_version: dict[str, dict] = {}
            for version_dir in sorted(
                p for p in versions_dir.iterdir() if p.is_dir()
            ):
                manifest = validate_version_dir(version_dir, uuid_dir.name)
                per_version[version_dir.name] = manifest
            if not per_version:
                fail(f"{uuid_dir}: no versions/ subdirectories")

            validate_latest_pointer(uuid_dir, per_version)

            # The index's per-module entry comes from the latest version.
            latest = max(per_version.keys(), key=lambda v: (
                tuple(int(p) for p in v.split(".")) if all(p.isdigit() for p in v.split(".")) else (v,)
            ))
            m = per_version[latest]
            expected_index_entries.append(
                {
                    "uuid": m["uuid"],
                    "name": m["name"],
                    "vendor": m["vendor"],
                    "version": m["version"],
                    "capabilities": m.get("capabilities", []),
                }
            )

    validate_index(modules_dir, expected_index_entries)

    print("validate ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
