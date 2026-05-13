# wkvrcft-legacy-registry

Mirror of every module the upstream [VRCFaceTracking](https://github.com/benaclejames/VRCFaceTracking) app shows in its Modules tab. Served at `https://legacy-registry.whyknot.dev` so the OpenVR-Pair face-tracking host can fetch and load the same modules without re-authoring any of them.

The native module SDK that will eventually replace this lives in [OpenVR-WKPairDriver](https://github.com/RealWhyKnot/OpenVR-WKPairDriver) under `modules/facetracking/`. Once it ships, new modules will be authored against it directly and surfaced separately in the host overlay; legacy modules stay supported here and continue to load via the existing compatibility shim.

## Endpoints

| URL | Returns |
|---|---|
| `https://legacy-registry.whyknot.dev/v1/index` | List of every module and its latest version |
| `https://legacy-registry.whyknot.dev/v1/modules/<uuid>/manifest` | Module's latest manifest JSON |
| `https://legacy-registry.whyknot.dev/v1/modules/<uuid>/versions/<ver>/manifest` | Pinned version's manifest |
| `https://legacy-registry.whyknot.dev/v1/modules/<uuid>/versions/<ver>/payload` | Module zip |

End users don't interact with this repository directly. The OpenVR-Pair host fetches manifests + payloads, verifies the payload SHA-256 against the manifest, and loads the module under the Legacy tab.

## Mirroring

Upstream's authoritative module list lives behind `https://rjlk4u22t36tvqz3bvbkwv675a0wbous.lambda-url.us-east-1.on.aws/modules` -- the same endpoint the VRCFaceTracking app reads. A scheduled workflow polls it once a day, re-imports any added or updated module, and republishes. Removed modules drop out of the index. The set is byte-for-byte aligned with what upstream considers natively supported, with at most a 24-hour propagation lag.

## Trust model

Curated mirror, not a marketplace. Both registries (this legacy one and the eventual native one) are owned by the same maintainer, so trust is administrative -- a module is here because the maintainer chose to mirror it. SHA-256 of `payload.zip` in each manifest catches transport corruption or CDN poisoning; no signing key is involved.

## License

GPL-3.0; see `LICENSE`. Includes redistributed copies of upstream-licensed assemblies whose licenses are reproduced in `NOTICE.md`.
