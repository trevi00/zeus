"""Record source identities and declared reading; does not execute upstream code."""
import hashlib
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
record_source = runpy.run_path(str(ROOT / "docs/full-analysis/baldrix-engine-001/record_review.py"))["record"]


def record(path, ranges=None):
    row = record_source(path, ranges)
    row["review_ref"] = "docs/full-analysis/baldrix-providers-001/resolution.md"
    return row


def main():
    primary = [record("scripts/lib/providers/" + name + ".py") for name in ("__init__", "base", "anthropic", "openai", "ollama")]
    support = [record(path, ranges) for path, ranges in (
        ("scripts/engine/external_jury.py", None),
        ("scripts/cli/endpoint_query.py", None),
        ("scripts/lib/model_router.py", None),
        ("scripts/tests/test_providers_ollama.py", None),
        ("scripts/lib/evaluator_dispatcher.py", [[347, 386], [473, 589], [753, 946]]),
        ("scripts/lib/research_extractor.py", [[194, 275]]),
        ("scripts/engine/jury_advisory.py", [[36, 80]]),
    )]
    assert sum(r["bytes"] for r in primary) == 19724
    scope = [{"source": r["source"], "revision": r["revision"], "path": r["path"], "sha256": r["pinned_sha256"]} for r in primary]
    checkpoint = {
        "partition": "baldrix:scripts/lib/providers:001",
        "scope_sha256": "f946d9363613d41347a188fa65135260ca9c2607b2d30865b7ad0430c481df0f",
        "record_scope_sha256": hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
        "record_scope_hash_encoding": "Python json.dumps(scope, sort_keys=True), UTF-8",
        "scope_items": scope, "primary_count": 5, "primary_bytes": 19724,
        "primary_body_read_complete": True, "root_supporting_count": 7,
        "root_supporting_full": 4, "root_supporting_partial": 3,
        "claude_additional_support": "claude-initial.md declares Claude's separate bounded reads; not counted as root support",
        "original_ollama_wrapper_assertions_passed": 8,
        "original_negative_component_programs_completed": 1,
        "actual_provider_model_invocations": 0,
        "fake_cli_or_sdk": False, "whole_analysis_complete": False,
        "partition_complete": False, "adoption_approved": False,
        "limits": "Full five primary bodies, incomplete transitive callers/config/tests. CLI-absent immutable Alpine execution only; no real model, usage, Windows/WSL upstream or user/device acceptance evidence.",
    }
    for name, data in (("files.json", primary), ("supporting-evidence.json", support), ("checkpoint.json", checkpoint)):
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(checkpoint))


if __name__ == "__main__":
    main()
