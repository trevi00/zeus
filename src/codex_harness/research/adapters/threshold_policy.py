"""Bind currently loaded threshold constants to inspected Git source text.

Layer: adapters
Context: research
Owns: GIT_PREFIX, POLICY_PATHS, current_policy, the binding of the loaded threshold constants to the source text of one Git revision
Does not own: the registry and the definition rules (research.domain.threshold_proposals, research.adapters.runtime_thresholds), the Git reader (host_os's GitWorkspace) and the CLI (entry.cli.threshold_proposals)
Entry points: current_policy, POLICY_PATHS, GIT_PREFIX
Contracts: INV-THRESHOLD-PROPOSAL-001

Moved from M7 `adapters/threshold_policy.py` (SOURCE e38aa722) by rule R-c19 R-t3 (S10 unit T1, DESIGN-s8 section 18 V20). `POLICY_PATHS` lists the target homes of M7's 24 sources (a split source lists every home), relative to the package root `codex_harness/`. `GIT_PREFIX` is where those paths sit in the Git tree: the `ls-tree` and `show` paths are `GIT_PREFIX + entry`.
S11 unit P (DESIGN-s11 §20.5): `GIT_PREFIX` is "src/" since the promotion made the target the repository root (it was "target/src/" before; the S10 T1 carry).
Owner correction of the V20 text: V20 section 18 says `parents[2]` while also writing the paths with `codex_harness/`; only `parents[3]` (`target/src/`) resolves them, so the loaded file is `Path(__file__).resolve().parents[3] / entry`. The `sources` dict is keyed by the package-relative entry. Every other statement is M7's.
"""
from pathlib import Path

from codex_harness.kernel.errors import require
from codex_harness.kernel.ids import digest
from codex_harness.research.adapters.runtime_thresholds import effective_policy, resolve_policy

GIT_PREFIX = 'src/'

POLICY_PATHS = (
    'codex_harness/context/domain/skills/ranking.py',
    'codex_harness/context/adapters/skill_routing.py',
    'codex_harness/research/domain/threshold_proposals.py',
    'codex_harness/research/domain/threshold_replay.py',
    'codex_harness/context/domain/skills/audit.py',
    'codex_harness/context/domain/skills/history.py',
    'codex_harness/kernel/ids.py',
    'codex_harness/kernel/errors.py',
    'codex_harness/kernel/message.py',
    'codex_harness/routing/domain/organization.py',
    'codex_harness/context/domain/packet.py',
    'codex_harness/research/application/threshold_proposals.py',
    'codex_harness/entry/cli/threshold_proposals.py',
    'codex_harness/research/adapters/threshold_policy.py',
    'codex_harness/research/adapters/threshold_reviews.py',
    'codex_harness/research/application/threshold_reviews.py',
    'codex_harness/execution/application/run_task.py',
    'codex_harness/review/application/decisions.py',
    'codex_harness/coordination/application/workflow.py',
    'codex_harness/coordination/application/messages.py',
    'codex_harness/host_os/adapters/git_workspace.py',
    'codex_harness/host_os/adapters/process_groups.py',
    'codex_harness/host_os/adapters/windows/no_console.py',
    'codex_harness/storage/adapters/file_artifacts.py',
    'codex_harness/storage/adapters/postgres_store.py',
    'codex_harness/storage/adapters/memory_store.py',
    'codex_harness/kernel/policy.py',
    'codex_harness/resources/organization.json',
    'codex_harness/research/adapters/runtime_thresholds.py',
    'codex_harness/resources/threshold-policy.json',
    'codex_harness/context/domain/skills/admission.py',
    'codex_harness/context/adapters/native_routing_replay.py',
)


def current_policy(git, revision='HEAD'):
    # INV-THRESHOLD-PROPOSAL-001: a separate, unused policy file is not live policy.
    require(isinstance(revision, str) and not revision.startswith('-'), 'Invalid policy revision')
    commit = git._git('rev-parse', '--verify', revision + '^{commit}')
    raw = git._git('ls-tree', '-rz', commit, '--', *(GIT_PREFIX + entry for entry in POLICY_PATHS), strip=False)
    inventory = {entry.split('\t', 1)[1]: entry.split(' ', 1)[0]
                 for entry in raw.split('\0') if '\t' in entry}
    root = Path(__file__).resolve().parents[3]
    sources = {}
    for entry in POLICY_PATHS:
        path = GIT_PREFIX + entry
        require(inventory.get(path) in {'100644', '100755'}, 'Missing regular policy source')
        committed = git._git('show', commit + ':' + path, strip=False)
        loaded = (root / entry).read_text(encoding='utf-8')
        require(committed == loaded, 'Loaded threshold source differs from selected Git revision')
        sources[entry] = {'text': committed, 'hash': digest(committed)}
    policy = effective_policy()
    require(policy == resolve_policy(sources['codex_harness/resources/threshold-policy.json']['text']),
            'Loaded routing threshold differs from definition')
    return {'revision': commit, 'values': policy['values'],
            'sources': sources, 'kind': 'current_native_git_policy',
            'encoding': 'UTF-8 text with normalized newlines'}
