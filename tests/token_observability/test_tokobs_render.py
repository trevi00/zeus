"""ACCEPTANCE A23, A24, A43 and the core: labels, redaction, render refusal, ledger, report, CLI."""

import json
import os
import re
import sqlite3
import stat

import pytest
from fixtures import (
    OPUS,
    SENTINELS,
    SESSION,
    SONNET,
    T0,
    Rig,
    assistant,
    claude_init,
    claude_result,
    entry,
    parse_prom,
    start_row,
    terminal_row,
    usage,
)
from tokobs.__main__ import main
from tokobs.config import ConfigError, parse_registry, validate_root
from tokobs.ledger import SCHEMA_VERSION, LedgerError, open_ledger
from tokobs.render import Labeler
from tokobs.vocab import LABEL_RE

TASK = "render-task"


def finished_task(rig, task=TASK, models=None):
    rig.record(task, start_row(task, 1, T0), terminal_row("finished", 1, T0 + 30))
    rig.events(task, 1, claude_init(), assistant(), claude_result(
        "r1", usage(1, 10, 100, 5), models or {SONNET: entry(1, 10, 100, 5, 0.25)}))
    rig.receipt(task, 1)


def label_values(text):
    return {(k, v) for _name, labels in parse_prom(text) for k, v in labels}


def test_a24_no_text_no_ids_and_every_label_is_bounded(tmp_path):
    rig = Rig(tmp_path)
    long_task = "t" + "x" * 199
    models = {SONNET: entry(1, 10, 100, 5)}
    models.update({f"foo-model-{n}": entry(0, 1, 0, 0) for n in range(50)})  # 50 unlisted models
    rig.registry = parse_registry('[task_classes]\nrouting = "^t"\n')
    finished_task(rig, long_task, models)
    prom = rig.scan(advance=60)  # Rig also asserts that no sentinel text is in the ledger or the exposition
    text = (rig.data / "data.prom").read_text() + (rig.data / "health.prom").read_text()
    for forbidden in (long_task, SESSION, "r1", "foo-model", *SENTINELS):
        assert forbidden not in text
    for key, value in label_values(text):
        assert LABEL_RE.match(value), (key, value)
    assert {v for k, v in label_values(text) if k == "model"} <= {SONNET, "other"}
    assert prom.sum("zeus_llm_tokens_total", model="other") == 50
    assert prom.sum("zeus_llm_model_unrecognized_total") == 50
    assert prom.sum("zeus_llm_tokens_total", task_class="routing") > 0
    # nothing in the ledger is prompt/result text: the sentinels are absent from every table
    for blob in (p.read_bytes() for p in rig.data.iterdir() if p.is_file()):
        for needle in SENTINELS:
            assert needle.encode() not in blob


def test_labeler_maps_out_of_list_values_to_other():
    label = Labeler({"routing", "Bad Class!", *{f"c{n}" for n in range(30)}})
    assert label(provider="mystery", role="implementer", model="foo", task_class="Bad Class!") == {
        "provider": "other", "role": "implementer", "model": "other", "task_class": "other"}
    assert len(label.classes) <= 16
    assert label(token_type="input")["token_type"] == "input"


