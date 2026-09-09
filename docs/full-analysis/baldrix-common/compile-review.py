"""Review artifact generator only: inert pinned bytes/manifest, no upstream imports."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8-sig'))
notes = {}
origins = {}
for path in sorted(OUT.glob('*-notes.json')):
    for name, note in json.loads(path.read_text(encoding='utf-8')).items():
        assert name not in notes, name
        notes[name] = note
        origins[name] = path.name
files = []
for item in manifest['inventory']:
    path = item['path']
    if not path.startswith('skills/_common/'):
        continue
    data = (SOURCE / 'pinned' / path).read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    name = path.removeprefix('skills/_common/')
    note = notes.get(name)
    row = {
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
        'git_blob': item['object'], 'manifest_bytes': item['bytes'],
        'pinned_bytes': len(data), 'pinned_sha256': sha,
        'matches_manifest_sha256': sha == item.get('snapshot_sha256'),
        'matches_manifest_bytes': len(data) == item['bytes'],
        'disposition': 'semantically_reviewed' if note else 'unreviewed',
        'review_ref': ('docs/full-analysis/baldrix-common/' + origins[name] + '#' + name
                       if note else 'docs/full-analysis/baldrix-common/remaining.txt'),
        'semantic_review': note,
        'actual_callability': ('Not collected: underscore authoring template' if name == '_template.md'
                              else 'Not collected: YAML authoring template' if name == 'tech-stack-template.yaml'
                              else 'Generic prompt-advisory candidate via score and budgets; no dedicated executable enforcement proven')
                             if note else 'Not semantically evaluated',
        'claude_dependencies': note['platform'] if note else 'Unreviewed',
        'windows_linux': note['platform'] if note else 'Unreviewed',
        'zeus_modules': {
            'confirmed_common_overlap': [
                'src/codex_harness/adapters/skill_routing.py',
                'src/codex_harness/domain/skill_admission.py',
                'src/codex_harness/domain/skill_guidance.py'],
            'feature_equivalence': 'Not established; specific counterpart in semantic_review. Git/PostgreSQL SSOT and six-W retained.'
        } if note else None,
        'adoption_decision': note['decision'] if note else 'defer_unreviewed',
        'tests_executed': [],
        'test_limits': 'Not run. Source/test reading and review hash validation only. Requires isolated no-network read-only-source execution receipts. No source code imported or executed.',
        'license_status': 'Unverified; no original/license equivalence established',
        'external_links': 'Remote originals not fetched; source assertions only',
        'duplicate_status': 'No generated/duplicate equivalence claimed' if note else 'Unreviewed',
        'remaining': ['Resolve specific analysis caveats',
                      'Complete dependency/registration and original-license/link verification',
                      'Execute isolated matched tests and record receipts',
                      'Independent reviewer/conductor adoption gates'] if note else
                     ['Read entire UTF-8 file semantically', 'Trace caller/implementation/configuration/tests',
                      'Record per-file decision and adaptation', 'Verify license/original links and run isolated tests']
    }
    if name == 'tech-stack-template.yaml':
        receipts = []
        for receipt_name in ['test-tech-stack-receipt.json', 'template-inline-comment-probe.json']:
            receipt_path = OUT / receipt_name
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                receipts.append({'argv': receipt['argv'], 'returncode': receipt['returncode'],
                                 'execution_receipt': 'docs/full-analysis/baldrix-common/' + receipt_name,
                                 'kind': receipt['kind']})
        row['tests_executed'] = receipts
        if receipts:
            row['test_limits'] = ('Linux Python3.13 isolated actual source test17 cases passed; separate reviewer probe confirms inline-comment defect. '
                                  'No native Windows/full hook/production verification; reviewer receipts do not create Zeus fenced audit approval.')
    assert row['matches_manifest_sha256'] and row['matches_manifest_bytes'], path
    files.append(row)
assert len(files) == 98
assert set(notes) <= {f['path'].removeprefix('skills/_common/') for f in files}
(OUT / 'files.json').write_text(json.dumps(files, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
remaining = [f['path'] for f in files if f['disposition'] == 'unreviewed']
(OUT / 'remaining.txt').write_text('\n'.join(remaining) + '\n', encoding='utf-8')
status = {'source': 'baldrix', 'revision': manifest['revision'], 'denominator': 98,
          'source_bytes': sum(f['manifest_bytes'] for f in files),
          'semantically_reviewed': len(notes), 'unreviewed': len(remaining),
          'tests_executed': sum(len(f['tests_executed']) for f in files),
          'upstream_test_cases_passed': 17 if (OUT / 'test-tech-stack-receipt.json').exists() else 0,
          'partition_complete': False, 'adoption_ready': False,
          'all_manifest_hashes_match': True,
          'review_refs': ['docs/full-analysis/baldrix-common/' + p.name for p in sorted(OUT.glob('*-notes.json'))]}
(OUT / 'status.json').write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(status, ensure_ascii=False))
