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
