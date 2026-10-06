"""Reproduce sibling-test imports in the incumbent release evaluator."""
import os
import subprocess
import sys


def test_incumbent_sibling_imports_use_candidate_package(tmp_path):
    incumbent = tmp_path / 'incumbent' / 'tests'
    incumbent.mkdir(parents=True)
    (incumbent / 'helper.py').write_text('VALUE = 42\n')
    candidate = tmp_path / 'candidate'
    candidate.mkdir()
    package = candidate / 'release_fixture.py'
    package.write_text('VERSION = "candidate"\n')
    old_source = incumbent.parent / 'src'
    old_source.mkdir()
    (old_source / 'release_fixture.py').write_text('VERSION = "incumbent"\n')
    (incumbent / 'test_import.py').write_text(
        'from helper import VALUE\nimport release_fixture\n'
        'def test_source():\n    assert VALUE == 42\n    assert release_fixture.VERSION == "candidate"\n')
    config = candidate / 'pytest.ini'
    config.write_text('[pytest]\n')
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', str(incumbent), '-c', str(config),
         '--import-mode=importlib', '-q'], cwd=candidate,
        env={**os.environ, 'PYTHONPATH': str(incumbent)},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
