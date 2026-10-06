"""Cutover G1-11: the first `approved_rebaselines` entry (main-s2r-b9d8f15) in the compare harness.

Behavioural: each test drives the public functions of `compare/run.py` (`check_tree`, `prepare_rebaseline`, `main`)
on the real tree or on a fixture git repository. Expected results come from AMD-1 section A and the decision record
REBASELINE-MAIN-S2R, not from the implementation:
  - rule (b) of the promoted archive rule also accepts `reference/<id>/<q>` for a delta path q whose blob equals the
    entry commit's blob; a missing delta file, an extra file and a differing blob are each `foreign_reference_paths`;
  - the entry's `delta_paths` equal `git diff --name-only parent_source commit` and `commit^{tree}` equals `tree`;
  - the overlay (SOURCE archive + delta archive) must reproduce the pinned tree BEFORE any build;
  - `run --record` with a rebaseline reference is refused (goldens stay M7's), except `--only <family>` of scenarios
    that declare that rebaseline as their reference (G1-13c).

Cutover G1-13c (decision G1-13C-COMPARE-DECISION rules 3-5): the expected results are the decision's rules, not the
implementation's output:
  - `--target-vs-reference` compares the target with the reference result of the SAME run (never a stored golden), needs
    a rebaseline reference and never `--record`;
  - a rebaseline record writes only the goldens of scenarios that declare `"reference": "rebaseline:<id>"`, under
    `goldens/rebaseline/<id>/`; every M7-referenced family stays refused;
  - the closed mask `rebaseline_runtime_revision` hides only a runtime revision (at a shared revision leaf, as a
    bijection) and the listed leaves, equality-preservingly; a changed state or result is never hidden;
  - `rebaseline`-layer declarations are the M7 golden -> rebaseline difference, the other declarations are the target's.
"""

import copy
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from _layout import REPO

ENTRY_ID = "main-s2r-b9d8f15"
PR3_ID = "pr3-bb579d5"  # G1-14c: entry 2, the reviewed PR-3 head (G1-09F-RELEASE-BRANCH-ONLY)


def _run_module():
    spec = importlib.util.spec_from_file_location("compare_run_for_rebaseline", REPO / "compare" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args], cwd=root,
                          check=True, capture_output=True, text=True).stdout.strip()


def _write(root: Path, rel: str, text: str) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")


def _baseline() -> dict:
    return json.loads((REPO / "compare" / "baseline.json").read_text(encoding="utf-8"))


# --- the real tree -------------------------------------------------------------------------------------------------

def test_the_baseline_holds_the_one_entry_and_its_archive_is_exactly_the_delta():
    entry = _baseline()["approved_rebaselines"][0]
    assert entry["id"] == ENTRY_ID and entry["archive_root"] == f"reference/{ENTRY_ID}"
    delta = subprocess.run(["git", "diff", "--name-only", entry["parent_source"], entry["commit"]], cwd=REPO,
                           check=True, capture_output=True, text=True).stdout.split()
    assert entry["delta_paths"] == sorted(delta) and len(delta) == 19
    archived = sorted(str(p.relative_to(REPO / entry["archive_root"]))
                      for p in (REPO / entry["archive_root"]).rglob("*") if p.is_file())
    assert archived == entry["delta_paths"]
    for rel in entry["delta_paths"]:
        want = subprocess.run(["git", "show", f"{entry['commit']}:{rel}"], cwd=REPO, check=True,
                              capture_output=True).stdout
        assert (REPO / entry["archive_root"] / rel).read_bytes() == want


def test_check_tree_on_the_real_tree_accepts_the_archive():
    report = _run_module().check_tree()
    assert report["ok"] is True
    assert report["foreign_reference_paths"] == [] and report["credential_shaped_strings"] == []
    assert report["rebaselines"] == [
        {"id": eid, "tree_matches": True, "delta_paths_match": True, "delta_paths_in_commit": True, "ok": True}
        for eid in (ENTRY_ID, PR3_ID)]


# --- rule (b) with fixture repositories ----------------------------------------------------------------------------

