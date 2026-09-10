"""Seam extraction from source with a real parser, original byte spans and honest denominators.

One extractor is implemented — Python enums through `ast` — and the registry names every other
stack unsupported: it returns an UNKNOWN observation, never a regex HIGH. Spans are byte offsets
into the exact blob (no comment stripping, no line renumbering); a member whose value is not a
literal is counted as unresolved and the observation is LOW, not HIGH. Discovery sorts before
it caps and reports what it omitted; read, decoding and syntax failures are separate states.
"""
import ast
import hashlib
import os
import sys
from pathlib import Path

from codex_harness.domain.model import require
from codex_harness.domain.seams import contract_identity, parse_observation, unknown_observation

MAX_BLOB_BYTES = 2 * 1024 * 1024
ENUM_BASES = {'Enum', 'IntEnum', 'StrEnum', 'Flag', 'IntFlag'}
EXTENSIONS = {'python': ('.py',)}


def _base_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _line_offsets(data):
    offsets = [0]
    for index, byte in enumerate(data):
        if byte == 0x0A:
            offsets.append(index + 1)
    return offsets


def _span(data, offsets, node):
    """Byte span of a node in the original blob; ast columns are UTF-8 byte offsets already."""
    start = offsets[node.lineno - 1] + node.col_offset
    end = offsets[node.end_lineno - 1] + node.end_col_offset
    return {'start': start, 'end': end, 'line': node.lineno, 'end_line': node.end_lineno,
            'text': data[start:end].decode('utf-8', 'replace')}


def _python_enums(data, package, revision, path):
    parser = f'python-ast-{sys.version_info[0]}.{sys.version_info[1]}'
    source = {'path': path, 'blob_sha': 'sha256:' + hashlib.sha256(data).hexdigest(), 'revision': revision,
              'parser': parser, 'bytes': len(data)}
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        return [unknown_observation(contract_identity('python', package, 'unreadable'), 'enum', source, 'decoding_error', str(exc)[:160])]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return [unknown_observation(contract_identity('python', package, 'unparseable'), 'enum', source, 'unsupported_syntax', str(exc)[:160])]
    offsets = _line_offsets(data)
    observations = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not any(_base_name(b) in ENUM_BASES for b in node.bases):
            continue
        members, unresolved, seen = [], 0, set()
        for statement in node.body:
            if not isinstance(statement, ast.Assign) or len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                continue
            name = statement.targets[0].id
            if name.startswith('_'):
                continue
            if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, (int, str)) \
                    and not isinstance(statement.value.value, bool):
                value = statement.value.value
                members.append({'name': name, 'type': type(value).__name__, 'tag': value, 'span': _span(data, offsets, statement)})
            else:
                unresolved += 1  # a call, expression or alias is not a literal member value
            seen.add(name)
        identity = contract_identity('python', package, node.name)
        found = len(members) + unresolved
        observations.append(parse_observation({
            'identity': identity, 'kind': 'enum', 'members': members,
            'fidelity': 'HIGH' if found and not unresolved else ('LOW' if found else 'UNKNOWN'),
            'denominator': {'symbols_found': found, 'unresolved': unresolved},
            'source': {**source, 'span': _span(data, offsets, node)}}))
    return observations


REGISTRY = {'python': _python_enums}


def extract(stack, root, relative_path, *, revision):
    """Extract every contract of one file; failure to read or parse is a named UNKNOWN observation."""
    require(type(revision) is str and revision, 'Extraction requires the source revision it was read at')
    path = Path(root) / relative_path
    package = Path(relative_path).parent.as_posix().replace('/', '.') or 'root'
    package = package if package != '.' else 'root'
    placeholder = {'path': relative_path, 'blob_sha': 'sha256:' + '0' * 64, 'revision': revision, 'parser': 'none', 'bytes': 0}
    if stack not in REGISTRY:
        return [unknown_observation(contract_identity(stack, package, 'unsupported'), 'enum', placeholder, 'unsupported_stack',
                                    f'no extractor is registered for {stack}; this is not a HIGH observation')]
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return [unknown_observation(contract_identity(stack, package, 'missing'), 'enum', placeholder, 'missing_source', str(path))]
    except OSError as exc:
        return [unknown_observation(contract_identity(stack, package, 'unreadable'), 'enum', placeholder, 'read_error', type(exc).__name__)]
    if len(data) > MAX_BLOB_BYTES:
        source = {**placeholder, 'blob_sha': 'sha256:' + hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        return [unknown_observation(contract_identity(stack, package, 'truncated'), 'enum', source, 'truncated',
                                    f'{len(data)} bytes exceed the {MAX_BLOB_BYTES} byte cap; not read partially')]
    return REGISTRY[stack](data, package, revision, relative_path)


def discover(root, stack, *, max_files=500):
    """Sorted discovery with an explicit cap: what was omitted is counted, never silently dropped."""
    require(type(max_files) is int and max_files > 0, 'max_files must be positive')
    extensions = EXTENSIONS.get(stack, ())
    found = []
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.venv', '__pycache__', 'node_modules'})
        for name in files:
            if name.endswith(extensions):
                found.append(Path(directory, name).relative_to(root).as_posix())
    found.sort()
    return {'stack': stack, 'supported': stack in REGISTRY, 'files': found[:max_files], 'omitted': max(0, len(found) - max_files),
            'found': len(found), 'cap': max_files}
