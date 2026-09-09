"""Observe original runner helpers on actual temporary files, without method patches."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from tests import run_all, run_units


def emit(case, **values):
    print(json.dumps({"case": case, **values}, ensure_ascii=True), flush=True)


def main():
    emit("dependencies", python=sys.version, pytest_available=importlib.util.find_spec("pytest") is not None)
    with tempfile.TemporaryDirectory(prefix="runner-observations-") as raw:
        root = Path(raw)
        for name, body in (
            ("empty", ""),
            ("stderr_marker", "import sys\nprint('[FAIL] diagnostic', file=sys.stderr)\n"),
            ("stdout_marker", "print('[FAIL] diagnostic')\n"),
            ("silent_nonzero", "raise SystemExit(2)\n"),
            ("skip_suite", "print('[SKIP-SUITE] dependency missing')\n"),
        ):
            path = root / (name + ".py")
            path.write_text(body, encoding="utf-8")
            direct = subprocess.run([sys.executable, str(path)], capture_output=True, text=True, timeout=5)
            rc, output = run_units._run_subprocess(path, root / "home")
            emit("subprocess_" + name, direct_rc=direct.returncode, direct_stdout=direct.stdout,
                 direct_stderr=direct.stderr, helper_rc=rc, helper_output=output)

        for name, body in (
            ("named_fixture", "def test_x(tmp_path): pass\n"),
            ("custom_fixture", "def test_x(custom_fixture): pass\n"),
            ("class_fixture", "class TestThing:\n    def test_x(self, tmp_path): pass\n"),
            ("async_fixture", "async def test_x(tmp_path): pass\n"),
            ("string_literal", '\"\"\"\ndef test_not_code(tmp_path): pass\n\"\"\"\n'),
        ):
            path = root / (name + ".py")
            path.write_text(body, encoding="utf-8")
            emit("selector_" + name, needs_pytest=run_units._needs_pytest(path))
        invalid = root / "invalid_utf8.py"
        invalid.write_bytes(b"\xff")
        try:
            emit("selector_invalid_utf8", result=run_units._needs_pytest(invalid))
        except UnicodeError as exc:
            emit("selector_invalid_utf8", error_type=type(exc).__name__)

        if importlib.util.find_spec("pytest") is not None:
            for name, body in (
                ("test_zero", "value = 1\n"),
                ("test_ordinary_failure", "def test_failure():\n    assert False, 'ordinary failure'\n"),
                ("test_dependency_phrase", "def test_failure():\n    assert False, 'No module named pytest'\n"),
            ):
                path = root / (name + ".py")
                path.write_text(body, encoding="utf-8")
                rc, output = run_units._run_pytest(path, root / "home")
                emit("pytest_" + name, helper_rc=rc, helper_output=output)
        else:
            emit("pytest_axis", status="unavailable", reason="existing immutable image has no pytest")

        target = root / "target"
        target.mkdir()
        home = root / "home-links"
        home.mkdir()
        link = home / "assets"
        created = run_units._make_junction(link, target)
        emit("asset_link", created=created, is_symlink=link.is_symlink())
        if created:
            (link / "written-through-link.txt").write_text("scratch", encoding="utf-8")
            (home / "ordinary-state.txt").write_text("scratch", encoding="utf-8")
            run_units._reset_writes(home, [link])
            emit("reset_writes", target_write_exists=(target / "written-through-link.txt").is_file(),
                 ordinary_write_exists=(home / "ordinary-state.txt").exists())
            run_units._cleanup_isolated_home(home, [link])
            emit("cleanup", target_exists=target.exists(), target_file_exists=(target / "written-through-link.txt").is_file(),
                 home_exists=home.exists())

        iso_home, links = run_units._build_isolated_home()
        emit("real_pinned_asset_home", created=iso_home is not None, link_count=len(links),
             linked_names=[p.name for p in links], original_root=str(run_units._real_home()))
        if iso_home is not None:
            run_units._cleanup_isolated_home(iso_home, links)
            emit("real_pinned_asset_cleanup", home_exists=iso_home.exists())

        # The original helper records False in its list; no SUT function is replaced.
        from tests import test_autopilot_compaction as compaction
        before = len(compaction._FAILS)
        value = compaction._ok(False, "controlled failed predicate")
        emit("compaction_failure_helper", returned=value, failures_added=len(compaction._FAILS) - before)
        emit("stdout_oracle", marker=run_all._has_failure_token("[FAIL] example text"),
             unbracketed=run_all._has_failure_token("ERROR 1"),
             indented_traceback=run_all._has_failure_token("  Traceback (most recent call last):"))


if __name__ == "__main__":
    main()
