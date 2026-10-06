"""RH-2 P5a: the guard-free file-root layer (`compare/rehearsal/fileroots.py`) and its metadata-only `check` verb.

Layer: harness tooling tests. Expected results come from the task spec (rh2-p5a-fileroots-check, decisions 2-3 and
Examples 1-3): the closed partition, the one symlink allowance, secret and lock names, the cp pin, the aibox_data origin
check. Every test builds a SYNTHETIC stand-in under tmp_path; a tripwire audit hook fails any open/scandir/listdir/
subprocess argv naming the real `/srv/zeus`. The linkage test is a cross-module contract (the allowance target lies under
the uv python directory the namespace binds); the origin tests drive a fresh interpreter. No structural source reads.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from _layout import REPO
from test_rehearsal_namespace import uv_python_dir

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import fileroots as fr  # noqa: E402
from rehearsal.evidence import check_facts  # noqa: E402

REAL = "/srv/zeus"
CANARY = "runtime/lanes/harness/workspaces/review-canary-0123456789abcdef/.venv/bin/python"
_state = {"active": False, "opens": [], "argvs": []}


def _hook(event, args):
    if not _state["active"]:
        return
    if event == "subprocess.Popen":
        _state["argvs"].append([str(a) for a in args[1]])
        scanned = [str(a) for a in args[:3]]
    elif event in ("open", "os.scandir", "os.listdir"):
        scanned = [str(args[0])] if args else []
        if event == "open":
            _state["opens"].append(str(args[0]))
    else:
        return
    if any(REAL in text for text in scanned):
        raise AssertionError(f"tripwire: {event} names the real {REAL}: {scanned}")


sys.addaudithook(_hook)


@pytest.fixture(autouse=True)
def tripwire():
    _state.update(active=True, opens=[], argvs=[])
    yield _state
    _state["active"] = False


def touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def srv(tmp_path):
    root = tmp_path / "srv"
    for d in ("runtime/control/artifacts", "runtime/control/observations/health", "runtime/control/observations/spool",
              "runtime/control/verification", "runtime/control/worker-sessions", "runtime/tokobs", "runtime/lanes/harness",
              "managed-fleet", "repo/.git", "worktrees/w"):
        (root / d).mkdir(parents=True)
    for f in ("runtime/control/monitoring.json", "runtime/control/monitor-collector.log",
              "runtime/control/observations/health/h.json", "runtime/control/artifacts/a.bin",
              "runtime/control/artifacts.lock", "runtime/control/fleet-owner.json", "runtime/control/host-activation.json",
              "runtime/managed-fleet/heartbeat.json", "runtime/managed-fleet/descriptor.json",
              "runtime/managed-fleet/owner-canary-1", "runtime/tokobs/ledger", "managed-fleet/f.json", "repo/a.py",
              "repo/.git/HEAD", "worktrees/w/a.py"):
        touch(root / f)
    touch(root / "worktrees/w/.git", "gitdir: /x")
    link = root / CANARY
    link.parent.mkdir(parents=True)
    link.symlink_to(fr.SYMLINK_ALLOWANCE[0]["target"])
    return root


def run_main(srv, out, monkeypatch, *, aibox=True):
    if aibox:
        monkeypatch.setattr(fr, "load_aibox_data", lambda repo: {rel: "0" * 64 for rel in fr.AIBOX_FILES})
    code = fr.main(["check", "--srv", str(srv), "--out", str(out)])
    return code, json.loads(out.read_text())


# ---- static checks ----

def test_static_checks_pass_for_the_shipped_partition_and_each_violation_raises():
    fr.static_checks()
    roots = fr.STABLE_ROOTS
    for kwargs in (
        {"stable_roots": (*roots, ("x", "runtime/lanes/harness"))},  # overlap
        {"stable_roots": (*roots, ("x", "other/dir"))},  # outside the tops
        {"volatile": (*fr.VOLATILE_PATHS, "repo/volatile.json")},  # volatile inside a stable root
        {"excluded": ("worktrees/tokobs",)},  # excluded inside a stable root
        {"containers": (*fr.CONTAINERS, "runtime/empty")},  # container with nothing below it
    ):
        with pytest.raises(Refused) as caught:
            fr.static_checks(**kwargs)
        assert caught.value.code == "partition_static"


# ---- classify ----

def test_classify_positive_stand_in(srv):
    got = fr.classify(srv)
    assert got["stable_files"] == [
        "runtime/control/artifacts.lock", "runtime/control/fleet-owner.json", "runtime/control/host-activation.json",
        "runtime/managed-fleet/descriptor.json", "runtime/managed-fleet/owner-canary-1"]
    assert got["volatile_present"] == ["runtime/control/monitor-collector.log", "runtime/control/monitoring.json",
                                       "runtime/control/observations/health", "runtime/managed-fleet/heartbeat.json"]
    assert got["excluded"] == ["runtime/tokobs"]
    assert got["stable_roots"] == [rel for _i, rel in fr.STABLE_ROOTS]


def test_a_regular_file_in_a_stable_file_dir_is_a_stable_single_file(srv):
    touch(srv / "runtime/control/new.json")
    assert "runtime/control/new.json" in fr.classify(srv)["stable_files"]


@pytest.mark.parametrize("make", [
    lambda s: (s / "runtime/newdir").mkdir(),
    lambda s: touch(s / "runtime/control/observations/new.json"),
    lambda s: (s / "runtime/managed-fleet/sub").mkdir(),
    lambda s: touch(s / "runtime/stray.txt"),
    lambda s: (s / "runtime/control/link").symlink_to("descriptor"),
])
def test_classify_refuses_an_unclassified_entry(srv, make):
    make(srv)
    with pytest.raises(Refused) as caught:
        fr.classify(srv)
    assert caught.value.code == "partition_unclassified"
    assert 1 <= len(caught.value.facts["paths"]) <= 16


def _replace(path, kind):
    if path.is_dir() and not path.is_symlink():
        os.rmdir(path) if not any(path.iterdir()) else __import__("shutil").rmtree(path)
    else:
        path.unlink()
    if kind == "symlink":
        path.symlink_to(path.parent)
    elif kind == "file":
        touch(path)


@pytest.mark.parametrize("rel,kind,reason", [
    ("runtime", "gone", "source_root_missing"),
    ("repo", "symlink", "source_root_symlink"),
    ("worktrees", "file", "source_root_not_directory"),
    ("managed-fleet", "gone", "source_root_missing"),
    ("runtime/control/worker-sessions", "gone", "source_root_missing"),
    ("runtime/lanes", "symlink", "source_root_symlink"),
    ("runtime/control/verification", "file", "source_root_not_directory"),
])
def test_classify_refuses_a_bad_top_container_or_stable_root(srv, rel, kind, reason):
    _replace(srv / rel, kind)
    with pytest.raises(Refused) as caught:
        fr.classify(srv)
    assert caught.value.code == reason
    assert caught.value.facts == {"path": rel}


# ---- secrets (names only; no content read) ----

@pytest.mark.parametrize("rel", ["runtime/lanes/x/secrets/y", "runtime/lanes/x/.codex/auth.json", "repo/.env",
                                 "worktrees/w/id_rsa", "repo/prod.env", "repo/.claude/s.json", "repo/id_ed25519.pub",
                                 "repo/.netrc", "repo/.git-credentials", "repo/.credentials.json"])
def test_a_secret_name_refuses_without_opening_any_file_under_the_source(srv, tripwire, tmp_path, monkeypatch, rel):
    touch(srv / rel, "TOPSECRETCONTENT")
    tripwire["opens"].clear()  # the planting above opened the file; only the check's own reads count
    code, record = run_main(srv, tmp_path / "out.json", monkeypatch)
    assert (code, record["refused"]) == (1, "secret_path_in_root")
    assert record["facts"]["count"] >= 1 and "TOPSECRETCONTENT" not in json.dumps(record)
    assert not any(o.startswith(str(srv)) for o in tripwire["opens"])
    assert not any("secrets" in p.split("/") for p in record["facts"]["paths"])


def test_a_clean_tree_has_no_secret_names(srv):
    found = fr.survey(srv)
    assert fr.secret_names([*found["files"], *found["dirs"]]) == []


# ---- symlinks ----

def test_the_allowed_review_canary_link_passes_with_count_one(srv):
    assert fr.symlink_facts(srv) == {"total": 1, "allowed": 1, "allowed_paths": [CANARY]}


@pytest.mark.parametrize("rel,target", [
    (CANARY, "/usr/bin/python3"),
    ("runtime/lanes/harness/other/python", fr.SYMLINK_ALLOWANCE[0]["target"]),
    ("repo/rel", "../../../../etc/passwd"),
    ("repo/abs", "/etc/passwd"),
    ("runtime/lanes/harness/workspaces/review-canary-ZZ/.venv/bin/python", fr.SYMLINK_ALLOWANCE[0]["target"]),
    ("repo/review-canary-0123456789abcdef/.venv/bin/python", fr.SYMLINK_ALLOWANCE[0]["target"]),
])
def test_an_unallowed_external_or_escaping_link_refuses(srv, rel, target):
    path = srv / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        path.unlink()
    path.symlink_to(target)
    with pytest.raises(Refused) as caught:
        fr.symlink_facts(srv)
    assert caught.value.code == "external_symlink_unallowed"


def test_a_relative_link_inside_its_top_is_counted_but_needs_no_allowance(srv):
    (srv / "repo/alias").symlink_to("a.py")
    assert fr.symlink_facts(srv)["total"] == 2


@pytest.mark.parametrize("rel,target", [
    ("runtime/lanes/harness/escape-to-control", "../../control/fleet-owner.json"),  # inside `runtime`, outside the root
    ("runtime/control/observations/health/alias.json", "h.json"),  # inside no stable root (D8)
])
def test_a_link_leaving_its_stable_root_or_in_none_refuses_even_when_relative(srv, rel, target):
    """D8: a link is judged against the containing stable root (as aibox_data's inventory does), not the top."""
    (srv / rel).symlink_to(target)
    with pytest.raises(Refused) as caught:
        fr.symlink_facts(srv)
    assert caught.value.code == "external_symlink_unallowed"


def test_venv_internal_relative_links_in_a_lanes_venv_pass(srv):
    venv = srv / "runtime/lanes/harness/workspaces/w1/.venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "lib").mkdir()
    (venv / "bin/python3").symlink_to("python")
    (venv / "lib64").symlink_to("lib")
    facts = fr.symlink_facts(srv)
    assert (facts["total"], facts["allowed"]) == (3, 1)  # the canary link plus two internal links


def test_the_allowance_target_lies_under_the_uv_python_directory_the_namespace_binds():
    assert fr.SYMLINK_ALLOWANCE[0]["target"].startswith(uv_python_dir() + "/")


# ---- git locks ----

@pytest.mark.parametrize("rel", ["repo/.git/index.lock", "worktrees/w2/.git/refs/heads/x.lock"])
def test_a_git_lock_refuses(srv, rel):
    touch(srv / rel)
    with pytest.raises(Refused) as caught:
        fr.git_locks(srv)
    assert caught.value.code == "git_lock_present"


def test_a_linked_worktree_git_file_and_a_non_git_lock_are_not_locks(srv):
    touch(srv / "repo/build.lock")
    assert fr.git_locks(srv) == []


# ---- cp identity ----

def test_the_real_gnucp_passes():
    got = fr.cp_identity()
    assert got["path"] == fr.CP and got["version"].startswith(fr.CP_VERSION_PREFIX) and len(got["sha256"]) == 64


def test_a_symlinked_or_non_gnu_cp_refuses(tmp_path, monkeypatch):
    stub = tmp_path / "cp"
    stub.write_text("#!/bin/sh\necho 'cp (uutils coreutils) 0.8.0'\n")
    stub.chmod(0o755)
    monkeypatch.setattr(fr, "CP", str(stub))
    with pytest.raises(Refused) as caught:
        fr.cp_identity()
    assert caught.value.code == "cp_identity"
    link = tmp_path / "gnucp-link"
    link.symlink_to("/usr/bin/gnucp")
    monkeypatch.setattr(fr, "CP", str(link))
    with pytest.raises(Refused) as caught:
        fr.cp_identity()
    assert caught.value.code == "cp_identity"


# ---- aibox_data (fresh interpreter, the verb's own) ----

def _fresh(code, cwd):
    return subprocess.run(["/usr/bin/python3", "-B", "-c", code], cwd=cwd, capture_output=True, text=True, timeout=120)


def test_load_aibox_data_positive_in_a_fresh_interpreter():
    code = ("import sys, json; sys.path.insert(0, %r)\nfrom rehearsal import fileroots as f\nfrom pathlib import Path\n"
            "got = f.load_aibox_data(Path(%r))\n"
            "import aibox_data.inventory as i\n"
            "print(json.dumps([sorted(got), i.__spec__.origin]))" % (str(REPO / "compare"), str(REPO)))
    done = _fresh(code, REPO)
    assert done.returncode == 0, done.stderr[-400:]
    keys, origin = json.loads(done.stdout)
    assert keys == sorted(fr.AIBOX_FILES) and len(keys) == 7
    assert os.path.realpath(origin).startswith(str(REPO.resolve()))


def test_a_foreign_aibox_data_earlier_on_sys_path_refuses(tmp_path):
    stub = tmp_path / "stub" / "aibox_data"
    touch(stub / "__init__.py", "")
    touch(stub / "inventory.py", "")
    touch(stub / "transfer.py", "")
    code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r)\nfrom rehearsal import fileroots as f, Refused\n"
            "from pathlib import Path\n"
            "try:\n    f.load_aibox_data(Path(%r))\nexcept Refused as e:\n    print(e.code)\n"
            % (str(REPO / "compare"), str(tmp_path / "stub"), str(REPO)))
    done = _fresh(code, REPO)
    assert (done.returncode, done.stdout.strip()) == (0, "aibox_data_origin_foreign"), done.stderr[-400:]


