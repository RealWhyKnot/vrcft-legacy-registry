#!/usr/bin/env python3
"""
Sync the registry to exactly the set of modules the upstream VRCFaceTracking
app shows in its Modules tab. The upstream module list is served from a
Lambda URL the app's ModuleDataService talks to (see VRCFaceTracking source
at VRCFaceTracking/Services/ModuleDataService.cs in the upstream repo).

Behaviour:
  - Fetch upstream module list.
  - Wipe local incoming/<uuid>/ + v1/modules/<uuid>/ trees entirely.
  - Re-import every upstream entry by running scripts/import-upstream.py
    against its DownloadUrl.
  - Leaves v1/index.json + v1/trust.json + everything else alone; the
    publish workflow regenerates them on the resulting commit.

This is intentionally destructive. Users will see a single bot commit
that drops 5 modules and adds 11 in one shot, lining the registry up
with what upstream natively supports.

Run with:
    conda run -n whyknot_dev python scripts/sync-upstream.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


UPSTREAM_URL = (
    "https://rjlk4u22t36tvqz3bvbkwv675a0wbous.lambda-url.us-east-1.on.aws/modules"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def fetch_upstream() -> list[dict]:
    print(f"GET {UPSTREAM_URL}")
    req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "wkvrcft-legacy-registry-sync/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def wipe_local_modules() -> None:
    """Drop incoming/<uuid>/ and v1/modules/<uuid>/ trees so the resulting
    publish run reflects only what we import in this script's pass."""
    incoming = repo_root() / "incoming"
    if incoming.is_dir():
        for child in incoming.iterdir():
            if child.is_dir():
                print(f"  wipe incoming/{child.name}/")
                shutil.rmtree(child)

    modules = repo_root() / "v1" / "modules"
    if modules.is_dir():
        for child in modules.iterdir():
            if child.is_dir():
                print(f"  wipe v1/modules/{child.name}/")
                shutil.rmtree(child)


def import_one(entry: dict) -> bool:
    name    = entry.get("ModuleName") or entry.get("moduleName") or "?"
    author  = entry.get("AuthorName") or entry.get("authorName") or "?"
    version = str(entry.get("Version") or entry.get("version") or "1.0.0")
    url     = entry.get("DownloadUrl") or entry.get("downloadUrl") or entry.get("downloadURL")

    if not url:
        print(f"  [SKIP] {name}: no DownloadUrl in upstream entry")
        return False

    # Normalize the version into something semver-ish that our publish workflow
    # accepts. The upstream registry has values like "1.0.5-fix" and "1.7"
    # and "4.10" -- keep them as-is; the publish + validate paths don't
    # enforce a particular shape.
    print(f"\n=== {name} ({author}) v{version} ===")
    print(f"  source: {url}")

    cmd = [
        sys.executable,
        str(repo_root() / "scripts" / "import-upstream.py"),
        "--source", url,
        "--name", name,
        "--vendor", author,
        "--version", version,
        "--allow-overwrite",
    ]
    r = subprocess.run(cmd, cwd=str(repo_root()), capture_output=True, text=True, timeout=240)
    if r.returncode != 0:
        print("  FAIL")
        for line in (r.stderr or r.stdout).splitlines()[-10:]:
            print("    " + line)
        return False

    for line in r.stdout.splitlines():
        if line.startswith(("staged at", "  module ", "  upstream", "  payload")):
            print("  " + line.strip())
    return True


def main() -> int:
    entries = fetch_upstream()
    print(f"upstream returned {len(entries)} modules\n")

    print("wiping local module trees...")
    wipe_local_modules()

    ok = 0
    fail = 0
    failed: list[str] = []
    for entry in entries:
        if import_one(entry):
            ok += 1
        else:
            fail += 1
            failed.append(entry.get("ModuleName") or entry.get("moduleName") or "?")

    print(f"\n========== sync summary ==========")
    print(f"  upstream entries: {len(entries)}")
    print(f"  imported ok:      {ok}")
    print(f"  failed:           {fail}")
    if failed:
        for f in failed:
            print(f"    - {f}")

    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
