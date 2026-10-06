"""Bind currently loaded threshold constants to inspected Git source text."""
from pathlib import Path

from codex_harness.adapters.runtime_thresholds import effective_policy, resolve_policy
from codex_harness.domain.model import digest, require

POLICY_PATHS = (
    'src/codex_harness/domain/skill_ranking.py',
    'src/codex_harness/adapters/skill_routing.py',
    'src/codex_harness/domain/threshold_proposals.py',
    'src/codex_harness/domain/threshold_replay.py',
    'src/codex_harness/domain/skill_audit.py',
    'src/codex_harness/domain/skill_history.py',
    'src/codex_harness/domain/model.py',
    'src/codex_harness/application/threshold_proposals.py',
    'src/codex_harness/adapters/threshold_proposals.py',
    'src/codex_harness/adapters/threshold_policy.py',
    'src/codex_harness/adapters/threshold_reviews.py',
    'src/codex_harness/application/threshold_reviews.py',
    'src/codex_harness/adapters/executor.py',
    'src/codex_harness/application/workflow.py',
    'src/codex_harness/adapters/git.py',
    'src/codex_harness/adapters/commands.py',
    'src/codex_harness/adapters/artifacts.py',
    'src/codex_harness/adapters/store.py',
    'src/codex_harness/domain/policy.py',
    'src/codex_harness/resources/organization.json',
    'src/codex_harness/adapters/runtime_thresholds.py',
    'src/codex_harness/resources/threshold-policy.json',
    'src/codex_harness/domain/skill_admission.py',
    'src/codex_harness/adapters/native_routing_replay.py',
)


def current_policy(git, revision='HEAD'):
    # INV-THRESHOLD-PROPOSAL-001: a separate, unused policy file is not live policy.
    require(isinstance(revision, str) and not revision.startswith('-'), 'Invalid policy revision')
    commit = git._git('rev-parse', '--verify', revision + '^{commit}')
    raw = git._git('ls-tree', '-rz', commit, '--', *POLICY_PATHS, strip=False)
    inventory = {entry.split('\t', 1)[1]: entry.split(' ', 1)[0]
                 for entry in raw.split('\0') if '\t' in entry}
    root = Path(__file__).resolve().parents[1]
    sources = {}
    for path in POLICY_PATHS:
        require(inventory.get(path) in {'100644', '100755'}, 'Missing regular policy source')
        committed = git._git('show', commit + ':' + path, strip=False)
        loaded = (root / path.removeprefix('src/codex_harness/')).read_text(encoding='utf-8')
        require(committed == loaded, 'Loaded threshold source differs from selected Git revision')
        sources[path] = {'text': committed, 'hash': digest(committed)}
    policy = effective_policy()
    require(policy == resolve_policy(sources['src/codex_harness/resources/threshold-policy.json']['text']),
            'Loaded routing threshold differs from definition')
    return {'revision': commit, 'values': policy['values'],
            'sources': sources, 'kind': 'current_native_git_policy',
            'encoding': 'UTF-8 text with normalized newlines'}
