"""Ported SOURCE M7 suite `tests/test_file_canary.py` (e38aa722) run against the S7 target (DESIGN-s7 §6).

Every assertion is M7's, unchanged. Adaptations, all construction, import and patch-target (the `m7_delivery` shim
docstring names the routing): `ReleaseRunner` is the release runner as composition wires it with its S8/S10/S5 carries
as labelled refusals; `deployment` is the moved `delivery.adapters.deployment` whose `run_process` is the runner's
injected process port; `attempt_resources` closes over `ExecutionContainerNaming()`; `FileArtifacts`, `MemoryStore` and
`organization` come from their target homes.

M7 docstring follows.

INV-RELEASE-FILE-CANARY-001: the file canary's ownership handoff, exact postcondition and receipt.

Every container here is a labelled fixture: `_check` is replaced by a function that writes the files
a container would leave in the bind-mounted directory. Nothing claims an actual Codex, Docker or
production verification.
"""
import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from m7_delivery import (
    ReleaseRunner,
    attempt_resources,
    canary_handoff_script,
    deployment,
    organization,
)

from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

ATTEMPT = "0123456789abcdef" * 2


def canary_root(argv) -> Path:
    mount = next(a for a in argv if str(a).startswith("type=bind,source=") and str(a).endswith(",target=/canary"))
    return Path(mount[len("type=bind,source="):-len(",target=/canary")])


def token_of(root: Path) -> str:
    return (root / "input.txt").read_text("utf-8")


def honest(root, token):  # what codex plus the handoff leave: both files readable by the controller
    (root / "output.txt").write_bytes(token.encode())
    (root / "result.json").write_text(json.dumps({"value": token}), "utf-8")
    os.chmod(root / "output.txt", 0o640)
    os.chmod(root / "result.json", 0o640)


def runner_with(tmp_path, monkeypatch, container, *, rc=0):
    auth = tmp_path / "fixture-auth.json"
    auth.write_text("{}", "utf-8")  # a labelled placeholder, not a credential
    service = SimpleNamespace(store=MemoryStore(), org=organization())
    artifacts = FileArtifacts(str(tmp_path / "artifacts"))
    runner = ReleaseRunner(service, None, artifacts, str(auth))
    seen = {"argv": None, "removed": [], "root": None}

    def check(argv, cwd=None, **kwargs):
        seen["argv"], root = [str(a) for a in argv], canary_root(argv)
        seen["root"] = root
        container(root, token_of(root))
        receipt = artifacts.put(json.dumps({"fixture": "command", "exit_code": rc}), "canary")
        return {"passed": rc == 0, "evidence": receipt["ref"], "outcome": "executed", "binding": {}}

    def process(argv, **kwargs):
        seen["removed"].append(list(argv))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner, "_check", check)
    monkeypatch.setattr(deployment, "run_process", process)
    return runner, artifacts, seen


def receipt(artifacts, answer) -> tuple[dict, str]:
    text = artifacts.read(answer["postcondition"], 0, 32000)
    return json.loads(text), text


def test_the_argv_is_the_same_container_with_only_the_handoff_entrypoint(tmp_path, monkeypatch):
    runner, _, seen = runner_with(tmp_path, monkeypatch, honest)
    owned = attempt_resources(ATTEMPT)
    name, labels = owned["containers"]["release-canary"], owned["labels"]["release-canary"]
    answer = runner.file_canary("sha256:" + "d" * 64, name=name, labels=labels)
    argv = seen["argv"]
    script = f'codex "$@"; rc=$?; chown -h {os.getuid()}:{os.getgid()} /canary/result.json /canary/output.txt 2>/dev/null; exit $rc'
    assert canary_handoff_script(os.getuid(), os.getgid()) == script
    image = argv.index("sha256:" + "d" * 64)
    assert argv[image - 2:image] == ["--entrypoint", "/bin/sh"]
    assert argv[image + 1:image + 4] == ["-c", script, "sh"]
    assert argv[image + 4:] == ["exec", "--ephemeral", "--skip-git-repo-check", "--sandbox", "danger-full-access",
                                "-c", 'approval_policy="never"', "--output-schema", "/canary/schema.json",
                                "--output-last-message", "/canary/result.json", "-C", "/canary",
                                "Read input.txt and write its exact contents to output.txt. "
                                "Return the input contents in value. Do not use network."]
    assert argv[:5] == ["docker", "run", "--rm", "--name", name]
    assert argv[5:9] == ["--label", labels[0], "--label", labels[1]]
    assert f"type=bind,source={runner.auth},target=/root/.codex/auth.json,readonly" in argv
    assert answer["passed"] is True and answer["postcondition_reason"] == "ok"
    assert seen["removed"] == [["docker", "rm", "-f", name]]
    assert answer["cleanup"] == {"removed": True} and not seen["root"].exists()


@pytest.mark.parametrize("uid,gid", [(-1, 0), ("1000", 1000), (1000, None), (True, 0)])
def test_the_handoff_ids_are_validated_integers(uid, gid):
    with pytest.raises(Exception):
        canary_handoff_script(uid, gid)


