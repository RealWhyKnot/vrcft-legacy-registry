# vrcft-legacy-registry

Signed CDN-hosted copy of every module the upstream [VRCFaceTracking](https://github.com/benaclejames/VRCFaceTracking) app shows in its Modules tab. Served at `https://registry.whyknot.dev` so the OpenVR-Pair face-tracking host can fetch and load the same modules without re-authoring any of them.

The native module SDK that will eventually replace this lives in [OpenVR-WKPairDriver](https://github.com/RealWhyKnot/OpenVR-WKPairDriver) under `modules/facetracking/`. Once it ships, new modules will be authored against it directly and this mirror's role tapers off; existing legacy modules stay supported here.

## Endpoints

| URL | Returns |
|---|---|
| `https://registry.whyknot.dev/v1/index` | List of every module and its latest version |
| `https://registry.whyknot.dev/v1/trust.json` | Trusted publisher Ed25519 public keys |
| `https://registry.whyknot.dev/v1/modules/<uuid>/manifest` | Module's latest manifest JSON |
| `https://registry.whyknot.dev/v1/modules/<uuid>/versions/<ver>/manifest` | Pinned version's manifest |
| `https://registry.whyknot.dev/v1/modules/<uuid>/versions/<ver>/payload` | Signed module zip |
| `https://registry.whyknot.dev/v1/modules/<uuid>/versions/<ver>/signature` | 64-byte Ed25519 signature |

End users don't interact with this repository directly. The OpenVR-Pair host fetches manifests + payloads from `registry.whyknot.dev`, verifies signatures against the keys in `v1/trust.json`, and loads the module.

## Mirroring

Upstream's authoritative module list lives behind `https://rjlk4u22t36tvqz3bvbkwv675a0wbous.lambda-url.us-east-1.on.aws/modules` -- the same endpoint the VRCFaceTracking app reads. A scheduled workflow polls it once a day, re-imports any added or updated module, and re-signs. Removed modules drop out of the index. The set is byte-for-byte aligned with what upstream considers natively supported, with at most a 24-hour propagation lag.

## License

GPL-3.0; see `LICENSE`. Includes redistributed copies of upstream-licensed assemblies whose licenses are reproduced in `NOTICE.md`.
