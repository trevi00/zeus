"""Shared S8 scenario steps (`review.sdd_adapter`): M7 `adapters/sdd.py` (`load_json`, `parse_json`, `read_spec`, `write_export`, `render_review`,
`device_probe`, `adb_inventory`, `replay_source`), characterized BEFORE the module moves into REVIEW (S8 batch B8, DESIGN-s8 §31/§32; R-sd1 injects
`root` and `run_process` into `read_spec`, R-sd2 injects `run_process` into `device_probe`).

Mirrors the adapter tests of M7 `tests/test_sdd.py` (`test_adb_diagnostics_are_not_transport_rows`, `test_bounded_json_duplicate_keys_and_export_integrity`,
`test_review_embedded_content_cannot_escape_json_script`, `test_replay_export_refuses_unknown_target_financial_flows_and_missing_bindings`,
`test_replay_attributes_every_assertion_to_its_oracle_and_requirements_at_runtime`, `test_replay_export_is_idempotent_and_never_overwrites_a_different_draft`)
and adds what they leave out: `read_spec` in git mode over a fixture repository (a pinned sha, a tag, `HEAD`, a missing path, an oversize blob, a bad
revision, a path outside the repository) and in working-tree-draft mode, and `device_probe` over a scripted fake `adb` (none, one device, the getprop values).
Not mirrored here: `test_offline_cli_review_runs_without_database_access` (the `zeus sdd` CLI, S10 entry) and the domain tests (`domain.sdd`, moved).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api` (`load_json`, `parse_json`, `read_spec`, `write_export`, `render_review`,
`device_probe`, `adb_inventory`, `replay_source`, `ContractError`). The repository root is the fixture repository both sides resolve from the working
directory (its `pyproject.toml` names `zeus-harness`); Git, `adb`, `aws` and `agent-device` are REAL processes: Git over a fixture repository with fixed
identities, and the three tools are LABELLED stand-in shell scripts on a scripted `PATH` (or under `ANDROID_HOME`, `ANDROID_SDK_ROOT` or `HOME`). Nothing
here is a device run. Paths are reported relative to the run root.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
from pathlib import Path

from s1_common import outcome, relative, sha
from s1_git import FIXED, git
from s8_sdd import spec


def safe(value):
    """JSON-safe form: NaN/Infinity become strings (the golden is strict JSON)."""
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return "float:" + repr(value)
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    return value


def write_script(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


def fake_adb(path: Path, log: Path, devices: str, rc: int, props: dict) -> Path:
    """A LABELLED `adb`: `devices -l` prints `devices` and exits `rc`; `-s S shell getprop P` answers props[(S, P)] (or fails); every call is logged."""
    lines = ["#!/bin/sh", 'printf \'%s\\n\' "$*" >> ' + shlex.quote(str(log)),
             'if [ "$1" = devices ]; then printf \'%s\' ' + shlex.quote(devices) + "; exit " + str(rc) + "; fi",
             'if [ "$1" = -s ] && [ "$3" = shell ] && [ "$4" = getprop ]; then', '  case "$2:$5" in']
    for (serial, prop), value in props.items():
        lines.append("    " + shlex.quote(serial + ":" + prop) + ") printf '%s\\n' " + shlex.quote(value) + "; exit 0;;")
    lines += ["  esac", "  exit 1", "fi", "exit 2", ""]
    return write_script(path, "\n".join(lines))


def stub(path: Path) -> Path:
    return write_script(path, "#!/bin/sh\nexit 0\n")


def getprops(serial: str, **values) -> dict:
    names = {"manufacturer": "ro.product.manufacturer", "model": "ro.product.model", "os_version": "ro.build.version.release",
             "one_ui_version": "ro.build.version.oneui", "qemu": "ro.kernel.qemu", "characteristics": "ro.build.characteristics"}
    return {(serial, names[key]): value for key, value in values.items()}


def with_env(**changes):
    """Context-free environment switch: returns the previous values for `restore`."""
    previous = {key: os.environ.get(key) for key in changes}
    for key, value in changes.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return previous


def restore(previous: dict) -> None:
    with_env(**previous)


def build_repository(root: Path) -> dict:
    """The fixture repository: pyproject (name zeus-harness), spec.json at two revisions, a tag, an oversize blob and a draft."""
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    (repo / "pyproject.toml").write_text('[project]\nname = "zeus-harness"\n', encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "spec.json").write_text(json.dumps(spec(title="First"), indent=1), encoding="utf-8")
    (repo / "big.json").write_text(json.dumps({"pad": "x" * (1024 * 1024 + 16)}), encoding="utf-8")
    (repo / "dup.json").write_text('{"id": 1, "id": 2}', encoding="utf-8")
    (repo / "bad.json").write_text(json.dumps(spec(schema="zeus.sdd.v9")), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "first")
    first = git(repo, "rev-parse", "HEAD")
    git(repo, "tag", "first-spec")
    (repo / "docs" / "spec.json").write_text(json.dumps(spec(title="Second"), indent=1), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "second")
    second = git(repo, "rev-parse", "HEAD")
    # the working tree is a third, uncommitted draft
    (repo / "docs" / "spec.json").write_text(json.dumps(spec(title="Draft"), indent=1), encoding="utf-8")
    (repo / "docs" / "empty.json").write_text("", encoding="utf-8")
    (repo / "docs" / "bom.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(spec(title="Bom")).encode("utf-8"))
    (repo / "docs" / "nan.json").write_text('{"value": NaN, "list": [Infinity, -Infinity]}', encoding="utf-8")
    (repo / "docs" / "dupkey.json").write_text('{"a": 1, "b": 2, "a": 3}', encoding="utf-8")
    (repo / "docs" / "latin.json").write_bytes(b'{"a": "\xe9"}')
    (repo / "docs" / "huge.json").write_bytes(b" " * (1024 * 1024 + 1))
    (repo / "docs" / "exact.json").write_bytes(b" " * (1024 * 1024 - 2) + b"{}")
    outside = root / "outside.json"
    outside.write_text(json.dumps(spec(title="Outside")), encoding="utf-8")
    return {"repo": repo.resolve(), "first": first, "second": second, "outside": outside.resolve()}


def run(api, root: Path) -> dict:
    os.environ.update(FIXED)
    for name in ("ZEUS_REPOSITORY", "HARNESS_REPOSITORY"):
        os.environ.pop(name, None)
    out: dict = {}
    fixture = build_repository(root)
    repo = fixture["repo"]
    roots = {"ROOT": str(root.resolve())}
    shown = lambda value: relative(safe(value), roots)  # noqa: E731
    call = lambda action: shown(outcome(action))  # noqa: E731
    previous_cwd = Path.cwd()
    os.chdir(repo)
    try:
        # load_json / parse_json (test_bounded_json_duplicate_keys_and_export_integrity)
        docs = repo / "docs"
        out["load_json"] = {name: call(lambda n=name: api.load_json(docs / n)) for name in
                            ("exact.json", "bom.json", "nan.json", "dupkey.json", "huge.json", "empty.json", "latin.json", "absent.json")}
        out["load_json"]["str_path"] = call(lambda: api.load_json(str(docs / "bom.json")))
        out["load_json"]["valid_title"] = call(lambda: api.load_json(docs / "spec.json")["title"])
        out["parse_json"] = {name: call(lambda b=body: api.parse_json(b)) for name, body in
                             {"ok": '{"a": [1, 2, {"b": null}]}', "dup": '{"a": 1, "a": 2}', "nested_dup": '{"a": {"b": 1, "b": 2}}',
                              "list_dup": '[{"k": 1, "k": 1}]', "nan": '[NaN]', "bad": "{", "scalar": "3"}.items()}

        # read_spec: working-tree draft (the working tree holds the third, uncommitted "Draft")
        out["read_spec_draft"] = {
            "absolute": call(lambda: api.read_spec(docs / "spec.json")),
            "relative": call(lambda: api.read_spec("docs/spec.json")),
            "str_empty_revision": call(lambda: api.read_spec(str(docs / "spec.json"), "")),
            "none_revision": call(lambda: api.read_spec(docs / "spec.json", None)),
            "outside_the_repository": call(lambda: api.read_spec(fixture["outside"])),
            "invalid_spec": call(lambda: api.read_spec(repo / "bad.json")),
            "duplicate_keys": call(lambda: api.read_spec(repo / "dup.json")),
            "oversize_file": call(lambda: api.read_spec(repo / "big.json")),
            "missing": call(lambda: api.read_spec(repo / "nowhere.json")),
        }

        # read_spec: git mode (a pinned sha, a tag, HEAD, abbreviated)
        title = lambda r: r["ok"][0]["title"] if "ok" in r else r  # noqa: E731
        git_cases = {}
        for label, revision in (("first_sha", fixture["first"]), ("second_sha", fixture["second"]), ("tag", "first-spec"), ("head", "HEAD"),
                                ("branch", "main"), ("abbreviated", fixture["first"][:10]), ("tag_peeled", "first-spec^{commit}")):
            result = call(lambda r=revision: api.read_spec(docs / "spec.json", r))
            git_cases[label] = {"title": title(result),
                                "provenance": result["ok"][1] if "ok" in result else None,
                                "outcome": None if "ok" in result else result}
        git_cases["relative_path"] = call(lambda: api.read_spec("docs/spec.json", "first-spec"))
        git_cases["missing_in_pinned_tree"] = call(lambda: api.read_spec(docs / "empty.json", fixture["first"]))
        git_cases["missing_path"] = call(lambda: api.read_spec(repo / "nowhere.json", "HEAD"))
        git_cases["unknown_revision"] = call(lambda: api.read_spec(docs / "spec.json", "no-such-revision"))
        git_cases["revision_is_a_tree"] = call(lambda: api.read_spec(docs / "spec.json", "HEAD^{tree}"))
        git_cases["revision_as_option"] = call(lambda: api.read_spec(docs / "spec.json", "--all"))
        git_cases["oversize_blob"] = call(lambda: api.read_spec(repo / "big.json", fixture["first"]))
        git_cases["invalid_spec_blob"] = call(lambda: api.read_spec(repo / "bad.json", fixture["first"]))
        git_cases["duplicate_keys_blob"] = call(lambda: api.read_spec(repo / "dup.json", fixture["first"]))
        git_cases["outside_the_repository"] = call(lambda: api.read_spec(fixture["outside"], "HEAD"))
        git_cases["pyproject_not_a_spec"] = call(lambda: api.read_spec(repo / "pyproject.toml", "HEAD"))
        out["read_spec_git"] = git_cases
        out["revisions_distinct"] = fixture["first"] != fixture["second"]

        # write_export / render_review (export integrity, embedded content, idempotent replay drafts)
        exports = root / "exports"
        review_path, replay_path = exports / "nested" / "review.html", exports / "draft.py.review"
        body = "검토"
        first = call(lambda: api.write_export(review_path, body))
        out["write_export"] = {
            "create": first,
            "again_equal": call(lambda: api.write_export(review_path, body)),
            "different_content": call(lambda: api.write_export(review_path, "변경")),
            "content_kept": review_path.read_text("utf-8"),
            "replay_create": call(lambda: api.write_export(replay_path, "print(1)\n", kind="replay")),
            "replay_again": call(lambda: api.write_export(replay_path, "print(1)\n", kind="replay")),
            "replay_different": call(lambda: api.write_export(replay_path, "print(1)\n# edited", kind="replay")),
            "replay_wrong_suffix": call(lambda: api.write_export(exports / "test_generated.py", "content", "replay")),
            "review_wrong_suffix": call(lambda: api.write_export(exports / "test_generated.py", "content", "review")),
            "replay_html_suffix": call(lambda: api.write_export(exports / "x.html", "content", "replay")),
            "review_py_review_suffix": call(lambda: api.write_export(exports / "x.py.review", "content")),
            "unknown_kind": call(lambda: api.write_export(exports / "x.html", "content", "other")),
            "relative_path": call(lambda: api.write_export("exports/rel.html", "<p>x</p>")),
            "empty_body": call(lambda: api.write_export(exports / "empty.html", "")),
            "test_generated_absent": not (exports / "test_generated.py").exists(),
            "directory_listing": sorted(str(p.relative_to(exports)) for p in exports.rglob("*") if p.is_file()),
        }
        out["write_export"]["parent_is_a_file"] = call(lambda: api.write_export(review_path / "inner.html", "x"))

        injected = spec(title='</script><script>alert("injected")</script> & <b>')
        page = api.render_review(injected)
        marker = '<script id="sdd-data" type="application/json">'
        data = page.split(marker)[1].split("</script>")[0] if marker in page else None
        out["render_review"] = {
            "page_sha": sha(page), "page_bytes": len(page.encode("utf-8")), "title_escaped": injected["title"] not in page,
            "angle_brackets_in_data": ("<" in (data or "")) or (">" in (data or "")), "ampersand_in_data": "&" in (data or ""),
            "data_title": json.loads(data)["spec"]["title"] if data else None,
            "data_report_keys": sorted(json.loads(data)["report"]) if data else None,
            "placeholder_left": "__ZEUS_SDD_DATA__" in page,
            "plain": sha(api.render_review(spec())),
            "with_report": sha(api.render_review(spec(), {"acceptance_passed": False, "stages": []})),
            "empty_report_is_default": api.render_review(spec(), {}) == api.render_review(spec()),
            "invalid_spec": call(lambda: api.render_review(spec(schema="zeus.sdd.v9"))),
            "not_a_dict": call(lambda: api.render_review([])),
        }

        # replay_source (the refusals in order, then the export and its runtime attribution)
        def ready(**over):
            document = spec()
            document["target"].update(kind="android", app_id="contract.test", build_hash="a" * 64)
            document["scenarios"][0]["bindings"] = [
                {"operation": "tap", "selector": {"strategy": "accessibility id", "value": "go"}, "value": None, "oracle_index": None,
                 "source_ref": "unverified-contract-input"},
                {"operation": "assert_text", "selector": {"strategy": "id", "value": "contract:id/label"}, "value": "the intent is shown",
                 "oracle_index": 0, "source_ref": "unverified-contract-input"}]
            document.update(over)
            return document

        replay = {}
        replay["unconfigured_target"] = call(lambda: api.replay_source(spec()))
        financial = ready()
        financial["requirements"][0]["risk"] = "financial"
        replay["financial"] = call(lambda: api.replay_source(financial))
        two = ready()
        two["scenarios"].append({**two["scenarios"][0], "id": "SCN.second"})
        replay["multi_scenario"] = call(lambda: api.replay_source(two))
        replay["no_active_scenario"] = call(lambda: api.replay_source(ready(scenarios=[{**spec()["scenarios"][0], "status": "retired"}])))
        unbound = ready()
        unbound["scenarios"][0]["bindings"] = []
        replay["no_bindings"] = call(lambda: api.replay_source(unbound))
        missing = ready()
        missing["scenarios"][0]["bindings"].pop()
        replay["missing_oracle_binding"] = call(lambda: api.replay_source(missing))
        inline = ready()
        inline["scenarios"][0]["bindings"].insert(0, {"operation": "input", "selector": {"strategy": "id", "value": "pw"}, "value": "hunter2",
                                                      "oracle_index": None, "source_ref": "unverified-contract-input"})
        replay["inline_credential"] = call(lambda: api.replay_source(inline))
        environment = ready()
        environment["scenarios"][0]["bindings"].insert(0, {"operation": "input", "selector": {"strategy": "id", "value": "pw"},
                                                           "value": "ZEUS_TEST_PASSWORD", "oracle_index": None, "source_ref": "unverified-contract-input"})
        replay["unknown_target_kind"] = call(lambda: api.replay_source(ready(target={"kind": "ios", "app_id": "x", "build_hash": "a" * 64, "alpha_url": None})))
        replay["no_app_id"] = call(lambda: api.replay_source(ready(target={"kind": "android", "app_id": None, "build_hash": "a" * 64, "alpha_url": None})))
        for label, document in (("tap_and_assert", ready()), ("with_env_input", environment)):
            source = api.replay_source(document)
            tree = ast.parse(source)
            replay[label] = {"sha": sha(source), "lines": source.count("\n"), "parses": isinstance(tree, ast.Module),
                             "subtests": source.count("self.subTest("), "has_oracles_table": "ORACLES = " in source,
                             "again_equal": source == api.replay_source(document), "head": source.splitlines()[:3]}
        quoted = ready()
        quoted["scenarios"][0]["then"] = ['it\'s "shown"\n# not code']
        quoted["scenarios"][0]["bindings"][1]["value"] = quoted["scenarios"][0]["then"][0]
        source = api.replay_source(quoted)
        replay["quoted_text"] = {"sha": sha(source), "parses": isinstance(ast.parse(source), ast.Module)}
        out["replay_source"] = replay

        # adb_inventory (test_adb_diagnostics_are_not_transport_rows)
        diagnostics = "* daemon not running; starting now at tcp:5037\n* daemon started successfully\nList of devices attached\n"
        out["adb_inventory"] = {
            "diagnostics": api.adb_inventory(diagnostics),
            "rows": api.adb_inventory(diagnostics + "emulator-5554 device product:sdk\nserial unauthorized\n"),
            "states": api.adb_inventory("a1 device\nb2 offline\nc3 unauthorized\nd4 authorizing\ne5 no permissions\nf6 recovery\ng7 device\n"),
            "tab_separated": api.adb_inventory("R58M1234ABC\tdevice usb:1-1 product:x\n"),
            "ip_serial": api.adb_inventory("192.168.0.5:5555 device\n"),
            "indented": api.adb_inventory("  abc device\n"), "empty": api.adb_inventory(""),
            "trailing_state_text": api.adb_inventory("abc devices\nabc device_x\n"),
        }

        # device_probe over a scripted PATH of stand-in tools
        probes = {}
        bins = root / "bins"
        homes = root / "homes"

        def probe(label, *, adb=None, aws=False, agent=False, android_home=None, sdk_root=None, home_adb=False, adb_args=None):
            bin_dir = bins / label
            bin_dir.mkdir(parents=True)
            home = homes / label
            home.mkdir(parents=True)
            log = root / ("adb-" + label + ".log")
            adb_dir = bin_dir
            if adb and adb.get("where") == "android_home":
                adb_dir = home / "android-home" / "platform-tools"
            elif adb and adb.get("where") == "sdk_root":
                adb_dir = home / "sdk-root" / "platform-tools"
            elif adb and adb.get("where") == "home":
                adb_dir = home / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools"
            if adb:
                fake_adb(adb_dir / "adb", log, adb.get("devices", ""), adb.get("rc", 0), adb.get("props", {}))
            if aws:
                stub(bin_dir / "aws")
            if agent:
                stub(bin_dir / "agent-device")
            env = {"PATH": str(bin_dir), "HOME": str(home), "ANDROID_HOME": None, "ANDROID_SDK_ROOT": None}
            if adb and adb.get("where") == "android_home":
                env["ANDROID_HOME"] = str(home / "android-home")
            if adb and adb.get("where") == "sdk_root":
                env["ANDROID_SDK_ROOT"] = str(home / "sdk-root")
            if android_home:
                env["ANDROID_HOME"] = str(home / android_home)
            if sdk_root:
                env["ANDROID_SDK_ROOT"] = str(home / sdk_root)
            saved = with_env(**env)
            try:
                result = call(api.device_probe)
            finally:
                restore(saved)
            calls = log.read_text("utf-8").splitlines() if log.exists() else []
            probes[label] = {"result": result, "adb_calls": calls}

        samsung = getprops("R5CT1", manufacturer="samsung", model="SM-S918B", os_version="14", one_ui_version="60100", qemu="0", characteristics="default")
        probe("no_tools")
        probe("no_adb_with_aws_and_agent_device", aws=True, agent=True)
        probe("android_home_missing_dir", android_home="nowhere")
        probe("adb_no_devices", adb={"devices": "List of devices attached\n"})
        probe("adb_devices_fail", adb={"devices": "error: server unreachable\n", "rc": 1}, aws=True)
        probe("one_samsung_phone", adb={"devices": "List of devices attached\nR5CT1 device usb:1-1 product:b0q model:SM_S918B\n", "props": samsung},
              agent=True)
        probe("android_home_adb", adb={"where": "android_home", "devices": "List of devices attached\nR5CT1 device\n", "props": samsung})
        probe("sdk_root_adb", adb={"where": "sdk_root", "devices": "List of devices attached\nR5CT1 device\n", "props": samsung})
        probe("home_appdata_adb", adb={"where": "home", "devices": "List of devices attached\nR5CT1 device\n", "props": samsung})
        tablet = getprops("T9", manufacturer="Samsung", model="SM-X710", os_version="14", one_ui_version="", qemu="", characteristics="tablet,nosdcard")
        probe("samsung_tablet_empty_qemu", adb={"devices": "List of devices attached\nT9 device\n", "props": tablet})
        emulator = getprops("emulator-5554", manufacturer="samsung", model="sdk", os_version="14", one_ui_version="", qemu="1", characteristics="default")
        probe("emulator_only", adb={"devices": "* daemon started successfully\nList of devices attached\nemulator-5554 device\n", "props": emulator})
        probe("emulator_named_but_qemu_zero", adb={"devices": "List of devices attached\nemulator-5556 device\n",
                                                   "props": getprops("emulator-5556", manufacturer="samsung", model="x", os_version="1",
                                                                     one_ui_version="", qemu="0", characteristics="default")})
        pixel = getprops("P1", manufacturer="Google", model="Pixel 8", os_version="14", one_ui_version="", qemu="0", characteristics="default")
        probe("not_samsung", adb={"devices": "List of devices attached\nP1 device\n", "props": pixel})
        probe("offline_and_unauthorized", adb={"devices": "List of devices attached\nO1 offline\nU2 unauthorized\nA3 authorizing\n"})
        mixed = {**pixel, **samsung, **getprops("X7", manufacturer="samsung", model="SM-A", os_version="13", qemu="0", characteristics="default")}
        probe("mixed_with_missing_props_and_offline",
              adb={"devices": "List of devices attached\nP1 device\nO1 offline\nR5CT1 device\nX7 device\n", "props": mixed})
        probe("getprop_all_fail", adb={"devices": "List of devices attached\nZ0 device\n", "props": {}})
        out["device_probe"] = probes
    finally:
        os.chdir(previous_cwd)
    return out
