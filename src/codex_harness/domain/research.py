"""Version one source-grounded audit contracts (INV-RESEARCH-001..004)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from codex_harness.domain.model import digest, require


def reference(value: str) -> None:
    require(isinstance(value, str) and bool(re.fullmatch(r'sha256:[0-9a-f]{64}', value)),
            'Invalid immutable evidence reference')


@dataclass(frozen=True)
class SourceIdentity:
    repository: str
    commit: str
    tree: str
    manifest_ref: str
    version: int = 1

    def validate(self):
        require(self.version == 1, 'Unsupported audit version')
        require(bool(re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',
                                  self.repository)), 'Noncanonical repository identity')
        require(not self.repository.endswith('.git'), 'Noncanonical repository identity')
        for value in (self.commit, self.tree):
            require(bool(re.fullmatch(r'[0-9a-f]{40}', value)), 'Invalid Git identity')
        reference(self.manifest_ref)


@dataclass(frozen=True)
class InventoryEntry:
    # Base64 of raw Git path bytes, avoiding Unicode normalization/loss.
    path: str
    mode: str
    object_id: str
    size: int | None
    artifact_ref: str | None

    def validate(self):
        import base64
        try:
            raw = base64.b64decode(self.path, validate=True)
        except ValueError:
            raw = b''
        require(bool(raw) and b'\0' not in raw and not raw.startswith(b'/')
                and all(p not in {b'', b'.', b'..'} for p in raw.split(b'/')), 'Invalid Git path')
        require(self.mode in {'100644', '100755', '120000', '160000'}, 'Unsupported Git mode')
        require(bool(re.fullmatch(r'[0-9a-f]{40}', self.object_id)), 'Invalid Git object')
        require((self.mode == '160000' and self.size is None and self.artifact_ref is None)
                or (self.mode != '160000' and type(self.size) is int and self.size >= 0
                    and self.artifact_ref is not None), 'Missing object size or artifact')
        if self.artifact_ref:
            reference(self.artifact_ref)


OBSERVED_BASES = ('observed', 'cache', 'private_session', 'nested_repository')
OBSERVED_PENDING_STATES = ('unreviewed_observed_asset', 'acquisition_pending',
                           'runtime_surface_classification_pending', 'requires_content_boundary_review',
                           'large_asset_pending_streamed_review',
                           'effective_config_requires_redacted_schema_review')
OBSERVED_FINAL_STATES = ('semantically_reviewed', 'excluded_private_session_or_credential_surface',
                         'generated_cache_metadata_only')


@dataclass(frozen=True)
class ObservedAsset:
    """A local asset outside Git (INV-RESEARCH-001): its own ledger, never the tracked denominator."""
    path: str  # Base64 of raw path bytes, like InventoryEntry.
    basis: str
    state: str
    sha256: str | None
    size: int | None
    evidence_refs: list[str]

    def validate(self):
        import base64
        try:
            raw = base64.b64decode(self.path, validate=True)
        except ValueError:
            raw = b''
        require(bool(raw) and b'\0' not in raw and not raw.startswith(b'/')
                and all(p not in {b'', b'.', b'..'} for p in raw.split(b'/')), 'Invalid observed asset path')
        require(self.basis in OBSERVED_BASES, 'Unknown observed asset basis')
        require(self.state in OBSERVED_PENDING_STATES + OBSERVED_FINAL_STATES, 'Unknown observed asset state')
        require(self.sha256 is None or bool(re.fullmatch(r'[0-9a-f]{64}', self.sha256)), 'Invalid observed asset hash')
        require(self.size is None or (type(self.size) is int and self.size >= 0), 'Invalid observed asset size')
        for ref in self.evidence_refs:
            reference(ref)
        if self.state == 'semantically_reviewed':
            require(self.sha256 is not None and bool(self.evidence_refs),
                    'Reviewed observed asset requires content hash and evidence')

    @property
    def pending(self):
        return self.state in OBSERVED_PENDING_STATES


@dataclass(frozen=True)
class PathDisposition:
    path: str
    disposition: str
    evidence_refs: list[str]
    symbols: list[str]
    justification: str
    links: list[str]
    method: str
    receipt_ids: list[str]

    def validate(self):
        require(self.disposition in {'unreviewed', 'semantic', 'generated', 'duplicate',
                                     'binary', 'unavailable'}, 'Unknown disposition')
        for ref in self.evidence_refs:
            reference(ref)
        if self.disposition not in {'unreviewed', 'unavailable'}:
            require(bool(self.evidence_refs) and bool(self.justification), 'Missing path evidence')
        if self.disposition in {'generated', 'duplicate'}:
            require(bool(self.links), 'Missing generator/original link')
        if self.disposition == 'binary':
            require(bool(self.method) and bool(self.receipt_ids), 'Missing binary inspection receipt')


@dataclass(frozen=True)
class SubsystemAnalysis:
    name: str
    paths: list[str]
    contracts: list[str]
    entry_points: list[str]
    implementations: list[str]
    callers: list[str]
    configuration: list[str]
    storage_authority: list[str]
    failure_paths: list[str]
    tests: list[str]
    receipt_ids: list[str]
    evidence_refs: list[str]
    contradictions: list[str]
    unresolved_dependencies: list[str]
    tests_not_run: list[dict]

    def validate(self):
        for field in ('name', 'paths', 'contracts', 'entry_points', 'implementations', 'callers',
                      'configuration', 'storage_authority', 'failure_paths', 'evidence_refs'):
            require(bool(getattr(self, field)), 'Missing subsystem trace: ' + field)
        # INV-RESEARCH-003: justified unexecuted tests are persistable, incomplete evidence.
        require(bool(self.tests or self.tests_not_run), 'Missing subsystem trace: tests')
        for ref in self.evidence_refs:
            reference(ref)
        require(bool(self.receipt_ids or self.tests_not_run),
                'Missing execution receipts or explicit tests not run')
        for test in self.tests_not_run:
            require(all(test.get(k) for k in ('test', 'reason', 'follow_up')), 'Unexplained test not run')


@dataclass(frozen=True)
class ExecutionReceipt:
    source: SourceIdentity
    environment_revision: str
    command: list[str]
    isolation: str
    exit_status: int
    output_ref: str
    runner_id: str
    inspection_blocked: bool = False
    version: int = 1
    # The runner's own verdict travels with the receipt (review, PR #58): an exit 0 with no output, an
    # all-skip pytest run or diagnostics-only stderr is executed but not passed, and every consumer
    # that grants approval reads `passed`, never exit_status alone.
    passed: bool = False
    outcome: str = 'unclassified'

    def validate(self):
        self.source.validate()
        require(self.version == 1 and self.environment_revision and self.command
                and self.isolation and self.runner_id, 'Incomplete execution receipt')
        require(type(self.passed) is bool and type(self.outcome) is str and self.outcome, 'Execution receipt requires its verdict')
        require(not (self.passed and (self.exit_status != 0 or self.inspection_blocked)),
                'A blocked or non-zero execution cannot be passed')
        require(type(self.exit_status) is int, 'Invalid execution status')
        reference(self.output_ref)

    @property
    def successful(self):
        return self.passed and self.exit_status == 0 and not self.inspection_blocked


def receipt_successful(record):
    """Approval consumers read the runner's verdict; a stored receipt without one is not a pass."""
    return (isinstance(record, dict) and record.get('passed') is True and record.get('exit_status') == 0
            and not record.get('inspection_blocked'))