# ---- the verb ----

def test_check_end_to_end_on_the_stand_in_in_process(srv, tmp_path, monkeypatch, tripwire):
    code, record = run_main(srv, tmp_path / "out.json", monkeypatch)
    assert code == 0 and record["ok"] is True and record["refused"] is None
    assert record["schema"] == "zeus:aibox-migration-001:rehearsal:fileroots-check:1" and record["srv"] == str(srv)
    check_facts(record["facts"])
    facts = record["facts"]
    assert facts["symlinks"]["allowed"] == 1 and facts["stable_files"]["count"] == 5
    assert set(facts["stable_roots"]) == {i for i, _r in fr.STABLE_ROOTS}
    assert facts["stable_roots"]["repo"]["files"] == 2 and facts["stable_roots"]["runtime-lanes"]["symlinks"] == 1
    assert facts["stable_roots"]["worktrees"]["bytes"] == 1 + len("gitdir: /x")
    assert tripwire["argvs"] == [[fr.CP, "--version"]]
    assert (tmp_path / "out.json").stat().st_mode & 0o777 == 0o600


def test_check_refuses_with_exit_one_for_each_example(srv, tmp_path, monkeypatch):
    touch(srv / "runtime/control/new.json")
    assert run_main(srv, tmp_path / "a.json", monkeypatch)[0] == 0
    (srv / "runtime/newdir").mkdir()
    code, record = run_main(srv, tmp_path / "b.json", monkeypatch)
    assert (code, record["refused"], record["ok"]) == (1, "partition_unclassified", False)
    (srv / "runtime/newdir").rmdir()
    touch(srv / "repo/.git/index.lock")
    code, record = run_main(srv, tmp_path / "c.json", monkeypatch)
    assert (code, record["refused"]) == (1, "git_lock_present")


