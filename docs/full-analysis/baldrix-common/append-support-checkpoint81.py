import json,hashlib,subprocess
from pathlib import Path
root=Path.cwd()
out=root/'docs/full-analysis/baldrix-common'
rows=json.loads((out/'supporting-evidence.json').read_text(encoding='utf-8'))
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
man=json.loads((root/'.runtime/absorption/sources/baldrix/manifest.json').read_text(encoding='utf-8-sig'))
idx={i['path']:i for i in man['inventory']}
items=[('zeus',p,'full') for p in ['src/codex_harness/adapters/bus.py','src/codex_harness/adapters/contracts.py','src/codex_harness/resources/message.schema.json','tests/test_bus.py','src/codex_harness/domain/sdd.py','src/codex_harness/adapters/sdd.py','tests/test_sdd.py']]
items += [('zeus','src/codex_harness/cli.py','partial: lines81-116'),('zeus','tests/test_integration.py','partial: lines1-230; trailing test incomplete')]
items += [('baldrix',p,'full') for p in ['scripts/cli/spec_bundle_emit.py','scripts/validators/spec_bundle.py','scripts/lib/spec_bundle.py','scripts/lib/spec_facets.py','scripts/tests/test_spec_bundle_emit.py']]
for source,path,extent in items:
 assert not any(r['source']==source and r['path']==path for r in rows),path
 fp=root/path if source=='zeus' else root/'.runtime/absorption/sources/baldrix/pinned'/path
 b=fp.read_bytes()
 row={'source':source,'path':path,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'read_extent':extent,'tests_executed':False}
 if source=='zeus': row.update(observed_head=head,binding='working-source bytes; not clean-tree or execution attestation')
 else: row.update(revision=man['revision'],git_blob=idx[path]['object'],manifest_matches=row['sha256']==idx[path]['snapshot_sha256'])
 rows.append(row)
(out/'supporting-evidence.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(len(rows))