@dataclass(frozen=True)
class PartitionCheckpoint:
    audit_id: str
    partition_id: str
    generation: int
    paths: list[str]
    subsystems: list[str]
    evidence_refs: list[str]
    remaining_paths: list[str]
    remaining_subsystems: list[str]
    open_questions: list[str]
    cursor: str
    version: int = 1

    def validate(self):
        require(self.version == 1 and self.audit_id and self.partition_id
                and self.generation >= 0 and self.cursor, 'Invalid partition checkpoint')
        for values in (self.paths, self.subsystems, self.remaining_paths, self.remaining_subsystems):
            require(len(values) == len(set(values)), 'Duplicate checkpoint coverage')
        require(set(self.remaining_paths) <= set(self.paths)
                and set(self.remaining_subsystems) <= set(self.subsystems), 'Checkpoint scope changed')
        for ref in self.evidence_refs:
            reference(ref)


@dataclass(frozen=True)
class AdaptationProposal:
    source: SourceIdentity
    scope: list[str]
    source_symbols: list[str]
    behavior: str
    failure_modes: str
    harness_symbols: list[str]
    overlap: str
    boundaries: str
    ssot: str
    six_w: str
    graph_impact: str
    attribution: str
    license_constraints: str
    dependency_constraints: str
    decision: str
    reason: str
    author: str
    version: int = 1

    def validate(self):
        self.source.validate()
        require(self.version == 1 and all(getattr(self, name) for name in self.__dataclass_fields__),
                'Incomplete adaptation mapping')
        require(self.decision in {'adopt', 'adapt', 'defer', 'reject'}, 'Invalid adaptation decision')


