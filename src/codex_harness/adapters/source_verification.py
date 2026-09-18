"""Read Git objects without checking out or executing upstream content."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from dataclasses import asdict

from codex_harness.adapters.commands import no_console_kwargs
from codex_harness.domain.model import canonical, require
from codex_harness.domain.research import InventoryEntry, SourceIdentity


class GitSourceVerifier:
    def __init__(self, repository, artifacts):
        self.repository, self.artifacts = str(repository), artifacts

    def git(self, *args):
        result = subprocess.run(['git', '--no-replace-objects', '-C', self.repository, *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                                **no_console_kwargs())
        require(result.returncode == 0, 'Source Git inspection failed: '
                + result.stderr.decode('utf-8', errors='replace'))
        return result.stdout

    def inventory(self, source: SourceIdentity):
        source.validate()
        origin = self.git('config', '--get', 'remote.origin.url').decode().strip()
        require(origin.removesuffix('.git') == source.repository, 'Cross-repository source binding')
        require(self.git('cat-file', '-t', source.commit).strip() == b'commit', 'Source is not a commit')
        tree = self.git('rev-parse', source.commit + '^{tree}').decode().strip()
        require(tree == source.tree, 'Changed commit/tree binding')
        entries = []
        for raw in self.git('ls-tree', '-r', '-z', '--full-tree', source.tree).split(b'\0'):
            if not raw:
                continue
            metadata, path = raw.split(b'\t', 1)
            mode, kind, oid = metadata.decode('ascii').split()
            artifact, size = None, None
            if mode == '160000':
                require(kind == 'commit', 'Invalid submodule object')
            else:
                require(kind == 'blob', 'Unsupported tracked object')
                data = self.git('cat-file', 'blob', oid)
                size = len(data)
                artifact = self.artifacts.put(canonical({'version': 1, 'encoding': 'base64',
                    'bytes_sha256': hashlib.sha256(data).hexdigest(),
                    'data': base64.b64encode(data).decode('ascii')}),
                    source.repository + '@' + source.commit + ':' + oid)['ref']
            entry = InventoryEntry(base64.b64encode(path).decode('ascii'), mode, oid, size, artifact)
            entry.validate()
            entries.append(asdict(entry))
        return entries

    def verify(self, source: SourceIdentity, entries: list[InventoryEntry]):
        source.validate()
        for entry in entries:
            entry.validate()
        require(len({e.path for e in entries}) == len(entries), 'Duplicate inventory path')
        manifest = self.artifacts._body(source.manifest_ref)
        expected = {'version': 1, 'repository': source.repository, 'commit': source.commit,
                    'tree': source.tree, 'entries': [asdict(e) for e in entries]}
        require(json.loads(manifest) == expected, 'Manifest/source mismatch')
        actual = self.inventory(source)
        require(sorted(actual, key=lambda e: e['path']) == sorted(expected['entries'], key=lambda e: e['path']),
                'Incomplete or changed source inventory')
        # Read every original envelope even if inventory() found an existing artifact.
        for entry in entries:
            if entry.artifact_ref:
                self.artifacts._body(entry.artifact_ref)
        return expected