def test_check_never_overwrites_an_existing_out_and_usage_errors_exit_two(srv, tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    out.write_text("keep")
    monkeypatch.setattr(fr, "load_aibox_data", lambda repo: {})
    assert fr.main(["check", "--srv", str(srv), "--out", str(out)]) == 2
    assert out.read_text() == "keep"
    assert fr.main(["check"]) == 2
    assert fr.main([]) == 2


def test_check_cli_end_to_end_in_a_fresh_interpreter(srv, tmp_path):
    out = tmp_path / "cli.json"
    done = subprocess.run(["/usr/bin/python3", "-B", "-m", "rehearsal.fileroots", "check", "--srv", str(srv),
                           "--out", str(out)], cwd=REPO / "compare", capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-400:]
    record = json.loads(out.read_text())
    assert record["ok"] and len(record["facts"]["aibox_data"]) == 7 and record["facts"]["cp"]["path"] == fr.CP


# ---- round-1 corrections: out placement, redaction and bounds, cp probe failures ----

def _source_files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if not p.is_dir())


def test_an_out_inside_the_source_is_a_usage_error_with_zero_source_writes(srv, monkeypatch):
    monkeypatch.setattr(fr, "load_aibox_data", lambda repo: {})
    before = _source_files(srv)
    assert fr.main(["check", "--srv", str(srv), "--out", str(srv / "runtime" / "lanes" / "out.json")]) == 2
    assert fr.main(["check", "--srv", str(srv), "--out", str(srv / "out.json")]) == 2
    assert _source_files(srv) == before


