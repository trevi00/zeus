"""Git-pinned YAML profiles and skills; working-tree initialization is explicit."""
from pathlib import Path
from uuid import uuid4

import yaml

from codex_harness.adapters.project_pipeline import pipeline_context
from codex_harness.domain.model import ContextItem, ContractError, canonical, require
from codex_harness.domain.project_skills import normalize_profile, select_skill_paths

PROFILE = '.harness/tech-stack.yaml'
SKILLS = '.harness/skills/'


class UniqueLoader(yaml.BaseLoader):
    def construct_object(self, node, deep=False):
        require(node.tag in {'tag:yaml.org,2002:str', 'tag:yaml.org,2002:seq',
                             'tag:yaml.org,2002:map'}, 'Unsupported YAML tag')
        return super().construct_object(node, deep=deep)


def unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        require(isinstance(key, str) and key not in result, 'Duplicate or non-string YAML key')
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(text, label='Project profile'):
    """Bounded string-only YAML (no tags, no implicit typing, unique keys); shared by lesson import."""
    require(len(text.encode('utf-8')) <= 65536, label + ' exceeds size limit')
    try:
        value = yaml.load(text, Loader=UniqueLoader)
    except (yaml.YAMLError, RecursionError) as exc:
        raise ContractError('Invalid ' + label + ' YAML') from exc
    pending, count = [(value, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        require(count <= 4096 and depth <= 64, label + ' YAML expansion exceeds limit')
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
        pending.extend((child, depth + 1) for child in children)
    return value


def parse_profile(text):
    value = load_yaml(text)
    return normalize_profile(value)


def import_legacy_profile(text):
    from codex_harness.domain.project_skills import BLOCKS

    value = load_yaml(text)
    require(isinstance(value, dict), 'Legacy profile must be a mapping')
    stacks, stack_fields, unmapped = [], {}, {}
    for role in BLOCKS:
        if role not in value:
            continue
        block = value[role]
        require(isinstance(block, dict), 'Invalid legacy stack block')
        if not block.get('language'):
            unmapped[role] = block
            continue
        stacks.append({k: v for k, v in block.items() if k in {'language', 'framework', 'version'}})
        extra = {k: v for k, v in block.items() if k not in {'language', 'framework', 'version'}}
        if extra:
            stack_fields[role] = extra
    extra = {k: v for k, v in value.items() if k not in {*BLOCKS, 'extensions'}}
    return normalize_profile({'stacks': stacks, 'extensions': value.get('extensions', []),
                              'metadata': {'legacy_fields': extra, 'stack_fields': stack_fields,
                                           'unmapped_stack_blocks': unmapped}})


def initialize(root, text, *, legacy=False):
    root = Path(root).resolve()
    require(root.is_dir(), 'Project root must exist')
    profile = import_legacy_profile(text) if legacy else parse_profile(text)
    profile.setdefault('project_id', str(uuid4()))
    path = root / PROFILE
    require(path.resolve().is_relative_to(root), 'Project profile escapes project root')
    path.parent.mkdir(parents=True, exist_ok=True)
    # INV-PROJECT-001: init never overwrites a user-authored project definition.
    with path.open('x', encoding='utf-8') as stream:
        yaml.safe_dump(profile, stream, sort_keys=False, allow_unicode=True)
    return {'path': str(path), 'profile': profile, 'commit_required': True}


def project_context(git, artifacts, cwd, revision, objective=None):
    cwd = git._git('rev-parse', '--show-toplevel', cwd=cwd)
    raw = git._git('ls-tree', '-rz', revision, '--', '.harness', '.claude/stages.yaml', cwd=cwd, strip=False)
    inventory = {entry.split('\t', 1)[1]: entry.split(' ', 1)[0]
                 for entry in raw.split('\0') if '\t' in entry}
    if PROFILE not in inventory and not any(p in inventory for p in (
            '.harness/stages.yaml', '.claude/stages.yaml')) and not any(
            p.startswith(SKILLS) for p in inventory):
        return [], {'status': 'not_configured', 'selected': 0}
    if PROFILE in inventory:
        require(inventory[PROFILE] in {'100644', '100755'}, 'Profile must be a regular Git file')
    text = git._git('show', revision + ':' + PROFILE, cwd=cwd, strip=False) if PROFILE in inventory else None
    profile = parse_profile(text) if text is not None else normalize_profile({})
    selection = select_skill_paths(profile, [p[len(SKILLS):] for p in inventory if p.startswith(SKILLS)])
    pipeline = pipeline_context(git, artifacts, cwd, revision, profile, load_yaml)
    recommended = {}
    for recommendation in pipeline['recommendations']:
        recommended.setdefault(recommendation['language'], set()).update(recommendation['skills'])
    items, records = [], []
    for relative in selection:
        path = SKILLS + relative
        require(inventory[path] in {'100644', '100755'}, 'Skill must be a regular Git file')
        body = git._git('show', revision + ':' + path, cwd=cwd, strip=False)
        require(len(body.encode('utf-8')) <= 1024 * 1024, 'Skill exceeds input size limit')
        stored = artifacts.put(body, f'git:{revision}:{path}')
        language = relative.split('/', 1)[0]
        names = (set().union(*recommended.values()) if language == '_common' else
                 recommended.get(language, set()) | recommended.get('project', set()))
        boost = 3 if Path(relative).name in names else 0
        pipeline_dims = sorted({f"pipeline:{r.get('stage', {}).get('id', 'unknown')}"
            for r in pipeline['recommendations'] if Path(relative).name in r['skills']
            and (language == '_common' or r['language'] in {language, 'project'})})
        records.append({'path': path, 'content_ref': stored['ref'], 'revision': revision,
                        'pipeline_boost': boost, 'pipeline_dimensions': pipeline_dims,
                        'file': str(artifacts.root / (stored['ref'][7:] + '.txt'))})
        items.append(ContextItem('project-skill:' + path, body, stored['ref'], revision, 15 + boost))
    routing, guidance_summary = {}, {}
    if objective is not None:
        from codex_harness.adapters.skill_routing import route_skills

        items, routing = route_skills(git, artifacts, cwd, revision, objective, items, records)
        from codex_harness.adapters.skill_guidance import guidance_context

        guidance_item, guidance_summary = guidance_context(
            artifacts, revision, objective, records, pipeline)
        items.append(guidance_item)
    manifest = artifacts.put(canonical({'profile': profile, 'revision': revision, 'skills': records,
                                         'pipeline': pipeline, 'routing': routing,
                                         'guidance': guidance_summary}),
                             'project-skill-selection')
    return items, {'status': 'configured' if text is not None else 'common_only',
                   'project_id': profile.get('project_id'),
                   'selected': sum(item.id.startswith('project-skill:') for item in items),
                   'guidance': guidance_summary,
                   'routing': {k: v for k, v in routing.items() if k != 'pattern_evidence'}, 'manifest_ref': manifest['ref'],
                   'pipeline': [{'language': r['language'], 'stage_id': r.get('stage', {}).get('id'),
                                 'phase': r.get('phase', ''), 'verified_complete': False}
                                for r in pipeline['recommendations']],
                   'file': str(artifacts.root / (manifest['ref'][7:] + '.txt')),
                   'instruction': 'Read the manifest with bounded reads for profile metadata and '
                                  'skill file handles; read omitted skill bodies from those files.'}
