"""Event signer: sets the pubkey, computes the NIP-01 id and has custody sign that id.

Layer: adapters
Context: observation
Owns: `NostrEventSigner` (the `EventSigner` implementation over two injected custody callables)
Does not own: the keys and the BIP-340 signing (credentials custody, wired in by composition or tests), the id
    serialization (`observation.domain.nostr_event`)
Entry points: NostrEventSigner
Contracts: NIP-01 https://github.com/nostr-protocol/nips/blob/master/01.md; design §5 (custody signs an id)
"""

from __future__ import annotations

from collections.abc import Callable

from codex_harness.kernel.errors import ContractError
from codex_harness.observation.domain.nostr_event import event_id

_UNSIGNED = frozenset({"kind", "created_at", "tags", "content"})


class NostrEventSigner:
    def __init__(self, pubkey: Callable[[str], str], sign_id: Callable[[str, str], str]):
        self._pubkey = pubkey
        self._sign_id = sign_id

    def pubkey(self, role: str) -> str:
        return self._pubkey(role)

    def sign(self, role: str, unsigned: dict) -> dict:
        """Set pubkey, id and sig on an event that has kind, created_at, tags and content."""
        if not isinstance(unsigned, dict) or not _UNSIGNED <= set(unsigned) or set(unsigned) - (
                _UNSIGNED | {"pubkey"}):
            raise ContractError("event signer: an unsigned event has kind, created_at, tags and content "
                                "(and optionally this role's pubkey)")
        pubkey = self._pubkey(role)
        if unsigned.get("pubkey", pubkey) != pubkey:
            raise ContractError("event signer: the event names another pubkey")
        ident = event_id(pubkey, unsigned["created_at"], unsigned["kind"], unsigned["tags"], unsigned["content"])
        sig = self._sign_id(role, ident)
        return {"id": ident, "pubkey": pubkey, "created_at": unsigned["created_at"], "kind": unsigned["kind"],
                "tags": [list(tag) for tag in unsigned["tags"]], "content": unsigned["content"], "sig": sig}