def test_an_out_in_an_outside_directory_that_aliases_the_source_is_a_usage_error(srv, tmp_path, monkeypatch):
    monkeypatch.setattr(fr, "load_aibox_data", lambda repo: {})
    alias = tmp_path / "alias"
    alias.symlink_to(srv / "repo")
    before = _source_files(srv)
    assert fr.main(["check", "--srv", str(srv), "--out", str(alias / "out.json")]) == 2
    assert _source_files(srv) == before


def test_an_outside_out_succeeds_and_an_existing_one_is_unchanged(srv, tmp_path, monkeypatch):
    code, _record = run_main(srv, tmp_path / "ok.json", monkeypatch)
    assert code == 0
    keep = tmp_path / "keep.json"
    keep.write_text("keep")
    assert fr.main(["check", "--srv", str(srv), "--out", str(keep)]) == 2 and keep.read_text() == "keep"


@pytest.mark.parametrize("rel,hidden", [
    ("repo/sub/secrets/y", "secrets"), ("repo/.codex/x", ".codex"), ("repo/.claude/x", ".claude"),
    ("repo/auth.json", "auth.json"), ("repo/.credentials.json", ".credentials.json"), ("repo/.netrc", ".netrc"),
    ("repo/.git-credentials", ".git-credentials"), ("repo/.env", ".env"), ("repo/prod.env", "prod.env"),
    ("repo/id_rsa", "id_rsa"), ("repo/id_ed25519.pub", "id_ed25519"), ("repo/id_ecdsa_x", "id_ecdsa"),
])
def test_each_secret_class_gives_a_redacted_bounded_receipt(srv, tripwire, tmp_path, monkeypatch, rel, hidden):
    touch(srv / rel, "TOPSECRETCONTENT")
    tripwire["opens"].clear()
    code, record = run_main(srv, tmp_path / "o.json", monkeypatch)
    assert (code, record["refused"]) == (1, "secret_path_in_root")
    check_facts(record["facts"])
    assert hidden not in "\n".join(record["facts"]["paths"]) and "<redacted>" in record["facts"]["paths"][0]
    assert not any(o.startswith(str(srv)) for o in tripwire["opens"])


