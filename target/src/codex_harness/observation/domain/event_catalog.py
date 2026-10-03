"""The observability event catalog (the SSOT of the X1 additions), DESIGN-s9-X §1 and §1.1.

Layer: domain
Context: observation
Owns: reading the packaged `observability-catalog.json` and refusing catalog attribute values (a CLOSED enum
    value outside the catalog, an unknown attribute, a non-opaque identifier) before an event is built
Does not own: the event contract and its type allow-lists (`observation.domain.observation.REGISTRY`, the one
    registry: a test keeps the two in agreement); producers (X1b), metrics (X2)
Entry points: load_catalog, check_catalog_attributes
Contracts: INV-OBSERVATION-001, OBSERVABILITY-COVERAGE-20261002

An `other` value is accepted only where the catalog itself lists it in that enum. Identifiers are opaque handles
(`opaque_identifier`), never metric labels. No attribute is free text. Attribute types use the REGISTRY's type keys.
"""
from __future__ import annotations

import json
from importlib.resources import files

from codex_harness.kernel.errors import require
from codex_harness.observation.domain.observation import _typed, opaque_identifier

CATALOG_RESOURCE = "observability-catalog.json"


def load_catalog() -> dict:
    """The packaged catalog, parsed fresh (callers must not mutate a shared copy)."""
    return json.loads((files("codex_harness.resources") / CATALOG_RESOURCE).read_text(encoding="utf-8"))


def check_catalog_attributes(event_type: str, attributes: dict) -> dict:
    """Refuse any attribute the catalog does not allow for `event_type`; returns a copy of the attributes.

    Names the offending attribute, never its value. Only attributes that are given are checked; type and key
    completeness stay with `observation.check_attributes` (the producer helper calls both)."""
    events = load_catalog()["events"]
    require(event_type in events, "Event type is not in the observability catalog: " + str(event_type))
    require(isinstance(attributes, dict), "Observation attributes must be an object")
    declared = events[event_type]["attributes"]
    unknown = sorted(str(key) for key in attributes if key not in declared)
    require(not unknown, f"Attributes not in the catalog for {event_type}: " + ", ".join(unknown))
    for name, value in attributes.items():
        spec = declared[name]
        require(_typed(spec["type"], value), f"Attribute type refused for {event_type}: {name}")
        if "enum" in spec:
            require(value in spec["enum"], f"Attribute value outside the closed enum for {event_type}: {name}")
        elif spec.get("opaque") and value is not None:
            opaque_identifier(value, name)
    return dict(attributes)
