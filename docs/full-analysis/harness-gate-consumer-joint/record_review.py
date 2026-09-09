import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[3]
base = root / '.runtime/absorption/sources/harness'
out = root / 'docs/full-analysis/harness-gate-consumer-joint'
manifest = json.loads((base / 'manifest.json').read_text(encoding='utf-8'))
inventory = {x['path']: x for x in manifest['inventory']}

def record(path, ranges=None):
    item = inventory[path]
    raw = (base / 'pinned' / path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert len(raw) == item['bytes'] and digest == item['snapshot_sha256']
    assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == item['object']
    lines = len(raw.decode('utf-8-sig').splitlines())
    ranges = ranges or [[1, lines]]
    assert all(1 <= a <= b <= lines for a, b in ranges), (path, ranges, lines)
    return {'source': 'harness', 'revision': manifest['revision'], 'path': path, 'bytes': len(raw), 'git_blob': item['object'], 'pinned_sha256': digest, 'line_count': lines, 'read_ranges': ranges, 'read_extent': 'full_body' if ranges == [[1, lines]] else 'explicit_supporting_ranges', 'reader': 'Codex root', 'disposition': 'body_reviewed_call_test_trace_pending', 'review_ref': 'docs/full-analysis/harness-gate-consumer-joint/resolution.md'}

primary = [record('scripts/engine/' + name + '.py') for name in ('checks', 'gate_runner', 'select_ready', 'testgen', 'tick')]
support = [record(path) for path in (
    'scripts/engine/pipeline_loader.py', 'scripts/engine/staleness.py',
    'scripts/engine/gate_ratchet.py', 'scripts/lib/preconditions.py',
    'scripts/cli/residual_cmd.py', 'scripts/cli/testgen_cmd.py',
    'scripts/handlers/stop/reenforce.py', 'scripts/validators/usecase_lint.py',
    'tests/unit/test_checks_smoke.py',
    'templates/_common/usecase.template.md',
)]
support.extend(record(path, ranges) for path, ranges in (
    ('scripts/lib/derive_state.py', [[1, 215]]),
    ('scripts/lib/ledger.py', [[111, 158], [243, 357], [361, 428]]),
    ('scripts/cli/step_cmd.py', [[449, 504]]),
    ('tests/integration/test_engine_smoke.py', [[186, 310]]),
    ('tests/integration/test_small_batch_smoke.py', [[738, 754]]),
))
for name, value in [('files.json', primary), ('supporting-evidence.json', support)]:
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
checkpoint = {'primary_paths': len(primary), 'primary_bytes': sum(x['bytes'] for x in primary), 'supporting_paths': len(support), 'all_recorded_source_hashes_match': True, 'original_executions': 0, 'original_test_executions': 0, 'blocked_normal_writer_probe_retried': False, 'whole_analysis_complete': False, 'adoption_approved': False, 'runtime_implemented': False, 'remaining': ['Complete transitive caller/config/tests and authentication/compaction traces', 'No static report replaces the unexecuted blocked normal-writer probe', 'Actual Windows/Linux/WSL, device, service and financial acceptance remain separate', 'Read final joint resolution for Claude/Codex agreements and corrections']}
(out / 'checkpoint.json').write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(checkpoint))
