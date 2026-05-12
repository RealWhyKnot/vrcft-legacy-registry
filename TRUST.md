# End-user trust setup

The OpenVR-Pair face-tracking host refuses to load any module whose signature it can't verify. Verification needs a local file at `%LocalAppDataLow%\OpenVR-Pair\facetracking\trust.json` that lists the Ed25519 public keys you trust.

For convenience, the canonical trust list is also served at `https://registry.whyknot.dev/v1/trust.json` (mirrored from this repo's `publishers/`). End users can copy it into place once and forget; it changes only when a new publisher is added or an old one rotates keys.

## Install (one-shot)

PowerShell:

```
$dest = "$env:LocalAppData\..\LocalLow\OpenVR-Pair\facetracking\trust.json"
New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
Invoke-WebRequest https://registry.whyknot.dev/v1/trust.json -OutFile $dest
```

curl:

```
mkdir -p "$LOCALAPPDATA/../LocalLow/OpenVR-Pair/facetracking"
curl -fsSL https://registry.whyknot.dev/v1/trust.json \
  -o "$LOCALAPPDATA/../LocalLow/OpenVR-Pair/facetracking/trust.json"
```

After dropping the file, the host picks it up on its next startup. Toggle the FaceTracking row off and on in the Modules tab if SteamVR is already running.

## What's in the trust list

```json
{
  "keys": [
    { "key_id": "whyknot", "ed25519_pub": "<base64 of 32-byte public key>" }
  ]
}
```

Each entry is one publisher. The host accepts a module manifest only when its `signed_by` field names a `key_id` present here AND the module's signature verifies against that key.

## Pinning a specific publisher (paranoid mode)

If you'd rather trust only a subset of what the canonical list endorses, edit `trust.json` by hand and remove the entries you don't want. Order doesn't matter; `key_id` lookup is case-insensitive.

## Developer mode

The host's overlay Advanced tab has an `Enable unsigned modules (developer mode)` toggle. With it on, the verifier is bypassed entirely -- the host will load any DLL you point at. Don't leave that on in production; it disables every safety check this registry exists to provide.

## Rotating a publisher key

A publisher who needs to rotate generates a new keypair, commits the new public key as a second `publishers/` entry (so old + new live side-by-side for a while), and signs new module versions with the new key. End users update their `trust.json` by re-running the install command above. Once everyone's rotated, the old `publishers/` entry can be retired and removed; manifests signed by the retired key will stop verifying for newly-updated clients.
