#!/usr/bin/env python3
"""
Process every incoming/<uuid>/<version>/ directory: validate the template,
compute the payload SHA-256, stamp the manifest, write the finished
artefacts under v1/modules/<uuid>/versions/<version>/, refresh the
"latest" pointer at v1/modules/<uuid>/manifest.json, regenerate
v1/index.json, and delete the consumed incoming/ directory.

Runs from .github/workflows/publish.yml on push. Idempotent: if no
incoming/ subdirectories exist, the script refreshes the index only if
content changed (the `generated_at` field is gated by a content-equality
check so a scheduled re-run of the sync workflow with no upstream
changes produces zero diff).

Integrity model: each version's manifest.payload_sha256 is the SHA-256
hex of payload.zip. End users verify the payload they download matches
the manifest's hash. There is no Ed25519 signature or trust list -- the
registry is a curated mirror; trust is administrative ("the repo owner
chose to mirror this") rather than cryptographic.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_TEMPLATE_FIELDS = (
    "uuid",
    "name",
    "vendor",
    "version",
    "sdk_version",
    "min_host_version",
    "supported_hmds",
    "capabilities",
    "platforms",
    "entry_assembly",
    "entry_type",
)

# Fields the workflow computes; if a template carries them they get overwritten.
COMPUTED_FIELDS = ("payload_sha256", "payload_size")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def process_incoming() -> list[Path]:
    """Place every incoming/<uuid>/<version>/. Returns processed dirs."""
    processed: list[Path] = []
    incoming = repo_root() / "incoming"
    if not incoming.exists():
        return processed

    for uuid_dir in sorted(p for p in incoming.iterdir() if p.is_dir()):
        for version_dir in sorted(p for p in uuid_dir.iterdir() if p.is_dir()):
            template_path = version_dir / "manifest.template.json"
            payload_path = version_dir / "payload.zip"
            if not template_path.exists() or not payload_path.exists():
                raise SystemExit(
                    f"incoming/{uuid_dir.name}/{version_dir.name}/ is "
                    "missing manifest.template.json or payload.zip."
                )

            with template_path.open("r", encoding="utf-8") as f:
                manifest = json.load(f)

            for field in REQUIRED_TEMPLATE_FIELDS:
                if field not in manifest:
                    raise SystemExit(
                        f"{template_path}: missing required field '{field}'."
                    )

            if manifest["uuid"] != uuid_dir.name:
                raise SystemExit(
                    f"{template_path}: uuid '{manifest['uuid']}' does not "
                    f"match directory name '{uuid_dir.name}'."
                )
            if manifest["version"] != version_dir.name:
                raise SystemExit(
                    f"{template_path}: version '{manifest['version']}' does "
                    f"not match directory name '{version_dir.name}'."
                )

            payload_bytes = payload_path.read_bytes()
            digest = hashlib.sha256(payload_bytes).digest()
            for field in COMPUTED_FIELDS:
                manifest.pop(field, None)
            manifest["payload_sha256"] = digest.hex()
            manifest["payload_size"] = len(payload_bytes)
            manifest.setdefault("schema", 1)
            manifest.setdefault("dependencies", [])

            dest = (
                repo_root()
                / "v1"
                / "modules"
                / uuid_dir.name
                / "versions"
                / version_dir.name
            )
            dest.mkdir(parents=True, exist_ok=True)
            with (dest / "manifest.json").open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, sort_keys=True)
                f.write("\n")
            (dest / "payload.zip").write_bytes(payload_bytes)

            # Refresh latest-pointer.
            latest_path = (
                repo_root() / "v1" / "modules" / uuid_dir.name / "manifest.json"
            )
            with latest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, sort_keys=True)
                f.write("\n")

            processed.append(version_dir)
            print(f"published {uuid_dir.name}/{version_dir.name}")

    for version_dir in processed:
        shutil.rmtree(version_dir)
    # Sweep emptied uuid directories.
    for uuid_dir in (repo_root() / "incoming").glob("*"):
        if uuid_dir.is_dir() and not any(uuid_dir.iterdir()):
            uuid_dir.rmdir()
    return processed


def latest_version(versions: list[str]) -> str:
    """Pick the highest semver-ish version; falls back to lexicographic."""

    def key(v: str) -> tuple[int, ...] | tuple[str]:
        parts = v.split(".")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (v,)

    return max(versions, key=key)


def _write_if_changed(path: Path, new_doc: dict, drift_keys: tuple[str, ...] = ()) -> bool:
    """Write `new_doc` to `path` only if it differs from the file currently
    on disk after stripping `drift_keys` (fields like `generated_at` that
    would otherwise spawn a spurious bot commit on every workflow run).
    Returns True if the file was written.
    """
    current: dict | None = None
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                current = json.load(f)
        except json.JSONDecodeError:
            current = None

    def strip(d: dict | None) -> dict | None:
        if d is None:
            return None
        return {k: v for k, v in d.items() if k not in drift_keys}

    if strip(current) == strip(new_doc):
        return False

    with path.open("w", encoding="utf-8") as f:
        json.dump(new_doc, f, indent=2, sort_keys=True)
        f.write("\n")
    return True


def regenerate_index() -> bool:
    """Rebuild v1/index.json from every v1/modules/<uuid>/versions/*/."""
    modules: list[dict] = []
    modules_dir = repo_root() / "v1" / "modules"
    if modules_dir.exists():
        for uuid_dir in sorted(p for p in modules_dir.iterdir() if p.is_dir()):
            versions_dir = uuid_dir / "versions"
            if not versions_dir.exists():
                continue
            versions = [
                p.name for p in versions_dir.iterdir() if p.is_dir()
            ]
            if not versions:
                continue
            latest = latest_version(versions)
            manifest_path = versions_dir / latest / "manifest.json"
            with manifest_path.open("r", encoding="utf-8") as f:
                m = json.load(f)
            modules.append(
                {
                    "uuid": m["uuid"],
                    "name": m["name"],
                    "vendor": m["vendor"],
                    "version": m["version"],
                    "capabilities": m.get("capabilities", []),
                }
            )

    doc = {
        "schema": 1,
        "modules": modules,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return _write_if_changed(
        repo_root() / "v1" / "index.json",
        doc,
        drift_keys=("generated_at",),
    )


def main() -> None:
    incoming = repo_root() / "incoming"
    has_incoming = (
        incoming.exists()
        and any(
            p.is_dir()
            and any(v.is_dir() for v in p.iterdir())
            for p in incoming.iterdir()
        )
    )

    if has_incoming:
        process_incoming()
    else:
        print("no incoming/ work; refreshing index only")

    regenerate_index()
    print("publish complete")


if __name__ == "__main__":
    sys.exit(main())
