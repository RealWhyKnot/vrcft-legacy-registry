# Incoming

Drop a new module version here as `incoming/<module_uuid>/<version>/` containing:

- `payload.zip` -- the module DLL bundle the C# host will load.
- `manifest.template.json` -- the manifest **without** the computed fields (the publish workflow fills `payload_sha256`, `payload_size`, and `signed_by` for you).

The `publish.yml` workflow runs on every push that touches `incoming/**`. For each `incoming/<uuid>/<version>/` directory it:

1. Verifies the template carries `uuid` == directory name, `version` == directory name.
2. Computes SHA-256 of `payload.zip` -> sets `payload_sha256` (lowercase hex) and `payload_size`.
3. Stamps `signed_by` to the active publisher key (from `EDDSA_SIGNING_SEED_HEX` -> matched against `publishers/`).
4. Signs `SHA256(payload.zip)` with the private key -> writes `signature.bin` (raw 64 bytes).
5. Writes the finished `manifest.json` + `payload.zip` + `signature.bin` to `v1/modules/<uuid>/versions/<version>/`.
6. Copies the finished manifest to `v1/modules/<uuid>/manifest.json` (the "latest" pointer).
7. Regenerates `v1/index.json` from every published manifest.
8. Deletes the consumed `incoming/<uuid>/<version>/` directory.
9. Commits and pushes the result; Cloudflare Pages auto-deploys.

If the manifest template is missing required fields or the directory shape is wrong, the workflow fails and nothing lands. Re-push after fixing.

## Manifest template fields you must fill

```json
{
  "schema": 1,
  "uuid":             "<must match the directory name>",
  "name":             "Vendor Module Display Name",
  "vendor":           "Vendor Co.",
  "homepage":         "https://example.com",
  "license":          "MIT",
  "version":          "<must match the directory name>",
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

`payload_sha256`, `payload_size`, and `signed_by` are filled by the workflow; if you include them, they get overwritten.
