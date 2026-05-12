#!/usr/bin/env python3
"""
Process every incoming/<uuid>/<version>/ directory: validate the template,
compute the payload hash, stamp the manifest, sign the SHA-256 digest of
the payload with the configured Ed25519 signing seed, write the finished
artefacts under v1/modules/<uuid>/versions/<version>/, refresh the
"latest" pointer at v1/modules/<uuid>/manifest.json, regenerate
v1/index.json, refresh v1/trust.json from publishers/*.json, and delete
the consumed incoming/ directory.

Runs from .github/workflows/publish.yml on push. Idempotent: if no
incoming/ subdirectories exist, the script still refreshes the index +
trust list (cheap) and exits 0 with no commit-worthy changes.

The signing seed must be available as EDDSA_SIGNING_SEED_HEX in the
environment (64 hex chars = 32 raw bytes). The script looks up which
publishers/ entry that seed matches by deriving the public key and
comparing against every publishers/*.json; that becomes the manifest's
signed_by value. Mismatched seed (no matching publisher file) is a hard
error.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from nacl.signing import SigningKey


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
COMPUTED_FIELDS = ("payload_sha256", "payload_size", "signed_by")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_signing_key() -> tuple[SigningKey, str]:
    """Decode EDDSA_SIGNING_SEED_HEX -> SigningKey + the matching key_id."""
    seed_hex = os.environ.get("EDDSA_SIGNING_SEED_HEX", "").strip()
    if len(seed_hex) != 64:
        raise SystemExit(
            "EDDSA_SIGNING_SEED_HEX must be 64 hex characters (32-byte seed)."
        )
    seed = bytes.fromhex(seed_hex)
    sk = SigningKey(seed)
    pub_b64 = (
        __import__("base64").b64encode(bytes(sk.verify_key)).decode("ascii")
    )

    publishers_dir = repo_root() / "publishers"
    for entry in sorted(publishers_dir.glob("*.json")):
        with entry.open("r", encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("ed25519_pub") == pub_b64:
            return sk, doc["key_id"]

    raise SystemExit(
        "EDDSA_SIGNING_SEED_HEX does not match any publishers/*.json "
        "(derived public key: " + pub_b64 + "). Commit the matching "
        "publisher file before publishing."
    )


def process_incoming(sk: SigningKey, key_id: str) -> list[Path]:
    """Sign + place every incoming/<uuid>/<version>/. Returns processed dirs."""
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
            manifest["signed_by"] = key_id
            manifest.setdefault("schema", 1)
            manifest.setdefault("dependencies", [])

            signature = sk.sign(digest).signature  # 64 raw bytes
            assert len(signature) == 64

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
            (dest / "signature.bin").write_bytes(signature)

            # Refresh latest-pointer.
            latest_path = (
                repo_root() / "v1" / "modules" / uuid_dir.name / "manifest.json"
            )
            with latest_path.open("w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, sort_keys=True)
                f.write("\n")

            processed.append(version_dir)
            print(f"published {uuid_dir.name}/{version_dir.name} signed_by={key_id}")

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
    """Rebuild v1/index.json from every v1/modules/<uuid>/versions/*/.
    Returns True if the file was written, False if the content was
    byte-equivalent (modulo `generated_at`)."""
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


def regenerate_trust() -> bool:
    """Build v1/trust.json from every publishers/*.json. Returns True if
    the file was written."""
    keys: list[dict] = []
    pubs = repo_root() / "publishers"
    if pubs.exists():
        for entry in sorted(pubs.glob("*.json")):
            with entry.open("r", encoding="utf-8") as f:
                doc = json.load(f)
            keys.append(
                {"key_id": doc["key_id"], "ed25519_pub": doc["ed25519_pub"]}
            )

    return _write_if_changed(repo_root() / "v1" / "trust.json", {"keys": keys})


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
        sk, key_id = load_signing_key()
        process_incoming(sk, key_id)
    else:
        print("no incoming/ work; refreshing index + trust only")

    regenerate_index()
    regenerate_trust()
    print("publish complete")


if __name__ == "__main__":
    sys.exit(main())
