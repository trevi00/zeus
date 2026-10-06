"""Versioned progress for the four-stage reverse documentation workflow.

Behavioral reference: Baldrix b9586c59, reverse_prd_checkpoint and
commands/harness-reverse-prd.md. This is one component, not the full reverse engine.
"""
import re

from codex_harness.domain.model import ContractError, digest, require, utcnow
from codex_harness.ports import AuditArtifacts, Store

STAGES = ('1-A', '1-B', '1-C', '2')
STATUSES = ('pending', 'partial', 'complete')


class ReverseProgress:
    def __init__(self, store: Store, artifacts: AuditArtifacts):
        self.store, self.artifacts = store, artifacts

    @staticmethod
    def _source(source):
        require(isinstance(source, dict), 'Source observation required')
        require(source.get('status') == 'clean', 'Source is dirty or unknown')
        require(isinstance(source.get('repository'), str) and bool(source['repository']),
                'Source repository identity required')
        for name in ('commit', 'tree'):
            require(isinstance(source.get(name), str) and bool(re.fullmatch(
                r'[0-9a-f]{40}|[0-9a-f]{64}', source[name])), 'Invalid source ' + name)
        require(len(source['commit']) == len(source['tree']), 'Mixed source hash formats')
        return {k: source[k] for k in ('repository', 'commit', 'tree')}

    def status(self, project, source):
        with self.store.transaction() as tx:
            row = tx.get('reverse_progress', project)
        if not isinstance(source, dict):
            state = 'unknown'
        elif source.get('status') != 'clean':
            state = source.get('status') if source.get('status') == 'dirty' else 'unknown'
        else:
            try:
                pinned = self._source(source)
                state = ('not_started' if row is None else
                         'unchanged' if row['source'] == pinned else 'changed')
            except ContractError:
                state = 'unknown'
        return {'project': project, 'source_state': state, 'progress': row}

    def record(self, project, stage, status, source, artifact_refs, expected_generation,
               request_id, *, rebaseline=False):
        require(isinstance(project, str) and bool(project), 'Project identity required')
        require(stage in STAGES and status in STATUSES, 'Unknown reverse stage or status')
        require(isinstance(request_id, str) and bool(request_id), 'Request identity required')
        require(type(expected_generation) is int and expected_generation >= 0,
                'Invalid expected generation')
        require(type(rebaseline) is bool, 'Rebaseline must be boolean')
        pinned = self._source(source)
        require(isinstance(artifact_refs, list) and all(isinstance(r, str) for r in artifact_refs),
                'Artifact references must be strings')
        refs = sorted(set(artifact_refs))
        require(status != 'complete' or bool(refs), 'Complete stage requires retained artifacts')
        for ref in refs:
            self.artifacts.inspect(ref)
        command = {'project': project, 'stage': stage, 'status': status, 'source': pinned,
                   'artifact_refs': refs, 'expected_generation': expected_generation,
                   'rebaseline': rebaseline}
        request_key = digest({'project': project, 'request_id': request_id})
        with self.store.transaction() as tx:
            previous = tx.get('reverse_requests', request_key)
            if previous:
                require(previous['command_hash'] == digest(command), 'Conflicting reverse request')
                return previous['result']
            row = tx.get('reverse_progress', project)
            generation = row['generation'] if row else 0
            require(generation == expected_generation, 'Stale reverse progress')
            releases = dict(row['releases']) if row else {}
            if row and row['source'] != pinned:
                require(rebaseline and stage == STAGES[0], 'Source changed; rebaseline required')
                releases = {}
            else:
                require(not rebaseline, 'Rebaseline requires a changed source')
            # INV-REVERSE-001: committed predecessor evidence cannot silently disappear.
            for earlier in STAGES[:STAGES.index(stage)]:
                require(releases.get(earlier, {}).get('status') == 'complete',
                        'Previous reverse stage is incomplete')
                for ref in releases[earlier]['artifact_refs']:
                    self.artifacts.inspect(ref)
            old = releases.get(stage)
            require(not old or old['status'] != 'complete', 'Completed stage is immutable')
            at = utcnow()
            releases[stage] = {'status': status, 'artifact_refs': refs, 'at': at}
            result = {'project': project, 'generation': generation + 1, 'source': pinned,
                      'releases': releases, 'at': at}
            tx.put('reverse_progress', project, result)
            tx.put('reverse_history', digest({'project': project, 'generation': generation + 1}),
                   result)
            tx.put('reverse_requests', request_key, {'command_hash': digest(command),
                                                    'result': result})
            return result
