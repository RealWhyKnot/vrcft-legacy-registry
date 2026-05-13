# Publishing a module

## One-time setup (publisher onboarding)

1. **Mint a keypair**. From a checkout of this repo:
   ```
   python -m pip install -r scripts/requirements.txt
   python scripts/keygen.py <your-key-id>
   ```
   `<your-key-id>` is a short slug -- it will appear as `signed_by` in every manifest you publish. Pick something memorable and unique (e.g. `whyknot`, `contoso-ft`). The script prints two things:
   - A JSON block you commit as `publishers/<your-key-id>.json`.
   - A 64-character hex seed you must add as the repo secret `EDDSA_SIGNING_SEED_HEX`.

2. **Commit the public key**. Save the printed JSON to `publishers/<your-key-id>.json` and push. Fill in the `name`, `contact`, `added_at` fields (humans-only -- the verifier ignores them). The publish workflow will refresh `v1/trust.json` automatically on push.

3. **Install the signing secret**:
   ```
   gh secret set EDDSA_SIGNING_SEED_HEX \
     --repo RealWhyKnot/vrcft-registry \
     --body '<paste the 64-hex seed from keygen.py>'
   ```
   Keep the seed off-machine after that (you don't need it locally unless you want to sign without CI). Anyone holding it can sign as you.

## Publishing a new module version

1. **Pick a UUID**. Use `python -c "import uuid; print(uuid.uuid4())"` if you're starting fresh. Reuse the same UUID for every version of the same module.

2. **Stage the artefacts** under `incoming/<uuid>/<version>/`:
   - `payload.zip` -- the module bundle the C# host will load. Must contain the entry assembly named in the manifest's `entry_assembly` field.
   - `manifest.template.json` -- the fields below. The workflow fills `payload_sha256`, `payload_size`, and `signed_by` for you; if you supply them, they get overwritten.

3. **Manifest template fields**:
   ```json
   {
     "schema":           1,
     "uuid":             "<must match directory name>",
     "name":             "Display name shown in the host overlay",
     "vendor":           "Vendor or maintainer name",
     "homepage":         "https://example.com",
     "license":          "MIT",
     "version":          "<must match directory name>",
     "sdk_version":      "1.0",
     "min_host_version": "1.0",
     "supported_hmds":   ["quest-pro"],
     "capabilities":     ["unified-expressions", "eye-gaze"],
     "platforms":        ["windows-x64"],
     "entry_assembly":   "VendorModule.dll",
     "entry_type":       "Vendor.FaceTracking.Module",
     "dependencies":     []
   }
   ```
   `homepage`, `license`, `payload_size`, and `dependencies` are optional; everything else is required and type-checked.

4. **Commit + push**. That's it:
   ```
   git add incoming/<uuid>/<version>/
   git commit -m "publish: <module name> <version>"
   git push origin main
   ```

5. **Watch the publish workflow** in the Actions tab. It signs, places the files under `v1/modules/<uuid>/versions/<version>/`, refreshes the latest pointer + index, removes the consumed `incoming/<uuid>/<version>/`, and commits the result. The validate workflow runs on the post-publish state and confirms it. Cloudflare Pages auto-deploys.

If the workflow fails:
- Schema validation errors are printed with the offending field.
- `EDDSA_SIGNING_SEED_HEX` mismatch (the secret doesn't match any `publishers/*.json`) hard-errors before any files move. Fix the secret or commit the missing publisher.
- Re-pushing after fixing re-triggers the workflow.

## Retiring a module version

Delete `v1/modules/<uuid>/versions/<version>/` and push. The validate workflow will refuse the push if `v1/modules/<uuid>/manifest.json` still points at the retired version -- update or delete the latest pointer too. Existing clients that already pulled the retired manifest continue to verify against the previously-fetched signature; the registry just stops serving it to new clients.

## Importing a VRCFaceTracking upstream module (no per-module C#)

The OpenVR-Pair host ships a reflection bridge (`OpenVRPair.FaceTracking.VrcftCompat.ReflectingExtTrackingModuleAdapter`) that loads any upstream VRCFT v2 module at runtime via reflection. To wrap an existing community module, you don't author C# at all -- you point a script at the upstream artifacts and let it generate the bridge config + manifest + payload zip:

```
python scripts/import-upstream.py \
  --source https://github.com/<author>/<module>/releases/download/v1.2/<Module>.zip \
  --name "Quest Pro Face Tracking" \
  --vendor "<author>" \
  --version 1.2.0
```

What the script does:

1. Downloads the upstream zip (or copies a local path / directory).
2. Picks the upstream module DLL by name heuristics (or use `--upstream-assembly Foo.dll` to be explicit).
3. Auto-detects the module's `ExtTrackingModule` subclass via dnfile metadata scan (or use `--upstream-type Namespace.Class` to skip).
4. Derives a stable UUIDv5 from the upstream identity (or use `--uuid <explicit>`).
5. Bundles upstream DLLs + `OpenVRPair.FaceTracking.VrcftCompat.dll` + `OpenVRPair.FaceTracking.ModuleSdk.dll` (+ `Microsoft.Extensions.Logging.Abstractions.dll` if present) into a `payload.zip` containing an `assemblies/` tree.
6. Emits `assemblies/bridge.json` so the reflecting adapter knows which upstream type to instantiate.
7. Writes a manifest template with `entry_type` pointed at the reflecting adapter.
8. Stages everything under `incoming/<uuid>/<version>/`.

Then commit + push as in the standard flow above. The publish workflow signs + places + indexes; no C# was touched.

**Where the script looks for host assemblies**: by default `../OpenVR-WKPairDriver/build/facetracking-host-publish/` (the standard output of `build.ps1` in the monorepo). Override with `--host-build-dir`.

**Caveats this approach inherits from the existing structural shim**:

- The shim assumes upstream's gaze is normalised sin(pitch)/sin(yaw); modules that emit raw radians or 3D gaze need a per-module wrapper or a future extension to the bridge config.
- The shim assumes shape ordering matches Unified Expressions v2; modules built against older SDKs may need a remapping table.
- Upstream constructors accepting parameters other than (parameterless) or `(ILogger)` are not handled; that's the failure case where you fall back to authoring a manual wrapper.

If a module trips one of those caveats, the host's `facetracking_log.<ts>.txt` shows a reflection error at load time naming the missing or mismatched member -- file an issue and we'll either tighten the bridge or ship a one-off wrapper for that module.

## Local signing (no CI)

If you can't (or don't want to) round-trip through the publish workflow, run the signer locally:

```
export EDDSA_SIGNING_SEED_HEX=<your-hex-seed>
python scripts/publish.py
git add -A
git commit -m "publish: ... (local)"
git push
```

The validate workflow still runs server-side and rejects anything broken.
