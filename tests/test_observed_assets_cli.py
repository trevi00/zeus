"""FA-010: manifest registration of observed assets through the adapter CLI."""
import copy
import json

from test_research_audits import audit  # noqa: F401  (fixture reuse)

from codex_harness.adapters.observed_assets import main


def manifest(tmp_path, entries):
    path = tmp_path / 'observed.json'
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
    return path


def test_dry_run_validates_without_writing_and_registration_uses_the_ledger(audit, tmp_path, capsys):  # noqa: F811
    service, record, _, _, _ = audit
    entries = [{'path': 'notes/미커밋.md', 'basis': 'observed', 'state': 'unreviewed_observed_asset',
                'sha256': None, 'size': 12, 'evidence_refs': []},
               {'path': '.cache/index.json', 'basis': 'cache', 'state': 'generated_cache_metadata_only',
                'sha256': None, 'size': None, 'evidence_refs': []}]
    path = manifest(tmp_path, entries)
    before = copy.deepcopy(service.store.data)
    assert main([record['id'], str(path), '--dry-run']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['preview_only'] and report['assets'] == 2 and report['pending'] == 1
    assert service.store.data == before
    assert main([record['id'], str(path)], store=service.store, artifacts=service.artifacts) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['changed'] == 2 and report['pending'] == 1
    coverage = service.coverage(record['id'])
    assert coverage['observed_assets']['total'] == 2 and not coverage['whole_analysis_complete']
    assert main([record['id'], str(path)], store=service.store, artifacts=service.artifacts) == 0
    assert json.loads(capsys.readouterr().out)['changed'] == 0
    for bad in ([], [{'path': ''}], [{'path': 'x', 'basis': 'observed', 'state': 'made_up',
                                       'sha256': None, 'size': None, 'evidence_refs': []}],
                [{'path': 'x', 'basis': 'observed', 'state': 'unreviewed_observed_asset', 'sha256': None,
                  'size': None, 'evidence_refs': [], 'extra': 1}]):
        assert main([record['id'], str(manifest(tmp_path, bad)), '--dry-run']) == 2
        assert 'ContractError' in capsys.readouterr().err
    assert main(['unknown-audit', str(path)], store=service.store, artifacts=service.artifacts) == 2
    assert main([record['id'], str(tmp_path / 'missing.json'), '--dry-run']) == 2
