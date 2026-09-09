"""Static review metadata only; no upstream imports or executions."""
import ast
import hashlib
import json
from pathlib import Path
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
SRC=ROOT/'.runtime/absorption/sources/baldrix'
PIN=SRC/'pinned'
manifest=json.loads((SRC/'manifest.json').read_text(encoding='utf-8-sig'))
inv={r['path']:r for r in manifest['inventory']}
part=next(r for r in json.loads((ROOT/'docs/full-analysis/partitions.json').read_text(encoding='utf-8-sig')) if r['partition']=='baldrix:scripts/cli:002')
notes=json.loads((OUT/'semantic-notes.json').read_text(encoding='utf-8'))
def bind(p,extent):
    raw=(PIN/p).read_bytes(); m=inv[p]; sha=hashlib.sha256(raw).hexdigest()
    assert sha==m['snapshot_sha256'] and len(raw)==m['bytes']
    return dict(source='baldrix',path=p,revision=manifest['revision'],git_blob=m['object'],pinned_sha256=sha,manifest_bytes=m['bytes'],pinned_bytes=len(raw),matches_manifest_sha256=True,matches_manifest_bytes=True,read_extent=extent)
full=['scripts/lib/insight_index_pollution_detector.py','scripts/lib/event_store.py','scripts/lib/frontmatter_norm.py','scripts/lib/milestone_spine.py','scripts/lib/endpoint_graph.py','scripts/tests/test_greenfield_spec_emit.py','scripts/tests/test_harness_normalize.py','scripts/cron/run_pollution_cleanup.py']
support=[bind(p,'full') for p in full]+[bind('scripts/handlers/session/init.py','lines 701-725 only; other search hits are not full review')]
(OUT/'supporting-evidence.json').write_text(json.dumps(support,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
targets={Path(r['path']).stem:r['path'] for r in part['paths']}
hits={k:[] for k in targets}
for p in inv:
    if not p.startswith(('scripts/','commands/','skills/')) or not p.endswith(('.py','.md','.yaml','.json')): continue
    lines=(PIN/p).read_text(encoding='utf-8-sig',errors='replace').splitlines()
    for stem,primary in targets.items():
        if p==primary: continue
        matching=[i for i,line in enumerate(lines,1) if 'cli.'+stem in line or 'cli/'+stem+'.py' in line]
        if matching: hits[stem].append(dict(path=p,lines=matching,extent='search_hits_only_not_semantic_review'))
files=[]
for item in part['paths']:
    p=item['path']; name=Path(p).name; note=notes[name]
    row=bind(p,'full')
    tree=ast.parse((PIN/p).read_text(encoding='utf-8'))
    imports=sorted({n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module and n.module.startswith(('cli','lib','validators','engine','cron'))})
    row.update(disposition='semantically_reviewed',review_ref='docs/full-analysis/baldrix-cli-002/semantic-notes.json#'+name,semantic_review=dict(purpose=note[0],analysis=note[1],decision=note[2]),actual_callability='python -m cli.'+Path(p).stem+'; main body reviewed, effective registration and transitive behavior partially unverified',adoption_decision=note[2],claude_dependencies='Claude homes/assets/state/skills/commands and role contracts; original instructions treated as DATA',windows_linux='Native Windows/Linux/WSL not executed in this partition. Source paths/home override and UTF-8/f-string/platform specifics retained in per-file analysis; pathlib/write_text is not cross-platform safety proof.',zeus_modules=['src/codex_harness/application/workflow.py','src/codex_harness/application/monitoring.py','src/codex_harness/domain/policy.py','src/codex_harness/domain/sdd.py'],zeus_equivalence='Architectural mapping only, not exact-current-revision implementation equivalence; CLI should invoke use cases, Git definitions/PostgreSQL runtime and six-W preserved.',direct_imports=imports,caller_config_test_search_hits=hits[Path(p).stem],tests_executed=[],test_limits='NOT RUN: explicit task restriction to static review. Test reading is not execution. Further source/transitive dependencies and fixtures need review before isolated execution.',license_status='Upstream original licenses/private source reports/remote links unverified',duplicate_status='No generated/byte-equivalence claim; generators and helper forwarding discussed semantically, original-output reconciliation incomplete',remaining=['Complete transitive implementation/effective configuration and caller review','Resolve per-file contradictions and malformed/concurrent/crash cases','Verify generator originals/outputs and licenses/external references','Execute matched tests after static dependency review in authorized isolation','Independent lead/conductor exact-revision adoption gates'])
    files.append(row)
assert len(files)==22 and len(notes)==22 and sum(x['pinned_bytes'] for x in files)==191539
(OUT/'files.json').write_text(json.dumps(files,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'remaining.txt').write_text('',encoding='utf-8')
state=dict(source='baldrix',revision=manifest['revision'],partition=part['partition'],scope_sha256=part['scope_sha256'],denominator=22,source_bytes=191539,semantically_reviewed=22,unreviewed=0,body_coverage_complete=True,partition_complete=False,adoption_ready=False,all_manifest_hashes_match=True,tests_executed=0,supporting_full=8,supporting_partial=1,review_ref='docs/full-analysis/baldrix-cli-002/review.md',files_ref='docs/full-analysis/baldrix-cli-002/files.json',workspace=str(ROOT),stop_reason='Bounded primary bodies reviewed; static-only task. Dependencies/configuration/test execution/license/adoption gaps remain explicit.')
(OUT/'checkpoint.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(state,ensure_ascii=False))
