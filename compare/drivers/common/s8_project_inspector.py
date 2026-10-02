"""Shared S8 scenario steps (`evidence.project_inspector`): M7 `adapters/project_evidence.py` (`load_profile`, `resolve_profile`,
`execution_instructions`, `worker_delivery`, `container_binding`, `resolve_container_profile`, `container_execution_instructions`,
`container_worker_delivery`, `ProjectEvidenceInspector`), characterized BEFORE the module moves into `evidence.adapters.project_evidence`
(DESIGN-s8 §27.1 V26 rule E-3: the execution constants become evidence-local published language; the batch B5b spec). Mirrors the behaviours
of M7 `tests/test_project_evidence.py` and the delivery/instruction/binding tests of `tests/test_isolated_project_evidence.py` that the module itself
decides (the operation identity, executor, bootstrap, entry and `IsolatedWorker` tests are S3/S10 composition and stay out).

- **k1_loading**: `load_profile` (no setting, both setting names, relative/absent/directory/oversized/non-JSON files, a version 1 profile whose host
  interpreter is missing, a version 2 profile that needs none).
- **k2_resolution**: `resolve_profile` (cwd, source paths, dependency digests, the interpreter digest, the snapshot environment without the parent's
  PYTHONPATH or secrets), every refusal before a child (missing cwd/source/dependency, an oversized dependency, a symlink escape, a missing interpreter),
  `execution_instructions` and `worker_delivery` rebound to each checkout.
- **k3_container**: `container_binding` in both directions, `resolve_container_profile`, `container_execution_instructions` and
  `container_worker_delivery` (container values only, never a host path) and their refusals before any container.
- **k4_host_route**: `ProjectEvidenceInspector` over REAL children (a stand-in `pytest` package shipped in the candidate's `backend/src`, so no installed
  pytest is needed): the required checks replayed in the project subdirectory, a reported failure kept, exit 5 not a pass, not_run/missing/unknown/duplicate
  that never spawn, the R1 profile boundary, the aggregate deadline (a ticking clock and an injected capture, then a real slow second replay), the replay
  snapshot, the identity and the legacy inspector without a profile.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. Children are REAL (this side's own interpreter) through
the REAL `ProcessTree`. Masks, declared: digests over a host path (`digest`, `project_digest`, `interpreter_sha256`, `environment_digest`, `inspection_id`,
`id`, `policy_hash` of a scenario policy and the profile digest of a host profile), durations and OS pids; host roots become symbolic names."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from s1_common import relative
from s8_isolated_inspector import IMAGE, LINT, OTHER_IMAGE, UNIT, expect

PY = sys.executable
PROBE = "zeus_backend_probe"
FAILING = "zeus_backend_failing"
TASK = {"id": "task-1", "generation": 1, "attempt": 1, "lease_owner": "worker"}
CANDIDATE = {"revision": "a" * 40, "base": "b" * 40, "tree": "c" * 40}
HOSTDIGESTS = {"digest", "project_digest", "interpreter_sha256", "environment_digest", "inspection_id", "id", "policy_hash"}
PIDISH = {"pid", "group", "pgid", "process_id", "leader"}
DURATIONS = {"duration_seconds", "elapsed_seconds", "seconds"}
FAKE_PYTEST = r'''import os
import sys
import time
from pathlib import Path

name = Path(sys.argv[1]).stem if len(sys.argv) > 1 else ""
if name == "empty_tests" or sys.argv[1:2] == ["empty_tests"]:
    print("no tests ran")
    sys.exit(5)
if name.endswith("failing"):
    print("1 failed")
    sys.exit(1)
if name.endswith("slow"):
    time.sleep(3)
    print("1 passed")
    sys.exit(0)
problems = []
if Path.cwd().name != "backend":
    problems.append("cwd")
if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
    problems.append("bytecode")
if "ZEUS_SECRET" in os.environ:
    problems.append("secret")
if not os.environ.get("PYTHONPATH", "").endswith("src") or "parent-path" in os.environ.get("PYTHONPATH", ""):
    problems.append("pythonpath")
print("1 passed" if not problems else "context: " + ",".join(problems))
sys.exit(0 if not problems else 2)
'''


def mask(value, extra=()):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in PIDISH and isinstance(item, int) and not isinstance(item, bool):
                out[key] = "<pid>"
            elif key in DURATIONS and isinstance(item, (int, float)) and not isinstance(item, bool):
                out[key] = "<duration>"
            elif (key in HOSTDIGESTS or key in extra) and isinstance(item, str) and len(item) == 64:
                out[key] = "<host digest>"
            else:
                out[key] = mask(item, extra)
        return out
    if isinstance(value, (list, tuple)):
        return [mask(v, extra) for v in value]
    return value


def argv_for(module):
    return ["python", "-m", "pytest", f"probes/test_{module}.py", "-q", "-p", "no:cacheprovider"]


def policy(**replay):
    base = {"version": 1, "replay": {"allowed_argv_prefixes": [["python", "-m", "pytest"], ["python", "-m", "ruff", "check"],
                                                              ["python", "-m", PROBE], ["ruff", "check"],
                                                              ["uv", "run", "python", "-m", "pytest"]],
                                     "per_command_seconds": 60, "total_seconds": 180, "max_claims": 8,
                                     "max_output_bytes": 4096, "replays_per_claim": 2},
            "files": {"max_bytes": 1024 * 1024}}
    base["replay"].update(replay)
    return base


def check(name, module, expected=0):
    return {"id": name, "context": "backend", "argv": argv_for(module), "expected_exit": expected}


def executed(name, code=0):
    return {"check_id": name, "status": "executed", "exit_code": code}


def workspace(root: Path, name="candidate") -> Path:
    base = root / name
    source = base / "backend" / "src"
    (source / "pytest").mkdir(parents=True)
    (source / "pytest" / "__init__.py").write_text("", encoding="utf-8")
    (source / "pytest" / "__main__.py").write_text(FAKE_PYTEST, encoding="utf-8")
    (base / "backend" / "empty_tests").mkdir()
    (base / "backend" / "requirements.lock").write_bytes(b"example==1.0\n")
    (source / (PROBE + ".py")).write_text("VALUE = 1\n", encoding="utf-8")
    probes = base / "backend" / "probes"
    probes.mkdir()
    for module in (PROBE, FAILING, "slow"):
        (probes / f"test_{module}.py").write_text("# the stand-in pytest decides by the file name\n", encoding="utf-8")
    return base


class Ctx:
    def __init__(self, api, root: Path):
        self.api, self.root = api, root
        self.roots = {"ROOT": str(root), "PY": PY}
        self.n = 0

    def fresh(self, name):
        self.n += 1
        path = self.root / f"{self.n:02d}-{name}"
        path.mkdir()
        return path

    def show(self, value, *extra):
        return relative(mask(value, extra), self.roots)

    def document(self, checks=None, **context):
        return {"schema": self.api.SCHEMA,
                "contexts": {"backend": {"cwd": "backend", "interpreter": PY, "source_paths": ["backend/src"],
                                         "dependency_files": ["backend/requirements.lock"], **context}},
                "checks": checks if checks is not None else [{"id": "probe", "context": "backend", "argv": argv_for(PROBE), "expected_exit": 0}]}

    def container_document(self, checks=None, execution=None, **context):
        api = self.api
        doc = self.document(checks, **{"interpreter": api.CONTAINER_INTERPRETER, **context})
        return {**doc, "schema": api.SCHEMA_V2, "execution": {"kind": "container", "image": IMAGE} if execution is None else execution}

    def parsed(self, doc=None, plc=None):
        return self.api.parse_profile(doc or self.document(), plc or self.api.parse_policy(policy()))

    def isolation(self, image=IMAGE):
        api = self.api
        config = api.load_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": image})
        body = {k: v for k, v in config.items() if k != "digest"}
        body["driver_sha256"] = "d" * 64
        return {**body, "digest": api.digest(body)}

    def inspector(self, tmp, doc=None):
        api = self.api
        return api.ProjectEvidenceInspector(api.FileArtifacts(str(tmp / "artifacts")), self.parsed(doc), policy())

    def ledger(self, tmp, doc=None):
        store = self.api.MemoryStore()
        return store, self.api.EvidenceInspections(store, self.inspector(tmp, doc))


# ---- k1 -------------------------------------------------------------------------------------------------------------------
def k1_loading(ctx):
    api, out = ctx.api, {}
    out["constants"] = {"setting": api.SETTING, "max_profile_bytes": api.MAX_PROFILE_BYTES, "max_dependency_bytes": api.MAX_DEPENDENCY_BYTES,
                        "unprintable": api.UNPRINTABLE.pattern}
    tmp = ctx.fresh("loading")
    plc = api.parse_policy(policy())
    out["absent"] = {"empty": api.load_profile({}), "blank": api.load_profile({"HARNESS_EVIDENCE_PROFILE": ""}),
                     "other_keys": api.load_profile({"SOMETHING": "x"})}
    path = tmp / "profile.json"
    path.write_text(json.dumps(ctx.document()), encoding="utf-8")
    loaded = api.load_profile({"HARNESS_EVIDENCE_PROFILE": str(path)}, plc)
    out["host_profile"] = {"digest_matches_parse": loaded["profile_digest"] == ctx.parsed()["profile_digest"], "keys": sorted(loaded),
                           "schema": loaded["schema"], "checks": loaded["checks"], "contexts": ctx.show(loaded["contexts"])}
    legacy = api.load_profile({"ZEUS_EVIDENCE_PROFILE": str(path)}, plc)
    out["alias_setting"] = {"same_digest": legacy["profile_digest"] == loaded["profile_digest"],
                            "harness_wins": api.load_profile({"HARNESS_EVIDENCE_PROFILE": str(path), "ZEUS_EVIDENCE_PROFILE": "relative.json"},
                                                             plc)["profile_digest"] == loaded["profile_digest"]}
    out["packaged_policy_default"] = {"loads": api.load_profile({"HARNESS_EVIDENCE_PROFILE": str(path)}) is not None}
    directory = tmp / "a-directory"
    directory.mkdir()
    big = tmp / "big.json"
    big.write_bytes(b" " * (api.MAX_PROFILE_BYTES + 1))
    bad = tmp / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    missing_python = tmp / "missing-python.json"
    missing_python.write_text(json.dumps(ctx.document(interpreter=str(tmp / "no-such-python"))), encoding="utf-8")
    out["refusals"] = {name: ctx.show(expect(lambda p=value: api.load_profile({"HARNESS_EVIDENCE_PROFILE": p}, plc)))
                       for name, value in (("relative", "relative.json"), ("absent", str(tmp / "absent.json")), ("directory", str(directory)),
                                           ("oversized", str(big)), ("not_json", str(bad)), ("missing_interpreter", str(missing_python)))}
    container = tmp / "container.json"
    container.write_text(json.dumps(ctx.container_document()), encoding="utf-8")
    parsed = api.load_profile({"HARNESS_EVIDENCE_PROFILE": str(container)}, plc)
    out["container_profile"] = {"image": parsed["execution"]["image"], "interpreter": parsed["contexts"]["backend"]["interpreter"],
                                "schema": parsed["schema"], "requires_container": api.requires_container(parsed)}
    return out


# ---- k2 -------------------------------------------------------------------------------------------------------------------
def k2_resolution(ctx):
    api, out = ctx.api, {}
    tmp = ctx.fresh("resolution")
    root = workspace(tmp)
    profile = ctx.parsed()
    saved = {name: os.environ.get(name) for name in ("PYTHONPATH", "ZEUS_SECRET")}
    os.environ["PYTHONPATH"] = str(tmp / "parent-path")
    os.environ["ZEUS_SECRET"] = "never-inherited"
    try:
        resolved = api.resolve_profile(profile, root)
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    context = resolved["contexts"]["backend"]
    out["resolved"] = {
        "keys": sorted(resolved), "workspace": ctx.show(resolved["workspace"]), "profile_digest_matches": resolved["profile_digest"] == profile["profile_digest"],
        "context_keys": sorted(context), "cwd": ctx.show(context["cwd"]), "interpreter_is_host_path": context["interpreter"] == PY,
        "interpreter_sha256_len": len(context["interpreter_sha256"]), "source_paths": ctx.show(context["source_paths"]),
        "dependency_files": context["dependency_files"],
        "environment": {"PYTHONPATH": ctx.show(context["environment"].get("PYTHONPATH")),
                        "PYTHONDONTWRITEBYTECODE": context["environment"].get("PYTHONDONTWRITEBYTECODE"),
                        "ZEUS_SECRET": "ZEUS_SECRET" in context["environment"], "PYTHONIOENCODING": context["environment"].get("PYTHONIOENCODING")},
        "environment_digest_len": len(context["environment_digest"]), "digest_len": len(resolved["digest"])}
    base = {"PATH": "/p", "HOME": "/h", "OTHER": "x", "PYTHONPATH": "/leak"}
    out["base_environment"] = api.resolve_profile(profile, root, base)["contexts"]["backend"]["environment"] | {"PYTHONPATH": "<src>"}
    no_sources = ctx.parsed(ctx.document(source_paths=[]))
    out["no_source_paths"] = ctx.show(api.resolve_profile(no_sources, root, base)["contexts"]["backend"]["environment"])

    # every refusal happens before any child
    cases = {"cwd_missing": ctx.document(cwd="backend/absent"), "source_missing": ctx.document(source_paths=["backend/absent"]),
             "dependency_missing": ctx.document(dependency_files=["backend/absent.lock"]),
             "cwd_is_file": ctx.document(cwd="backend/requirements.lock"),
             "dependency_is_directory": ctx.document(dependency_files=["backend/src"]),
             "interpreter_missing": ctx.document(interpreter=str(tmp / "no-python.exe"))}
    out["refusals"] = {name: ctx.show(expect(lambda doc=doc: api.resolve_profile(ctx.parsed(doc), root))) for name, doc in cases.items()}
    out["workspace_missing"] = ctx.show(expect(lambda: api.resolve_profile(profile, tmp / "no-such-workspace")))
    big = workspace(tmp, "big")
    with open(big / "backend" / "requirements.lock", "r+b") as handle:
        handle.truncate(api.MAX_DEPENDENCY_BYTES + 1)
    out["oversized_dependency"] = ctx.show(expect(lambda: api.resolve_profile(profile, big)))
    outside = tmp / "outside"
    outside.mkdir()
    escaped = workspace(tmp, "escaped")
    os.symlink(outside, escaped / "backend" / "linked", target_is_directory=True)
    out["symlink_escape"] = {"source": ctx.show(expect(lambda: api.resolve_profile(ctx.parsed(ctx.document(source_paths=["backend/linked"])), escaped))),
                             "cwd": ctx.show(expect(lambda: api.resolve_profile(ctx.parsed(ctx.document(cwd="backend/linked")), escaped)))}
    interpreter = tmp / "interpreter.bin"
    interpreter.write_bytes(b"one")
    pinned = ctx.parsed(ctx.document(interpreter=str(interpreter)))
    before = api.resolve_profile(pinned, root)
    interpreter.write_bytes(b"two")
    after = api.resolve_profile(pinned, root)
    out["interpreter_bytes_in_identity"] = {"digest_changes": before["digest"] != after["digest"],
                                            "sha_changes": before["contexts"]["backend"]["interpreter_sha256"] != after["contexts"]["backend"]["interpreter_sha256"]}

    # what a worker or reviewer is told, rebound to each checkout
    implementation, review = workspace(tmp, "implementation"), workspace(tmp, "review")
    told = api.execution_instructions(profile, review)
    out["instructions"] = {"keys": sorted(told), "schema": told["schema"], "contexts": ctx.show(told["contexts"]), "commands": ctx.show(told["commands"]),
                           "checks_equal": told["checks"] == profile["checks"], "profile_digest_matches": told["profile_digest"] == profile["profile_digest"],
                           "instruction": told["instruction"],
                           "no_other_checkout": str(implementation.resolve()) not in json.dumps(told),
                           "rebound": api.execution_instructions(profile, implementation)["contexts"] != told["contexts"]}
    delivery = api.worker_delivery(profile, implementation)
    out["worker_delivery"] = ctx.show({**delivery, "profile_digest": "<profile digest>"})
    out["worker_delivery_shape"] = {"keys": sorted(delivery), "workspace": ctx.show(delivery["workspace"]),
                                    "rules_wildcard_free": all(rule.startswith("Bash(") and "*" not in rule for rule in delivery["permissions_allow"]),
                                    "parts_removed": all("parts" not in entry for entry in delivery["commands"])}
    two = ctx.parsed(ctx.document([check("probe", PROBE), check("second", FAILING, 1)]))
    out["worker_delivery_two_checks"] = ctx.show(api.worker_delivery(two, implementation), "profile_digest")
    out["resolved_argument"] = {"same": api.worker_delivery(profile, implementation, resolved=api.resolve_profile(profile, implementation)) == delivery}
    out["shell_command"] = {
        "quoted": ctx.show(api.shell_command({"cwd": "/tmp/a b", "interpreter": "/usr/bin/python3", "environment": {"PYTHONPATH": "/x y"}},
                                             ["python", "-m", "pytest", "-q", "it's"])),
        "no_pythonpath": api.shell_command({"cwd": "/c", "interpreter": "/py", "environment": {}}, ["python", "-m", "ruff", "check", "."]),
        "not_enforceable": ctx.show(expect(lambda: api.shell_command({"cwd": "/c", "interpreter": "/py", "environment": {}}, ["uv", "run", "pytest"]))),
        "control_character": ctx.show(expect(lambda: api.shell_command({"cwd": "/c\n", "interpreter": "/py", "environment": {}},
                                                                         ["python", "-m", "pytest"])))}
    return out


# ---- k3 -------------------------------------------------------------------------------------------------------------------
def k3_container(ctx):
    api, out = ctx.api, {}
    tmp = ctx.fresh("container")
    root = backend_tree(tmp / "candidate")
    isolation = ctx.isolation()
    profile = api.parse_profile(container_profile_document(ctx), api.packaged_policy())
    v1 = api.parse_profile(ctx.document(interpreter=PY), api.packaged_policy())
    out["constants"] = {"container_interpreter_equals_trusted": api.CONTAINER_INTERPRETER == api.TRUSTED_PYTHON, "trusted": api.TRUSTED_PYTHON,
                        "workspace": api.WORKSPACE, "mode": api.MODE, "image_pattern": api.IMAGE.pattern,
                        "note": api.CONTAINER_NOTE}
    out["binding"] = {
        "ok": ctx.show(api.container_binding(profile, isolation)),
        "version_one": ctx.show(expect(lambda: api.container_binding(v1, isolation))),
        "no_isolation": ctx.show(expect(lambda: api.container_binding(profile, None))),
        "not_a_dict": ctx.show(expect(lambda: api.container_binding(profile, "docker"))),
        "other_mode": ctx.show(expect(lambda: api.container_binding(profile, {**isolation, "mode": "host"}))),
        "image_not_text": ctx.show(expect(lambda: api.container_binding(profile, {**isolation, "image": 7}))),
        "image_not_pinned": ctx.show(expect(lambda: api.container_binding(profile, {**isolation, "image": "latest"}))),
        "image_with_suffix": ctx.show(expect(lambda: api.container_binding(profile, {**isolation, "image": IMAGE + "\n"}))),
        "other_image": ctx.show(expect(lambda: api.container_binding(profile, {**isolation, "image": OTHER_IMAGE}))),
        "limits_copied": api.container_binding(profile, isolation)["limits"] is not isolation["limits"]}
    resolved = api.resolve_container_profile(profile, root, isolation)
    context = resolved["contexts"]["backend"]
    out["resolved"] = {"keys": sorted(resolved), "workspace": ctx.show(resolved["workspace"]), "execution": ctx.show(resolved["execution"]),
                       "context_keys": sorted(context), "context": ctx.show({k: v for k, v in context.items() if k != "workspace"}),
                       "context_workspace": ctx.show(context["workspace"]), "digest_len": len(resolved["digest"])}
    root_context = api.parse_profile(container_profile_document(ctx, cwd="."), api.packaged_policy())
    out["root_context"] = ctx.show({k: v for k, v in api.resolve_container_profile(root_context, root, isolation)["contexts"]["backend"].items()
                                    if k != "workspace"})
    out["resolve_refusals"] = {
        "version_one": ctx.show(expect(lambda: api.resolve_container_profile(v1, root, isolation))),
        "other_image": ctx.show(expect(lambda: api.resolve_container_profile(profile, root, {**isolation, "image": OTHER_IMAGE}))),
        "no_isolation": ctx.show(expect(lambda: api.resolve_container_profile(profile, root, None))),
        "workspace_missing": ctx.show(expect(lambda: api.resolve_container_profile(profile, tmp / "absent", isolation)))}
    empty = tmp / "empty"
    empty.mkdir()
    partial = backend_tree(tmp / "partial")
    (partial / "backend" / "requirements.lock").unlink()
    no_source = backend_tree(tmp / "no-source")
    (no_source / "backend" / "src" / "mod.py").unlink()
    (no_source / "backend" / "src").rmdir()
    escaped = backend_tree(tmp / "escaped")
    (escaped / "backend" / "src" / "mod.py").unlink()
    (escaped / "backend" / "src").rmdir()
    outside = tmp / "outside"
    outside.mkdir()
    os.symlink(outside, escaped / "backend" / "src", target_is_directory=True)
    out["tree_refusals"] = {name: {call.__name__: ctx.show(expect(lambda call=call, path=path: call(profile, str(path), isolation)))
                                   for call in (api.container_worker_delivery, api.container_execution_instructions)}
                            for name, path in (("empty", empty), ("dependency_missing", partial), ("source_missing", no_source),
                                               ("symlink_escape", escaped))}

    delivery = api.container_worker_delivery(profile, str(root), isolation)
    out["delivery"] = ctx.show({**delivery, "project_digest": "<project digest>"}, "project_digest")
    out["delivery_shape"] = {
        "keys": sorted(delivery), "workspace": delivery["workspace"], "host_workspace": ctx.show(delivery["host_workspace"]),
        "execution": ctx.show(delivery["execution"]), "wildcard_free": all(r.startswith("Bash(") and "*" not in r for r in delivery["permissions_allow"]),
        "heading_inside_container": "## Host project checks (this run, inside this container)" in delivery["document"],
        "no_host_path": str(root.resolve()) not in json.dumps([delivery["commands"], delivery["permissions_allow"], delivery["document"]]),
        "cd_part_allowed": "Bash(cd /workspace/backend)" in delivery["permissions_allow"]}
    told = api.container_execution_instructions(profile, str(root), isolation)
    other = backend_tree(tmp / "other")
    out["instructions"] = {
        "keys": sorted(told), "schema": told["schema"], "execution": ctx.show(told["execution"]), "workspace": told["workspace"],
        "host_workspace": ctx.show(told["host_workspace"]), "contexts": ctx.show(told["contexts"]), "commands": ctx.show(told["commands"]),
        "checks_equal": told["checks"] == profile["checks"], "instruction": told["instruction"],
        "project_digest_follows_tree": told["project_digest"] != api.container_execution_instructions(profile, str(other), isolation)["project_digest"],
        "project_digest_is_resolved_digest": told["project_digest"] == resolved["digest"]}
    out["refusals"] = {
        "other_image": {call.__name__: ctx.show(expect(lambda call=call: call(profile, str(root), {**isolation, "image": OTHER_IMAGE})))
                        for call in (api.container_worker_delivery, api.container_execution_instructions)},
        "version_one": {call.__name__: ctx.show(expect(lambda call=call: call(v1, str(root), isolation)))
                        for call in (api.container_worker_delivery, api.container_execution_instructions)},
        "no_isolation": {call.__name__: ctx.show(expect(lambda call=call: call(profile, str(root), None)))
                         for call in (api.container_worker_delivery, api.container_execution_instructions)}}
    return out


def backend_tree(root: Path) -> Path:
    (root / "backend" / "src").mkdir(parents=True)
    (root / "backend" / "probes").mkdir()
    (root / "backend" / "requirements.lock").write_bytes(b"example==1.0\n")
    (root / "backend" / "src" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    return root


def container_profile_document(ctx, **context):
    api = ctx.api
    return {"schema": api.SCHEMA_V2,
            "contexts": {"backend": {"cwd": "backend", "interpreter": api.CONTAINER_INTERPRETER, "source_paths": ["backend/src"],
                                     "dependency_files": ["backend/requirements.lock"], **context}},
            "checks": [{"id": "unit", "context": "backend", "argv": UNIT, "expected_exit": 0},
                       {"id": "lint", "context": "backend", "argv": LINT, "expected_exit": 0}],
            "execution": {"kind": "container", "image": IMAGE}}


# ---- k4 -------------------------------------------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def host_env(**values):
    """The parent's environment as M7's test sets it for the first replay."""
    saved = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    return saved


def restore_env(saved):
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def brief(ctx, finding):
    return ctx.show({k: v for k, v in finding.items() if k not in ("runs", "claim")}, "profile_digest")


def k4_host_route(ctx):
    api, out = ctx.api, {}

    tmp = ctx.fresh("replay")
    root = workspace(tmp)
    saved = host_env(PYTHONPATH=str(tmp / "parent-path"), ZEUS_SECRET="never-inherited")
    try:
        store, inspections = ctx.ledger(tmp)
        row = inspections.inspect(TASK, CANDIDATE, [executed("probe")], str(root))
    finally:
        restore_env(saved)
    finding = row["findings"][0]
    project = row["inspector"]["project"]
    with store.transaction() as tx:
        stored = tx.get(api.BUCKET, row["id"])["verdict"]
    out["required_check"] = {
        "verdict": row["verdict"], "finding": brief(ctx, finding), "runs": ctx.show([{k: v for k, v in run.items() if k not in ("cleanup",)}
                                                                                    for run in finding["runs"]]),
        "replay_argv_head_is_host": finding["replay_argv"][0] == PY, "replay_argv_tail": finding["replay_argv"][1:],
        "contexts": ctx.show(project["contexts"]), "project_digest_in_context": row["context"]["project_digest"] == project["digest"],
        "no_pycache": not list(root.rglob("__pycache__")), "stored": stored, "denominator": row["denominator"], "binding_keys": sorted(row["binding"])}

    tmp = ctx.fresh("failure")
    root = workspace(tmp)
    doc = ctx.document([check("must-pass", FAILING, 0), check("negative", FAILING, 1), check("probe", PROBE)])
    _, inspections = ctx.ledger(tmp, doc)
    row = inspections.inspect(TASK, CANDIDATE, [executed("must-pass", 1), executed("negative", 1), executed("probe", 1)], str(root))
    states = {f["check_id"]: f for f in row["findings"]}
    out["failure_kept"] = {"verdict": row["verdict"], "states": {name: brief(ctx, f) for name, f in states.items()}}

    tmp = ctx.fresh("exit-five")
    root = workspace(tmp)
    argv = ["python", "-m", "pytest", "empty_tests", "-q", "-p", "no:cacheprovider"]
    doc = ctx.document([{"id": "unit", "context": "backend", "argv": argv, "expected_exit": 0}])
    row = ctx.ledger(tmp, doc)[1].inspect(TASK, CANDIDATE, [executed("unit", 0)], str(root))
    out["exit_five"] = {"verdict": row["verdict"], "finding": brief(ctx, row["findings"][0])}

    tmp = ctx.fresh("no-spawn")
    root = workspace(tmp)
    doc = ctx.document([check("probe", PROBE), check("second", PROBE)])
    spawned = []
    insp = ctx.inspector(tmp, doc)
    ledger = api.EvidenceInspections(api.MemoryStore(), insp)
    with api.injected_capture(insp, lambda *a, **k: spawned.append(a) or {}):
        row = ledger.inspect(TASK, CANDIDATE, [{"check_id": "probe", "status": "not_run", "exit_code": None}], str(root))
        empty = ledger.inspect(TASK, CANDIDATE, [], str(root))
        claims, refusals = api.observed_checks(insp.profile, [
            executed("probe"), executed("probe"), executed("invented"), "python -m pytest",
            {"check_id": "second", "status": "executed", "exit_code": None},
            {"check_id": "probe", "status": "executed", "exit_code": 0, "argv": ["rm", "-rf", "/"]}])
    out["never_spawned"] = {"verdict": row["verdict"], "spawned": len(spawned), "states": [f["state"] for f in row["findings"]],
                            "causes": [f["cause"] for f in row["findings"]], "empty_verdict": empty["verdict"],
                            "empty_claims": empty["denominator"]["claims"], "claim_statuses": [c["status"] for c in claims],
                            "refusals": len(refusals), "claims_argv_are_the_profile": all(c["argv"] == argv_for(PROBE) for c in claims)}
    tmp = ctx.fresh("refusal-findings")
    root = workspace(tmp)
    row = ctx.ledger(tmp)[1].inspect(TASK, CANDIDATE, [executed("probe"), executed("invented")], str(root))
    out["refusals_are_findings"] = {"verdict": row["verdict"], "states": [f["state"] for f in row["findings"]]}

    # R1: the profile's own version-1 boundary, then defense in depth
    out["r1_profile_boundary"] = {}
    for argv in (["uv", "run", "python", "-m", "pytest", "-q"], ["ruff", "check", "."], ["python", "-m", PROBE], ["python", "-m", "ruff"],
                 ["python", "-mpytest"], ["python3", "-m", "pytest"]):
        out["r1_profile_boundary"][" ".join(argv)] = ctx.show(expect(
            lambda argv=argv: ctx.parsed(ctx.document([{"id": "a", "context": "backend", "argv": argv, "expected_exit": 0}]))))
    packaged = {}
    for accepted in (["python", "-m", "pytest", "-q"], ["python", "-m", "ruff", "check", "."]):
        parsed = api.parse_profile(ctx.document([{"id": "a", "context": "backend", "argv": accepted, "expected_exit": 0}]), api.packaged_policy())
        packaged[" ".join(accepted)] = parsed["checks"][0]["argv"] == accepted
    out["r1_packaged_accepts"] = packaged
    out["r1_legacy_form_authorized"] = api.authorized(["uv", "run", "python", "-m", "pytest", "-q"], api.packaged_policy())
    tmp = ctx.fresh("r1-bypass")
    root = workspace(tmp)
    spawned = []
    insp = ctx.inspector(tmp)
    insp.profile = {**insp.profile, "checks": [{**insp.profile["checks"][0], "argv": ["uv", "run", "python", "-m", "pytest"]}]}
    with api.injected_capture(insp, lambda *a, **k: spawned.append(a) or {}):
        found = insp.inspect([executed("probe")], str(root), {})
    out["r1_bypass"] = {"state": found["findings"][0]["state"], "spawned": len(spawned)}

    # R2: each repeat gets only what the absolute deadline still holds
    def timed(durations, total=1):
        tmp = ctx.fresh("deadline")
        root = workspace(tmp)
        insp = api.ProjectEvidenceInspector(api.FileArtifacts(str(tmp / "artifacts")), ctx.parsed(), policy(total_seconds=total, per_command_seconds=total))
        clock, given, pending = Clock(), [], list(durations)
        insp.clock = clock

        def capture(argv, cwd, timeout, max_bytes, env, progress=None, process_tree=None):  # E-4d: the host route passes its port
            given.append(timeout)
            clock.now += pending.pop(0)
            return {"failure": None, "terminated": False, "returncode": 0, "duration_seconds": 0.0}
        with api.injected_capture(insp, capture):
            found = insp.inspect([executed("probe")], str(root), {})["findings"][0]
        return {"given": given, "finding": brief(ctx, found)}
    out["r2_remainder"] = timed([0.75, 0.75])
    out["r2_no_repeat_beyond"] = timed([1.0, 0.1])
    out["r2_timely"] = timed([0.25, 0.25])

    tmp = ctx.fresh("slow")
    root = workspace(tmp)
    insp = api.ProjectEvidenceInspector(api.FileArtifacts(str(tmp / "artifacts")), ctx.parsed(ctx.document([check("probe", "slow")])),
                                        policy(total_seconds=5, per_command_seconds=5))
    found = insp.inspect([executed("probe")], str(root), {})["findings"][0]
    out["r2_real_second_replay"] = {"not_checked": found["state"] != "checked", "attempts_at_most_two": len(found["timeouts_seconds"]) <= 2,
                                    "first_timeout_near_budget": abs(found["timeouts_seconds"][0] - 5) <= 0.2,
                                    "second_shrunk": len(found["timeouts_seconds"]) < 2 or (found["timeouts_seconds"][1] < 2.1
                                                                                            and found["runs"][1]["terminated"] is True)}

    tmp = ctx.fresh("before-spawn")
    root = workspace(tmp)
    spawned = []
    refusals = {}
    for name, doc in (("source", ctx.document(source_paths=["backend/absent"])), ("dependency", ctx.document(dependency_files=["backend/absent.lock"])),
                      ("cwd", ctx.document(cwd="backend/absent")), ("interpreter", ctx.document(interpreter=str(tmp / "no-python.exe")))):
        insp = ctx.inspector(tmp, doc)
        with api.injected_capture(insp, lambda *a, **k: spawned.append(a) or {}):
            refusals[name] = ctx.show(expect(lambda insp=insp: api.EvidenceInspections(api.MemoryStore(), insp).inspect(
                TASK, CANDIDATE, [executed("probe")], str(root))))
    out["refuse_before_spawn"] = {"refusals": refusals, "spawned": len(spawned)}

    # identity: dependency bytes, profile, environment
    tmp = ctx.fresh("identity")
    root = workspace(tmp)
    store = api.MemoryStore()

    def run(doc=None):
        return api.EvidenceInspections(store, ctx.inspector(tmp, doc)).inspect(TASK, CANDIDATE, [executed("probe")], str(root))
    first, again = run(), run()
    (root / "backend" / "requirements.lock").write_text("example==2.0\n", encoding="utf-8")
    locked = run()
    changed = run(ctx.document([check("probe", PROBE), check("extra", PROBE)]))
    saved = host_env(LANG="zeus-changed-value")
    try:
        moved = run()
    finally:
        restore_env(saved)
    out["identity"] = {"same_read_back": again["id"] == first["id"], "dependency_is_new": locked["id"] != first["id"],
                       "profile_is_new": changed["id"] not in (first["id"], locked["id"]), "profile_verdict": changed["verdict"],
                       "environment_is_new": moved["id"] not in (first["id"], locked["id"])}

    tmp = ctx.fresh("snapshot")
    root = workspace(tmp)
    insp = ctx.inspector(tmp)
    taken = insp.snapshot(root)

    class Changing(api.ProjectEvidenceInspector):
        def snapshot(self, cwd=None):
            return taken

        def inspect(self, *args, **kwargs):
            # the host environment moves between the keyed snapshot and the replay
            os.environ["PYTHONPATH"] = str(tmp / "late-parent-path")
            os.environ["ZEUS_SECRET"] = "late"
            return super().inspect(*args, **kwargs)
    saved = host_env()
    try:
        changing = Changing(api.FileArtifacts(str(tmp / "artifacts")), insp.profile, policy())
        row = api.EvidenceInspections(api.MemoryStore(), changing).inspect(TASK, CANDIDATE, [executed("probe")], str(root))
    finally:
        os.environ.pop("PYTHONPATH", None)
        os.environ.pop("ZEUS_SECRET", None)
        restore_env(saved)
    out["replay_under_snapshot"] = {"verdict": row["verdict"], "digest_matches": row["context"]["project_digest"] == taken["project"]["digest"]}
    out["snapshot"] = {"keys": sorted(taken), "identity_keys": sorted(taken["identity"]), "project_keys": sorted(taken["project"]),
                       "identity_project_keys": sorted(taken["identity"]["project"]),
                       "identity_project_contexts": ctx.show(taken["identity"]["project"]["contexts"]),
                       "needs_cwd": ctx.show(expect(lambda: insp.snapshot())), "clock_is_monotonic": insp.clock.__name__}

    class Dropping(api.ProjectEvidenceInspector):
        def snapshot(self, cwd=None):
            got = super().snapshot(cwd)
            return {**got, "project": {**got["project"], "digest": "f" * 64}}
    dropping = Dropping(api.FileArtifacts(str(tmp / "artifacts")), ctx.parsed(), policy())
    out["project_snapshot_not_named"] = ctx.show(expect(lambda: api.EvidenceInspections(api.MemoryStore(), dropping).inspect(
        TASK, CANDIDATE, [executed("probe")], str(root))))
    out["constructor"] = ctx.show(expect(lambda: api.ProjectEvidenceInspector(api.FileArtifacts(str(tmp / "artifacts")), {"profile_digest": 1}, policy())))

    schema = api.worker_schema(ctx.parsed())
    second = api.worker_schema(ctx.parsed(ctx.document([check("other", PROBE)])))
    item = schema["properties"]["tests"]["items"]
    out["worker_schema"] = {"properties": sorted(schema["properties"]), "check_enum": item["properties"]["check_id"]["enum"],
                            "closed": item["additionalProperties"] is False, "status_enum": item["properties"]["status"]["enum"],
                            "second_enum": second["properties"]["tests"]["items"]["properties"]["check_id"]["enum"]}

    tmp = ctx.fresh("legacy")
    root = workspace(tmp)
    legacy = api.EvidenceInspector(api.FileArtifacts(str(tmp / "artifacts")), policy())
    snapshot = legacy.snapshot(root)
    row = api.EvidenceInspections(api.MemoryStore(), legacy).inspect(TASK, CANDIDATE, [], str(root))
    out["legacy_without_profile"] = {"project_in_snapshot": "project" in snapshot, "project_in_identity": "project" in snapshot["identity"],
                                     "verdict": row["verdict"], "project_digest_in_context": "project_digest" in row["context"]}
    return out


def run(api, root: Path) -> dict:
    ctx = Ctx(api, root.resolve())
    return {"k1_loading": k1_loading(ctx), "k2_resolution": k2_resolution(ctx), "k3_container": k3_container(ctx), "k4_host_route": k4_host_route(ctx)}
