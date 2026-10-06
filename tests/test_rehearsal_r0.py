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
DESC, INST, PLAN = "e" * 64, "inst-1", "plan-1"
TARGET = "t"
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
        self.lane_status = tmp / "lane-status.json"
        self.write_managed()
        self.write_lane()
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
        self.launcher = tmp / "usr" / "bin" / "python3"  # the managed unit's ExecStart argv[0]
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b"launcher-bin")
        self.version = "3.12.3 (main) [GCC]"

    def write_managed(self, revision=REV_M, **overrides):
        """The five recorded managed records in their observed shapes; none of them carries a plan id."""
        root = str(self.srv / "releases" / revision)
        docs = {"descriptor.json": {"revision": revision, "schema": "urn:zeus:host-descriptor:1", "target_id": TARGET,
                                    "predecessor": "p", "profile_digest": "f" * 64, "root": "/r", "worker_image": "w"},
                "startup-receipt.json": {"revision": revision, "instance_id": INST, "descriptor_sha256": DESC,
                                         "schema": "x", "runtime_root": root, "module_root": root + "/src", "pid": 1,
                                         "started_at": "t0", "target_id": TARGET},
                "controller-state.json": {"invocation_id": "inv-1", "descriptor_sha256": DESC, "pid": 2},
                "managed-launch.json": {"descriptor_sha256": DESC, "schema": "y", "target_id": TARGET},
                "heartbeat.json": {"descriptor_sha256": DESC, "instance_id": INST, "at": "t1", "schema": "z"}}
        docs.update(overrides)
        for name, doc in docs.items():
            (self.srv / "runtime" / "managed-fleet" / name).write_text(json.dumps(doc))

    def write_lane(self, revision=REV_M, **row):
        """The authoritative lane status (`host-delivery status --lane harness`): the only source of the plan id."""
        target = {"target_id": TARGET, "descriptor_sha256": DESC, "instance_id": INST, "plan_id": PLAN,
                  "revision": revision, "consumed": True}
        target.update(row)
        other = {"target_id": "other", "descriptor_sha256": "0" * 64, "instance_id": "x", "plan_id": "other-plan",
                 "revision": REV_A}
        self.lane_status.write_text(json.dumps({"targets": [other, {k: v for k, v in target.items() if v is not None}]}))

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
        if unit == MANAGED:
            return "".join(f"{p}={{ path={self.launcher} ; argv[]={self.launcher} -m zeus ; code=exited}}\n"
                           for p in props if p == "ExecStart")
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
        if argv[0] == str(self.launcher):
            assert argv[1:] == ["-c", "import sys;print(sys.version)"]
            return ok(self.version + "\n")
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
                      unit_dir=str(self.unit_dir) + "/", now=lambda: "T", lane_status=str(self.lane_status))

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
    assert record["per_invocation"]["managed_fleet"]["startup-receipt.json"]["instance_id"] == INST


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
    w.write_lane(plan_id="plan-2")


def _instance(w):
    w.write_lane(instance_id="inst-2")
    w.write_managed(**{"startup-receipt.json": {**json.loads((w.srv / "runtime" / "managed-fleet" / "startup-receipt.json").read_text()),
                                                "instance_id": "inst-2"},
                       "heartbeat.json": {"descriptor_sha256": DESC, "instance_id": "inst-2", "at": "t1", "schema": "z"}})


def _child(w):
    w.add_child()


def _image(w):
    w.docker["image_ls"] = ["zeus-worker:tag1 sha256:" + "f" * 64]


def _payload_revision(w):
    make_release(w.srv, "9" * 40)
    w.write_managed(revision="9" * 40)
    w.write_lane(revision="9" * 40)


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
    (_no_descriptor, "managed:descriptor.json"), (_no_payload_dir, "managed_payload:location:"),
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


# -- RH-8 F3 final: the authoritative descriptor/plan/instance binding (FLEET-RH8-REVIEW.md Round 2, F3 controls 1-5) --

MANAGED_DIR = lambda w: w.srv / "runtime" / "managed-fleet"  # noqa: E731


def _read_managed(w, name):
    return json.loads((MANAGED_DIR(w) / name).read_text())


def test_control1_no_authoritative_plan_identity_is_incomplete_naming_the_plan_and_main_exits_1(world, tmp_path):
    world.write_lane(plan_id=None)  # the lane status row has no plan id; no managed record carries one either
    record = world.collect()
    assert record["complete"] is False and "managed.binding.plan_id" in record["incomplete"]
    assert "plan_id" not in record["stable"]["managed"]["binding"]
    out = tmp_path / "r0-noplan.json"
    assert r0.main(str(out), world.env()) == 1 and "managed.binding.plan_id" in json.loads(out.read_text())["incomplete"]


