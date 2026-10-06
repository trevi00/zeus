"""Explicit-root, read-only project detection; no project code or installers execute."""
import hashlib
import json
import os
import tomllib
from pathlib import Path

from codex_harness.domain.model import ContractError, require
from codex_harness.domain.project_skills import normalize_profile

# Baldrix b9586c59 skill_match.PROJECT_FILE_SIGNALS / PROJECT_DIR_SIGNALS.
FILE_SIGNALS = {
    'package.json': 'node', 'tsconfig.json': 'node', 'pyproject.toml': 'python',
    'requirements.txt': 'python', 'setup.py': 'python', 'Cargo.toml': 'rust',
    'go.mod': 'go', 'pom.xml': 'java', 'build.gradle': 'java',
    'build.gradle.kts': 'kotlin', 'settings.gradle.kts': 'kotlin',
    'pubspec.yaml': 'flutter', 'project.godot': 'godot', 'Gemfile': 'ruby',
    'Dockerfile': 'docker', 'docker-compose.yml': 'docker', 'docker-compose.yaml': 'docker',
}
NODE_FRAMEWORKS = {'react': 'react', 'next': 'nextjs', 'vue': 'vue', 'nuxt': 'nuxt',
                   'svelte': 'svelte', '@angular/core': 'angular', 'express': 'express',
                   'fastify': 'fastify', '@nestjs/core': 'nestjs'}


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate package.json key: ' + key)
        result[key] = value
    return result


def is_home_directory(root):
    try:
        home = Path.home()
    except RuntimeError as exc:
        raise ContractError('Cannot resolve home directory for project boundary check') from exc
    try:
        return root.samefile(home)
    except OSError:
        return os.path.normcase(str(root)) == os.path.normcase(os.path.abspath(home))


def detect_project(root):
    root = Path(root).resolve()
    require(root.is_dir(), 'Project root must be an existing directory')
    require(not is_home_directory(root), 'Home directory is not an implicit project')
    signals, types, contents = [], set(), {}
    entries = {entry.name for entry in root.iterdir()}
    for filename, kind in FILE_SIGNALS.items():
        path = root / filename
        if filename not in entries:
            continue
        require(not path.is_symlink() and path.is_file(), 'Manifest must be a regular file: ' + filename)
        # INV-PROJECT-001: narrow replacement races before opening; not an atomic snapshot.
        require(path.resolve().is_relative_to(root), 'Manifest escapes project root')
        with path.open('rb') as stream:
            data = stream.read(262145)
        require(len(data) <= 262144, 'Manifest exceeds detection size limit: ' + filename)
        signals.append({'kind': 'file', 'path': filename, 'project_type': kind,
                        'sha256': hashlib.sha256(data).hexdigest()})
        types.add(kind)
        contents[filename] = data
    workflows = root / '.github/workflows'
    github = root / '.github'
    if '.github' in entries:
        require(not github.is_symlink(), 'Workflow parent must not be a symlink')
    if '.github' in entries and github.is_dir() and 'workflows' in {p.name for p in github.iterdir()}:
        require(not workflows.is_symlink() and workflows.is_dir(),
                'Workflow signal must be a regular directory')
        require(workflows.resolve().is_relative_to(root), 'Workflow directory escapes project root')
        types.add('github-actions')
        signals.append({'kind': 'directory', 'path': '.github/workflows', 'project_type': 'github-actions',
                        'observation': 'directory presence; workflow contents not inspected'})
    stacks, declarations = [], {}
    if 'node' in types:
        dependencies = {}
        if 'package.json' in contents:
            try:
                package = json.loads(contents['package.json'], object_pairs_hook=unique_json)
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise ContractError('Invalid package.json') from exc
            require(isinstance(package, dict), 'package.json must contain an object')
            for field in ('dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies'):
                values = package.get(field, {})
                require(isinstance(values, dict), 'Invalid package dependency mapping')
                for name, spec in values.items():
                    require(isinstance(spec, str), 'Dependency declarations must be strings')
                    dependencies.setdefault(name, []).append({'field': field, 'spec': spec})
        language = 'typescript' if 'tsconfig.json' in contents or 'typescript' in dependencies else 'javascript'
        frameworks = [(name, framework) for name, framework in NODE_FRAMEWORKS.items() if name in dependencies]
        stacks.extend({'language': language, 'framework': framework} for _, framework in frameworks)
        if not frameworks:
            stacks.append({'language': language})
        declarations.update({name: dependencies[name] for name, _ in frameworks})
        if 'typescript' in dependencies:
            declarations['typescript'] = dependencies['typescript']
    if 'pyproject.toml' in contents:
        try:
            pyproject = tomllib.loads(contents['pyproject.toml'].decode('utf-8-sig'))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ContractError('Invalid pyproject.toml') from exc
        project = pyproject.get('project', {})
        require(isinstance(project, dict), 'Invalid Python project metadata')
        if isinstance(project.get('requires-python'), str):
            declarations['requires-python'] = [{'field': 'project.requires-python',
                                               'spec': project['requires-python']}]
    for kind in sorted(types - {'node', 'docker', 'github-actions'}):
        stacks.append({'language': kind})
    return normalize_profile({'stacks': stacks, 'metadata': {'detection': {
        'root': '.', 'project_types': sorted(types), 'signals': signals,
        'status': 'detected' if types else 'unknown',
        'declarations': declarations,
        'confidence': 'provisional manifest presence and declared dependencies; not runtime verification',
        'version_policy': 'Dependency ranges are retained verbatim; no exact skill version inferred',
        'scope': 'Explicit root only; nested projects require their own detection call',
    }}})
