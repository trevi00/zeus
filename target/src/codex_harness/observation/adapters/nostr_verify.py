"""Nostr event verification: the id recomputed from the fields, then the BIP-340 signature over that id.

Layer: adapters
Context: observation
Owns: `verify_event` (the `EventVerifier` implementation)
Does not own: the id serialization and the event shape (`observation.domain.nostr_event`), the BIP-340
    arithmetic (`observation.domain.bip340`)
Entry points: verify_event
Contracts: NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md (id and sig);
    BIP-340 https://github.com/bitcoin/bips/blob/master/bip-0340.mediawiki

A malformed shape raises ContractError; a well-formed event with a wrong id or signature returns False.
"""

from __future__ import annotations

from codex_harness.observation.domain.bip340 import verify
from codex_harness.observation.domain.nostr_event import event_id, validate_event


def verify_event(event: dict) -> bool:
    checked = validate_event(event)
    ident = event_id(checked["pubkey"], checked["created_at"], checked["kind"], checked["tags"],
                     checked["content"])
    if ident != checked["id"]:
        return False
    return verify(bytes.fromhex(checked["pubkey"]), bytes.fromhex(ident), bytes.fromhex(checked["sig"]))
