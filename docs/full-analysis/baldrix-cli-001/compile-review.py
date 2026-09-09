"""Inert review metadata assembly; never imports upstream modules."""
import ast
import hashlib
import json
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SOURCE = ROOT / '.runtime/absorption/sources/baldrix'
PIN = SOURCE / 'pinned'
manifest = json.loads((SOURCE / 'manifest.json').read_text(encoding='utf-8-sig'))
inv = {r['path']: r for r in manifest['inventory']}
partition = next(p for p in json.loads((ROOT / 'docs/full-analysis/partitions.json').read_text(encoding='utf-8-sig')) if p['partition'] == 'baldrix:scripts/cli:001')
notes = json.loads((OUT / 'semantic-notes.json').read_text(encoding='utf-8'))
support_full = ['scripts/lib/paths.py', 'scripts/lib/timefmt.py', 'scripts/lib/__init__.py', 'scripts/lib/event_store.py', 'scripts/lib/canary.py', 'scripts/lib/debate_doubts.py', 'scripts/tests/test_debate_landing_contract.py', 'scripts/tests/test_critic_policy_override_cli.py', 'scripts/tests/test_action_evolver_selfcheck.py', 'scripts/tests/test_agents_capability.py', 'scripts/tests/test_agents_normalize.py']
def bound(path, extent):
    raw = (PIN / path).read_bytes()
    meta = inv[path]
    sha = hashlib.sha256(raw).hexdigest()
    assert sha == meta['snapshot_sha256'] and len(raw) == meta['bytes']
    return dict(source='baldrix', path=path, revision=manifest['revision'], pinned_sha256=sha, bytes=len(raw), manifest_bytes=meta['bytes'], pinned_bytes=len(raw), matches_manifest_sha256=True, matches_manifest_bytes=True, git_blob=meta['object'], read_extent=extent)
support = [bound(p, 'full') for p in support_full]
texts = {}
for path in inv:
    if path.startswith(('scripts/', 'commands/', 'skills/')) and path.endswith(('.py', '.md', '.yaml', '.json')):
        texts[path] = (PIN / path).read_text(encoding='utf-8-sig', errors='replace')
files = []
for item in partition['paths']:
    path = item['path']
    name = Path(path).name
    note = notes[name]
    row = bound(path, 'full')
    tree = ast.parse(texts[path])
    imports = sorted({n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(('lib', 'cli', 'cron', 'engine', 'validators'))})
    search = []
    for caller, txt in texts.items():
        if caller == path:
            continue
        hits = [i for i, line in enumerate(txt.splitlines(), 1) if ('cli.' + Path(name).stem in line or 'cli/' + name in line)]
        if hits:
            search.append(dict(path=caller, lines=hits, extent='search_hits_only_not_semantic_review'))
    tests = []
    test_by_source = {'action_evolver.py':'test_action_evolver_selfcheck.py', 'agents_capability.py':'test_agents_capability.py', 'agents_normalize.py':'test_agents_normalize.py'}
    if name in test_by_source:
        receipt = OUT / (test_by_source[name] + '.receipt.json')
        rec = json.loads(receipt.read_text(encoding='utf-8'))
        tests.append(dict(argv=rec['argv'], returncode=rec['returncode'], execution_receipt='docs/full-analysis/baldrix-cli-001/' + receipt.name, receipt_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest()))
    row.update(disposition='semantically_reviewed', review_ref='docs/full-analysis/baldrix-cli-001/semantic-notes.json#' + name, semantic_review=dict(purpose=note[0], analysis=note[1], decision=note[2]), adoption_decision=note[2], actual_callability='Package import only; no standalone command' if name=='__init__.py' else 'python -m cli.' + Path(name).stem + '; entry point body reviewed, effective runtime registration not fully verified', claude_dependencies='CLAUDE_HOME/STATE_DIR/assets roots and Claude-specific producer/role schemas; instructions treated as data', windows_linux='Paths vary by USERPROFILE/HOME, import-time constants versus call-time env. Native Windows/WSL execution not performed. UTF-8 reconfigure coverage differs by module; individual caveats in semantic_review.', zeus_modules=['src/codex_harness/application/workflow.py', 'src/codex_harness/application/monitoring.py', 'src/codex_harness/domain/policy.py', 'src/codex_harness/domain/sdd.py', 'src/codex_harness/adapters/skill_routing.py'], zeus_equivalence='Candidate boundaries only; not current exact-revision feature-equivalence certification. Common98 supporting reads are historical; new Zeus source changes not reviewed in this partition.', direct_imports=imports, caller_config_test_search_hits=search, tests_executed=tests, test_limits='Three isolated Linux test processes only; see receipts. Others not run: transitive imports, live-state/asset dependencies or mutation callbacks not fully reviewed. No native Windows/WSL/live hook/production verification.', license_status='Original upstream license and linked/private source originals not verified', duplicate_status='No byte-equivalence/generated claim; debate_doubts explicitly forwards lib namespace and policy wrappers share structure only', remaining=['Complete transitive dependency and effective registration/configuration review', 'Resolve per-file semantic caveats and malformed/concurrent input cases', 'Verify original licenses and external/private references', 'Run remaining matched tests in reviewed isolation; resolve source-only unavailable fixtures', 'Independent lead/conductor exact-revision adoption gates'])
    files.append(row)
assert len(files)==23 and sum(r['bytes'] for r in files)==199004 and len(notes)==23
(OUT / 'files.json').write_text(json.dumps(files, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
(OUT / 'supporting-evidence.json').write_text(json.dumps(support, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
(OUT / 'remaining.txt').write_text('', encoding='utf-8')
state = dict(source='baldrix', revision=manifest['revision'], partition=partition['partition'], scope_sha256=partition['scope_sha256'], denominator=23, source_bytes=199004, semantically_reviewed=23, unreviewed=0, body_coverage_complete=True, partition_complete=False, adoption_ready=False, all_manifest_hashes_match=True, upstream_execution_processes=3, upstream_assertions_passed=34, supporting_full_reads=11, tests_not_run='All other tests; effective caller/config and transitive dependencies incomplete', workspace=str(ROOT), review_ref='docs/full-analysis/baldrix-cli-001/review.md', files_ref='docs/full-analysis/baldrix-cli-001/files.json', execution_refs=['docs/full-analysis/baldrix-cli-001/'+p.name for p in sorted(OUT.glob('*.receipt.json'))])
(OUT / 'checkpoint.json').write_text(json.dumps(state, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(state, ensure_ascii=False))