@dataclass(frozen=True)
class IndependentReview:
    binding: str
    actor: str
    execution_id: str
    accepted: bool
    license_assessment: str
    dependency_assessment: str
    sre_assessment: str
    architecture_assessment: str
    graph_assessment: str
    version: int = 1

    def validate(self):
        require(self.version == 1 and self.actor in {'lead:research', 'conductor'}
                and all(getattr(self, f) for f in ('binding', 'execution_id', 'license_assessment',
                    'dependency_assessment', 'sre_assessment', 'architecture_assessment',
                    'graph_assessment')), 'Incomplete independent review')


def review_binding(source, evidence, proposal, revision, policy):
    return digest({'source': source, 'evidence': evidence, 'proposal': proposal,
                   'harness_revision': revision, 'policy': policy, 'version': 1})


def research_origin(value):
    if isinstance(value, dict):
        if any(k in value for k in ('source_url', 'research_provenance', 'audit_id', 'source_revision')):
            return True
        return any(research_origin(v) for v in value.values())
    if isinstance(value, list):
        return any(research_origin(v) for v in value)
    return False


def require_dispatch(details):
    # INV-RESEARCH-004: dormant rollout has no executable approval authority.
    # Legacy model verdicts and caller-supplied approval dictionaries cannot unlock it.
    if research_origin(details) or 'proposal' in details:
        require(False, 'Research adoption deferred: verified audit rollout is not active')


CONTRACTS = {cls.__name__: cls for cls in (
    SourceIdentity, InventoryEntry, PathDisposition, SubsystemAnalysis, ExecutionReceipt,
    PartitionCheckpoint, AdaptationProposal, IndependentReview, ObservedAsset)}


def parse_record(document: dict):
    """Strict versioned wire boundary; unknown fields and coerced types fail closed."""
    from dataclasses import fields, is_dataclass
    from types import UnionType
    from typing import get_args, get_origin, get_type_hints

    def decode(kind, value):
        origin, args = get_origin(kind), get_args(kind)
        if origin is UnionType:
            if value is None and type(None) in args:
                return None
            return decode(next(a for a in args if a is not type(None)), value)
        if origin is list:
            require(type(value) is list, 'Expected audit list')
            return [decode(args[0], v) for v in value]
        if is_dataclass(kind):
            require(type(value) is dict and set(value) == {f.name for f in fields(kind)},
                    'Invalid typed audit fields')
            hints = get_type_hints(kind)
            result = kind(**{k: decode(hints[k], v) for k, v in value.items()})
            result.validate()
            return result
        require(type(value) is kind, 'Invalid audit field type')
        return value

    require(type(document) is dict and set(document) == {'version', 'kind', 'record'}
            and type(document['version']) is int and document['version'] == 1
            and document['kind'] in CONTRACTS, 'Unsupported audit envelope')
    return decode(CONTRACTS[document['kind']], document['record'])
