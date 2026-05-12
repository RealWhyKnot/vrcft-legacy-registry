# vrcft-registry

Static module registry for the FaceTracking feature of [OpenVR-Pair](https://github.com/RealWhyKnot/OpenVR-WKPairDriver). Hosted at `https://registry.whyknot.dev` via Cloudflare Pages; backed by the contents of this repo.

The C# host (`OpenVRPair.FaceModuleHost`) fetches module manifests + payloads + Ed25519 signatures from `registry.whyknot.dev`. This repo is the source-of-truth for what's served there: every push that touches `incoming/` or `publishers/` runs the publish workflow, which signs the new payload, places it under `v1/modules/<uuid>/versions/<version>/`, refreshes the index + trust list, and commits the result. Cloudflare Pages picks up the new commit and deploys.

## Layout

```
v1/
  index.json                              listing of every module's latest version
  trust.json                              publishers' public keys, mirrored from publishers/
  modules/
    <uuid>/
      manifest.json                       "latest" pointer (copy of newest version's manifest)
      versions/
        <semver>/
          manifest.json                   fully stamped + signed manifest
          payload.zip                     the module DLL bundle
          signature.bin                   Ed25519(SHA256(payload.zip)), 64 raw bytes
publishers/
  <key_id>.json                           one file per trusted publisher
incoming/
  <uuid>/<version>/
    payload.zip                           author drops this
    manifest.template.json                author drops this; workflow fills computed fields
scripts/
  publish.py                              signs incoming/, places under v1/, regenerates index + trust
  validate.py                             CI: schema + payload hash + signature checks
  keygen.py                               one-shot helper to mint a publisher keypair
_headers / _redirects                     Cloudflare Pages config (extensionless URLs + caching)
```

## Endpoints

| URL (as the C# host calls it) | Served from | Content-Type |
|---|---|---|
| `GET /v1/index` | `v1/index.json` | `application/json` |
| `GET /v1/trust.json` | `v1/trust.json` | `application/json` |
| `GET /v1/modules/<uuid>/manifest` | `v1/modules/<uuid>/manifest.json` | `application/json` |
| `GET /v1/modules/<uuid>/versions/<ver>/manifest` | `.../manifest.json` | `application/json` |
| `GET /v1/modules/<uuid>/versions/<ver>/payload` | `.../payload.zip` | `application/zip` |
| `GET /v1/modules/<uuid>/versions/<ver>/signature` | `.../signature.bin` (exactly 64 bytes) | `application/octet-stream` |

`_redirects` handles the extensionless mapping. `/v1/index` ships with a short cache lifetime (60 s, ETag-revalidated); per-version artefacts carry `Cache-Control: immutable` for a year because a republish always ships as a new directory.

## Publishing a module

See [PUBLISHING.md](PUBLISHING.md).

## End-user trust setup

See [TRUST.md](TRUST.md).

## License

GPL-3.0. The signed payloads each carry their own license inside the zip.
