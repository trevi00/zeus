"""Reference driver: the S6 coordination atomic units (REBUILD-DESIGN-v2 §2.9) of the continuation and owner-action
coordinators on M7, scenario family `effects.continuation_units` (M7 `MemoryStore` only; the PostgreSQL variant is
recorded separately). Fake clock and deterministic ids, reset per case.

The API is the s5_units one (`backend(name)`, `recording(store)`, `reset()`: the S0 RecordingStore over a fresh
`MemoryStore`, its stored rows readable) plus the S6 entries the worlds need, each a plain M7 object or a lambda over one:
`MemoryStore` (the worlds build their control and lane stores through it), `Fleet(store, clock, token)`, `LaneEvidence`,
`Continuation(store, *, fleet, lanes, conductor, validate, clock, evidence=None)`, `OwnerActions(store, **ports)`,
`organization` (M7 `bootstrap.organization`), `validate_manifest`, `repository_identity`, `canonical` (M7
`domain.model.canonical`), `domain` (M7 `domain.continuation`) and `owner_domain` (M7 `domain.owner_actions`), the module
names the M7 helpers of the recorded research worlds use."""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import recorder as rec  # noqa: E402
import s6_units  # noqa: E402

from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore  # noqa: E402
from codex_harness.application.continuation import Continuation, LaneEvidence  # noqa: E402
from codex_harness.application.fleet import Fleet  # noqa: E402
from codex_harness.application.owner_actions import OwnerActions  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import continuation as continuation_domain  # noqa: E402
from codex_harness.domain import operation as operation_domain  # noqa: E402
from codex_harness.domain import owner_actions as owner_domain  # noqa: E402
from codex_harness.domain.fleet import repository_identity  # noqa: E402
from codex_harness.domain.model import canonical  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
determinism.install(CLOCK, IDS)
POLICY = packaged_policy()


def digest(body) -> str:
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Backend:
    """A fresh MemoryStore whose stored rows are readable as [bucket, key, status, body digest]."""

    def __init__(self, name: str):
        assert name == "memory", name
        self.store = MemoryStore()

    def rows(self) -> list:
        return sorted([b, k, (v or {}).get("status") or "", digest(v)] for (b, k), v in self.store.data.items())

    def drop(self) -> None:
        pass


def reset():
    CLOCK.reset()
    IDS.reset()


API = SimpleNamespace(
    backend=Backend, reset=reset, recording=lambda store: rec.RecordingStore(store), MemoryStore=MemoryStore,
    Fleet=lambda store, clock, token: Fleet(store, clock=clock, token=token), LaneEvidence=LaneEvidence,
    Continuation=lambda store, *, fleet, lanes, conductor, validate, clock, evidence=None: Continuation(
        store, fleet=fleet, lanes=lanes, conductor=conductor, validate=validate, clock=clock, evidence=evidence),
    OwnerActions=lambda store, **ports: OwnerActions(store, **ports), organization=organization,
    validate_manifest=lambda document: operation_domain.validate_manifest(document, POLICY),
    repository_identity=repository_identity, canonical=canonical, domain=continuation_domain,
    owner_domain=owner_domain)

if __name__ == "__main__":
    driver.finish("reference", "effects.continuation_units", s6_units.run(API))
