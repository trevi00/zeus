import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters.scratch import Scratch


def runner():
    spec = importlib.util.spec_from_file_location('remaining_runner', Path.cwd() / 'scripts/claude_real_call.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def args():
    return SimpleNamespace(label='review', fixture=True, model='claude-stub-normal', budget=1,
                           timeout=60, database_url=os.environ['HARNESS_DATABASE_URL'],
                           redis_url=os.environ['HARNESS_REDIS_URL'])


def clean_owned(root):
    assert root.name.startswith('zeus-claude-call-')
    assert root.resolve().parent == Path(os.environ['TEMP']).resolve()
    Scratch(root).remove()


@pytest.mark.parametrize('case', ['capped', 'missing_reference'])
def test_empty_entries_does_not_mean_complete(tmp_path, monkeypatch, case):
    module = runner()
    scratch = Scratch.create('zeus-claude-call-')
    try:
        receipt = {}
        if case == 'capped':
            artifact = scratch.root / 'artifacts' / 'execution.txt'
            artifact.parent.mkdir()
            artifact.write_bytes(b'ab')
            monkeypatch.setattr(module, 'SWEEP_BYTE_CAP', 1)
        else:
            receipt['provider_receipt'] = {'execution_ref': 'sha256:' + 'a' * 64}
        report = module.preserve_evidence(scratch, receipt, tmp_path, 'review', case)
        assert report['complete'] is False, 'empty entries bypass capped sweep / required execution reference validation'
    finally:
        clean_owned(scratch.root)


def test_destination_creation_failure_is_reported(tmp_path, monkeypatch):
    module = runner()
    (tmp_path / 'review-evidence').write_text('an existing file blocks directory creation', encoding='utf-8')
    original = module.execute
    seen = {}

    def execute(*a, **kw):
        seen['root'] = a[2]
        return original(*a, **kw)

    monkeypatch.setattr(module, 'execute', execute)
    try:
        code = module.call(args(), tmp_path)
        assert code != 0
        [receipt_path] = list(tmp_path.glob('*-receipt.json'))
        receipt = json.loads(receipt_path.read_text('utf-8'))
        assert receipt['evidence_complete'] is False
        assert receipt['recovery']['scratch']
    finally:
        if 'root' in seen and seen['root'].exists():
            clean_owned(seen['root'])


def test_late_collection_exception_does_not_pass(tmp_path, monkeypatch):
    module = runner()
    original = module.execute
    seen = {}

    def execute(*a, **kw):
        seen['root'] = a[2]
        original(*a, **kw)
        assert a[1]['execution']['status'] == 'succeeded'
        raise RuntimeError('review late collection boundary failure')

    monkeypatch.setattr(module, 'execute', execute)
    try:
        code = module.call(args(), tmp_path)
        [receipt_path] = list(tmp_path.glob('*-receipt.json'))
        receipt = json.loads(receipt_path.read_text('utf-8'))
        assert receipt['error'] and not receipt['workdir_removed']
        assert code != 0 and receipt['passed'] is False, 'unexpected collection failure exits 0/passed'
    finally:
        if 'root' in seen and seen['root'].exists():
            clean_owned(seen['root'])