def test_control1b_a_plan_id_inside_a_runtime_record_is_not_authoritative(world):
    world.write_lane(plan_id=None)
    world.write_managed(**{"descriptor.json": {**_read_managed(world, "descriptor.json"), "plan_id": "plan-1"}})
    record = world.collect()
    assert record["complete"] is False and "managed.binding.plan_id" in record["incomplete"]


def test_control2_a_valid_binding_is_complete_recorded_and_stable_on_repeat(world):
    first, second = world.collect(), world.collect()
    assert first["complete"] is True and first["incomplete"] == [] and first == second
    assert first["stable"]["managed"]["binding"] == {"plan_id": PLAN, "descriptor_sha256": DESC, "instance_id": INST,
                                                     "revision": REV_M}


def test_control3_changing_the_plan_changes_the_binding_and_the_baseline(world):
    before = world.collect()
    world.write_lane(plan_id="plan-2")
    after = world.collect()
    assert after["complete"] is True and after["stable"]["managed"]["binding"]["plan_id"] == "plan-2"
    assert {**before, "at": ""} != {**after, "at": ""}


def test_control4_a_missing_or_inconsistent_binding_is_incomplete(world):
    world.lane_status.write_text(json.dumps({"targets": [{"target_id": "other", "plan_id": "p"}]}))  # no managed row
    record = world.collect()
    assert record["complete"] is False
    assert {"managed.binding.plan_id", "managed.binding.descriptor_sha256", "managed.binding.instance_id",
            "managed.binding.revision", "managed.binding:target_row"} <= set(record["incomplete"])
    world.lane_status.unlink()  # unreadable status
    assert "managed.binding:lane_status" in world.collect()["incomplete"]


@pytest.mark.parametrize("name,field,expected", [
    ("startup-receipt.json", "instance_id", "managed.binding.instance_id:inconsistent"),
    ("heartbeat.json", "instance_id", "managed.binding.instance_id:inconsistent"),
    ("startup-receipt.json", "descriptor_sha256", "managed.binding.descriptor_sha256:inconsistent"),
    ("controller-state.json", "descriptor_sha256", "managed.binding.descriptor_sha256:inconsistent"),
    ("heartbeat.json", "descriptor_sha256", "managed.binding.descriptor_sha256:inconsistent")])
def test_control4b_a_runtime_record_that_disagrees_with_the_lane_status_is_inconsistent(world, name, field, expected):
    doc = _read_managed(world, name)
    doc[field] = "other-value"
    world.write_managed(**{name: doc})
    record = world.collect()
    assert record["complete"] is False and expected in record["incomplete"]


def test_control4c_a_record_without_the_bound_identity_or_an_unreadable_heartbeat_is_incomplete(world):
    doc = _read_managed(world, "startup-receipt.json")
    del doc["instance_id"]
    world.write_managed(**{"startup-receipt.json": doc})
    record = world.collect()
    assert record["complete"] is False and "managed.binding.instance_id:startup-receipt.json:instance_id" in record["incomplete"]
    world.write_managed()
    os.unlink(MANAGED_DIR(world) / "heartbeat.json")
    assert "managed:heartbeat.json" in world.collect()["incomplete"]


def test_control5_the_recorded_runtime_root_and_module_root_bind_the_runtime_and_executable(world):
    other = world.srv / "payloads" / "p1"  # a payload outside releases/<rev>: located by its runtime.json
    (other / ".venv" / "bin").mkdir(parents=True)
    (other / ".venv" / "bin" / "python").write_bytes(b"alt-py")
    (other / ".venv" / "pyvenv.cfg").write_text("home = /y\n")
    (other / "runtime.json").write_text(json.dumps({"revision": REV_M, "tree": "t", "built_at": "b"}))
    receipt = _read_managed(world, "startup-receipt.json")
    receipt.update(runtime_root=str(other), module_root=str(other / "src" / "zeus"))
    world.write_managed(**{"startup-receipt.json": receipt})
    record = world.collect()
    managed = record["stable"]["managed_payload"]
    assert managed["binding"]["locations"] == [str(other)]
    assert managed["releases"][str(other)]["interpreter_sha256"] == sha(b"alt-py")
    assert managed["releases"][str(other)]["runtime_json_sha256"] == sha((other / "runtime.json").read_bytes())
    assert "managed_payload:location:" not in " ".join(record["incomplete"])


