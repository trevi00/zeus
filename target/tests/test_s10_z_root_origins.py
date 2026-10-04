"""S10 unit Z: the per-root fresh-process R-O audit and the production-profile transport audit
(DESIGN-s10 §4 A2/A3/A6, §17d disclosure 26; PREP-S11 §3 AR3 "Missing" and §6.2 #6).

`conftest.py` audits the UNION of everything the tests import in one process. Here every root is imported in its
OWN fresh subprocess (R-P child environment; `provider_guard.install()` then `origin.install_import_audit` before
any import of ours) and the subprocess ends with `origin.assert_tree_origins`, so each root's own closure is audited.

Root list (measured at collection, not hard-coded): every subcommand of `entry.cli.parser()` (53 at int41; the module
is `entry.cli.<root with - -> _>` and its composition modules are the `composition` imports found in its source),
every module under `entry/processes/`, every `import_rules.SHIMS` entry, `zeus` (and `zeus.__main__`, run with
`--version`), and `composition` (`codex_harness.composition`; `build` is a function there, not a module).

Built, not only imported: the `composition` root and `execute-one` (the executor builder with a MemoryStore handle and
the development profile, as `test_s10_c5c2_profile.py`). Every other root is import-audited only: their builders open
PostgreSQL/Redis, a Docker/host service or a checkout, which this unit may not touch (those are audited by the `.pg`
families' target drivers at TI/CI).

Production profile (§17d disclosure 26): `composition.operation` imports the provider adapters and `host_os` helpers
at module top, so those modules ARE in `sys.modules` in production. The audit therefore asserts what matters: the
composed transport factories are `_host_transport_refused` (identity), no AppServer / ClaudeCodeRuntime / codex-exec
transport instance exists, and no `host_os.adapters.windows.*` module other than `no_console` is loaded. The imported
module names are printed as evidence; the reasons (shared isolated-path helpers, the pure W-B `no_console` flag
helper, the inert `CLAUDE_HOST` holder) are §17d's reason table. The development control shows the real factories.
The R-O negative control: a rogue `codex_harness/rogue.py` ahead of the target must raise `OriginError`
(in-process twin: `test_compare_harness.py::test_import_audit_refuses_a_codex_harness_origin_outside_the_target`).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import import_rules
import provider_guard

from codex_harness.entry import cli as entry_cli

TARGET = Path(__file__).resolve().parents[1]
ROOT = TARGET.parent
SRC = TARGET / "src"
PKG = SRC / "codex_harness"
BUILT = {"composition", "execute-one"}

PREAMBLE = textwrap.dedent("""
    import importlib, json, re, sys
    from pathlib import Path
    SRC = Path({src!r})
    sys.path[:0] = [{harness!r}, {guard!r}, str(SRC)]
    import provider_guard, origin
    provider_guard.install()
    origin.install_import_audit(SRC)
""")


def _preamble() -> str:
    return PREAMBLE.format(src=str(SRC), harness=str(ROOT / "compare" / "harness"),
                           guard=str(ROOT / "compare" / "guard"))


def _parser_roots() -> list[str]:
    action = next(a for a in entry_cli.parser()._actions if getattr(a, "choices", None))
    return sorted(action.choices)


def _composition_modules(module: str) -> list[str]:
    text = (SRC / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8")
    found = re.findall(r"from codex_harness\.composition import ([\w, ]+)", text)
    names = [n.strip() for group in found for n in group.split(",")]
    names += re.findall(r"from codex_harness\.composition\.(\w+) import", text)
    return sorted({"codex_harness.composition." + n for n in names if (PKG / "composition" / f"{n}.py").is_file()})


def _process_modules() -> list[str]:
    return sorted("codex_harness.entry.processes." + p.stem
                  for p in (PKG / "entry" / "processes").glob("*.py") if p.stem != "__init__")


def _cases() -> list[tuple[str, list[str], bool]]:
    cases = []
    for root in _parser_roots():
        module = "codex_harness.entry.cli." + root.replace("-", "_")
        cases.append((f"cli:{root}", [module, *_composition_modules(module)], root in BUILT))
    cases += [(f"process:{m.rsplit('.', 1)[1]}", [m], False) for m in _process_modules()]
    cases += [(f"shim:{m}", [m], False) for m in sorted(import_rules.SHIMS)]
    cases += [("zeus", ["zeus"], False), ("zeus.__main__", ["zeus.__main__"], False),
              ("composition", ["codex_harness.composition"], True)]
    return cases


CASES = _cases()
ROOT_SCRIPT = textwrap.dedent("""
    modules, build = json.loads(sys.argv[1]), json.loads(sys.argv[2])
    sys.argv = ["zeus", "--version"]
    for name in modules:
        try:
            importlib.import_module(name)
        except SystemExit:
            pass
    if build:
        from types import SimpleNamespace
        from codex_harness import composition
        from codex_harness.composition import configuration, operation
        from codex_harness.routing.adapters.organization_source import packaged_organization
        from codex_harness.storage.adapters.memory_store import MemoryStore
        import tempfile
        runtime = tempfile.mkdtemp(prefix="zroot")
        configuration.settings = lambda: {{"HARNESS_RUNTIME_DIR": runtime, "ZEUS_COMPOSITION_PROFILE": "development"}}
        handle = composition.ServiceHandle(MemoryStore(), packaged_organization())
        composition.build = lambda: handle
        executor = operation.build_executor(knowledge=False, evidence_profile=None)
        assert executor.run_task.transports.host_app_server is operation._host_app_server
    audited = origin.assert_tree_origins(SRC)
    print(json.dumps({{"count": len(audited), "has_root": modules[0] in audited}}))
