"""PROGRAMDATA in the replay allowlist (INV-OPERATION-001, goal-progress-001 residual).

The value takes part in the snapshot identity; Zeus settings and secrets stay absent. The real
ssh-keygen check runs only on a Windows host with OpenSSH; elsewhere only the semantics are tested
and no native Windows behavior is claimed."""
import os
import shutil
import subprocess
import sys

import pytest

from codex_harness.adapters.artifacts import FileArtifacts
from codex_harness.adapters.evidence_inspection import (
    KEEP_ENV,
    EvidenceInspector,
    replay_environment,
)

SECRETS = {"ZEUS_DATABASE_URL": "postgresql://u:p@h/db", "HARNESS_REDIS_URL": "redis://h", "ANTHROPIC_API_KEY": "k",
           "PYTHONPATH": "parent-leak", "POSTGRES_PASSWORD": "pw", "CLAUDE_CODE_OAUTH_TOKEN": "t"}


def test_programdata_is_kept_under_both_spellings_and_secrets_stay_absent():
    assert "PROGRAMDATA" in KEEP_ENV and "ProgramData" in KEEP_ENV
    env = replay_environment({**SECRETS, "PATH": "p", "PROGRAMDATA": "C:/ProgramData", "ProgramData": "C:/ProgramData"})
    assert env["PROGRAMDATA"] == "C:/ProgramData" and env["ProgramData"] == "C:/ProgramData" and env["PATH"] == "p"
    assert not (set(SECRETS) & set(env)) and env["PYTHONIOENCODING"] == "utf-8"
    assert "PROGRAMDATA" not in replay_environment({"PATH": "p"}), "absent on the host stays absent"


def test_programdata_value_participates_in_the_snapshot_identity(tmp_path, monkeypatch):
    inspector = EvidenceInspector(FileArtifacts(str(tmp_path / "artifacts")))
    monkeypatch.setenv("PROGRAMDATA", "C:/ProgramData")
    first = inspector.snapshot(tmp_path)["identity"]
    monkeypatch.setenv("PROGRAMDATA", "D:/Elsewhere")
    second = inspector.snapshot(tmp_path)["identity"]
    monkeypatch.delenv("PROGRAMDATA")
    third = inspector.snapshot(tmp_path)["identity"]
    assert "PROGRAMDATA" in first["environment_names"] and "PROGRAMDATA" not in third["environment_names"]
    assert len({first["environment_digest"], second["environment_digest"], third["environment_digest"]}) == 3
    assert first["policy_hash"] == second["policy_hash"] == third["policy_hash"], "policy identity is unchanged"


@pytest.mark.skipif(os.name != "nt" or shutil.which("ssh-keygen") is None,
                    reason="native Windows OpenSSH only; other hosts test semantics, not Windows behavior")
def test_windows_ssh_keygen_creates_a_disposable_key_under_the_replay_environment(tmp_path):
    key = tmp_path / "disposable-ed25519"
    env = replay_environment()
    assert "PROGRAMDATA" in env or "ProgramData" in env, "this host must carry PROGRAMDATA for the check to mean anything"
    done = subprocess.run([shutil.which("ssh-keygen"), "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
                          env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-500:]
    assert key.is_file() and key.with_suffix(".pub").is_file()


def test_replay_child_sees_programdata_but_no_zeus_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))
    monkeypatch.setenv("ZEUS_DATABASE_URL", "postgresql://secret")
    env = replay_environment(cwd=tmp_path)
    code = "import os,json;print(json.dumps({'pd': os.environ.get('PROGRAMDATA'), 'zeus': os.environ.get('ZEUS_DATABASE_URL')}))"
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() == '{"pd": "%s", "zeus": null}' % str(tmp_path).replace("\\", "\\\\")
