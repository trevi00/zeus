"""Stage recommendations from immutable output observations, never completion approval."""
import re
from pathlib import PurePosixPath

from codex_harness.domain.model import require

SEARCH_DIRS = ('', '.harness', '.harness/design', '.harness/design/db',
               '.harness/design/api', '.claude', '.claude/design',
               '.claude/design/db', '.claude/design/api', 'etc/sql', 'src')


def stages_list(value):
    stages = value.get('stages') if isinstance(value, dict) else value
    require(isinstance(stages, list) and len(stages) <= 256, 'Invalid pipeline stages')
    ids = set()
    for stage in stages:
        require(isinstance(stage, dict), 'Stage must be a mapping')
        sid = stage.get('id')
        require(isinstance(sid, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]+', sid)),
                'Invalid stage id')
        require(sid not in ids, 'Duplicate stage id')
        ids.add(sid)
        for field in ('name', 'dge'):
            require(field not in stage or isinstance(stage[field], str), 'Invalid stage label')
        require(str(stage.get('optional', 'false')).lower() in {'true', 'false'},
                'Invalid optional flag')
        for field in ('output', 'skills'):
            tokens(stage.get(field, ''))
    return stages


def tokens(value, *, skills=False):
    if isinstance(value, list):
        require(all(isinstance(item, str) for item in value), 'Invalid stage list')
        return value
    require(isinstance(value, str), 'Stage field must be a string or list')
    if not value:
        return []
    if skills or (value.startswith('[') and value.endswith(']')):
        return [v.strip().strip('\'"') for v in
                re.split(r'[,\s]+' if skills else ',', value.strip('[]')) if v.strip()]
    return [value]


def merge_stages(core, overlay):
    stages = stages_list(core)
    require(isinstance(overlay, dict), 'Overlay must be a mapping')
    by_id = {stage['id']: stage for stage in stages}
    overrides = overlay.get('stages', {})
    require(isinstance(overrides, dict), 'Invalid stage overrides')
    order = overlay.get('applicable_stages') or list(by_id)
    require(isinstance(order, list) and all(isinstance(sid, str) for sid in order),
            'Invalid applicable stages')
    merged = []
    for sid in order:
        patch = overrides.get(sid, {})
        require(isinstance(patch, dict), 'Invalid stage override')
        merged.append({**by_id.get(sid, {}), **patch, 'id': sid})
    return stages_list(merged)


def recommend(stages, regular_files):
    stages = stages_list(stages)
    if not stages:
        return {'status': 'empty', 'verified_complete': False, 'skills': []}
    paths = set(regular_files)
    directories = {parent.as_posix() for p in paths for parent in PurePosixPath(p).parents
                   if parent.as_posix() != '.'}
    observed, last = [], -1
    for index, stage in enumerate(stages):
        if str(stage.get('optional', 'false')).lower() == 'true':
            continue
        outputs = tokens(stage.get('output', ''))
        matches = []
        for output in outputs:
            # INV-PIPELINE-001: external/parent paths cannot prove a project observation.
            if PurePosixPath(output).is_absolute() or '..' in PurePosixPath(output).parts or '\\' in output:
                continue
            for prefix in SEARCH_DIRS:
                path = (PurePosixPath(prefix) / output).as_posix()
                if path in paths or path in directories:
                    matches.append(path)
        heuristic = any('src/' in output for output in outputs) and 'src' in directories
        if matches or heuristic:
            observed.append({'id': stage['id'], 'matches': sorted(set(matches)),
                             'src_presence_heuristic': heuristic})
            last = index
    selected = stages[min(last + 1, len(stages) - 1)]
    role = selected.get('dge', '')
    return {'status': 'recommended', 'stage': selected, 'observed_outputs': observed,
            'skills': [name if name.endswith('.md') else name + '.md'
                       for name in tokens(selected.get('skills', ''), skills=True)],
            'phase': {'designer': 'plan', 'generator': 'implement', 'evaluator': 'review'}.get(role, ''),
            'incomplete_definition': set(selected) == {'id'},
            'verified_complete': False,
            'basis': 'Committed output presence; no gate or test execution attestation'}
