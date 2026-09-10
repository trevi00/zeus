"""Portable SDD file, Git, device discovery and review/export adapters."""
import json
import os
import re
import shutil
from importlib.resources import files
from pathlib import Path

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.configuration import repository_root
from codex_harness.domain.model import digest, require
from codex_harness.domain.sdd import gate_report, validate_spec


def load_json(path):
    with Path(path).open("rb") as stream:
        body = stream.read(1024 * 1024 + 1)
    require(len(body) <= 1024 * 1024, "SDD input exceeds 1 MiB budget")
    return parse_json(body.decode("utf-8-sig"))


def parse_json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(body, object_pairs_hook=unique)


def read_spec(path, revision=None):
    path, root = Path(path).resolve(), repository_root()
    if revision:
        relative = path.relative_to(root).as_posix()
        commit = run_process(["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=str(root))
        require(commit.returncode == 0, "Spec Git revision unavailable")
        pinned = commit.stdout.strip()
        source = run_process(["git", "show", pinned + ":" + relative], cwd=str(root))
        require(source.returncode == 0, "Spec does not exist in pinned Git tree")
        require(len(source.stdout.encode("utf-8")) <= 1024 * 1024, "Spec exceeds size budget")
        spec = validate_spec(parse_json(source.stdout))
        provenance = {"mode": "git", "repository": str(root), "revision": pinned, "path": relative}
    else:
        spec = validate_spec(load_json(path))
        provenance = {"mode": "working_tree_draft", "repository": str(root), "revision": None, "path": str(path)}
    return spec, provenance


def write_export(path, body, kind="review"):
    path = Path(path).resolve()
    require(kind in {"review", "replay"}, "Unknown SDD export kind")
    require(path.name.endswith(".html" if kind == "review" else ".py.review"),
            "Review requires .html; replay drafts require .py.review to avoid automatic test collection")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = body.encode("utf-8")
    if path.exists():
        require(path.read_bytes() == encoded, "Export exists with different content; choose a new path")
    else:
        with path.open("xb") as stream:
            stream.write(encoded)
    return {"path": str(path), "bytes": len(encoded), "content_hash": digest(body)}


def render_review(spec, report=None):
    spec = validate_spec(spec)
    data = json.dumps({"spec": spec, "report": report or gate_report(spec)}, ensure_ascii=True)
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = files("codex_harness.resources").joinpath("sdd-review.html").read_text("utf-8")
    return template.replace("__ZEUS_SDD_DATA__", data)


def device_probe():
    candidate = shutil.which("adb")
    if not candidate:
        for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                     str(Path.home() / "AppData/Local/Android/Sdk")):
            if root:
                path = Path(root) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
                if path.is_file():
                    candidate = str(path)
                    break
    report = {"adb_available": bool(candidate), "aws_cli_available": bool(shutil.which("aws")),
              "agent_device_available": bool(shutil.which("agent-device")), "devices": [],
              "target": "Samsung Android phone and tablet", "authority": "discovery_only", "acceptance_passed": False}
    if not candidate:
        return {**report, "status": "blocked", "reason": "Android platform-tools/adb and authorized Samsung devices required"}
    result = run_process([candidate, "devices", "-l"], timeout=20)
    if result.returncode:
        return {**report, "status": "unavailable", "reason": "ADB device inventory unavailable"}
    for serial, state in adb_inventory(result.stdout):
        device = {"device_id": digest(serial), "state": state}
        if state == "device":
            for key, prop in (("manufacturer", "ro.product.manufacturer"), ("model", "ro.product.model"),
                ("os_version", "ro.build.version.release"), ("one_ui_version", "ro.build.version.oneui"),
                ("qemu", "ro.kernel.qemu"), ("characteristics", "ro.build.characteristics")):
                value = run_process([candidate, "-s", serial, "shell", "getprop", prop], timeout=10)
                device[key] = value.stdout.strip() if value.returncode == 0 else "unknown"
            device["physical_candidate"] = (device["manufacturer"].lower() == "samsung"
                and device["qemu"] in {"", "0"} and not serial.startswith("emulator-"))
            device["form_factor"] = "tablet" if "tablet" in device["characteristics"] else "phone"
        report["devices"].append(device)
    report.update(status="discovered" if any(d.get("physical_candidate") for d in report["devices"]) else "blocked",
                  reason="Discovery is not a real-device scenario run; app/build/reset and session evidence remain required")
    return report


def adb_inventory(output):
    """Parse transport rows only; daemon diagnostics are not device identifiers."""
    return re.findall(r"^([A-Za-z0-9_.:-]+)\s+(device|offline|unauthorized|authorizing|no)(?:\s|$)", output, re.MULTILINE)


def replay_source(spec):
    """Generate actual assertions, never pass/xfail placeholders or an acceptance receipt."""
    spec = validate_spec(spec)
    require(spec["target"]["kind"] == "android" and spec["target"]["app_id"]
            and spec["target"]["build_hash"], "Concrete Android app and build hash required for replay export")
    require(not any(r["risk"] == "financial" for r in spec["requirements"]),
            "Financial replay requires reviewed backend reconciliation and payment environment integration")
    active = [s for s in spec["scenarios"] if s["status"] == "active"]
    require(len(active) == 1, "Multi-scenario replay requires a verified per-scenario reset integration")
    for scenario in active:
        require(scenario["bindings"], "Scenario has no observed selector bindings: " + scenario["id"])
        oracles = {b["oracle_index"] for b in scenario["bindings"] if b["operation"].startswith("assert_")}
        require(oracles == set(range(len(scenario["then"]))), "Every oracle requires an explicit assertion binding")
        for binding in scenario["bindings"]:
            if binding["operation"] == "input":
                require(re.fullmatch(r"ZEUS_TEST_[A-Z0-9_]+", binding["value"]), "Use environment parameter references for input, never inline credentials")
    lines = [
        '"""Generated Appium replay; unexecuted and not human acceptance evidence.',
        'Review the spec oracles and satisfy its reset contract before execution.',
        'Spec hash: ' + digest(spec) + '\n"""',
        "import json", "import os", "from pathlib import Path", "import unittest",
        "from appium import webdriver", "from appium.options.android import UiAutomator2Options",
        "from selenium.webdriver.support.ui import WebDriverWait",
        "from selenium.webdriver.support import expected_conditions as EC",
        "from selenium.common.exceptions import StaleElementReferenceException", "",
        "def exact_text(locator, expected):",
        "    def matches(driver):",
        "        try:",
        "            return driver.find_element(*locator).text == expected",
        "        except StaleElementReferenceException:",
        "            return False",
        "    return matches", "",
        "class SpecReplay(unittest.TestCase):",
        "    def setUp(self):",
        "        if os.environ.get('ZEUS_TARGET_ENV') not in {'local', 'alpha'}:",
        "            raise RuntimeError('Explicit isolated local/alpha environment required')",
        "        manifest = json.loads(Path(os.environ['ZEUS_REPLAY_ENVIRONMENT']).read_text('utf-8'))",
        "        if manifest['app_build_hash'] != " + repr(spec["target"]["build_hash"]) + ":",
        "            raise RuntimeError('App build differs from specification')",
        "        if not manifest['reset_receipt'] or manifest['manufacturer'] != 'samsung' or manifest['physical_device'] is not True:",
        "            raise RuntimeError('Samsung physical-device and reset evidence required')",
        "        options = UiAutomator2Options().load_capabilities({",
        "            'platformName': 'Android', 'appium:automationName': 'UiAutomator2',",
        "            'appium:udid': os.environ['ZEUS_DEVICE_SERIAL'], 'appium:noReset': True,",
        "            'appium:appPackage': " + repr(spec["target"]["app_id"]) + "})",
        "        self.driver = webdriver.Remote(os.environ['ZEUS_APPIUM_URL'], options=options)",
        "        self.addCleanup(self.driver.quit)", "",
    ]
    # FA-014: every generated check is attributed at runtime to its scenario, oracle index and
    # requirement IDs (subTest), so a failure maps back to the acceptance criterion it exercised.
    # All spec text enters the source as Python literals (repr), never as raw code or comments.
    oracles = {scenario["id"]: {"requirement_ids": list(scenario["requirement_ids"]),
                                "oracles": list(scenario["then"])} for scenario in active}
    position = lines.index("class SpecReplay(unittest.TestCase):")
    lines[position:position] = ["SPEC_HASH = " + repr(digest(spec)), "ORACLES = " + repr(oracles), ""]
    for index, scenario in enumerate(active, 1):
        lines += ["    def test_" + str(index).zfill(4) + "_" + digest(scenario["id"])[:16] + "(self):",
                  "        " + repr("Scenario " + scenario["id"] + ": " + scenario["title"])]
        for binding in scenario["bindings"]:
            locator = (binding["selector"]["strategy"], binding["selector"]["value"])
            operation = binding["operation"]
            indent = "        "
            if operation.startswith("assert_"):
                attribution = {"scenario": scenario["id"], "oracle": binding["oracle_index"],
                               "requirement_ids": list(scenario["requirement_ids"]),
                               "expected": scenario["then"][binding["oracle_index"]]}
                lines.append(indent + "with self.subTest(**" + repr(attribution) + "):")
                indent += "    "
            lines.append(indent + "element = WebDriverWait(self.driver, 20).until(EC.visibility_of_element_located(" + repr(locator) + "))")
            if operation == "tap":
                lines.append(indent + "element.click()")
            elif operation == "input":
                lines += [indent + "element.clear()", indent + "element.send_keys(os.environ[" + repr(binding["value"]) + "])"]
            elif operation == "assert_visible":
                lines.append(indent + "self.assertTrue(element.is_displayed())")
            else:
                lines.append(indent + "WebDriverWait(self.driver, 20).until(exact_text(" + repr(locator) + ", " + repr(binding["value"]) + "))")
        lines.append("")
    lines += ["if __name__ == '__main__':", "    unittest.main()", ""]
    return "\n".join(lines)