@pytest.fixture
def fixture(tmp_path):
    """-> (root, baseline): SOURCE commit C0, a "main" commit C1 (one file modified, one added; C1 stays an object),
    the working tree at C0 with the delta archive of C1 under `reference/rb1/` and an entry describing it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _write(root, "src/a.py", "A = 1\n")
    _write(root, "docs/x.md", "# x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "source")
    c0 = _git(root, "rev-parse", "HEAD")
    _write(root, "src/a.py", "A = 2\n")
    _write(root, "src/new.py", "N = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "main")
    c1 = _git(root, "rev-parse", "HEAD")
    _git(root, "reset", "-q", "--hard", c0)
    for rel in ("src/a.py", "src/new.py"):
        _write(root, f"reference/rb1/{rel}", "")
        (root / "reference" / "rb1" / rel).write_bytes(
            subprocess.run(["git", "show", f"{c1}:{rel}"], cwd=root, check=True, capture_output=True).stdout)
    _write(root, "reference/README.md", "the archive\n")
    entry = {"id": "rb1", "commit": c1, "tree": _git(root, "rev-parse", f"{c1}^{{tree}}"), "parent_source": c0,
             "delta_paths": ["src/a.py", "src/new.py"], "archive_root": "reference/rb1"}
    baseline = {"source": {"tree": _git(root, "rev-parse", f"{c0}^{{tree}}")},
                "layout": {"mode": "promoted", "additions_only": {}}, "approved_rebaselines": [entry]}
    return root, c0, baseline


def _check(fixture, baseline=None):
    root, c0, base = fixture
    return _run_module().check_tree(root=root, source_commit=c0, baseline=base if baseline is None else baseline)


def test_a_faithful_delta_archive_is_ok(fixture):
    report = _check(fixture)
    assert report["ok"] is True and report["foreign_reference_paths"] == []
    assert report["rebaselines"][0]["ok"] is True


def test_an_appended_byte_is_foreign(fixture):
    with (fixture[0] / "reference/rb1/src/a.py").open("ab") as handle:
        handle.write(b"\n")
    report = _check(fixture)
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/rb1/src/a.py"]


def test_an_extra_file_is_foreign(fixture):
    _write(fixture[0], "reference/rb1/src/extra.py", "X = 1\n")
    report = _check(fixture)
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/rb1/src/extra.py"]


def test_a_missing_delta_file_is_foreign(fixture):
    (fixture[0] / "reference/rb1/src/new.py").unlink()
    report = _check(fixture)
    assert report["ok"] is False and report["foreign_reference_paths"] == ["reference/rb1/src/new.py"]


def test_a_file_outside_the_delta_list_is_foreign_even_when_it_is_the_commits_blob(fixture):
    root, c0, base = fixture
    narrowed = copy.deepcopy(base)
    narrowed["approved_rebaselines"][0]["delta_paths"] = ["src/a.py"]
    report = _check(fixture, narrowed)
    assert report["ok"] is False and "reference/rb1/src/new.py" in report["foreign_reference_paths"]
    assert report["rebaselines"][0]["delta_paths_match"] is False


def test_a_wrong_delta_list_is_named(fixture):
    root, c0, base = fixture
    wrong = copy.deepcopy(base)
    wrong["approved_rebaselines"][0]["delta_paths"] = ["src/a.py", "src/new.py", "docs/x.md"]
    report = _check(fixture, wrong)
    assert report["ok"] is False and report["rebaselines"][0]["delta_paths_match"] is False


def test_a_wrong_tree_is_named(fixture):
    root, c0, base = fixture
    wrong = copy.deepcopy(base)
    wrong["approved_rebaselines"][0]["tree"] = "0" * 40
    report = _check(fixture, wrong)
    assert report["ok"] is False and report["rebaselines"][0]["tree_matches"] is False


def test_a_credential_shaped_string_in_a_modified_delta_file_is_still_scanned(fixture):
    _write(fixture[0], "reference/rb1/src/a.py", "KEY = 'ghp_" + "a" * 24 + "'\n")
    report = _check(fixture)
    assert report["ok"] is False
    assert [s["path"] for s in report["credential_shaped_strings"]] == ["reference/rb1/src/a.py"]


def test_without_entries_the_report_has_no_rebaselines_key(fixture):
    root, c0, base = fixture
    bare = copy.deepcopy(base)
    bare["approved_rebaselines"] = []
    shutil.rmtree(root / "reference" / "rb1")
    report = _check(fixture, bare)
    assert report["ok"] is True and "rebaselines" not in report


# --- the overlay proof and the run selector ------------------------------------------------------------------------

def test_a_differing_overlay_is_refused_before_any_build(tmp_path):
    entry = _baseline()["approved_rebaselines"][0]
    archive_base = tmp_path / "archive"
    shutil.copytree(REPO / entry["archive_root"], archive_base / entry["archive_root"])
    swapped = "src/codex_harness/adapters/host_delivery.py"  # modified by the delta: M7's bytes differ
    (archive_base / entry["archive_root"] / swapped).write_bytes(
        subprocess.run(["git", "show", f"{entry['parent_source']}:{swapped}"], cwd=REPO, check=True,
                       capture_output=True).stdout)
    scratch = tmp_path / "scratch"
    facts = _run_module().prepare_rebaseline(ENTRY_ID, scratch=scratch, archive_base=archive_base)
    assert facts["overlay_matches_tree"] is False and facts["differing_paths"] == [swapped]
    assert "nothing was built" in facts["refused"] and facts["wheel_record_matches_baseline"] is False
    assert not list((scratch / f"rebaseline-{ENTRY_ID}" / "dist").glob("*.whl"))
    assert not (scratch / f"venv-rb-{ENTRY_ID}").exists()


def test_a_missing_archive_file_is_refused_with_its_path(tmp_path):
    entry = _baseline()["approved_rebaselines"][0]
    archive_base = tmp_path / "archive"
    shutil.copytree(REPO / entry["archive_root"], archive_base / entry["archive_root"])
    (archive_base / entry["archive_root"] / entry["delta_paths"][0]).unlink()
    facts = _run_module().prepare_rebaseline(ENTRY_ID, scratch=tmp_path / "scratch", archive_base=archive_base)
    assert facts["differing_paths"] == [entry["delta_paths"][0]] and "refused" in facts


def test_run_record_with_a_rebaseline_reference_is_refused(capsys):
    module = _run_module()
    with pytest.raises(SystemExit) as refused:
        module.main(["run", "--record", "--reference", f"rebaseline:{ENTRY_ID}"])
    assert "refused" in str(refused.value.code) and "--record" in str(refused.value.code)


def test_an_unknown_reference_selector_is_refused():
    module = _run_module()
    for bad in ("rebaseline:nope", "other", "rebaseline:"):
        with pytest.raises(SystemExit):
            module.resolve_reference(bad, False)


def test_the_selector_picks_the_rebaseline_venv_and_overlay_and_the_default_stays_m7():
    module = _run_module()
    assert module.resolve_reference("m7", True) == (module.SCRATCH / "venv-ref", module.SCRATCH / "source", None)
    venv, source, entry_id = module.resolve_reference(f"rebaseline:{ENTRY_ID}", False)
    assert (venv, source, entry_id) == (module.SCRATCH / f"venv-rb-{ENTRY_ID}",
                                        module.SCRATCH / f"rebaseline-{ENTRY_ID}" / "source", ENTRY_ID)


def test_package_file_identity_follows_the_origin_record_method():
    """The rebaseline wheel's pinned identity uses the method the drivers' origin check applies to the installed
    distribution (`origin.record_files`): sorted `<path>,sha256=<b64>` rows of codex_harness/ and zeus/ only, rows
    without a hash excluded. A different package file changes the digest (G1-11 owner correction)."""
    import hashlib

    run = _run_module()
    record = (b"codex_harness/a.py,sha256=AAA,10\r\nzeus/b.py,sha256=BBB,5\r\nother/c.py,sha256=CCC,1\r\n"
              b"zeus_harness-0.2.0.dist-info/RECORD,,\r\n")
    identity = run.package_file_identity(record)
    expected_rows = sorted(["codex_harness/a.py,sha256=AAA", "zeus/b.py,sha256=BBB"])
    assert identity == {"package_files": 2,
                        "package_files_digest": hashlib.sha256("\n".join(expected_rows).encode()).hexdigest()}
    changed = run.package_file_identity(record.replace(b"sha256=BBB", b"sha256=BBC"))
    assert changed["package_files"] == 2 and changed["package_files_digest"] != identity["package_files_digest"]


def test_rebaseline_entry_pins_its_own_package_file_identity():
    run = _run_module()
    entry = run.rebaseline_entry("main-s2r-b9d8f15")["rebaseline_wheel"]
    assert entry["package_files"] == 276 and len(entry["package_files_digest"]) == 64
    assert entry["package_files_digest"] != run.BASELINE["source"]["reference_wheel"]["package_files_digest"]


# --- G1-13c: the rebaseline modes of `run` --------------------------------------------------------------------------

def test_a_rebaseline_record_is_refused_for_an_m7_referenced_family_and_when_mixed_or_unknown():
    module = _run_module()
    reference = f"rebaseline:{ENTRY_ID}"
    for only in (["cli.parser"], ["delivery.maintenance.pg", "cli.parser"], ["no.such.family"], []):
        with pytest.raises(SystemExit) as refused:
            module.resolve_reference(reference, True, only)
        assert str(refused.value.code).startswith("refused: --record with a rebaseline reference")
    with pytest.raises(SystemExit):
        module.main(["run", "--record", "--reference", reference, "--only", "cli.parser"])
    with pytest.raises(SystemExit):
        module.resolve_reference("m7", True, ["delivery.maintenance"]) and (_ for _ in ()).throw(SystemExit)


def test_a_rebaseline_record_is_allowed_for_the_scenarios_that_declare_it_and_only_under_the_rebaseline_golden_dir(
        monkeypatch, tmp_path):
    module = _run_module()
    # G1-14c: both maintenance families are on entry 2; the owner recorded the .pg golden against a live PostgreSQL
    # and repointed it (144dcf7d).
    homes = {"delivery.maintenance": PR3_ID, "delivery.maintenance.pg": PR3_ID}
    declared = {s["family"]: s for s in module.scenarios() if s.get("reference")}
    assert set(declared) == set(homes)
    for family, entry_id in homes.items():
        assert module.resolve_reference(f"rebaseline:{entry_id}", True, [family])[2] == entry_id
        assert declared[family]["reference"] == f"rebaseline:{entry_id}"
        assert declared[family]["golden"] == f"goldens/rebaseline/{entry_id}/{family}.json"
    reference = f"rebaseline:{ENTRY_ID}"
    # a scenario that declares the reference but keeps its golden elsewhere (e.g. under the M7 goldens) is refused
    strays = [{"family": "x.stray", "reference": reference, "golden": "goldens/reference/x.stray.json"}]
    monkeypatch.setattr(module, "scenarios", lambda: strays)
    with pytest.raises(SystemExit) as refused:
        module.resolve_reference(reference, True, ["x.stray"])
    assert "outside goldens/rebaseline" in str(refused.value.code)


def test_target_vs_reference_needs_a_rebaseline_reference_and_never_record():
    module = _run_module()
    for argv in (["run", "--target-vs-reference"], ["run", "--target-vs-reference", "--reference", "m7"],
                 ["run", "--target-vs-reference", "--record", "--reference", f"rebaseline:{ENTRY_ID}"]):
        with pytest.raises(SystemExit) as refused:
            module.main(argv)
        assert refused.value.code == 2
    with pytest.raises(SystemExit):
        module.run(False, False, [], reference="m7", target_vs_reference=True)


def _synthetic(module, monkeypatch, tmp_path, *, golden, reference_result, target_result, declared=(), family="x.fam",
               reference_field=None):
    """`run` over ONE synthetic scenario with LABELLED stub drivers: the reference driver returns
    `reference_result`, the target driver `target_result`; the venv python and the golden are files in `tmp_path`."""
    entry = {"id": ENTRY_ID, "rebaseline_wheel": {"package_files": 1, "package_files_digest": "d"}}
    monkeypatch.setattr(module, "SCRATCH", tmp_path)
    monkeypatch.setattr(module, "rebaseline_entry", lambda entry_id, baseline=None: entry)
    for venv in (f"venv-rb-{ENTRY_ID}", "venv-ref"):
        (tmp_path / venv / "bin").mkdir(parents=True, exist_ok=True)
        (tmp_path / venv / "bin" / "python").write_text("")
    golden_path = tmp_path / "golden.json"
    if golden is not None:
        golden_path.write_text(json.dumps(golden), encoding="utf-8")
    scenario = {"family": family, "slice": "T", "reference_driver": "ref.py", "target_driver": "target.py",
                "golden": str(golden_path), "intended_differences": list(declared)}
    if reference_field:
        scenario["reference"] = reference_field
    monkeypatch.setattr(module, "scenarios", lambda: [scenario])
    wheel = module.BASELINE["source"]["reference_wheel"]  # the default (M7) reference is held to the M7 identity
    origins = {a: {"package_files": 1, "package_files_digest": "d", "modules_checked": 1} for a in ("rebaseline",)}
    origins["m7"] = {"package_files": wheel["package_files"], "package_files_digest": wheel["package_files_digest"],
                     "modules_checked": 1}
    monkeypatch.setattr(module, "run_driver", lambda python, *a, **k: {
        "origin": origins["rebaseline" if "venv-rb-" in str(python) else "m7"], "result": reference_result})
    (tmp_path / "target.py").write_text("")
    monkeypatch.setattr(module, "COMPARE", tmp_path)
    monkeypatch.setattr(module, "run_target", lambda *a, **k: {
        "side": "target", "origin": {"tree": str(module.TARGET_SRC), "modules_checked": 1}, "result": target_result})
    return golden_path


def _row(report, family="x.fam"):
    return report["scenarios"][family]


def test_target_vs_reference_compares_the_target_with_the_reference_result_of_the_same_run(monkeypatch, tmp_path):
    """Expected (decision rule 3): golden {o: {n: 1}}; S2R makes the reference {o: {n: 2, extra: 7}} (rebaseline-layer
    declarations); the target declares one OWN difference (a new key) on top. Equal only when the target equals the
    REFERENCE result plus its own declaration, and a target that keeps the M7 value is DIFFERENT."""
    module = _run_module()
    s2r = [{"layer": "rebaseline", "path": "$.o.n", "op": "replace", "value": 2,
            "authority": "REBASELINE-MAIN-S2R hunk A"},
           {"layer": "rebaseline", "path": "$.o", "op": "add", "key": "extra", "value": 7,
            "authority": "REBASELINE-MAIN-S2R hunk B"}]
    own = [{"path": "$.o", "op": "add", "key": "mine", "value": "m", "authority": "S10 own addition"}]
    reference = f"rebaseline:{ENTRY_ID}"
    _synthetic(module, monkeypatch, tmp_path, golden={"o": {"n": 1}}, reference_result={"o": {"n": 2, "extra": 7}},
               target_result={"o": {"n": 2, "extra": 7, "mine": "m"}}, declared=s2r + own)
    report, ok = module.run(False, False, [], reference=reference, target_vs_reference=True)
    row = _row(report)
    assert (row["reference"], row["target"], row["target_vs_reference"]) == ("equal", "equal", True), row
    assert ok
    # the target equals the M7 golden plus its own declaration, not the S2R reference: DIFFERENT against the reference
    _synthetic(module, monkeypatch, tmp_path, golden={"o": {"n": 1}}, reference_result={"o": {"n": 2, "extra": 7}},
               target_result={"o": {"n": 1, "mine": "m"}}, declared=s2r + own)
    report, ok = module.run(False, False, [], reference=reference, target_vs_reference=True)
    assert not ok and (_row(report)["reference"], _row(report)["target"]) == ("equal", "DIFFERENT")
    assert sorted(_row(report)["target_differing_paths"]) == ["$.o.extra (missing on one side)", "$.o.n"]
    # the reference result is not what the declared S2R layer says: the reference row is DIFFERENT
    _synthetic(module, monkeypatch, tmp_path, golden={"o": {"n": 1}}, reference_result={"o": {"n": 3, "extra": 7}},
               target_result={"o": {"n": 3, "extra": 7, "mine": "m"}}, declared=s2r + own)
    report, ok = module.run(False, False, [], reference=reference, target_vs_reference=True)
    assert not ok and (_row(report)["reference"], _row(report)["target"]) == ("DIFFERENT", "equal")


def test_the_default_target_comparison_applies_the_rebaseline_layer_then_the_target_declarations(monkeypatch, tmp_path):
    module = _run_module()
    s2r = [{"layer": "rebaseline", "path": "$.o.n", "op": "replace", "value": 2, "authority": "REBASELINE-MAIN-S2R"}]
    own = [{"path": "$.o", "op": "add", "key": "mine", "value": "m", "authority": "S10"}]
    _synthetic(module, monkeypatch, tmp_path, golden={"o": {"n": 1}}, reference_result={"o": {"n": 1}},
               target_result={"o": {"n": 2, "mine": "m"}}, declared=s2r + own)
    report, ok = module.run(False, False, [])  # the default (M7) reference: reference == the raw golden
    assert (_row(report)["reference"], _row(report)["target"]) == ("equal", "equal"), _row(report)
    assert ok


def test_a_family_that_declares_its_rebaseline_reference_is_skipped_by_the_default_reference(monkeypatch, tmp_path):
    module = _run_module()
    _synthetic(module, monkeypatch, tmp_path, golden={"a": 1}, reference_result={"a": 1}, target_result={"a": 1},
               reference_field=f"rebaseline:{ENTRY_ID}")
    report, ok = module.run(False, False, [])
    assert ok and _row(report)["reference"].startswith("not requested (its reference is rebaseline:")
    assert "target" not in _row(report)


def test_a_scoped_rebaseline_record_writes_the_golden_under_the_rebaseline_dir(monkeypatch, tmp_path):
    module = _run_module()
    reference = f"rebaseline:{ENTRY_ID}"
    home = tmp_path / "goldens" / "rebaseline"
    monkeypatch.setattr(module, "GOLDENS_REBASELINE", home)
    golden_path = home / ENTRY_ID / "x.fam.json"
    _synthetic(module, monkeypatch, tmp_path, golden=None, reference_result={"a": 1}, target_result={"a": 1},
               reference_field=reference)
    scenario = module.scenarios()[0]
    scenario["golden"] = str(golden_path)
    report, ok = module.run(True, False, ["x.fam"], reference=reference)
    assert ok and json.loads(golden_path.read_text(encoding="utf-8")) == {"a": 1}
    assert _row(report)["reference"] == "equal" and _row(report)["target"] == "equal"
    with pytest.raises(SystemExit):  # the same scenario without the declaration is an M7 family: refused
        scenario.pop("reference")
        module.run(True, False, ["x.fam"], reference=reference)


# --- the closed revision mask -----------------------------------------------------------------------------------------

REV_A, REV_B = "a" * 40, "b" * 40
FAMILY = "delivery.managed_runtime"


def test_the_revision_mask_hides_a_revision_and_its_derivatives_but_nothing_behavioural():
    module = _run_module()
    golden = {"d": {"revision": REV_A, "root": f"<root>/runtimes/{REV_A}", "status": "running"},
              "runtime_dirs": {f"runtimes.{REV_A}": {"files": 274, "sha256": "1" * 64}},
              "launch": {"manifest_sha256": "2" * 64, "again": {"manifest_sha256": "2" * 64}}}
    actual = {"d": {"revision": REV_B, "root": f"<root>/runtimes/{REV_B}", "status": "running"},
              "runtime_dirs": {f"runtimes.{REV_B}": {"files": 275, "sha256": "3" * 64}},
              "launch": {"manifest_sha256": "4" * 64, "again": {"manifest_sha256": "4" * 64}}}
    expected, observed, masked = module.rebaseline_normalise(FAMILY, golden, actual)
    assert masked and expected == observed
    # a state change is never hidden
    changed = json.loads(json.dumps(actual))
    changed["d"]["status"] = "stopped"
    expected, observed, _ = module.rebaseline_normalise(FAMILY, golden, changed)
    assert expected != observed
    # the golden's two equal digests became unequal on the actual side: equality is preserved, so it is DIFFERENT
    unequal = json.loads(json.dumps(actual))
    unequal["launch"]["again"]["manifest_sha256"] = "5" * 64
    expected, observed, _ = module.rebaseline_normalise(FAMILY, golden, unequal)
    assert expected != observed
    # the sealed tree and the fixture source revisions (`revisions.a`/`.b`) are revision leaves too
    tree_golden = {"manifest": {"tree": REV_A}, "revisions": {"a": REV_A, "b": "c" * 40}}
    tree_actual = {"manifest": {"tree": REV_B}, "revisions": {"a": REV_B, "b": "d" * 40}}
    expected, observed, _ = module.rebaseline_normalise(FAMILY, tree_golden, tree_actual)
    assert expected == observed
    # a revision-looking value that is NOT at a revision leaf is not masked
    other = json.loads(json.dumps(actual))
    other["d"]["root"] = f"<root>/runtimes/{'c' * 40}"
    expected, observed, _ = module.rebaseline_normalise(FAMILY, golden, other)
    assert expected != observed
    # a non-bijective pairing (one expected revision, two actual ones) is reported, not masked
    golden2 = {"x": {"revision": REV_A}, "y": {"revision": REV_A}}
    actual2 = {"x": {"revision": REV_B}, "y": {"revision": "c" * 40}}
    expected, observed, _ = module.rebaseline_normalise(FAMILY, golden2, actual2)
    assert expected != observed


def test_the_revision_mask_applies_only_to_its_families_and_is_a_declared_closed_entry():
    module = _run_module()
    values = ({"revision": REV_A}, {"revision": REV_B})
    assert module.rebaseline_normalise("cli.parser", *values) == (values[0], values[1], False)
    mask = module.rebaseline_revision_mask(FAMILY)
    assert mask["id"] == "rebaseline_runtime_revision" and mask["reason"]
    assert set(mask["scenarios"]) == {"delivery.host_targets", "delivery.managed_runtime", "delivery.managed_systemd"}
    assert module.rebaseline_revision_mask("effects.delivery_units") is None


# --- the declaration ops and layers ------------------------------------------------------------------------------------

def test_append_items_extends_the_list_and_a_stale_or_invalid_declaration_is_refused():
    module = _run_module()
    ok = {"path": "$.nodes", "op": "append_items", "value": [3, 4], "authority": "A"}
    expected, problems = module.apply_intended_differences({"nodes": [1, 2]}, [ok])
    assert (expected, problems) == ({"nodes": [1, 2, 3, 4]}, [])
    for bad in ({**ok, "value": 3}, {**ok, "layer": "other"}, {**ok, "key": "k"}, {**ok, "authority": ""}):
        _, problems = module.apply_intended_differences({"nodes": [1, 2]}, [bad])
        assert problems == ["intended_differences[0]: invalid declaration"]
    _, problems = module.apply_intended_differences({"nodes": "x"}, [ok])
    assert problems and "not a list" in problems[0]
    _, problems = module.apply_intended_differences({}, [ok])
    assert problems and "stale" in problems[0]


def test_split_layers_separates_the_rebaseline_layer_in_declared_order():
    module = _run_module()
    a, b, c = ({"layer": "rebaseline", "n": 1}, {"n": 2}, {"layer": "rebaseline", "n": 3})
    assert module.split_layers([a, b, c]) == ([a, c], [b]) and module.split_layers(None) == ([], [])


def test_the_s2r_declarations_of_the_affected_families_cite_the_rebaseline_and_a_hunk():
    """Structural (provenance contract of G1-13C-COMPARE-DECISION rule 2): every rebaseline-layer declaration of the
    S2R-affected families names REBASELINE-MAIN-S2R (or, for the PR-3 hunk, G1-09F-RELEASE-BRANCH-ONLY) and the source file it comes from."""
    module = _run_module()
    by_family = {s["family"]: s for s in module.scenarios()}
    for family in ("cli.parser", "static.source", "effects.delivery_units", "effects.delivery_units.pg"):
        layer, _ = module.split_layers(by_family[family].get("intended_differences"))
        assert layer, family
        for declaration in layer:
            assert ("REBASELINE-MAIN-S2R" in declaration["authority"]
                    or "G1-09F-RELEASE-BRANCH-ONLY" in declaration["authority"])
            assert any(name in declaration["authority"] for name in
                       ("adapters/host_delivery.py", "application/host_delivery.py", "domain/host_delivery.py",
                        "docs/contracts.md", "adapters/managed_runtime.py", "adapters/maintenance_evidence.py",
                        "the delta adds")), declaration["path"]


# --- entry 2 (pr3-bb579d5, G1-14c): the same controls on the real entry --------------------------------------------

def _entry2() -> dict:
    return _baseline()["approved_rebaselines"][1]


def test_entry_two_pins_the_reviewed_pr3_head_and_its_archive_is_exactly_the_delta():
    entry = _entry2()
    assert (entry["id"], entry["commit"], entry["tree"], entry["parent_source"], entry["archive_root"]) == (
        PR3_ID, "bb579d558cd5902fa9d6493fad9b92ebd5be4b68", "936dec623dc9cf266ef465c723499b723a9040bd", "e38aa722ff1e91dc01ec650689cfe3eebe1ff699", f"reference/{PR3_ID}")
    delta = subprocess.run(["git", "diff", "--name-only", entry["parent_source"], entry["commit"]], cwd=REPO,
                           check=True, capture_output=True, text=True).stdout.split()
    assert entry["delta_paths"] == sorted(delta) and len(delta) == 24
    archive = REPO / entry["archive_root"]
    assert sorted(str(p.relative_to(archive)) for p in archive.rglob("*") if p.is_file()) == entry["delta_paths"]
    for rel in entry["delta_paths"]:
        want = subprocess.run(["git", "show", f"{entry['commit']}:{rel}"], cwd=REPO, check=True,
                              capture_output=True).stdout
        assert (archive / rel).read_bytes() == want


def test_entry_two_a_wrong_delta_list_and_a_wrong_tree_are_each_not_ok():
    module = _run_module()
    base = _baseline()
    wrong_list = copy.deepcopy(base)
    wrong_list["approved_rebaselines"][1]["delta_paths"] = sorted(
        [*wrong_list["approved_rebaselines"][1]["delta_paths"], "docs/research-standard.md"])
    report = module.check_tree(baseline=wrong_list)
    row = next(r for r in report["rebaselines"] if r["id"] == PR3_ID)
    assert report["ok"] is False and row["delta_paths_match"] is False and row["ok"] is False
    wrong_tree = copy.deepcopy(base)
    wrong_tree["approved_rebaselines"][1]["tree"] = "0" * 40
    report = module.check_tree(baseline=wrong_tree)
    row = next(r for r in report["rebaselines"] if r["id"] == PR3_ID)
    assert report["ok"] is False and row["tree_matches"] is False and row["ok"] is False


def test_entry_two_a_modified_delta_file_is_foreign(tmp_path):
    """A shared clone without checkout (the commits' objects, no working files) plus a copy of entry 2's archive: the
    faithful copy has no foreign path, one appended byte makes exactly that path foreign."""
    module = _run_module()
    entry = _entry2()
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(REPO), str(clone)], check=True)
    shutil.copytree(REPO / entry["archive_root"], clone / entry["archive_root"])
    base = copy.deepcopy(_baseline())
    base["approved_rebaselines"] = [entry]
    clean = module.check_tree(root=clone, baseline=base)
    assert clean["foreign_reference_paths"] == [] and clean["rebaselines"][0]["ok"] is True
    target = entry["delta_paths"][0]
    with (clone / entry["archive_root"] / target).open("ab") as handle:
        handle.write(b"\n")
    report = module.check_tree(root=clone, baseline=base)
    assert report["ok"] is False
    assert report["foreign_reference_paths"] == [f"{entry['archive_root']}/{target}"]
