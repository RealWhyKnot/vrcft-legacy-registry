#!/usr/bin/env python3
"""
Generate a fresh Ed25519 publisher keypair. Prints the seed hex (for the
EDDSA_SIGNING_SEED_HEX repo secret) and the public key base64 (for the
publishers/<key_id>.json file). Does not touch the filesystem -- you
copy + commit + add-secret yourself so the private material never lives
in the repo or in shell history.

Usage:
  python scripts/keygen.py <key_id>

The key_id is the string that will appear as 'signed_by' in every
manifest you publish and as the filename in publishers/.  Choose
something memorable and unique (e.g. 'whyknot', 'contoso-ft').
"""

from __future__ import annotations

import base64
import json
import sys

from nacl.signing import SigningKey


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: keygen.py <key_id>", file=sys.stderr)
        return 2
    key_id = argv[1].strip().lower()
    if not key_id:
        print("key_id must be non-empty", file=sys.stderr)
        return 2

    sk = SigningKey.generate()
    seed_hex = bytes(sk).hex()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode("ascii")

    print()
    print("===== publishers/" + key_id + ".json =====")
    print(json.dumps(
        {
            "key_id": key_id,
            "ed25519_pub": pub_b64,
            "name": "",
            "contact": "",
            "added_at": ""
        },
        indent=2,
    ))
    print()
    print("===== GitHub repo secret EDDSA_SIGNING_SEED_HEX =====")
    print(seed_hex)
    print()
    print("Add the secret with:")
    print(
        "  gh secret set EDDSA_SIGNING_SEED_HEX "
        "--repo RealWhyKnot/vrcft-registry --body '"
        + seed_hex
        + "'"
    )
    print()
    print("KEEP THE SEED OUT OF GIT.  Anyone with the seed can sign modules "
          "as this publisher.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