def test_a_forced_0600_result_is_readable_after_the_handoff(tmp_path, monkeypatch):
    def container(root, token):
        honest(root, token)
        os.chmod(root / "result.json", 0o600)  # the handoff made the controller the owner

    runner, artifacts, _ = runner_with(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    record, _ = receipt(artifacts, answer)
    assert answer["passed"] is True
    assert record["files"]["result.json"]["mode"] == "0600" and record["files"]["result.json"]["read"] == "ok"
    assert record["files"]["result.json"]["uid"] == os.getuid()


def write(name, data):
    def container(root, token):
        honest(root, token)
        target = root / name
        target.unlink()
        if data is not None:
            target.write_bytes(data(token) if callable(data) else data)
    return container


@pytest.mark.parametrize("container,reason,file", [
    (write("result.json", None), "missing", "result.json"),
    (write("output.txt", None), "missing", "output.txt"),
    (write("result.json", b"{not json"), "not_json", "result.json"),
    (write("result.json", b"\xff\xfe"), "not_json", "result.json"),
    (write("result.json", b'["HARNESS"]'), "not_object", "result.json"),
    (write("result.json", b'"HARNESS"'), "not_object", "result.json"),
    (write("result.json", b'{"other": 1}'), "no_value", "result.json"),
    (write("result.json", b'{"value": "HARNESS_CANARY_0000000000000000"}'), "value_mismatch", "result.json"),
    (write("result.json", lambda t: json.dumps({"value": [t]}).encode()), "value_mismatch", "result.json"),
    (write("output.txt", lambda t: (t + "\n").encode()), "bytes_mismatch", "output.txt"),
])
def test_each_postcondition_failure_is_named_and_never_a_pass(tmp_path, monkeypatch, container, reason, file):
    runner, artifacts, seen = runner_with(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    record, _ = receipt(artifacts, answer)
    assert answer["passed"] is False and answer["outcome"] == "executed"
    assert answer["postcondition_reason"] == reason == record["reason"] and record["reason_file"] == file
    assert record["files"][file]["outcome"] == reason
    assert answer["cleanup"] == {"removed": True} and not seen["root"].exists()


def test_a_symlink_is_refused_not_followed(tmp_path, monkeypatch):
    outside = tmp_path / "outside.txt"

    def container(root, token):
        honest(root, token)
        outside.write_bytes(token.encode())
        (root / "output.txt").unlink()
        (root / "output.txt").symlink_to(outside)

    runner, artifacts, _ = runner_with(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    record, _ = receipt(artifacts, answer)
    entry = record["files"]["output.txt"]
    assert answer["passed"] is False and answer["postcondition_reason"] == "not_regular"
    assert entry["type"] == "symlink" and entry["read"] is None and entry["sha256"] is None
    assert outside.exists()


def test_a_directory_is_not_regular(tmp_path, monkeypatch):
    def container(root, token):
        honest(root, token)
        (root / "result.json").unlink()
        (root / "result.json").mkdir()

    runner, _, _ = runner_with(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    assert answer["passed"] is False and answer["postcondition_reason"] == "not_regular"


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="root reads a 000 file")
def test_an_unreadable_file_is_named_by_its_error_type(tmp_path, monkeypatch):
    def container(root, token):  # F6: a root-owned 0640 file without the handoff
        honest(root, token)
        os.chmod(root / "output.txt", 0o000)

    runner, artifacts, seen = runner_with(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    record, _ = receipt(artifacts, answer)
    assert answer["passed"] is False and answer["postcondition_reason"] == "unreadable:PermissionError"
    assert record["files"]["output.txt"]["read"] == "error:PermissionError"
    assert record["files"]["output.txt"]["mode"] == "0000"
    assert answer["cleanup"] == {"removed": True} and not seen["root"].exists()


def test_a_failed_command_keeps_its_evidence_and_still_records_the_postcondition(tmp_path, monkeypatch):
    runner, artifacts, _ = runner_with(tmp_path, monkeypatch, honest, rc=7)
    answer = runner.file_canary("img")
    record, _ = receipt(artifacts, answer)
    assert answer["passed"] is False and answer["postcondition_reason"] == "ok"
    assert record["command_ref"] == answer["evidence"] and record["command_passed"] is False


def test_the_receipt_has_no_token_or_raw_contents(tmp_path, monkeypatch):
    tokens = []

    def container(root, token):
        tokens.append(token)
        honest(root, token)

    runner, artifacts, _ = runner_with(tmp_path, monkeypatch, container)
    answer = runner.file_canary("img")
    record, text = receipt(artifacts, answer)
    assert tokens[0] not in text and "HARNESS_CANARY_" not in text
    assert record["token_sha256"] == hashlib.sha256(tokens[0].encode()).hexdigest()
    assert record["files"]["output.txt"]["sha256"] == record["token_sha256"]
    assert set(record["files"]["result.json"]) == {"exists", "type", "mode", "uid", "gid", "size", "sha256",
                                                   "read", "parse", "compare", "outcome"}


def test_a_cleanup_failure_is_recorded_and_never_flips_the_verdict(tmp_path, monkeypatch):
    def refuse(path, *args, **kwargs):
        raise PermissionError("fixture: cleanup refused")

    for container, passed in ((write("result.json", None), False), (honest, True)):
        (tmp_path / str(passed)).mkdir()
        runner, _, seen = runner_with(tmp_path / str(passed), monkeypatch, container)
        monkeypatch.setattr(deployment.shutil, "rmtree", refuse)
        answer = runner.file_canary("img")
        monkeypatch.undo()
        assert answer["passed"] is passed
        assert answer["cleanup"] == {"removed": False, "error_type": "PermissionError"}
        assert seen["root"].exists()
        shutil.rmtree(seen["root"])


def test_a_failed_receipt_write_is_never_a_pass(tmp_path, monkeypatch):
    runner, artifacts, seen = runner_with(tmp_path, monkeypatch, honest)
    original = artifacts.put

    def put(content, kind):
        if kind == "canary-postcondition":
            raise OSError("fixture: store unavailable")
        return original(content, kind)

    monkeypatch.setattr(artifacts, "put", put)
    answer = runner.file_canary("img")
    assert answer["passed"] is False and answer["postcondition"] is None
    assert answer["postcondition_reason"] == "postcondition_artifact_unavailable:OSError"
    assert answer["outcome"] == "observation_error" and answer["cleanup"] == {"removed": True}
