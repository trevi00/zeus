"""Review metadata recorder. Never imports or executes upstream code."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PINNED = SOURCE / 'pinned'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8-sig'))
partitions = json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8-sig'))
partition = next(p for p in partitions if p['partition'] == 'baldrix:scripts/cli:003')
inventory = {p['path']: p for p in manifest['inventory']}
notes = json.loads((OUT / 'semantic-notes.json').read_text(encoding='utf-8'))
assert len(partition['paths']) == len(notes) == 14
rows = []
for item in partition['paths']:
    path = item['path']
    raw = (PINNED / path).read_bytes()
    original = inventory[path]
    note = notes[Path(path).name]
    assert sha(raw) == original['snapshot_sha256']
    assert len(raw) == original['bytes']
    tree = ast.parse(raw.decode('utf-8'))  # metadata only; full-body review preceded this
    imports = sorted({node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)})
    rows.append({
        'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
        'git_blob': original['object'], 'pinned_sha256': sha(raw),
        'manifest_bytes': original['bytes'], 'pinned_bytes': len(raw),
        'matches_manifest_sha256': True, 'matches_manifest_bytes': True,
        'read_extent': 'full', 'line_count': len(raw.decode('utf-8').splitlines()),
        'disposition': 'semantically_reviewed',
        'review_ref': 'docs/full-analysis/baldrix-cli-003/semantic-notes.json#' + Path(path).name,
        'semantic_review': note, 'actual_callability': 'python -m cli.' + Path(path).stem + '; main and direct calls read; effective live registration/transitive imports not fully verified',
        'adoption_decision': note['decision'], 'claude_dependencies': note['authority'] + ' Claude homes/assets/state and operator-role contracts are upstream DATA.',
        'windows_linux': note['platform'], 'zeus_modules': [
            'src/codex_harness/application/audit_gate.py',
            'src/codex_harness/domain/model_routing.py',
            'src/codex_harness/domain/project_skills.py',
            'src/codex_harness/adapters/store.py'],
        'zeus_equivalence': 'Architecture mapping only. audit_gate/model_routing fully read; project_skills/store mapped by repository role and AGENTS, not full implementation equivalence.',
        'direct_imports': imports, 'tests_executed': [],
        'test_limits': 'NOT RUN: explicit static-only task. Read test bodies/search hits are not executed receipts. ' + note['tests'],
        'license_status': 'Original upstream license, linked external source/debate/fleet and copied-code provenance not verified.',
        'duplicate_status': 'No file claimed generated or byte-equivalent. Onboard-generated tests examined in template; actual generated outputs/core merge equivalence not reconciled.',
        'remaining': ['Transitive implementation and effective live configuration/caller completion',
                      'Source-specific malformed input, authorization, concurrency and crash regression execution in authorized isolation',
                      'License and external original/source-output provenance verification',
                      'Independent lead/conductor exact-source and current-Zeus revision review; no adoption authorization']})
assert sum(r['pinned_bytes'] for r in rows) == partition['bytes'] == 179681
write('files.json', rows)
support_ranges = {
    'scripts/lib/milestone_gate.py': [(278, 408)],
    'scripts/lib/evaluator_dispatcher.py': [(160, 230), (334, 386), (473, 589)],
    'scripts/lib/operator_ledger.py': [(306, 355)],
    'scripts/lib/mutation_runner.py': [(114, 203)],
    'scripts/lib/mirror_drift.py': [(113, 255)],
    'scripts/lib/validators/structural.py': [(1, 170), (175, 186)],
    'scripts/tests/test_onboard_stack.py': [(1, 165)],
    'scripts/tests/test_output_schema_audit.py': [(1, 207)],
    'scripts/cli/validate_project.py': [(120, 199)],
    'scripts/lib/phase_graph_query.py': [(1, 91)],
    'scripts/lib/phase_graph_builder.py': [(179, 201)],
    'scripts/tests/test_milestone_step.py': [(30, 108)],
    'commands/harness-milestone.md': [(70, 130)],
    'agents/research-stack-onboarder.md': [(60, 86)],
    'skills/kha-plan-phase/SKILL.md': [(48, 75)],
    'commands/harness-pinit.md': [(20, 38)],
    'scripts/lib/milestone_spine.py': [(103, 180)],
}
support = []
for path, ranges in support_ranges.items():
    raw = (PINNED / path).read_bytes()
    lines = raw.splitlines(keepends=True)
    pieces = [{'start_line': lo, 'end_line': hi,
               'raw_range_sha256': sha(b''.join(lines[lo-1:hi]))} for lo, hi in ranges]
    support.append({'source': 'baldrix', 'path': path, 'revision': manifest['revision'],
                    'pinned_sha256': sha(raw), 'line_count': len(lines), 'read_ranges': pieces,
                    'read_extent': 'full' if ranges == [(1, len(lines))] else 'partial',
                    'coverage_role': 'supporting only; no primary disposition change', 'tests_executed': []})
revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
for path in ['src/codex_harness/domain/model_routing.py', 'src/codex_harness/application/audit_gate.py']:
    raw = (ROOT / path).read_bytes()
    support.append({'source': 'zeus', 'path': path, 'observed_head': revision,
                    'working_bytes_sha256': sha(raw), 'read_extent': 'full',
                    'read_ranges': [{'start_line': 1, 'end_line': len(raw.splitlines())}],
                    'coverage_role': 'current working file comparison only; not upstream primary'})
write('supporting-evidence.json', support)
patterns = '|'.join(Path(item['path']).stem for item in partition['paths'])
search = subprocess.run(['rg', '-n', patterns, str(PINNED / 'scripts/tests'), str(PINNED / 'commands'), str(PINNED / 'skills'), str(PINNED / 'agents'), '--glob', '*.py', '--glob', '*.md'], capture_output=True)
(OUT / 'caller-test-search.stdout').write_bytes(search.stdout)
(OUT / 'caller-test-search.stderr').write_bytes(search.stderr)
write('search-receipt.json', {'argv': ['rg', '-n', patterns, 'pinned/scripts/tests', 'pinned/commands', 'pinned/skills', 'pinned/agents', '--glob', '*.py', '--glob', '*.md'],
                             'exit_code': search.returncode, 'stdout_sha256': sha(search.stdout),
                             'stderr_sha256': sha(search.stderr), 'meaning': 'Discovery only, not semantic review. Only supporting ranges marked read.'})
write('checkpoint.json', {'partition': partition['partition'], 'revision': manifest['revision'],
                          'scope_sha256': partition['scope_sha256'], 'primary_total': 14,
                          'primary_bodies_read': 14, 'primary_bytes_read': 179681,
                          'primary_remaining': [], 'body_coverage_complete': True,
                          'partition_complete': False, 'adoption_ready': False,
                          'tests_executed': 0, 'supporting_records': len(support),
                          'remaining': ['Dependency/effective configuration and execution/license/independent adoption gates remain; see per-file rows.'],
                          'stop_reason': 'Bounded primary static review completed; no expansion to another partition.'})
(OUT / 'remaining.txt').write_text('', encoding='utf-8')
write('artifact-hashes.json', [{'path': p.name, 'sha256': sha(p.read_bytes())}
                              for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'artifact-hashes.json'])
print('14 primary bodies, 179681 bytes; hashes match; 0 upstream/test executions; supporting records', len(support))
