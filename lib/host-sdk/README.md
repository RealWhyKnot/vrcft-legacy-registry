# Vendored OpenVR-Pair face-module host assemblies

Two host-side C# assemblies copied into every module's `payload.zip` by
`scripts/import-upstream.py`. The reflecting adapter that bridges upstream
`ExtTrackingModule` types into our host runtime lives in
`OpenVRPair.FaceTracking.VrcftCompat.dll`, and the small contract surface it
links against lives in `OpenVRPair.FaceTracking.ModuleSdk.dll`. A module zip
without these two DLLs fails to load -- the reflecting adapter is the
`entry_type` named in the manifest.

The script falls back to a sibling-checkout host build at
`../WKOpenVR/build/facetracking-host-publish/` only if `--host-build-dir` is
passed explicitly; the default resolves to this directory. That keeps the
daily `sync-upstream` workflow self-contained on `ubuntu-latest`, where the
WKOpenVR repo isn't present.

## Contents

- `OpenVRPair.FaceTracking.VrcftCompat.dll` -- the reflecting adapter
  (`ReflectingExtTrackingModuleAdapter`). Reads `bridge.json` at module load
  time and reflects into the upstream module type.
- `OpenVRPair.FaceTracking.ModuleSdk.dll` -- module SDK contract surface the
  adapter compiles against.

`Microsoft.Extensions.Logging.Abstractions.dll` is intentionally not
duplicated here; the `lib/vrcft-sdk/` tree already ships it and every payload
gets both trees merged into `assemblies/`.

## Updating

Run from the WKOpenVR checkout:

```
cd WKOpenVR
dotnet publish modules/facetracking/src/host/OpenVRPair.FaceModuleHost/OpenVRPair.FaceModuleHost.csproj \
    -c Release \
    -o build/facetracking-host-publish
```

Then copy the two DLLs over and refresh this README's date:

```
cp WKOpenVR/build/facetracking-host-publish/OpenVRPair.FaceTracking.VrcftCompat.dll \
   WKOpenVR/build/facetracking-host-publish/OpenVRPair.FaceTracking.ModuleSdk.dll \
   wkvrcft-legacy-registry/lib/host-sdk/
```

Re-run `python scripts/sync-upstream.py` locally before committing -- a stale
host-sdk produces module payloads that load but throw on first sample.

## License

GPL-3.0; same license as the rest of `wkvrcft-legacy-registry` and the
WKOpenVR host source these assemblies are built from. See the repository
root `LICENSE` and `NOTICE.md`.
