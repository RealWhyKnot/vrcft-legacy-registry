#!/usr/bin/env python3
"""
Import a VRCFaceTracking-format upstream module and stage it under
incoming/ so the publish workflow can sign + ship it.

Goal: zero per-module C# wrapper code. The OpenVRPair.FaceTracking.VrcftCompat
host project ships a ReflectingExtTrackingModuleAdapter that reads a
bridge.json sidecar at load time and reflects into the upstream module's
type via the standard VRCFT v2 surface. This script generates that
bridge.json, gathers the upstream DLLs alongside our own SDK + shim
assemblies, and emits the manifest the publish workflow consumes.

Usage:
    python scripts/import-upstream.py \\
        --source <url-or-path-to-zip-or-dir-with-upstream-files> \\
        --name "Display Name" \\
        --vendor "Vendor Co." \\
        --version 1.0.0 \\
        [--uuid auto] \\
        [--upstream-type FullNamespace.ClassName] \\
        [--supported-hmds quest-pro,vive-pro-eye] \\
        [--capabilities eye,expression] \\
        [--host-build-dir <path>]

If --upstream-type is omitted, the script tries to auto-detect by parsing
the upstream DLLs for a class extending ExtTrackingModule. Requires the
optional dnfile dependency; install via pip install -r scripts/requirements.txt.

If --uuid is omitted or set to "auto", a deterministic UUIDv5 is generated
from the upstream-assembly name + upstream-type name, so a re-import of
the same module under a new version reuses the same UUID.

If --host-build-dir is omitted, the script looks for the OpenVR-Pair
monorepo's host build output at the default sibling location:
    ../OpenVR-WKPairDriver/build/facetracking-host-publish/

The output is staged under incoming/<uuid>/<version>/. Push to main and
the publish workflow signs + places + indexes it.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import uuid as _uuid
import zipfile
from pathlib import Path


# UUIDv5 namespace for vrcft-registry module IDs. Arbitrary fixed value; any
# import that resolves the same (upstream_assembly, upstream_type) pair gets
# the same module UUID, so version bumps stay under one identity.
MODULE_NS = _uuid.UUID("0c5f8a06-b6f0-4a02-b3c2-2f4b3df8a915")

# Files copied from the host's facetracking-host-publish directory into
# every packaged module's assemblies/ folder. These are the bare minimum
# the reflecting adapter needs at load time.
REQUIRED_HOST_ASSEMBLIES = (
    "OpenVRPair.FaceTracking.VrcftCompat.dll",
    "OpenVRPair.FaceTracking.ModuleSdk.dll",
)

# Optional but commonly needed for upstream modules that take an ILogger
# constructor parameter. Copied if present in the host build dir; if not,
# the upstream module is expected to have a parameterless constructor.
OPTIONAL_HOST_ASSEMBLIES = (
    "Microsoft.Extensions.Logging.Abstractions.dll",
)

# Every DLL under vrcft-registry/lib/vrcft-sdk/ is copied into each
# imported module's assemblies/ directory. Upstream VRCFT modules extend
# VRCFaceTracking.Core.Library.ExtTrackingModule -- without VRCFaceTracking.Core
# (and its transitive deps) on the load path, the module's class
# hierarchy fails to resolve and the reflecting adapter throws on type
# lookup. See lib/vrcft-sdk/README.md for what's in there and how to
# rebuild it.
VRCFT_SDK_DIR_NAME = "vrcft-sdk"

# Upstream base class the auto-detector looks for. VRCFT v2 SDK convention.
UPSTREAM_BASE_TYPE_NAME = "ExtTrackingModule"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- arg parsing

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Stage a VRCFaceTracking upstream module under incoming/.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--source", required=True,
                   help="URL of a zip, path to a local zip, or path to a directory containing upstream DLLs.")
    p.add_argument("--name", required=True,
                   help="Human-readable module name shown in the host overlay.")
    p.add_argument("--vendor", required=True,
                   help="Vendor / publisher name shown in the host overlay.")
    p.add_argument("--version", required=True,
                   help="Module version (semver-ish: 1.2.3, 1.2.3.4, etc.).")
    p.add_argument("--uuid", default="auto",
                   help='Module UUID, or "auto" to derive deterministically from upstream identity.')
    p.add_argument("--upstream-type", default=None,
                   help="Fully-qualified upstream class name (Namespace.Class). "
                        "Omit to auto-detect via dnfile.")
    p.add_argument("--upstream-assembly", default=None,
                   help="Filename of the upstream DLL inside the source archive. Omit for auto-pick.")
    p.add_argument("--supported-hmds", default="*",
                   help='Comma-separated HMD identifiers, or "*" for all.')
    p.add_argument("--capabilities", default="eye,expression",
                   help="Comma-separated subset of: eye, expression.")
    p.add_argument("--host-build-dir", default=None, type=Path,
                   help="Where to find OpenVRPair.FaceTracking.VrcftCompat.dll etc.")
    p.add_argument("--allow-overwrite", action="store_true",
                   help="Allow overwriting an existing incoming/<uuid>/<version>/ directory.")
    return p.parse_args()


def parse_csv(v: str) -> list[str]:
    return [s.strip() for s in v.split(",") if s.strip()]


# ---------------------------------------------------------------- source fetch

def fetch_source(source: str, workdir: Path) -> Path:
    """Resolve --source into a directory containing upstream files.

    Returns the directory holding the extracted/copied tree.
    """
    if source.startswith(("http://", "https://")):
        return _download(source, workdir)

    sp = Path(source).expanduser().resolve()
    if not sp.exists():
        fail(f"--source path does not exist: {sp}")

    if sp.is_dir():
        return sp

    target = workdir / "extracted"
    target.mkdir(parents=True, exist_ok=True)
    suffix = sp.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(sp) as zf:
            zf.extractall(target)
    elif suffix == ".dll":
        shutil.copy2(sp, target / sp.name)
    else:
        fail(f"--source must be a zip, dll, or directory; got {sp.suffix}")
    return target


def _download(url: str, workdir: Path) -> Path:
    """Download a release asset (zip or bare DLL) into a working directory."""
    print(f"downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "vrcft-registry-importer/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()

    target = workdir / "extracted"
    target.mkdir(parents=True, exist_ok=True)

    # Sniff: zips start with PK; DLLs start with MZ.
    if body[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            zf.extractall(target)
    elif body[:2] == b"MZ":
        # Bare DLL. Name it from the URL's last path component.
        name = url.rsplit("/", 1)[-1].split("?", 1)[0] or "upstream.dll"
        if not name.lower().endswith(".dll"):
            name += ".dll"
        (target / name).write_bytes(body)
    else:
        fail(f"Downloaded asset isn't a zip or DLL (first 2 bytes: {body[:2]!r}).")
    return target


# ---------------------------------------------------------------- DLL discovery

def discover_dlls(source_dir: Path) -> list[Path]:
    """All .dll files in source_dir recursively. Sorted for determinism."""
    return sorted(p for p in source_dir.rglob("*.dll"))


def pick_upstream_dll(dlls: list[Path], hint: str | None) -> Path:
    """Choose which DLL is the upstream vendor module.

    If --upstream-assembly was given, find it exactly. Otherwise pick a
    DLL whose name looks like a vendor module (not Microsoft.*, not
    System.*, not VRCFaceTracking.Core, not our own assemblies).
    """
    if hint is not None:
        match = [d for d in dlls if d.name.lower() == hint.lower()]
        if not match:
            fail(f"--upstream-assembly '{hint}' not found in source. "
                 f"Available DLLs: {', '.join(d.name for d in dlls)}")
        return match[0]

    excluded = re.compile(
        r"^(System\.|Microsoft\.|VRCFaceTracking\.Core|OpenVRPair\.FaceTracking\.|"
        r"netstandard|mscorlib|WindowsBase|PresentationCore|UnityEngine|"
        r"Newtonsoft\.Json|NSec\.|libsodium|fti_osc)",
        re.IGNORECASE,
    )
    # macOS sometimes ships resource-fork sidecars (`._Foo.dll`) inside zips
    # created on macOS. Those aren't real PE images; skip them.
    candidates = [d for d in dlls
                  if not excluded.match(d.name)
                  and not d.name.startswith("._")]

    # Filter to managed (.NET) DLLs. Native libs (SRanipal SDK, openxr_loader,
    # starvr_api, etc.) ship inside many module zips alongside the actual
    # ExtTrackingModule implementation. dnfile's mdtables presence is the
    # tell: managed assemblies carry CLR metadata, native ones don't.
    try:
        import dnfile  # noqa: F401
        managed: list[Path] = []
        for c in candidates:
            try:
                pe = __import__("dnfile").dnPE(str(c))
                if pe.net is not None and pe.net.mdtables is not None:
                    managed.append(c)
            except Exception:
                continue
        if managed:
            candidates = managed
    except ImportError:
        pass  # dnfile optional; native DLLs may slip through and the disambig error fires

    if not candidates:
        fail("Could not pick an upstream DLL automatically. "
             "Pass --upstream-assembly with the filename.")

    if len(candidates) > 1:
        # Heuristic: prefer a DLL whose name carries one of the conventional
        # markers VRCFT module authors use (VRCFT / Module / ExtTracking /
        # FaceTracking). Falls back to the disambiguation error.
        marker = re.compile(r"(VRCFT|FaceTracking|ExtTracking|Module)", re.IGNORECASE)
        marked = [c for c in candidates if marker.search(c.name)]
        if len(marked) == 1:
            return marked[0]
        names = ", ".join(c.name for c in candidates)
        fail(f"Multiple candidate upstream DLLs found ({names}). "
             f"Pass --upstream-assembly to disambiguate.")
    return candidates[0]


def detect_upstream_type(dll: Path) -> str | None:
    """Use dnfile to find a class extending ExtTrackingModule. Returns
    the fully-qualified type name, or None on auto-detect failure."""
    try:
        import dnfile  # type: ignore[import-not-found]
    except ImportError:
        return None

    try:
        pe = dnfile.dnPE(str(dll))
    except Exception as e:
        print(f"warning: dnfile could not parse {dll.name}: {e}", file=sys.stderr)
        return None

    if pe.net is None or pe.net.mdtables is None:
        return None

    typedef_table = pe.net.mdtables.TypeDef
    typeref_table = pe.net.mdtables.TypeRef
    if typedef_table is None:
        return None

    matches: list[str] = []
    for row in typedef_table.rows:
        if row.TypeName == "<Module>":
            continue
        # row.Extends is a coded index (TypeDefOrRef). dnfile resolves it to
        # the row reference if available; otherwise to a raw index.
        base = getattr(row, "Extends", None)
        base_name = None
        if base is None:
            continue
        # When Extends is a row reference (dnfile resolved it), it has TypeName.
        if hasattr(base, "row") and base.row is not None:
            base_name = getattr(base.row, "TypeName", None)
        elif hasattr(base, "TypeName"):
            base_name = base.TypeName
        if base_name != UPSTREAM_BASE_TYPE_NAME:
            continue
        full = f"{row.TypeNamespace}.{row.TypeName}" if row.TypeNamespace else row.TypeName
        matches.append(full)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"warning: {dll.name} has multiple ExtTrackingModule subclasses: {matches}. "
              f"Pass --upstream-type to disambiguate.", file=sys.stderr)
        return None
    return None


# ---------------------------------------------------------------- host assets

def resolve_host_build_dir(arg: Path | None) -> Path:
    if arg is not None:
        d = arg.expanduser().resolve()
        if not d.is_dir():
            fail(f"--host-build-dir does not exist: {d}")
        return d

    default = repo_root().parent / "OpenVR-WKPairDriver" / "build" / "facetracking-host-publish"
    if not default.is_dir():
        fail(f"Default host build dir not found at {default}. "
             "Build the host (cmake --build ... or build.ps1) or pass --host-build-dir.")
    return default


# ---------------------------------------------------------------- packaging

def stage_module(args: argparse.Namespace) -> Path:
    workdir = Path(tempfile.mkdtemp(prefix="vrcft-import-"))
    try:
        return _stage_module_inner(args, workdir)
    finally:
        # Always clean the temp work area; the staged files live under
        # incoming/ on the repo tree and are committed by the caller.
        shutil.rmtree(workdir, ignore_errors=True)


def _stage_module_inner(args: argparse.Namespace, workdir: Path) -> Path:
    source_dir = fetch_source(args.source, workdir)
    dlls = discover_dlls(source_dir)
    if not dlls:
        fail(f"No .dll files found in source ({source_dir}).")

    upstream_dll = pick_upstream_dll(dlls, args.upstream_assembly)
    upstream_type = args.upstream_type or detect_upstream_type(upstream_dll)
    if not upstream_type:
        fail("Could not auto-detect upstream type. "
             f"Pass --upstream-type 'Namespace.ClassName' (target DLL: {upstream_dll.name}). "
             "Auto-detect requires dnfile -- install via pip install -r scripts/requirements.txt.")

    module_uuid = args.uuid
    if module_uuid == "auto":
        ident = f"{upstream_dll.name}:{upstream_type}"
        module_uuid = str(_uuid.uuid5(MODULE_NS, ident))

    incoming = repo_root() / "incoming" / module_uuid / args.version
    if incoming.exists():
        if not args.allow_overwrite:
            fail(f"{incoming} already exists. Pass --allow-overwrite or bump --version.")
        shutil.rmtree(incoming)
    incoming.mkdir(parents=True)

    host_dir = resolve_host_build_dir(args.host_build_dir)

    # Build the assemblies/ tree inside the workdir, then zip it.
    asm_root = workdir / "assemblies"
    asm_root.mkdir()

    # Copy every upstream DLL into assemblies/, no exceptions. This is
    # deliberately broader than the auto-pick: pick_upstream_dll's exclude
    # list is for "which one carries the primary class" only. The payload
    # itself must include all upstream DLLs, including native libs the
    # vendor module P/Invokes (SRanipal SDK, openxr_loader, starvr_api,
    # tobii_stream_engine, libHTC_License, nanomsg, Meta-OpenXR-Bridge,
    # etc.) -- otherwise the module loads but throws DllNotFoundException
    # on its first hardware sample. The host's ModuleLoadContext.LoadUnmanagedDll
    # override probes this directory at native-load time.
    for d in dlls:
        shutil.copy2(d, asm_root / d.name)
    # Native .dll / .so / config / runtimes/ subtrees that ship next to the upstream module.
    for extra in source_dir.rglob("*"):
        if not extra.is_file():
            continue
        if extra.suffix.lower() in (".dll", ".so", ".dylib", ".pdb", ".xml"):
            continue
        if extra.suffix.lower() in (".json", ".config"):
            target = asm_root / extra.relative_to(source_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extra, target)

    # Bring in host-side assemblies the adapter needs at load time.
    for asm in REQUIRED_HOST_ASSEMBLIES:
        src = host_dir / asm
        if not src.exists():
            fail(f"required host assembly missing: {src}")
        shutil.copy2(src, asm_root / asm)
    for asm in OPTIONAL_HOST_ASSEMBLIES:
        src = host_dir / asm
        if src.exists():
            shutil.copy2(src, asm_root / asm)

    # Bundle the vendored VRCFaceTracking SDK + transitive deps so the
    # upstream module's class hierarchy resolves at load time. Don't
    # overwrite a copy the upstream zip already shipped (the upstream
    # author may have pinned a specific SDK version on purpose).
    sdk_dir = repo_root() / "lib" / VRCFT_SDK_DIR_NAME
    if sdk_dir.is_dir():
        for sdk_dll in sdk_dir.glob("*.dll"):
            target = asm_root / sdk_dll.name
            if target.exists():
                continue
            shutil.copy2(sdk_dll, target)
    else:
        fail(f"lib/{VRCFT_SDK_DIR_NAME}/ not found. "
             "See lib/vrcft-sdk/README.md for how to populate it.")

    # Emit bridge.json alongside the VrcftCompat DLL.
    bridge = {
        "uuid":              module_uuid,
        "name":              args.name,
        "vendor":            args.vendor,
        "version":           args.version,
        "supported_hmds":    parse_csv(args.supported_hmds),
        "capabilities":      parse_csv(args.capabilities),
        "upstream_assembly": upstream_dll.name,
        "upstream_type":     upstream_type,
    }
    with (asm_root / "bridge.json").open("w", encoding="utf-8") as f:
        json.dump(bridge, f, indent=2, sort_keys=True)
        f.write("\n")

    # Zip the assemblies/ tree into payload.zip.
    payload = workdir / "payload.zip"
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(asm_root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(workdir))

    shutil.copy2(payload, incoming / "payload.zip")

    # Manifest template -- publish workflow fills in payload_sha256 / size / signed_by.
    manifest = {
        "schema":           1,
        "uuid":             module_uuid,
        "name":             args.name,
        "vendor":           args.vendor,
        "version":          args.version,
        "sdk_version":      "1.0",
        "min_host_version": "1.0",
        "supported_hmds":   parse_csv(args.supported_hmds),
        "capabilities":     parse_csv(args.capabilities),
        "platforms":        ["windows-x64"],
        "entry_assembly":   "OpenVRPair.FaceTracking.VrcftCompat.dll",
        "entry_type":       "OpenVRPair.FaceTracking.VrcftCompat.ReflectingExtTrackingModuleAdapter",
        "dependencies":     [],
    }
    with (incoming / "manifest.template.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"\nstaged at {incoming.relative_to(repo_root())}")
    print(f"  module name:    {args.name}")
    print(f"  module uuid:    {module_uuid}")
    print(f"  version:        {args.version}")
    print(f"  upstream dll:   {upstream_dll.name}")
    print(f"  upstream type:  {upstream_type}")
    print(f"  payload bytes:  {payload.stat().st_size:,}")
    print()
    print("Next:")
    print(f"  git add incoming/")
    print(f"  git commit -m 'publish: {args.name} {args.version}'")
    print(f"  git push origin main")
    print()
    print("The publish workflow will sign + place + index. Cloudflare deploys.")
    return incoming


def main() -> None:
    args = parse_args()
    stage_module(args)


if __name__ == "__main__":
    main()
