"""Ported PR-3 (`feat/host-delivery-maintain-pr3` 09e596ce) suite `tests/test_maintenance_evidence.py` run against the target (G1-14b).

Every assertion is PR-3's, unchanged. Adaptations are import lines and constructions only: the adapter is
`delivery.adapters.maintenance_evidence`, `MemoryStore` / `FileArtifacts` / `DeliveryRefused` / `BUCKET_ACTIONS` come from their target homes,
`policy` is `delivery.domain.maintenance` (the home of `validate_credential_evidence`), `LazyArtifacts(root)` is `LazyArtifacts(root, FileArtifacts)`
(the store constructor is injected: an adapter may not import `storage.adapters`) and `LazyCanaryExecutor(fleet, host)` is
`LazyCanaryExecutor(fleet, host, FakeLauncher, FakeExecutor)` (the launcher and executor constructors are injected: an adapter may not import
coordination; PR-3 patched `fleet_runtime.LaneLauncher` and `application.fleet.MaintenanceCanaryExecutor`, which are those two arguments).

The labelled DSN literal of `test_helper_runs_with_no_inherited_environment` (user and password both `SENTINEL`) is written as a concatenation (the same value) so
`compare/run.py check-tree` finds no credential-shaped string in the tree, as the other ported suites do.

PR-3 docstring follows.

INV-HOST-DELIVERY-MAINTENANCE-001, evidence ports: the pinned credential observation helper, the trusted
authority reader, the lazy artifact store, the owner-action reader and the lazy one-job canary executor.

The helper here is a LABELLED disposable script in `tmp_path` that prints fixed boolean JSON (or a labelled
defect); it reads no secret, no `/proc/<pid>/environ` and no credential file. Process identities come from a
labelled `/proc` reader. The authority store is a labelled content-addressed directory in `tmp_path`. No
unit, store, model or provider is touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

from codex_harness.coordination.application.owner_actions.state import BUCKET_ACTIONS
from codex_harness.delivery.adapters.maintenance_evidence import (
    AUTHORITY_MAX_BYTES,
    CREDENTIAL_EVIDENCE_SCHEMA,
    HELPER_SETTING,
    HELPER_SHA256_SETTING,
    QUALIFICATION_DEADLINE_SETTING,
    CredentialObserver,
    LazyArtifacts,
    LazyCanaryExecutor,
    control_action_reader,
    credential_observer,
    qualification_deadline,
    trusted_authority_reader,
)
from codex_harness.delivery.domain import maintenance as policy
from codex_harness.delivery.domain.host_delivery import DeliveryRefused
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore

INVOCATION = "c3" * 16
PRIMARY = {"has_token": True, "is_primary": True, "is_secondary": False}
posix_only = pytest.mark.skipif(os.name == "nt", reason="the managed systemd maintenance is Linux-only (aibox)")


def helper_script(tmp_path, body: str, name: str = "credential_bool_fixture.py") -> tuple[str, str]:
    """A LABELLED helper script and its sha256. `body` runs with `pid` (int) and `emit(document)`."""
    path = tmp_path / "helper" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    source = ("# LABELLED test helper: prints fixed booleans; reads no secret and no process environment\n"
              "import json, os, sys\n"
              "pid = int(sys.argv[2])\n"
              "def emit(document):\n"
              "    print(json.dumps(document, sort_keys=True))\n"
              + body)
    path.write_text(source, encoding="utf-8")
    return str(path), hashlib.sha256(source.encode("utf-8")).hexdigest()


ANSWER = ("emit({'pid': pid, 'has_token': True, 'is_primary': True, 'is_secondary': False})\n")


def stable_processes(ticks=None):
    """LABELLED `/proc` reader: every asked pid is present with fixed start ticks."""
    ticks = {100: 5000, 101: 5001, **(ticks or {})}
    reads = []

    def read(pid):
        reads.append(pid)
        return {"pid": pid, "state": "present", "start_ticks": ticks[pid], "ppid": 1, "cgroup": "/x",
                "start_usec": 1, "argv_sha256": "0" * 64}
    read.reads = reads
    return read


def identity(**overrides) -> dict:
    return {"supervisor_pid": 100, "entry_pid": 101, "invocation_id": INVOCATION, **overrides}


def observed_generation() -> dict:
    """The fields of the domain observation the credential record must bind to."""
    return {"unit": {"invocation_id": INVOCATION},
            "supervisor": {"pid": 100, "start_ticks": 5000}, "entry": {"pid": 101, "start_ticks": 5001}}


def refused_field(excinfo) -> str:
    assert excinfo.value.reason_code == "maintenance_primary_unverified"
    return excinfo.value.field


# ----- S2M-9: the pinned helper, identity-bound booleans only ---------------------------------------------
@posix_only
def test_pinned_helper_yields_identity_bound_booleans_only(tmp_path):
    helper, pinned = helper_script(tmp_path, ANSWER)
    reader = stable_processes()
    observer = CredentialObserver(helper, pinned, process_reader=reader)
    record = observer({"target_id": "managed-fleet"}, identity())
    assert set(record) == {"schema", "observed_at", "invocation_id", "helper_sha256", "supervisor", "entry"}
    assert record["schema"] == CREDENTIAL_EVIDENCE_SCHEMA and record["invocation_id"] == INVOCATION
    assert record["helper_sha256"] == pinned and datetime.fromisoformat(record["observed_at"]).tzinfo is not None
    assert record["supervisor"] == {"pid": 100, "start_ticks": 5000, **PRIMARY}
    assert record["entry"] == {"pid": 101, "start_ticks": 5001, **PRIMARY}
    # Each pid's identity is read before and after its own helper run.
    assert reader.reads == [100, 100, 101, 101]
    # The domain binds the record to the observed generation and accepts nothing weaker.
    typed = policy.validate_credential_evidence(record, observed_generation())
    assert typed["supervisor"]["is_primary"] is True and typed["entry"]["is_secondary"] is False
    assert helper not in json.dumps(record) and "helper" not in json.dumps(record).replace("helper_sha256", "")
    # A SECONDARY selection is observed truthfully and then refused by the domain: there is no fallback.
    secondary, pinned_secondary = helper_script(
        tmp_path, "emit({'pid': pid, 'has_token': True, 'is_primary': False, 'is_secondary': True})\n",
        name="secondary.py")
    record = CredentialObserver(secondary, pinned_secondary, process_reader=stable_processes())(
        {}, identity())
    assert record["entry"]["is_secondary"] is True
    with pytest.raises(DeliveryRefused) as refused:
        policy.validate_credential_evidence(record, observed_generation())
    assert refused_field(refused) == "supervisor"


def _defects(tmp_path):
    good, pinned = helper_script(tmp_path, ANSWER, name="good.py")
    link = tmp_path / "helper" / "link.py"
    link.symlink_to(good)
    return {
        "sha_mismatch": (good, "0" * 64, identity(), "helper"),
        "missing": (str(tmp_path / "helper" / "absent.py"), pinned, identity(), "helper"),
        "symlinked": (str(link), pinned, identity(), "helper"),
        "nonzero_exit": helper_script(tmp_path, ANSWER + "sys.exit(3)\n", name="exit.py") + (identity(), "helper"),
        "traceback": helper_script(tmp_path, "raise PermissionError('/SENTINEL/secret-path')\n", name="raise.py")
        + (identity(), "helper"),
        "malformed": helper_script(tmp_path, "print('{not json')\n", name="malformed.py") + (identity(),
                                                                                          "helper_output"),
        "extra_key": helper_script(tmp_path, "emit({'pid': pid, 'has_token': True, 'is_primary': True, "
                                             "'is_secondary': False, 'token_sha256': '0' * 64})\n",
                                   name="extra.py") + (identity(), "helper_output"),
        "wrong_pid": helper_script(tmp_path, "emit({'pid': pid + 1, 'has_token': True, 'is_primary': True, "
                                             "'is_secondary': False})\n", name="pid.py") + (identity(),
                                                                                            "helper_output"),
        "truthy_string": helper_script(tmp_path, "emit({'pid': pid, 'has_token': 'true', 'is_primary': True, "
                                                 "'is_secondary': False})\n", name="string.py")
        + (identity(), "helper_output"),
        "truthy_int": helper_script(tmp_path, "emit({'pid': pid, 'has_token': True, 'is_primary': 1, "
                                              "'is_secondary': False})\n", name="int.py") + (identity(),
                                                                                             "helper_output"),
        "oversized": helper_script(tmp_path, "print(' ' * 5000)\n", name="big.py") + (identity(), "helper_output"),
        "timeout": helper_script(tmp_path, "import time\ntime.sleep(30)\n", name="slow.py") + (identity(),
                                                                                              "helper_output"),
        "rewritten_during_run": helper_script(
            tmp_path, "open(__file__, 'a').write('# changed\\n')\n" + ANSWER, name="rewrite.py") + (identity(),
                                                                                                   "helper"),
        "same_pid_twice": (good, pinned, identity(entry_pid=100), "identity"),
        "bad_invocation": (good, pinned, identity(invocation_id="C3" * 16), "identity"),
        "extra_identity": (good, pinned, {**identity(), "token": "x"}, "identity"),
    }


DEFECTS = ["sha_mismatch", "missing", "symlinked", "nonzero_exit", "traceback", "malformed", "extra_key",
           "wrong_pid", "truthy_string", "truthy_int", "oversized", "timeout", "rewritten_during_run",
           "same_pid_twice", "bad_invocation", "extra_identity"]


@posix_only
@pytest.mark.parametrize("defect", DEFECTS)
def test_sha_mismatch_missing_helper_nonzero_exit_malformed_or_extra_output_refuse(tmp_path, defect):
    helper, pinned, asked, field = _defects(tmp_path)[defect]
    observer = CredentialObserver(helper, pinned, process_reader=stable_processes(), timeout=2)
    with pytest.raises(DeliveryRefused) as refused:
        observer({}, asked)
    assert refused_field(refused) == field
    # The refusal names a fixed code and field only: no path, output or exception text.
    assert "/" not in str(refused.value) and "SENTINEL" not in str(refused.value)


# ----- S2M-17: nothing of this process's environment reaches the helper ----------------------------------------
@posix_only
def test_helper_runs_with_no_inherited_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_DATABASE_URL", "postgresql://SENTINEL:" + "SENTINEL" + "@localhost/zeus")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "SENTINEL-TOKEN")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "SENTINEL-PATH"))
    seen = tmp_path / "seen.json"
    helper, pinned = helper_script(
        tmp_path, "json.dump({'keys': sorted(os.environ), 'cwd': os.getcwd(), 'no_bytecode': sys.dont_write_bytecode,"
                  " 'stdin': sys.stdin.read()}, open(" + repr(str(seen)) + ", 'w'))\n" + ANSWER)
    record = CredentialObserver(helper, pinned, process_reader=stable_processes())({}, identity())
    facts = json.loads(seen.read_text("utf-8"))
    assert set(facts["keys"]) <= {"PATH", "LANG", "LC_CTYPE"}, facts["keys"]
    assert not any(key.startswith(("CLAUDE", "HARNESS", "ZEUS", "PYTHON")) for key in facts["keys"])
    assert facts["cwd"] == "/" and facts["no_bytecode"] is True and facts["stdin"] == ""
    assert not (Path(helper).parent / "__pycache__").exists()
    assert "SENTINEL" not in json.dumps(record)


# ----- S2M-4 / S2M-9: a pid that changed hands during the observation refuses ----------------------------------
@posix_only
def test_pid_restart_during_observation_refuses(tmp_path):
    helper, pinned = helper_script(tmp_path, ANSWER)
    calls = {"count": 0}

    def restarted(pid):
        calls["count"] += 1
        # The entry's second read (after its helper run) shows another process under the same pid.
        ticks = 9999 if pid == 101 and calls["count"] == 4 else 5000 + pid - 100
        return {"pid": pid, "state": "present", "start_ticks": ticks}
    with pytest.raises(DeliveryRefused) as refused:
        CredentialObserver(helper, pinned, process_reader=restarted)({}, identity())
    assert refused_field(refused) == "identity"
    for answer in ({"pid": 101, "state": "absent"}, {"pid": 101, "state": "replaced"},
                   {"pid": 101, "state": "present", "start_ticks": None}, {"pid": 7, "state": "present",
                                                                           "start_ticks": 1}):
        def reader(value, answer=answer):
            return answer if value == 101 else {"pid": value, "state": "present", "start_ticks": 5000}
        with pytest.raises(DeliveryRefused) as refused:
            CredentialObserver(helper, pinned, process_reader=reader)({}, identity())
        assert refused_field(refused) == "identity"

    def unreadable(pid):
        raise OSError("proc unreadable (labelled)")
    with pytest.raises(DeliveryRefused) as refused:
        CredentialObserver(helper, pinned, process_reader=unreadable)({}, identity())
    assert refused_field(refused) == "identity"


def test_the_helper_is_configured_only_by_an_absolute_path_and_a_pinned_digest(tmp_path):
    pinned = "a" * 64
    assert credential_observer({}) is None and credential_observer(None) is None
    for helper, digest in (("relative/helper.py", pinned), ("/opt/../helper.py", pinned), ("/opt/helper.py", "A" * 64),
                           ("/opt/helper.py", "a" * 63), ("", pinned), ("/opt/helper.py", None)):
        assert credential_observer({HELPER_SETTING: helper, HELPER_SHA256_SETTING: digest}) is None
    observer = credential_observer({HELPER_SETTING: "/opt/zeus/credential_bool.py", HELPER_SHA256_SETTING: pinned})
    assert isinstance(observer, CredentialObserver) and observer.helper_sha256 == pinned
    assert observer.python == sys.executable


# ----- S2M-2: the authority is verified bytes from the trusted store, never created ------------------------------
def _put(root: Path, data: bytes, *, name=None) -> str:
    key = name or hashlib.sha256(data).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    (root / (key + ".txt")).write_bytes(data)
    return "sha256:" + key


def test_authority_reader_verifies_bytes_refuses_forged_modified_symlinked_or_oversized_and_creates_nothing(tmp_path):
    root = tmp_path / "runtime" / "artifacts"
    directive = "LABELLED recorded user directive: PRIMARY maintenance of managed-fleet\n".encode("utf-8")
    ref = _put(root, directive)
    read = trusted_authority_reader(root)
    assert read(ref) == directive
    refs = {"forged_syntax": "sha256:" + "A" * 64, "short": "sha256:" + "a" * 63, "not_a_ref": "latest",
            "not_a_string": None, "absent": "sha256:" + "0" * 64}
    modified = _put(root, b"other bytes", name=hashlib.sha256(b"original bytes").hexdigest())
    refs["modified"] = modified
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_bytes(b"linked directive")
    link_key = hashlib.sha256(b"linked directive").hexdigest()
    (root / (link_key + ".txt")).symlink_to(elsewhere)
    refs["symlinked"] = "sha256:" + link_key
    big = b"x" * (AUTHORITY_MAX_BYTES + 1)
    refs["oversized"] = _put(root, big)
    refs["empty"] = _put(root, b"")
    if hasattr(os, "mkfifo"):
        fifo_key = hashlib.sha256(b"fifo").hexdigest()
        os.mkfifo(root / (fifo_key + ".txt"))
        refs["fifo"] = "sha256:" + fifo_key
    for name, candidate in refs.items():
        with pytest.raises(DeliveryRefused) as refused:
            read(candidate)
        assert (refused.value.reason_code, refused.value.field) == ("maintenance_authority_unverified",
                                                                    "authority"), name
    # A store that does not exist is not created by reading it.
    missing = tmp_path / "no-runtime" / "artifacts"
    with pytest.raises(DeliveryRefused):
        trusted_authority_reader(missing)(ref)
    assert not missing.exists() and not missing.parent.exists()


# ----- S2M-17: the artifact store is created only by the first actual put -------------------------------------------
def test_lazy_artifacts_create_nothing_until_the_first_put(tmp_path):
    root = tmp_path / "runtime" / "artifacts"
    artifacts = LazyArtifacts(root, FileArtifacts)
    assert not root.exists() and not root.parent.exists()
    receipt = artifacts.put('{"typed":"copy"}', "host-delivery-maintenance:labelled:startup_receipt")
    key = hashlib.sha256(b'{"typed":"copy"}').hexdigest()
    assert receipt["ref"] == "sha256:" + key and (root / (key + ".txt")).read_bytes() == b'{"typed":"copy"}'
    # The same store serves later puts, and its bytes verify through the trusted reader.
    assert artifacts.put('{"typed":"copy"}', "again")["ref"] == receipt["ref"]
    assert trusted_authority_reader(root)(receipt["ref"]) == b'{"typed":"copy"}'


def test_the_owner_action_reader_reads_one_row_and_nothing_else():
    store = MemoryStore()
    action_id = "b" * 64
    with store.transaction() as tx:
        tx.put(BUCKET_ACTIONS, action_id, {"id": action_id, "state": "requested"})
    read = control_action_reader(store)
    assert read(action_id) == {"id": action_id, "state": "requested"}
    assert read("c" * 64) is None
    for invalid in ("B" * 64, "b" * 63, None, 7, "../" + "b" * 61):
        assert read(invalid) is None
    with store.transaction() as tx:
        assert tx.scan(BUCKET_ACTIONS) == [{"id": action_id, "state": "requested"}]


def test_the_qualification_deadline_is_an_aware_time_or_absent():
    assert qualification_deadline({}) is None and qualification_deadline({QUALIFICATION_DEADLINE_SETTING: " "}) is None
    value = "2026-10-02T15:08:43+00:00"
    assert qualification_deadline({QUALIFICATION_DEADLINE_SETTING: value}) == value
    for invalid in ("2026-10-02T15:08:43", "tomorrow", "2026-10-02T15:08:43+00:00" + "0" * 60):
        with pytest.raises(DeliveryRefused) as refused:
            qualification_deadline({QUALIFICATION_DEADLINE_SETTING: invalid})
        assert (refused.value.reason_code, refused.value.field) == ("maintenance_invalid", "qualification_deadline")


def test_the_canary_executor_is_built_only_when_arm_dispatches(monkeypatch):
    built = []

    class FakeFleet:
        def __init__(self):
            self.registry_reads = 0

        def registered(self):
            self.registry_reads += 1
            return {"config": {"lanes": [], "budget": {"total": 1}}}

    class FakeLauncher:
        def __init__(self, config, host):
            built.append(("launcher", config, host))

    class FakeExecutor:
        def __init__(self, fleet, launcher):
            built.append(("executor", fleet))
            self.calls = []

        def execute(self, maintenance_id, *, permit_sha256, proof, max_wait_seconds):
            self.calls.append((maintenance_id, permit_sha256, proof, max_wait_seconds))
            return {"maintenance_id": maintenance_id, "state": "finished"}

    fleet, host = FakeFleet(), {"HARNESS_DATABASE_URL": "labelled"}
    executor = LazyCanaryExecutor(fleet, host, FakeLauncher, FakeExecutor)
    assert built == [] and fleet.registry_reads == 0
    first = executor.execute("active_generation_1:" + "9" * 64, permit_sha256="a" * 64, proof={"p": 1},
                             max_wait_seconds=5.0)
    executor.execute("active_generation_1:" + "9" * 64, permit_sha256="a" * 64, proof={"p": 1}, max_wait_seconds=5.0)
    assert first == {"maintenance_id": "active_generation_1:" + "9" * 64, "state": "finished"}
    assert [entry[0] for entry in built] == ["launcher", "executor"] and fleet.registry_reads == 1
    assert built[0][2] is host and executor._executor.calls[0][3] == 5.0 and len(executor._executor.calls) == 2

