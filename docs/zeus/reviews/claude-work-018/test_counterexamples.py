import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

from codex_harness.adapters.scratch import Scratch, file_digest

ROOT = Path.cwd()


def runner():
    spec = importlib.util.spec_from_file_location('review_runner', ROOT / 'scripts/claude_real_call.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def args():
    return SimpleNamespace(label='review', fixture=True, model='claude-stub-normal',
                           budget=1, timeout=60, database_url=os.environ['HARNESS_DATABASE_URL'],
                           redis_url=os.environ['HARNESS_REDIS_URL'])


def test_repeated_label_preserves_first_receipt_bytes(tmp_path):
    module = runner()
    scratch = Scratch.create('zeus-review-073-')
    try:
        first = module.preserve_evidence(scratch, {'preservable': {'diff_text': 'first'}}, tmp_path, 'same')
        original = first['kept'][0]
        second = module.preserve_evidence(scratch, {'preservable': {'diff_text': 'second'}}, tmp_path, 'same')
        assert first['complete'] and second['complete']
        assert file_digest(Path(original['path'])) == original['sha256'], 'second run overwrote first receipt evidence'
    finally:
        scratch.remove()


def test_post_execution_failure_keeps_actual_artifact(tmp_path, monkeypatch):
    from codex_harness.adapters.executor import Executor
    module = runner()
    original = Executor.execute_one
    seen = {}

    def fail_after(self, *a, **kw):
        row = original(self, *a, **kw)
        assert row['status'] == 'succeeded'
        ref = row['result']['execution_ref']
        artifact = self.artifacts.root / (ref[7:] + '.txt')
        assert artifact.is_file()
        seen['artifact'] = artifact
        raise RuntimeError('review injected post-execution collection failure')

    monkeypatch.setattr(Executor, 'execute_one', fail_after)
    module.call(args(), tmp_path)
    receipt = json.loads((tmp_path / 'review-fixture-receipt.json').read_text('utf-8'))
    assert 'artifact' in seen, 'must reach real execution artifact creation'
    assert seen['artifact'].exists() or receipt['preserved']['kept'], (
        'actual artifact deleted while preservation says complete/no evidence')


def test_failed_diff_collection_is_not_complete(tmp_path, monkeypatch):
    module = runner()
    original = module.run
    seen = []

    def fail_diff(argv, **kw):
        if argv[:2] == ['git', 'diff'] and len(argv) == 4:
            seen.append(True)
            return {'argv': argv, 'exit_code': 128, 'stdout': '', 'stderr': 'review diff failed', 'timed_out': False}
        return original(argv, **kw)

    monkeypatch.setattr(module, 'run', fail_diff)
    module.call(args(), tmp_path)
    receipt = json.loads((tmp_path / 'review-fixture-receipt.json').read_text('utf-8'))
    assert seen
    assert receipt['preserved']['complete'] is False, 'failed git diff exported as verified empty evidence'


def test_failed_preservation_is_not_passing_run(tmp_path, monkeypatch):
    module = runner()
    seen = {}

    def fail_preserve(self, destination, entries):
        seen['root'] = self.root
        return {'complete': False, 'kept': [], 'failures': [{'error': 'OSError'}]}

    monkeypatch.setattr(Scratch, 'preserve', fail_preserve)
    try:
        code = module.call(args(), tmp_path)
        receipt = json.loads((tmp_path / 'review-fixture-receipt.json').read_text('utf-8'))
        assert receipt['preserved']['complete'] is False and not receipt['workdir_removed']
        assert code != 0 and receipt['passed'] is False, 'required evidence unavailable but runner exits 0/passed'
    finally:
        if 'root' in seen:
            root = seen['root']
            assert root.resolve().parent == Path(os.environ['TEMP']).resolve()
            assert root.name.startswith('zeus-claude-call-')
            Scratch(root).remove()
