# Vendored VRCFaceTracking SDK assemblies

Copies of the upstream VRCFaceTracking SDK runtime, bundled with every module the `scripts/import-upstream.py` packager produces. Upstream modules `using VRCFaceTracking.Core.Library.ExtTrackingModule` need these DLLs present in the same `AssemblyLoadContext` to load -- our host (`OpenVRPair.FaceModuleHost`) does not carry them at the host level, so each packaged module brings its own copy.

## Contents

- `VRCFaceTracking.Core.dll` -- the upstream SDK assembly. Provides `ExtTrackingModule`, `UnifiedTracking.Data` static singleton, expression shape definitions, eye data types.
- `Newtonsoft.Json.dll` -- transitive dependency referenced by upstream Core at compile time.
- `Microsoft.Extensions.Logging.Abstractions.dll` -- transitive dependency for the `ILogger` constructor parameter pattern most modules use.
- `fti_osc.dll` -- the native OSC sender library upstream Core copies as a content asset. Carried for completeness; our host has its own OSC path so this is normally inert, but some modules reference symbols from it at load time.

## Provenance

Built from source at `https://github.com/benaclejames/VRCFaceTracking` tag `5.2.3.0` (`AssemblyVersion = 5.1.1.1`) via `dotnet publish VRCFaceTracking.Core -c Release --no-self-contained`.

The official GitHub release zip (`VRCFaceTracking_5.2.3.0_x64.zip`) has the central-directory `encrypted` flag set on every entry by Microsoft's WiX/NSIS toolchain, which trips standard zip-extraction libraries (Python's `zipfile`, PowerShell's `Expand-Archive`, 7-Zip without a password). Building from source side-steps that.

## Updating

```
git clone --depth 1 --branch <new-tag> https://github.com/benaclejames/VRCFaceTracking.git /tmp/vrcft-source
cd /tmp/vrcft-source
dotnet publish VRCFaceTracking.Core/VRCFaceTracking.Core.csproj -c Release --no-self-contained -o /tmp/vrcft-publish
cp /tmp/vrcft-publish/{VRCFaceTracking.Core.dll,Newtonsoft.Json.dll,Microsoft.Extensions.Logging.Abstractions.dll,fti_osc.dll} \
   D:/Github/OpenVR/vrcft-registry/lib/vrcft-sdk/
```

Bump the upstream tag pin in this file when you do.

## License

VRCFaceTracking is licensed under MIT (`https://github.com/benaclejames/VRCFaceTracking/blob/master/LICENSE`). MIT permits redistribution of compiled binaries with the license + copyright notice preserved. The MIT license text is reproduced in this repository's root `NOTICE.md` alongside the GPL-3.0 notice for the registry itself.

Newtonsoft.Json is MIT-licensed (`https://www.newtonsoft.com/json`). Microsoft.Extensions.* are MIT-licensed (`https://github.com/dotnet/runtime/blob/main/LICENSE.TXT`).
