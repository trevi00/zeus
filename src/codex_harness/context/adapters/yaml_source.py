"""The bounded, string-only YAML loader shared by project profiles, skill frontmatter and pipelines.

Layer: adapters
Context: context
Owns: UniqueLoader (no tags, no implicit typing, unique string keys) and `load_yaml` (size, node-count
and depth limits)
Does not own: what a loaded document means (project_skills, skill_routing, project_pipeline)
Entry points: load_yaml, UniqueLoader
Contracts: INV-PROJECT-001, INV-SKILL-001

Moved out of SOURCE M7 `adapters/project_skills.py` unchanged. At M7 `skill_routing` imported
`project_skills.load_yaml` while `project_skills` imported `skill_routing`, an import cycle (the
`project_skills<->skill_routing` SCC of design §2.2); both now import this module, so the cycle is gone.
"""
import yaml

from codex_harness.kernel.errors import ContractError, require


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
