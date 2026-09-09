"""Actual original functions on isolated temporary files; no provider or worker invocation."""
import contextlib
import io
import json
from pathlib import Path

import yaml

from engine import debate, orchestrator as orch, trigger_summary
from lib.event_store import EventStore
from lib.telemetry_log import jsonl_append


def main():
    result = {"kind": "actual_original_component_observations", "pyyaml_version": yaml.__version__}
    result["empty_proposal_fast_path"] = debate.is_fast_path_eligible("architecture", {}, [])
    store = EventStore("bounded-review-debate")
    for gen in (1, 2):
        store.append("verdict", gen, "explicit-input-fixture", {"ontology_snapshot": {"fields": [{"id": "x", "value": gen}]}})
    result["history_after_current_gen_append"] = debate.load_history_snapshots(store)

    sess = orch.new_session("isolated review fixture")
    orch.update_phase(sess, sess.root_phase)
    result["phase_id_after_update"] = next(r for r in orch.list_sessions() if r["sid"] == sess.sid)["phase_id"]
    sess.child_sids_path.write_text("[]", encoding="utf-8")
    result["valid_wrong_shape_child_sidecar"] = type(orch.load_session(sess.sid).child_sids).__name__

    panes = sess.dir / "panes"
    panes.mkdir()
    shard = panes / "p1.jsonl"
    jsonl_append(sess.events_path, {"ts": "2025-01-01T00:00:00Z", "type": "pane_status", "payload": {"pane_id": "p1", "status": "running", "generation": 2}})
    jsonl_append(shard, {"ts": "2024-01-01T00:00:00Z", "type": "pane_status", "pane_id": "p1", "status": "exited", "generation": 1})
    result["pane_state_before_merge"] = orch.replay_pane_state(sess.sid)["p1"]
    result["merged_count"] = orch.merge_pane_shards(sess.sid)
    result["pane_state_after_merge"] = orch.replay_pane_state(sess.sid)["p1"]
    result["merged_row"] = json.loads(sess.events_path.read_text(encoding="utf-8").splitlines()[-1])
    bad = panes / "invalid.jsonl"
    bad.write_text("not-json\n", encoding="utf-8")
    result["all_invalid_merge_count"] = orch.merge_pane_shards(sess.sid)
    result["all_invalid_shard_preserved"] = bad.exists()

    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        rc = trigger_summary.main(["--json", "--ack-ts", "2025-01-01T00:00:00Z"])
    result["json_with_ack"] = {"returncode": rc, "report": json.loads(stream.getvalue()), "ack_file_exists": trigger_summary._strict_design.ack_path.exists()}
    ack = trigger_summary._strict_design
    result["duplicate_bulk_ack_count"] = ack.ack_many(["same-event-key", "same-event-key"])
    result["unique_ack_keys"] = sorted(ack.load())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