def test_control5b_an_unresolved_payload_location_shape_stays_incomplete_and_no_release_is_substituted(world):
    receipt = _read_managed(world, "startup-receipt.json")
    receipt.update(runtime_root=str(world.srv / "nowhere"), module_root=str(world.srv / "nowhere" / "src"))
    world.write_managed(**{"startup-receipt.json": receipt})
    record = world.collect()  # REV_M's release directory exists, but must not be substituted for the unresolved shape
    assert record["complete"] is False
    assert any(n.startswith("managed_payload:location:") for n in record["incomplete"])
    assert record["stable"]["managed_payload"]["releases"] == {}
    del receipt["runtime_root"], receipt["module_root"]
    world.write_managed(**{"startup-receipt.json": receipt})
    assert "managed_payload:location" in world.collect()["incomplete"]


def make_runtime_dir(base, rev=REV_M, files=None):
    """The observed managed payload shape: runtime.json, runtime-files.json, pyproject.toml, uv.lock, src/; no .venv."""
    base.mkdir(parents=True)
    (base / "src").mkdir()
    (base / "runtime.json").write_text(json.dumps({"revision": rev, "tree": "t", "built_at": "b"}))
    for name, data in {"runtime-files.json": b"[1]", "uv.lock": b"lock", "pyproject.toml": b"proj", **(files or {})}.items():
        (base / name).write_bytes(data)
    return base


def _runtime_dir_world(world):
    base = make_runtime_dir(world.srv / "runtimes" / REV_M)
    receipt = _read_managed(world, "startup-receipt.json")
    receipt.update(runtime_root=str(base), module_root=str(base / "src"))
    world.write_managed(**{"startup-receipt.json": receipt})
    return base


def test_shape1_the_runtime_dir_shape_binds_digests_and_the_launching_units_interpreter(world):
    base = _runtime_dir_world(world)
    record = world.collect()
    facts = record["stable"]["managed_payload"]["releases"][str(base)]
    assert facts["shape"] == "runtime_dir" and facts["runtime"] == {"revision": REV_M, "tree": "t", "built_at": "b"}
    assert (facts["runtime_json_sha256"], facts["runtime_files_json_sha256"]) == (
        sha((base / "runtime.json").read_bytes()), sha(b"[1]"))
    assert (facts["uv_lock_sha256"], facts["pyproject_toml_sha256"]) == (sha(b"lock"), sha(b"proj"))
    assert facts["interpreter_realpath"] == str(world.launcher) and facts["interpreter_sha256"] == sha(b"launcher-bin")
    assert facts["interpreter_version"] == world.version
    assert record["complete"] is True and record["incomplete"] == []


@pytest.mark.parametrize("name,data", [("runtime-files.json", b"[2]"), ("uv.lock", b"lock2"), ("pyproject.toml", b"p2")])
def test_shape2_changing_a_runtime_dir_file_changes_the_baseline(world, name, data):
    base = _runtime_dir_world(world)
    before = world.collect()
    (base / name).write_bytes(data)
    assert {**before, "at": ""} != {**world.collect(), "at": ""}


def test_shape3_the_interpreter_identity_comes_from_the_unit_not_the_runtime_dir(world):
    base = _runtime_dir_world(world)
    (base / "src" / "python3").write_bytes(b"decoy")  # nothing inside the payload is a source of identity
    before = world.collect()
    world.launcher.write_bytes(b"launcher-2")
    world.version = "3.13.0"
    facts = world.collect()["stable"]["managed_payload"]["releases"][str(base)]
    assert facts["interpreter_sha256"] == sha(b"launcher-2") and facts["interpreter_version"] == "3.13.0"
    assert before["stable"]["managed_payload"]["releases"][str(base)]["interpreter_sha256"] == sha(b"launcher-bin")


def test_shape3b_a_launcher_inside_the_payload_dir_or_a_failed_version_probe_is_incomplete(world):
    base = _runtime_dir_world(world)
    world.docker["fail"].add(f"{world.launcher} -c import sys;print(sys.version)")
    record = world.collect()
    assert f"payload:{base}:interpreter_version" in record["incomplete"]
    world.docker["fail"].clear()
    world.launcher = base / "src" / "python3"  # would execute code from the runtime dir: refused
    world.launcher.write_bytes(b"x")
    assert f"payload:{base}:launching_executable" in world.collect()["incomplete"]


def test_shape4_a_directory_of_neither_shape_is_incomplete_naming_the_shape(world):
    base = _runtime_dir_world(world)
    (base / "uv.lock").unlink()
    record = world.collect()
    assert record["complete"] is False and f"managed_payload:shape:{base}" in record["incomplete"]
    assert record["stable"]["managed_payload"]["releases"][str(base)]["shape"] == "unknown"


def test_shape5_the_release_shape_is_unchanged_and_never_asks_the_launching_unit(world):
    record = world.collect()
    facts = record["stable"]["managed_payload"]["releases"][str(world.srv / "releases" / REV_M)]
    assert "shape" not in facts and facts["interpreter_sha256"] == sha(b"py-bin") and record["complete"] is True