""")


def _run(code: str, tmp: Path, *args: str, extra: dict | None = None):
    env = provider_guard.child_environment(tmp, extra=extra)
    return subprocess.run([sys.executable, "-c", _preamble() + code, *args], cwd=TARGET, env=env,
                          capture_output=True, text=True, timeout=300)


def _root_case(case, base: Path):
    name, modules, build = case
    tmp = base / re.sub(r"\W", "_", name)
    tmp.mkdir()
    return name, _run(ROOT_SCRIPT.replace("{{", "{").replace("}}", "}"), tmp,
                      json.dumps(modules), json.dumps(build))


def test_the_root_list_is_measured_and_complete():
    names = [c[0] for c in CASES]
    assert len(_parser_roots()) == 53 and {"research-package", "dlq"} <= set(_parser_roots())
    assert len(_process_modules()) == 13
    assert len([n for n in names if n.startswith("shim:")]) == len(import_rules.SHIMS)
    assert {"zeus", "composition"} <= set(names) and len(names) == len(set(names))


def test_every_root_imports_in_its_own_fresh_process_under_the_origin_audit(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda c: _root_case(c, tmp_path), CASES))
    failures = {}
    for (name, modules, _), (_, done) in zip(CASES, results):
        if done.returncode != 0:
            failures[name] = done.stderr.strip().splitlines()[-1:] or done.stdout[-200:]
            continue
        report = json.loads(done.stdout.strip().splitlines()[-1])
        if report["count"] <= 0:
            failures[name] = "no audited modules"
        elif modules[0].startswith("codex_harness.") and not report["has_root"]:
            failures[name] = "root module not among the audited"
    assert not failures, failures


PRODUCTION_SCRIPT = textwrap.dedent("""
    import gc, tempfile
    from types import SimpleNamespace
    profile = sys.argv[1]
    from codex_harness import composition
    from codex_harness.composition import configuration, isolation, operation
    from codex_harness.execution.adapters.providers import claude_cli, codex_app_server, codex_exec
    from codex_harness.routing.adapters.organization_source import packaged_organization
    from codex_harness.storage.adapters.memory_store import MemoryStore
    image = "sha256:" + "a" * 64
    values = {"HARNESS_RUNTIME_DIR": tempfile.mkdtemp(prefix="zprod"), "ZEUS_COMPOSITION_PROFILE": profile}
    configuration.settings = lambda: values
    composition.build = lambda: composition.ServiceHandle(MemoryStore(), packaged_organization())
    if profile == "production":
        values.update({{"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": image}})
        stand_in = SimpleNamespace(config={{"image": image}}, root=Path(values["HARNESS_RUNTIME_DIR"]), docker=None,
                                   summary=lambda *a, **k: None, review_context=lambda *a, **k: None)
        isolation.isolated_worker = lambda config: stand_in
    executor = operation.build_executor(knowledge=False, evidence_profile=None)
    transports = executor.run_task.transports
    refused = (transports.host_app_server is operation._host_transport_refused
               and transports.claude_runtime is operation._host_transport_refused)
    real = (transports.host_app_server is operation._host_app_server
            and transports.claude_runtime is operation._host_claude_runtime)
    classes = tuple(c for mod in (claude_cli, codex_app_server, codex_exec) for c in vars(mod).values()
                    if isinstance(c, type) and c.__module__ == mod.__name__
                    and c.__name__ in ("AppServer", "ClaudeCodeRuntime", "CodexExec", "CodexExecRuntime"))
    instances = sorted({{type(o).__name__ for o in gc.get_objects() if type(o) in classes}})
    imported = sorted(m for m in sys.modules if m.startswith((
        "codex_harness.execution.adapters.providers.", "codex_harness.host_os.adapters.windows.")))
    origin.assert_tree_origins(SRC)
    print(json.dumps({{"refused": refused, "real": real, "instances": instances, "classes": len(classes),
                      "imported": imported}}))
""")


def _production(profile: str, tmp_path: Path) -> dict:
    done = _run(PRODUCTION_SCRIPT.replace("{{", "{").replace("}}", "}"), tmp_path, profile)
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_production_composes_refused_factories_and_no_transport_instance_or_windows_job_module(tmp_path):
    report = _production("production", tmp_path)
    assert report["refused"] and not report["real"] and report["instances"] == []
    assert report["classes"] >= 2
    windows = [m for m in report["imported"] if ".host_os.adapters.windows." in m]
    assert windows == ["codex_harness.host_os.adapters.windows.no_console"], windows
    assert any(m.endswith("providers.claude_cli") for m in report["imported"])  # §17d: imported, never built


def test_development_control_composes_the_real_factories(tmp_path):
    report = _production("development", tmp_path)
    assert report["real"] and not report["refused"]


def test_the_origin_audit_refuses_a_rogue_codex_harness_module_in_a_fresh_process(tmp_path):
    rogue = tmp_path / "rogue"
    (rogue / "codex_harness").mkdir(parents=True)
    (rogue / "codex_harness" / "__init__.py").write_text("", encoding="utf-8")
    (rogue / "codex_harness" / "rogue.py").write_text("VALUE = 1\n", encoding="utf-8")
    done = _run(textwrap.dedent("""
        sys.path.insert(0, {rogue!r})
        try:
            importlib.import_module("codex_harness.rogue")
        except origin.OriginError as exc:
            print("OriginError", str(exc)[:60])
            raise SystemExit(0)
        raise SystemExit(3)
    """).format(rogue=str(rogue)), tmp_path / "child")
    assert done.returncode == 0 and done.stdout.startswith("OriginError"), done.stderr[-400:]
