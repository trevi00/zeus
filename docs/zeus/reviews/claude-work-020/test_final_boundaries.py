import os
import json
from pathlib import Path

import pytest

from test_remaining import runner, args, clean_owned
from codex_harness.adapters.scratch import Scratch
from codex_harness.adapters.call_budget import CallBudget


def test_scandir_denial_is_not_empty(tmp_path, monkeypatch):
    module = runner()
    scratch = Scratch.create('zeus-claude-call-')
    directory = scratch.root / 'artifacts'
    directory.mkdir()
    (directory / 'execution.txt').write_text('actual evidence', encoding='utf-8')
    original = os.scandir
    denied = []

    def scandir(path):
        if Path(path) == directory:
            denied.append(str(path))
            raise PermissionError('review injected OS enumeration denial')
        return original(path)

    monkeypatch.setattr(os, 'scandir', scandir)
    try:
        report = module.preserve_evidence(scratch, {}, tmp_path, 'review', 'denied')
        assert denied
        assert report['complete'] is False, 'Path.rglob suppresses the scandir denial and reports empty'
    finally:
        monkeypatch.undo()
        clean_owned(scratch.root)


@pytest.mark.parametrize('failure', ['preservation', 'settlement'])
def test_real_isolated_ledger_failure_accounting(tmp_path, monkeypatch, failure):
    module = runner()
    ledger = CallBudget(tmp_path / 'isolated-ledger')
    monkeypatch.setattr(module, 'CallBudget', lambda: ledger)
    original_preflight = module.preflight
    original_execute = module.execute

    def preflight(config):
        ready = original_preflight(config)
        assert ready['mode'] == 'fixture'
        return {**ready, 'mode': 'real'}

    def execute(config, receipt, workdir, ready):
        # Exercise the reservation branch with a private real file ledger, but always run
        # the protocol child. Never resolve or start an actual model executable.
        assert config.fixture is True
        return original_execute(config, receipt, workdir, {**ready, 'mode': 'fixture'})

    monkeypatch.setattr(module, 'preflight', preflight)
    monkeypatch.setattr(module, 'execute', execute)
    seen = []
    original_settle = ledger.settle

    def settle(*a, **kw):
        seen.append(True)
        if failure == 'settlement':
            raise OSError('review isolated ledger write failure')
        return original_settle(*a, **kw)

    monkeypatch.setattr(ledger, 'settle', settle)
    if failure == 'preservation':
        (tmp_path / 'review-evidence').write_text('directory creation blocked', encoding='utf-8')
    try:
        code = module.call(args(), tmp_path)
        [file] = list(tmp_path.glob('*-receipt.json'))
        receipt = json.loads(file.read_text('utf-8'))
        assert seen and len(ledger.slots()) == 1, 'must enter actual private ledger settlement'
        if failure == 'preservation':
            assert ledger.slots()[0]['status'] == 'used'
            assert receipt['call_budget_settled'] is True
        else:
            assert ledger.slots()[0]['status'] == 'reserved'
            assert receipt['call_budget_settled'] is False
        assert code != 0 and receipt['passed'] is False, 'settlement failed but runner reports success'
    finally:
        files = list(tmp_path.glob('*-receipt.json'))
        if files:
            root = Path(json.loads(files[0].read_text('utf-8'))['workdir_cleanup']['root'])
            if root.exists():
                clean_owned(root)