def test_a43_render_refusal_keeps_data_prom_and_rewrites_health(tmp_path):
    rig = Rig(tmp_path)
    finished_task(rig)
    rig.scan(advance=60)
    good = (rig.data / "data.prom").read_bytes()
    last_ok = rig.health().sum("zeus_tokobs_last_render_success_timestamp_seconds")
    assert rig.health().sum("zeus_tokobs_render_refused") == 0
    invocation = "routine:render-task:1"
    classes = ["unclassified", "unattributed_interval", "identity_unavailable", "coordination", "other",
               *[f"c{n}" for n in range(11)]]
    rows, n = [], 0
    for provider, source in (("anthropic", "routine"), ("anthropic", "lane"), ("openai", "codex_exec")):
        for model in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-4-5", "gpt-6-astra", "other"):
            for role in ("implementer", "advisor", "advisor_or_nested", "nested_unattributed", "coordinator",
                         "lane_worker", "reviewer"):
                for tau in ("input", "output", "cache_read", "cache_write"):
                    for task_class in classes:
                        n += 1
                        rows.append((f"synthetic-{n}", invocation, "main_result", provider, model, role, source,
                                     task_class, tau, 1, T0))
    conn = sqlite3.connect(rig.data / "ledger.sqlite3")
    conn.executemany("INSERT INTO contributions(id,invocation_id,kind,provider,model,role,source,task_class,"
                     "token_type,value,published_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    assert len(rows) > 6000
    rig.history.clear()
    rig.now += 60
    assert main(["render", "--data", str(rig.data), "--now", str(rig.now)]) == 1
    assert (rig.data / "data.prom").read_bytes() == good  # the last good render is kept
    health = rig.health()
    assert health.sum("zeus_tokobs_render_refused") == 1
    assert health.sum("zeus_tokobs_series_count") > 5000
    assert health.sum("zeus_tokobs_last_render_success_timestamp_seconds") == last_ok  # unchanged
    assert not list(rig.data.glob(".*.tmp"))


def test_render_files_are_private_and_replaced_atomically(tmp_path):
    rig = Rig(tmp_path)
    finished_task(rig)
    rig.scan(advance=60)
    for name in ("data.prom", "health.prom", "ledger.sqlite3", "ledger.lock"):
        assert stat.S_IMODE((rig.data / name).stat().st_mode) == 0o600, name
    assert not list(rig.data.glob(".*.tmp"))
    assert main(["render", "--data", str(rig.data), "--now", str(rig.now)]) == 0


def test_ledger_migrations_append_only_and_newer_schema_refused(tmp_path):
    rig = Rig(tmp_path)
    finished_task(rig)
    rig.scan(advance=60)
    open_ledger(rig.data).close()  # reopening is idempotent
    assert rig.sql("SELECT value FROM schema_meta WHERE key='version'") == [(str(SCHEMA_VERSION),)]
    conn = sqlite3.connect(rig.data / "ledger.sqlite3")
    conn.execute("INSERT INTO corrections(dedupe_key,kind,invocation_id,detail_enum,recorded_at) "
                 "VALUES('k','late_tail',NULL,'x',1)")
    for statement in ("UPDATE contributions SET value=value+1", "DELETE FROM contributions",
                      "UPDATE corrections SET kind='late_tail'", "DELETE FROM cost_contributions"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            conn.execute(statement)
    conn.execute("UPDATE schema_meta SET value='99' WHERE key='version'")
    conn.commit()
    conn.close()
    with pytest.raises(LedgerError, match="newer"):
        open_ledger(rig.data)


def test_a23_roots_validate_on_any_platform():
    assert validate_root("C:\\Users\\synthetic\\A").drive == "C:"
    assert validate_root("D:/workspaces/zeus/artifacts").is_absolute()
    assert validate_root("\\\\host\\share\\A").is_absolute()
    assert str(validate_root("/home/synthetic/A")) == "/home/synthetic/A"
    for bad in ("relative/dir", "", "C:relative"):
        with pytest.raises(ConfigError):
            validate_root(bad)


def test_task_class_registry_is_bounded_and_validated():
    registry = parse_registry('[task_classes]\nrouting = "^s7-"\nreview = "review"\n')
    assert registry.classify("s7-host") == "routing" and registry.classify("my-review") == "review"
    assert registry.classify("other") == "unclassified"
    with pytest.raises(ConfigError):
        parse_registry("[task_classes]\n" + "".join(f'c{n} = "x"\n' for n in range(12)))
    with pytest.raises(ConfigError):
        parse_registry('[task_classes]\n"Bad Name" = "x"\n')
    with pytest.raises(ConfigError):
        parse_registry('[task_classes]\nunclassified = "x"\n')
    with pytest.raises(ConfigError):
        parse_registry('[task_classes]\nok = "("\n')


def test_cli_scan_render_report_end_to_end(tmp_path, capsys):
    rig = Rig(tmp_path)
    finished_task(rig, "s7-cli-task")
    rig.record("s7-cli-task", {"event": "completed", "outcome": "accepted", "at": "2026-09-27T00:00:00Z"})
    registry = tmp_path / "classes.toml"
    registry.write_text('[task_classes]\nrouting = "^s7-"\n')
    data = tmp_path / "cli-data"
    now = str(T0 + 600)
    assert main(["scan", "--data", str(data), "--source-root", str(rig.root), "--task-classes", str(registry),
                 "--now", now]) == 0
    assert main(["render", "--data", str(data), "--now", now]) == 0
    prom = parse_prom((data / "data.prom").read_text())
    assert any(n == "zeus_llm_tokens_total" and ("task_class", "routing") in ls for n, ls in prom)
    capsys.readouterr()
    assert main(["report", "--data", str(data), "--task", "s7-cli-task"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["task"]["outcome"] == "accepted" and report["rework"] == 0
    (inv,) = report["invocations"]
    assert inv["id"] == "routine:s7-cli-task:1" and inv["outcome"] == "finished"
    assert {c["role"] for c in inv["contributions"]} == {"implementer"}
    assert inv["consultations"] == 0 and inv["corrections"] == []
    assert main(["report", "--data", str(data), "--task", "missing-task"]) == 1
    assert main(["report", "--data", str(tmp_path / "no-ledger"), "--task", "x"]) == 1
    assert not (tmp_path / "no-ledger").exists() or not (tmp_path / "no-ledger" / "ledger.sqlite3").exists()
    assert main(["scan", "--data", str(data), "--source-root", "relative/path"]) == 1
    assert main(["bogus"]) == 2


def test_report_shows_corrections_and_shares_without_text(tmp_path, capsys):
    rig = Rig(tmp_path)
    rig.record(TASK, start_row(TASK, 1, T0, timeout=100))
    rig.events(TASK, 1, claude_init(), claude_result("r1", usage(1, 10, 100, 5), {SONNET: entry(1, 10, 100, 5),
                                                                                  OPUS: entry(1, 2, 0, 0)}))
    rig.scan(advance=100 + 30 + 600 + 1)
    rig.record(TASK, terminal_row("finished", 1, rig.now))
    rig.scan(advance=10)
    capsys.readouterr()
    assert main(["report", "--data", str(rig.data), "--task", TASK]) == 0
    out = capsys.readouterr().out
    (inv,) = json.loads(out)["invocations"]
    assert inv["unknown_reason"] == "terminal_unproven"
    assert [c["kind"] for c in inv["corrections"]] == ["late_terminal"]
    assert {s["model"] for s in inv["unknown_shares"]} == {SONNET, OPUS}
    for needle in SENTINELS:
        assert needle not in out
    assert re.search(r'"outcome": "terminal_unproven"', out)


def test_empty_source_renders_valid_exposition_and_health(tmp_path):
    rig = Rig(tmp_path)
    prom = rig.scan(advance=10)
    assert prom.sum("zeus_llm_invocations_total") == 0
    assert prom.sum("zeus_llm_open_invocations", state="open") == 0  # S1 is collected: 0 is a true count
    health = rig.health()
    assert health.sum("zeus_tokobs_source_up", source="routine") == 1
    assert health.sum("zeus_tokobs_last_scan_success_timestamp_seconds") == T0 + 10
    os.remove(rig.data / "data.prom")
