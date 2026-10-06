"""Git-owned overrides plus byte-pinned Baldrix pipeline assets."""
import hashlib
import json
from importlib.resources import files

from codex_harness.domain.model import require
from codex_harness.domain.pipeline import merge_stages, recommend, stages_list


def pipeline_context(git, artifacts, cwd, revision, profile, load_yaml):
    raw = git._git('ls-tree', '-rz', revision, cwd=cwd, strip=False)
    inventory = {entry.split('\t', 1)[1]: entry.split(' ', 1)[0]
                 for entry in raw.split('\0') if '\t' in entry}
    regular = [path for path, mode in inventory.items() if mode in {'100644', '100755'}]
    sources = []
    override = next((path for path in ('.harness/stages.yaml', '.claude/stages.yaml')
                     if path in inventory), '.harness/stages.yaml')
    if override in inventory:
        require(override in regular, 'Pipeline override must be a regular Git file')
        body = git._git('show', revision + ':' + override, cwd=cwd, strip=False)
        source = artifacts.put(body, f'git:{revision}:{override}')
        sources.append(source['ref'])
        definitions = [('project', stages_list(load_yaml(body)), {})]
    else:
        root = files('codex_harness.resources').joinpath('baldrix_pipeline')
        provenance = json.loads(root.joinpath('provenance.json').read_text('utf-8'))
        hashes = {p['destination']: p['sha256'] for p in provenance['files']}

        cache = {}

        def read(name):
            if name in cache:
                return cache[name]
            require(name in hashes, 'Pipeline asset missing from provenance')
            body = root.joinpath(name).read_bytes()
            require(hashlib.sha256(body).hexdigest() == hashes[name], 'Pipeline asset drift')
            stored = artifacts.put(body.decode('utf-8'),
                                   f'baldrix:{provenance["revision"]}:{name}')
            sources.append(stored['ref'])
            cache[name] = load_yaml(body.decode('utf-8'))
            return cache[name]

        definitions = []
        languages = list(dict.fromkeys(stack['language'] for stack in profile['stacks']))
        for language in languages:
            alias = {'typescript': 'node', 'javascript': 'node'}.get(language, language)
            overlay_path = f'overlays/{alias}.overlay.yaml'
            if overlay_path in hashes:
                overlay = read(overlay_path)
                definitions.append((language, merge_stages(read('stages.core.yaml'), overlay),
                                    {k: v for k, v in overlay.items() if k != 'stages'}))
            else:
                variant = f'stages-{alias}.yaml'
                definitions.append((language, stages_list(read(
                    variant if variant in hashes else 'stages.yaml')), {}))
    recommendations = []
    for language, stages, metadata in definitions:
        recommendations.append({'language': language, **recommend(stages, regular),
                                'overlay_metadata': metadata})
    return {'revision': revision, 'definitions': list(dict.fromkeys(sources)),
            'recommendations': recommendations, 'verified_complete': False}
