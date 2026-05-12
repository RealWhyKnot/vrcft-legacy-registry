# Publishers

Each file in this directory is the public-key record for one trusted module publisher. Filenames are `<key_id>.json`, where `key_id` is the string the manifest's `signed_by` field will reference.

## Shape

```json
{
  "key_id": "whyknot",
  "ed25519_pub": "<base64-of-32-raw-public-key-bytes>",
  "name": "WhyKnot",
  "contact": "https://github.com/RealWhyKnot",
  "added_at": "2026-05-12"
}
```

The C# host's `Ed25519Verifier` only reads `key_id` and `ed25519_pub` (the rest is for humans). The aggregator script copies these two fields into `/v1/trust.json` so end users can `curl` a fresh trust list.

## Adding a publisher

1. Generate an Ed25519 keypair (see PUBLISHING.md for the exact `python -c` one-liner).
2. Commit the public-key JSON under this directory.
3. The `publish.yml` workflow rebuilds `/v1/trust.json` automatically.
4. Add the private key as the repo secret `EDDSA_SIGNING_SEED_HEX` if this publisher is going to sign through CI. Local-signing publishers keep their key off-repo.

## Removing trust

Delete the publisher file and let the workflow rebuild the trust list. Modules signed by a removed key continue to live in `/v1/modules/` until they're explicitly retired, but end users will refuse to load them after they pull the new trust list.
