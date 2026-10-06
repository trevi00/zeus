"""S9 D6: the research program's JSONL `EventLog` is registered in the observability catalog as a SEPARATE log.

OWNER-DECISIONS-S9 D6: retain and register, do not fold before cutover. The catalog's `separate_logs` entry is the
registration; these tests keep it truthful against the code: the producer symbol, the location template, the record
fields and the categories are the ones `EventLog` actually writes, its free event names are not REGISTRY types, and
the entry says it is not collected (no metric or monitor projection counts it).
"""

from __future__ import annotations

import importlib
import json

from codex_harness.observation.domain import observation as obs
from codex_harness.observation.domain.event_catalog import load_catalog
from codex_harness.research.adapters import research_program
from codex_harness.research.adapters.research_program import CATEGORIES, EventLog

KEY = "research.program_event_log"


def entry() -> dict:
    return load_catalog()["separate_logs"][KEY]


def test_the_catalog_registers_exactly_one_separate_log_and_names_its_real_producer():
    catalog = load_catalog()
    assert catalog["catalog_version"] == 4
    assert set(catalog["separate_logs"]) == {KEY}
    module, _, name = entry()["producer"].rpartition(".")
    assert getattr(importlib.import_module(module), name) is EventLog
    assert entry()["owner_context"] == "research" and entry()["decision"].startswith("OWNER-DECISIONS-S9 D6")
    assert entry()["collected"] is False and entry()["format"] == "jsonl"


def test_location_fields_and_categories_match_what_eventlog_writes(tmp_path):
    log = EventLog(tmp_path, "prog-1")
    template = entry()["location"]
    assert template.startswith("<runtime>/")
    expected = template.replace("<runtime>", str(tmp_path)).replace("<program_id>", "prog-1")
    assert str(log.path) == expected
    assert tuple(entry()["categories"]) == CATEGORIES
    for category in CATEGORIES:
        log.emit(category, "fixture_event", cycle=1, count=2)
    records = [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]
    assert [r["category"] for r in records] == list(CATEGORIES)
    assert all(set(r) == set(entry()["record_fields"]) for r in records)


def test_the_separate_log_is_not_a_registry_or_catalog_event_source():
    events = load_catalog()["events"]
    assert KEY not in events and KEY not in obs.REGISTRY
    assert not any(name.startswith("research.") for name in obs.REGISTRY)
    assert "free" in entry()["event_names"] and "validate_observation" in entry()["event_names"]


def test_the_entry_has_no_absolute_path_or_host_detail():
    text = json.dumps(entry())
    assert "/home/" not in text and "/srv/" not in text and research_program.__file__ not in text
