"""Cutover RH-8 F3 for the R0 baseline recorder (`compare/rehearsal/r0.py`).

Layer: harness tooling tests (never shipped). Expected results come from FLEET-RH8-REVIEW.md F3 "Verification": a
disabled drop-in, a payload outside releases/current and a child must all appear; changing each required identity must
change the baseline; a required-read failure is `complete: false` naming the field; secret and environment files stay
path-only. The oracles are independent: sha256 of the bytes this test wrote, and the synthetic tree's own paths.
Every production path (`/srv/zeus`, `/sys/fs/cgroup`, `/proc`, `/etc/systemd/system`) is replaced by a synthetic root
under tmp_path and systemctl/docker by a table-driven `run`: NO production file or command is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import r0  # noqa: E402

REV_A, REV_B, REV_M = "a" * 40, "b" * 40, "c" * 40  # A: ExecStart, B: releases/current, M: the managed payload
UNIT = "zeus-aibox-fleet.service"
MANAGED = "zeus-aibox-managed-fleet.service"
IMAGE = "sha256:" + "d" * 64
FRAGMENT = b"[Service]\nExecStart=/bin/true\n"
DROP = {"10-a.conf": b"[Service]\nEnvironment=A=1\n", "20-b.conf.disabled": b"[Service]\nEnvironment=B=2\n",
        "README": b"not a conf\n"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_release(srv, rev, *, interpreter=b"py-bin"):
    base = srv / "releases" / rev
    (base / ".venv" / "bin").mkdir(parents=True)
    (base / ".venv" / "bin" / "python").write_bytes(interpreter)
    (base / ".venv" / "pyvenv.cfg").write_text("home = /x\n")
    record = base / ".venv" / "lib" / "python3.12" / "site-packages" / "zeus_harness-1.0.dist-info"
    record.mkdir(parents=True)
    (record / "RECORD").write_text("files\n")
    (base / "runtime.json").write_text(json.dumps({"revision": rev, "tree": "t-" + rev[:4], "built_at": "2026-10-01"}))
    return base


class World:
    def __init__(self, tmp):
        self.tmp = tmp
        self.srv, self.cg, self.proc = tmp / "srv", tmp / "cg", tmp / "proc"
        self.unit_dir = tmp / "etc" / "systemd" / "system"
        self.unit_dir.mkdir(parents=True)
        for rev in (REV_A, REV_B, REV_M):
            make_release(self.srv, rev)
        os.symlink(self.srv / "releases" / REV_B, self.srv / "releases" / "current")
        managed = self.srv / "runtime" / "managed-fleet"
        managed.mkdir(parents=True)
        self.write_managed()
        (self.srv / "runtime" / "control").mkdir()
        (self.srv / "runtime" / "control" / "host-activation.json").write_text("{}")
        (self.srv / "runtime" / "lanes").mkdir()
        (self.srv / "runtime" / "lanes" / "lane-1").mkdir()
        (self.srv / "secrets").mkdir()
        (self.srv / "secrets" / "zeus.env").write_text("TOKEN=SECRETVALUE\n")
        (self.unit_dir / "zeus-aibox.target").write_bytes(b"[Unit]\n")
        self.fragment = self.unit_dir / UNIT
        self.fragment.write_bytes(FRAGMENT)
        self.dropdir = self.unit_dir / (UNIT + ".d")
        self.dropdir.mkdir()
        for name, data in DROP.items():
            (self.dropdir / name).write_bytes(data)
        self.effective = [str(self.dropdir / "10-a.conf")]
        self.docker = {"image_ls": [f"zeus-worker:tag1 {IMAGE}"], "fail": set()}
        self.env_file = str(self.srv / "secrets" / "zeus.env")

    def write_managed(self, **overrides):
        docs = {"descriptor.json": {"revision": REV_M, "schema": "urn:zeus:host-descriptor:1", "target_id": "t",
                                    "plan_id": "plan-1"},
                "startup-receipt.json": {"revision": REV_M, "instance_id": "inst-1", "descriptor_sha256": "e" * 64,
                                         "schema": "x"},
                "controller-state.json": {"invocation_id": "inv-1", "descriptor_sha256": "e" * 64},
                "managed-launch.json": {"descriptor_sha256": "e" * 64, "schema": "y"}}
        docs.update(overrides)
        for name, doc in docs.items():
            (self.srv / "runtime" / "managed-fleet" / name).write_text(json.dumps(doc))

    def add_child(self, pid=4242, argv=(b"python", b"-m", b"zeus", b"tick", b"--secret-ish", b"x")):
        (self.cg / UNIT).mkdir(parents=True, exist_ok=True)
        (self.cg / UNIT / "cgroup.procs").write_text(f"{pid}\n")
        (self.proc / str(pid)).mkdir(parents=True, exist_ok=True)
        (self.proc / str(pid) / "cmdline").write_bytes(b"\0".join(argv) + b"\0")

    def systemctl(self, argv):
        if argv[1] == "list-unit-files":
            return f"{UNIT} static\nzeus-aibox.target static\n"
        unit = argv[2]
        props = [a[2:] for a in argv[3:]]
        frag = str(self.fragment) if unit == UNIT else str(self.unit_dir / unit)
        table = {"FragmentPath": frag, "DropInPaths": " ".join(self.effective if unit == UNIT else []),
                 "ExecStart": f"{{ path={self.srv}/releases/{REV_A}/.venv/bin/python ; argv[]=x -m zeus ; stop_time=[now]; code=exited}}",
                 "EnvironmentFiles": f"{self.env_file} (ignore_errors=no)", "Id": unit, "ActiveState": "active",
                 "WorkingDirectory": str(self.srv / "runtime")}
        return "".join(f"{p}={table[p]}\n" for p in props if p in table)

    def run(self, argv):
        argv = list(argv)
        ok = lambda out="": subprocess.CompletedProcess(argv, 0, out, "")  # noqa: E731
        key = " ".join(argv[:3])
        if key in self.docker["fail"]:
            return subprocess.CompletedProcess(argv, 1, "", "boom")
        if argv[0] == "systemctl":
            if argv[1] == "show" and f"show:{argv[2]}" in self.docker["fail"]:
                return subprocess.CompletedProcess(argv, 1, "", "boom")
            return ok(self.systemctl(argv))
        if argv[:2] == ["docker", "inspect"]:
            return ok(json.dumps({"Id": "cid-" + argv[-1], "Image": "sha256:img", "StartedAt": "t", "RestartCount": 0,
                                  "ExecIDs": []}))
        if argv[:2] == ["docker", "diff"]:
            return ok("C /etc\nA /x\n")
        if argv[:3] == ["docker", "image", "ls"]:
            assert "--no-trunc" in argv  # the full immutable id is requested
            return ok("".join(line + "\n" for line in self.docker["image_ls"]))
        raise AssertionError(argv)

    def env(self):
        return r0.Env(run=self.run, srv=str(self.srv), cgroup=str(self.cg), proc=str(self.proc),
                      unit_dir=str(self.unit_dir) + "/", now=lambda: "T")

    def collect(self):
        return r0.collect(self.env())


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_a_complete_record_is_repeatable_and_names_no_incompleteness(world):
    first, second = world.collect(), world.collect()
    assert first["complete"] is True and first["incomplete"] == [] and first == second
    assert first["schema"] == r0.SCHEMA and set(first["stable"]["releases"]) == {
        str(world.srv / "releases" / REV_A), str(world.srv / "releases" / REV_B)}


def test_the_disabled_and_non_conf_drop_ins_appear_with_their_sha256(world):
    entries = {e["name"]: e for e in world.collect()["stable"][UNIT]["DropInDir"]["entries"]}
    assert set(entries) == set(DROP)  # oracle: the names this test created, disabled and README included
    for name, data in DROP.items():
        assert entries[name]["sha256"] == sha(data) and entries[name]["size"] == len(data) and entries[name]["type"] == "file"
    unit = world.collect()["stable"][UNIT]
    assert [d["path"] for d in unit["DropIns"]] == world.effective  # the effective list is still recorded
    assert unit["DropInDir"]["path"] == str(world.fragment) + ".d" and unit["FragmentSha256"] == sha(FRAGMENT)


def test_an_absent_drop_in_directory_is_evidenced_absence_not_incomplete(world):
    for name in os.listdir(world.dropdir):
        os.unlink(world.dropdir / name)
    os.rmdir(world.dropdir)
    world.effective = []
    record = world.collect()
    assert record["stable"][UNIT]["DropInDir"] == {"path": str(world.fragment) + ".d", "present": False, "entries": []}
    assert record["complete"] is True


def test_secret_and_environment_files_stay_path_only(world):
    os.symlink(world.srv / "secrets" / "zeus.env", world.dropdir / "30-secret.conf")
    (world.dropdir / "40.env").write_text("TOKEN=SECRETVALUE2\n")
    record = world.collect()
    text = json.dumps(record)
    assert "SECRETVALUE" not in text
    entries = {e["name"]: e for e in record["stable"][UNIT]["DropInDir"]["entries"]}
    assert entries["30-secret.conf"].get("path_only") is True and "sha256" not in entries["30-secret.conf"]
    assert entries["40.env"].get("path_only") is True and "sha256" not in entries["40.env"]
    assert record["stable"][UNIT]["EnvironmentFiles"] == [world.env_file]  # the path, never a digest of the content
    assert sha(b"TOKEN=SECRETVALUE\n") not in text


def test_a_payload_outside_releases_current_is_bound_to_its_runtime_and_executable_identity(world):
    record = world.collect()
    payload_dir = str(world.srv / "releases" / REV_M)
    assert payload_dir not in record["stable"]["releases"]  # neither an ExecStart release nor releases/current
    managed = record["stable"]["managed_payload"]
    assert managed["binding"]["revisions"] == [REV_M] and managed["binding"]["locations"] == [payload_dir]
    facts = managed["releases"][payload_dir]
    runtime_json = (world.srv / "releases" / REV_M / "runtime.json").read_bytes()
    assert facts["runtime_json_sha256"] == sha(runtime_json) and facts["interpreter_sha256"] == sha(b"py-bin")
    assert facts["interpreter_realpath"] == str(world.srv / "releases" / REV_M / ".venv" / "bin" / "python")
    assert facts["runtime"]["revision"] == REV_M
    assert managed["binding"]["descriptor.json"]["plan_id"] == "plan-1"  # plan identity is carried
    assert record["per_invocation"]["managed_fleet"]["startup-receipt.json"]["instance_id"] == "inst-1"


def test_a_continuation_child_appears_with_argv_0_to_2_only_and_absence_is_evidenced(world):
    assert world.collect()["per_invocation"]["children"][UNIT] == {"cgroup": "absent", "children": []}
    world.add_child()
    children = world.collect()["per_invocation"]["children"][UNIT]
    assert children == {"cgroup": "present", "children": [{"pid": 4242, "argv": ["python", "-m", "zeus"]}]}
    assert "--secret-ish" not in json.dumps(world.collect())


def test_a_child_that_exits_between_the_reads_is_recorded_gone_not_incomplete(world):
    world.add_child()
    os.unlink(world.proc / "4242" / "cmdline")
    record = world.collect()
    assert record["per_invocation"]["children"][UNIT]["children"] == [{"pid": 4242, "gone": True}]
    assert record["complete"] is True


def test_the_worker_image_identity_is_the_full_sha256_id(world):
    assert world.collect()["stable"]["worker_images"] == [{"ref": "zeus-worker:tag1", "id": IMAGE}]


def _drop_in(w):
    (w.dropdir / "20-b.conf.disabled").write_bytes(b"[Service]\nEnvironment=B=3\n")


def _new_entry(w):
    (w.dropdir / "50-new.conf.bak").write_bytes(b"x")


def _interpreter(w):
    (w.srv / "releases" / REV_M / ".venv" / "bin" / "python").write_bytes(b"other-py")


def _runtime_json(w):
    (w.srv / "releases" / REV_M / "runtime.json").write_text(json.dumps({"revision": REV_M, "tree": "other"}))


def _plan(w):
    w.write_managed(**{"descriptor.json": {"revision": REV_M, "schema": "urn:zeus:host-descriptor:1", "target_id": "t",
                                           "plan_id": "plan-2"}})


def _instance(w):
    w.write_managed(**{"startup-receipt.json": {"revision": REV_M, "instance_id": "inst-2", "descriptor_sha256": "e" * 64,
                                                "schema": "x"}})


def _child(w):
    w.add_child()


def _image(w):
    w.docker["image_ls"] = ["zeus-worker:tag1 sha256:" + "f" * 64]


def _payload_revision(w):
    make_release(w.srv, "9" * 40)
    w.write_managed(**{"descriptor.json": {"revision": "9" * 40, "schema": "urn:zeus:host-descriptor:1", "target_id": "t",
                                           "plan_id": "plan-1"}, "startup-receipt.json": {
        "revision": "9" * 40, "instance_id": "inst-1", "descriptor_sha256": "e" * 64, "schema": "x"}})


@pytest.mark.parametrize("mutate", [_drop_in, _new_entry, _interpreter, _runtime_json, _plan, _instance, _child, _image,
                                    _payload_revision], ids=lambda f: f.__name__.strip("_"))
def test_changing_each_required_identity_changes_the_baseline(world, mutate):
    before = world.collect()
    mutate(world)
    after = world.collect()
    assert {**before, "at": ""} != {**after, "at": ""}


def _rm_runtime(w):
    os.unlink(w.srv / "releases" / REV_M / "runtime.json")


def _unreadable_dropin(w):
    os.chmod(w.dropdir / "10-a.conf", 0)


def _unreadable_dropdir(w):
    os.chmod(w.dropdir, 0)


def _no_descriptor(w):
    os.unlink(w.srv / "runtime" / "managed-fleet" / "descriptor.json")


def _no_payload_dir(w):
    import shutil
    shutil.rmtree(w.srv / "releases" / REV_M)


def _unreadable_cgroup(w):
    w.add_child()
    os.chmod(w.cg / UNIT / "cgroup.procs", 0)


def _unreadable_cmdline(w):
    w.add_child()
    os.chmod(w.proc / "4242" / "cmdline", 0)


def _short_image(w):
    w.docker["image_ls"] = ["zeus-worker:tag1 8fe15097a0e9"]


def _image_cmd(w):
    w.docker["fail"].add("docker image ls")


def _show(w):
    w.docker["fail"].add(f"show:{UNIT}")


def _inspect(w):
    w.docker["fail"].add("docker inspect --format")


def _diff(w):
    w.docker["fail"].add("docker diff zeus-aibox-postgres")


@pytest.mark.parametrize("mutate,field", [
    (_rm_runtime, "release:%s:runtime.json"), (_unreadable_dropin, "dropin:" + UNIT), (_unreadable_dropdir, "dropin_dir:" + UNIT),
    (_no_descriptor, "managed:descriptor.json"), (_no_payload_dir, "managed_payload:location:" + REV_M),
    (_unreadable_cgroup, "cgroup:" + UNIT), (_unreadable_cmdline, "cmdline:" + UNIT), (_short_image, "worker_images"),
    (_image_cmd, "worker_images"), (_show, "show:" + UNIT), (_inspect, "container:zeus-aibox-postgres"),
    (_diff, "diff:zeus-aibox-postgres")], ids=lambda x: getattr(x, "__name__", x))
def test_a_required_unreadable_fact_is_complete_false_naming_the_field(world, mutate, field):
    mutate(world)
    try:
        record = world.collect()
    finally:
        for path in (world.dropdir, world.dropdir / "10-a.conf", world.cg / UNIT / "cgroup.procs", world.proc / "4242" / "cmdline"):
            if path.exists():
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
    assert record["complete"] is False
    wanted = field % str(world.srv / "releases" / REV_M) if "%s" in field else field
    assert any(name == wanted or name.startswith(wanted) for name in record["incomplete"]), record["incomplete"]


def test_main_writes_the_record_once_and_exits_1_when_incomplete(world, tmp_path, capsys):
    out = tmp_path / "r0.json"
    assert r0.main(str(out), world.env()) == 0 and json.loads(out.read_text())["complete"] is True
    with pytest.raises(FileExistsError):
        r0.main(str(out), world.env())  # never overwrites a recorded baseline
    _short_image(world)
    out2 = tmp_path / "r0b.json"
    assert r0.main(str(out2), world.env()) == 1
    assert json.loads(out2.read_text())["incomplete"] == ["worker_images"]
