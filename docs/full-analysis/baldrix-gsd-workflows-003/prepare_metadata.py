"""Prepare owned inert review metadata; no source imports or source execution."""

import json
import re
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-gsd-workflows-003'
PIN = ROOT / '.runtime/absorption/sources/baldrix/pinned'
for name in ['record_review.py', 'check_metadata.py', 'order_notes.py']:
    content = (ROOT / 'docs/full-analysis/baldrix-gsd-references-001' / name).read_text(encoding='utf-8')
    for before, after in [
        ('baldrix-gsd-references-001', 'baldrix-gsd-workflows-003'),
        ('baldrix:get-shit-done/references:001', 'baldrix:get-shit-done/workflows:003'),
        ('9d4101a80187e82f3fe8beccb5294e3825496e7baffb489e2b398c0c17c3ff77',
         '4bb1361ed48b4e09ccea7f76f397e57cc5b5d0fe2982c06d0fa1b9e7c2bfb432'),
        ('5acaeced22de71ae3eb8584643e00557762745c0', '31d5091407566d4988980485246ed031784203b2'),
        ('178518', '184092'), ('reads32', 'reads17'), ('Ordered32', 'Ordered17'),
    ]:
        content = content.replace(before, after)
    content = re.sub(r'\b32\b', '17', content)
    content = re.sub(r'\b20\b', '24', content)
    (OUT / name).write_text(content.rstrip() + '\n', encoding='utf-8', newline='\n')

specs = [
    ['get-shit-done/bin/lib/init.cjs', [[296, 471], [819, 1124], [1297, 1387]], [6, 7, 8, 10, 11, 12]],
    ['get-shit-done/bin/gsd-tools.cjs', [[324, 390], [602, 636], [940, 954]], [4, 10, 11, 13, 17]],
    ['get-shit-done/bin/lib/phase.cjs', [[393, 488]], [4]],
    ['get-shit-done/bin/lib/milestone.cjs', [[249, 282]], [10]],
    ['get-shit-done/bin/lib/core.cjs', [[307, 351], [583, 628]], [1, 4, 11]],
    ['get-shit-done/bin/lib/config.cjs', [[198, 242]], [11]],
    ['get-shit-done/bin/lib/profile-output.cjs', [[911, 1010]], [11]],
    ['get-shit-done/workflows/execute-plan.md', [[326, 374]], [14]],
    ['get-shit-done/workflows/resume-project.md', [[60, 104]], [16]],
]
wrappers = [
    ('kha-advance', 13), ('kha-capture-note', 15), ('kha-help', 1),
    ('kha-import-plan', 2), ('kha-insert-phase', 4), ('kha-list-workspaces', 6),
    ('kha-map-codebase', 8), ('kha-milestone-manager', 7), ('kha-milestone-summary', 9),
    ('kha-new-milestone', 10), ('kha-new-project', 11), ('kha-new-workspace', 12),
    ('kha-pause-work', 16), ('kha-phase-assumptions', 5), ('kha-plan-gap-phases', 17),
]
for name, index in wrappers:
    path = f'skills/{name}/SKILL.md'
    specs.append([path, [[1, len((PIN / path).read_bytes().splitlines())]], [index]])
(OUT / 'support-specs.json').write_text(json.dumps(specs, indent=2) + '\n', encoding='utf-8', newline='\n')
print('Prepared 3 owned recorders and 24 actual-read support specifications.')
