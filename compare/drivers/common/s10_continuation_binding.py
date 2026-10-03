"""Shared S10 scenario steps (`coordination.continuation_binding`): M7 `Executor._continuation` (INV-CONTINUATION-001, OWNER-DECISIONS-S10 #16).

Layer: harness (never shipped); standard library only.

`binding` is the side's callable taking `(store, details)`: the reference calls M7 `Executor._continuation` UNBOUND with a minimal `self`
(`service.store` = the M7 MemoryStore), the target calls `ContinuationBindings(store).binding`. Cases (a) a stored, identical, operation-naming binding
is returned, (b) the operation id differs, (c) no stored row, (d) a stored row differing in one field, (e) an invalid binding document, (f) no
`continuation` attached (the reference is M7's legacy None; the target is RunTask._continuation unbound with no port, which returns None before the port is called). Each case records the outcome (the returned
binding's digest, or the refusal type and message) and whether the store changed (none expected). No clock, process, network or database.
"""

from __future__ import annotations

import copy
import hashlib
import json

BUCKET = "continuation_bindings"
OPERATION = "operation-1"


def canonical_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()


def store_digest(store) -> str:
    return canonical_digest(sorted((repr(key), value) for key, value in store.data.items()))


def valid_binding(**changes) -> dict:
    document = {"schema": "urn:zeus:continuation-binding:1", "operation_id": OPERATION, "policy_sha256": "a" * 64, "intent_id": "b" * 64,
                "family": "family-1", "route": None, "session": None, "workspace": None, "predecessor": None}
    document.update(changes)
    return document


def outcome(binding, store_factory, stored, details) -> dict:
    store = store_factory()
    if stored is not None:
        with store.transaction() as tx:
            tx.put(BUCKET, stored["operation_id"], copy.deepcopy(stored))
    before = store_digest(store)
    try:
        result = binding(store, details)
        record = {"returned": None if result is None else {"digest": canonical_digest(result), "operation_id": result["operation_id"]}}
    except Exception as exc:  # the refusal is the characterized result
        record = {"refused": type(exc).__name__, "message": str(exc)[:200]}
    record["store_changed"] = store_digest(store) != before
    return record


def run(binding, store_factory, legacy=None) -> dict:
    good = valid_binding()
    cases = {
        "a_valid_returned": (good, {"operation": {"id": OPERATION}, "continuation": copy.deepcopy(good)}),
        "b_other_operation": (good, {"operation": {"id": "operation-2"}, "continuation": copy.deepcopy(good)}),
        "c_no_stored_row": (None, {"operation": {"id": OPERATION}, "continuation": copy.deepcopy(good)}),
        "d_stored_row_differs": (valid_binding(family="family-2"), {"operation": {"id": OPERATION}, "continuation": copy.deepcopy(good)}),
        "e_invalid_document": (good, {"operation": {"id": OPERATION}, "continuation": {**good, "schema": "urn:other"}}),
    }
    result = {name: outcome(binding, store_factory, stored, details) for name, (stored, details) in cases.items()}
    result["f_not_attached"] = outcome(legacy or binding, store_factory, good, {"operation": {"id": OPERATION}})
    return result
