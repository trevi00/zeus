"""Project stack definitions and deterministic eligibility, independent of file formats."""
import re
from uuid import UUID

from codex_harness.domain.model import require

BLOCKS = ('stack', 'backend', 'frontend', 'mobile')


def segment(value):
    require(isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.+-]*', value))
            and value not in {'.', '..'}, 'Invalid stack path segment')
    return value


def normalize_profile(value):
    require(isinstance(value, dict), 'Project profile must be a mapping')
    require(set(value) <= {'schema_version', 'project_id', 'stacks', 'extensions', 'metadata', *BLOCKS},
            'Unknown project profile field')
    require(str(value.get('schema_version', '1')) == '1', 'Unsupported project profile version')
    require(not ('stacks' in value and any(k in value for k in BLOCKS)),
            'Do not mix canonical stacks and legacy stack blocks')
    stacks = value.get('stacks', [value[k] for k in BLOCKS if k in value])
    require(isinstance(stacks, list), 'Stacks must be a list')
    normalized = []
    for stack in stacks:
        require(isinstance(stack, dict) and set(stack) <= {'language', 'framework', 'version'},
                'Invalid stack definition')
        entry = {'language': segment(stack.get('language'))}
        for key in ('framework', 'version'):
            if stack.get(key):
                entry[key] = segment(stack[key])
        if entry not in normalized:
            normalized.append(entry)
    extensions = value.get('extensions', [])
    require(isinstance(extensions, list), 'Extensions must be a list')
    for extension in extensions:
        require(isinstance(extension, str), 'Extension path must be a string')
        for part in extension.split('/'):
            require(part == '_common' or bool(segment(part)), 'Invalid extension')
    metadata = value.get('metadata', {})
    require(isinstance(metadata, dict), 'Profile metadata must be a mapping')
    result = {'schema_version': '1', 'stacks': normalized,
              'extensions': list(dict.fromkeys(extensions)), 'metadata': metadata}
    if 'project_id' in value:
        identity = value['project_id']
        require(isinstance(identity, str), 'Invalid project UUID')
        try:
            parsed = UUID(identity)
        except ValueError:
            require(False, 'Invalid project UUID')
        require(str(parsed) == identity and parsed.int != 0, 'Invalid project UUID')
        result['project_id'] = identity
    return result


def eligible_paths(profile):
    profile = normalize_profile(profile)
    paths = ['_common']
    for stack in profile['stacks']:
        language, framework, version = (stack.get(k, '') for k in ('language', 'framework', 'version'))
        if framework and version:
            paths.append(f'{language}/{framework}-{version}')
        if framework:
            paths.append(f'{language}/{framework}')
        if version:
            paths.append(f'{language}/{version}')
            # INV-PROJECT-001: `18` and `3.2` both route to their major line (`18.x`, `3.x`).
            major = version.split('.')[0]
            if major.isdigit():
                paths.append(f'{language}/{major}.x')
        paths.extend([f'{language}/lang', language])
    return list(dict.fromkeys(paths + profile['extensions']))


def select_skill_paths(profile, inventory):
    profile = normalize_profile(profile)
    selected = []
    for prefix in eligible_paths(profile):
        for path in sorted(inventory):
            if not path.startswith(prefix + '/'):
                continue
            tail = path[len(prefix) + 1:]
            parts = tail.split('/')
            direct = '/' not in tail and tail.endswith('.md') and not tail.startswith('_')
            # Packaged skills may sit at any depth below an eligible prefix; scanning is not
            # limited to one directory level, only underscore-prefixed directories are skipped.
            packaged = (prefix == '_common' or '/' in prefix or prefix in profile['extensions']) and (
                len(parts) >= 2 and parts[-1] == 'SKILL.md'
                and not any(part.startswith('_') for part in parts[:-1]))
            if direct or packaged:
                selected.append(path)
    return list(dict.fromkeys(selected))