def test_overlong_paths_give_bounded_named_receipts_secret_or_not(srv, tmp_path, monkeypatch):
    deep = "/".join(["a" * 180] * 3)
    touch(srv / "repo" / deep / "id_rsa")
    code, record = run_main(srv, tmp_path / "s.json", monkeypatch)
    assert (code, record["refused"]) == (1, "secret_path_in_root")
    check_facts(record["facts"])
    assert all(len(p) <= fr.PATH_LIMIT for p in record["facts"]["paths"]) and record["facts"]["paths"][0].endswith("…")


def test_a_long_non_secret_refusal_path_is_bounded(srv, tmp_path, monkeypatch):
    (srv / "runtime" / ("n" * 250)).mkdir()
    code, record = run_main(srv, tmp_path / "n.json", monkeypatch)
    assert (code, record["refused"]) == (1, "partition_unclassified")
    check_facts(record["facts"])
    assert all(len(p) <= fr.PATH_LIMIT for p in record["facts"]["paths"])


def _cp_stub(tmp_path, mode):
    stub = tmp_path / "cp"
    stub.write_text("#!/bin/sh\necho 'cp (GNU coreutils) 9'\n")
    stub.chmod(mode)
    return str(stub)


@pytest.mark.parametrize("kind", ["missing", "not_executable", "spawn_error", "timeout", "undecodable"])
def test_a_cp_probe_failure_is_a_sanitized_refusal_before_any_source_read(srv, tripwire, tmp_path, monkeypatch, kind):
    if kind == "missing":
        monkeypatch.setattr(fr, "CP", str(tmp_path / "nope"))
    elif kind == "not_executable":
        monkeypatch.setattr(fr, "CP", _cp_stub(tmp_path, 0o644))
    else:
        monkeypatch.setattr(fr, "CP", _cp_stub(tmp_path, 0o755))
        raising = {"spawn_error": PermissionError("RAWSPAWNTEXT"),
                   "timeout": subprocess.TimeoutExpired(["RAWSPAWNTEXT"], 10),
                   "undecodable": UnicodeDecodeError("utf-8", b"\xff", 0, 1, "RAWSPAWNTEXT")}[kind]

        def boom(*a, **k):
            raise raising

        monkeypatch.setattr(fr.subprocess, "run", boom)
    tripwire["opens"].clear()
    code, record = run_main(srv, tmp_path / "o.json", monkeypatch)
    assert (code, record["refused"]) == (1, "cp_identity")
    check_facts(record["facts"])
    assert "RAWSPAWNTEXT" not in json.dumps(record)
    assert not any(o.startswith(str(srv)) for o in tripwire["opens"])
