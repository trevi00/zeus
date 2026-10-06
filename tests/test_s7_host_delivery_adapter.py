"""S7 pilot 42a: the moved host_delivery adapter's package-directory rule and its canary pass-through."""
from pathlib import Path

import codex_harness
from codex_harness.delivery.adapters import host_delivery
from codex_harness.delivery.domain.host_delivery import CANARY_COLLECT


def test_loaded_runtime_resolves_to_the_imported_package_directory():
    package = Path(codex_harness.__file__).resolve().parent
    loaded = host_delivery.loaded_runtime()
    assert loaded["module_root"] == str(package)
    assert loaded["runtime_root"] == str(package.parent.parent if package.parent.name == "src" else package.parent)


def test_canary_checks_pass_facts_through_to_the_collect_canary():
    seen = []

    def facts(store):
        seen.append(store)
        return {"targets": []}

    check = host_delivery.canary_checks("store", facts=facts)[CANARY_COLLECT]
    result = check({"target_id": "t"}, {}, {})
    assert seen == ["store"] and result["reason_code"] == "canary_target_unobserved"


def test_collect_canary_without_a_store_keeps_the_refusal():
    result = host_delivery.collect_monitor_canary({"target_id": "t"}, {}, {}, facts=lambda store: {})
    assert result["reason_code"] == "canary_store_unavailable"
