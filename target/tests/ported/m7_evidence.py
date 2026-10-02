"""M7 evidence surface (inspections, the isolated/project inspectors, completion authority, gate verdicts) over the S8
target, for the ported M7 suites `test_evidence_inspection`, `test_isolated_evidence`, `test_project_evidence`,
`test_operation_environment`, `test_completion_authority`, `test_gate_verdicts` and `test_runner_categories`.

Layer: harness (never shipped). A TEST shim: it lets those M7 suites run, with their assertions unchanged, against the
moved evidence objects as `compare/drivers/target/s8_evidence_inspector.py`, `s8_isolated_inspector.py`,
`s8_project_inspector.py`, `s8_evidence_inspections.py` and `s8_completion.py` build them. Ids and clocks are NOT
scripted here: as in M7 the real clock and uuid4 are used.

Named adaptations (each is a construction/import/patch-target adaptation, never a behaviour change):
- `EvidenceInspector(artifacts, policy=None, interpreter=None)` and `ProjectEvidenceInspector(artifacts, profile,
  policy=None, interpreter=None)` are the moved classes with the host_os `ProcessTree` CLASS injected as
  `process_tree` (E-4c/E-4d; composition passes the class itself, so a test that replaces `ProcessTree.spawn` on it
  is seen by every spawn).
- `DockerEvidenceInspector(artifacts, isolation, root, docker="docker", policy=None)` and
  `IsolatedProjectEvidenceInspector(artifacts, profile, isolation, root, docker="docker", policy=None)` are the moved
  classes with `containers=ContainerEvidenceReplay(isolation, root, docker, runner=run_process)` (the execution-owned
  container replay, E-2, over the production `run_process`) and `process_tree=ProcessTree` injected. Their attached
  capture (`_capture_fn`) is the module's `_capture` as a test replaced it, read at call time: M7's replay called the
  module global `_capture`, which cases replace with `monkeypatch.setattr(ie, "_capture", ...)`.
- `ei` stands for the module M7 cases patched (`codex_harness.adapters.evidence_inspection`): a facade over
  `evidence.adapters.evidence_inspection`. A name reads from the module and an assignment lands on the module (so
  `READER_JOIN_SECONDS` is seen by the capture); `ProcessTree` is the host_os class the inspectors are built with (M7's
  module imported it, and a case replaces `ei.ProcessTree.spawn`); `_capture` is M7's `_capture(argv, cwd, timeout,
  max_bytes, env, progress=None)` with that class bound as the `process_tree` the moved function takes.
- `ie` stands for `codex_harness.adapters.isolated_evidence`: a facade over `evidence.adapters.isolated_evidence` with the
  inspector classes above, and a settable `_capture` (the default is the bound capture above).
- `iw` (isolated worker) is `m7_containers.iw`; the case that replaced `iw._docker` calls `m7_containers.install_docker`
  and the cases that replaced `iw._write_record` or a method of `iw.OwnedContainer` patch the owning target module/class
  (`cleanup_ledger._write_record`, `owned_container.OwnedContainer`), named in the ported file.
- The M7 `packaged_policy`, `replay_environment`, `replay_argv`, `trusted_interpreter`, `KEEP_ENV`, `POLICY_FILE`
  are the module's own; `EvidenceInspections(store, inspector)` and `BUCKET`, `NOTICES` the application's;
  `CompletionAuthority(store, artifacts=None, org=None)` is the moved class unchanged.
- The M7 domain names are `evidence.domain.evidence`, `evidence.domain.project_evidence`,
  `evidence.domain.check_results`, `evidence.domain.gate_verdicts` and `kernel.ids`/`kernel.errors`.
- `SDD(store, artifacts, human_provider=None)` is the moved class with its two ports injected, as
  `compare/drivers/target/s8_sdd.py` does: intake's `ticket_binding` and the kernel's system clock. `SOURCE` is a verbatim
  copy of `tests/test_sdd.py`'s `SOURCE` (DESIGN-s8 §29.2: that suite is P8's and not yet ported); `spec_data` of the same
  module is `load_json(SPEC)` over the M7 file loader `adapters.sdd.load_json`, whose ledger home
  (`review.adapters.sdd:load_json`) is designed and absent on the target, so `spec_data` is a placeholder
  (`unavailable("S8", ...)`) and only the tests that call it are skipped.
- `audit`, `FixtureRunner`, `activate_fixture`, `complete_fixture_audit` and `lease_review` are VERBATIM copies of the
  helpers of `tests/test_research_audits.py` (P3's suite, not yet ported: DESIGN-s8 §29.2), AST-equal to M7 modulo their
  in-function import lines (module imports here) and two constructions: the verifier gets host_os's `ChokepointProcesses` as
  `processes`, and `ResearchAudits` is built with its three ports as `s8_audit_core.py` builds it (coordination's
  `ExecutionRecovery` with research's `audit_gate.binding`, `Outbox`, `PendingDecisions`; the system clock and ids).
  `Workflow(store, org)` is `m7_coordination.Workflow`, `Releases` is `m7_delivery.Releases`. They are replaced by imports
  from the ported suite when P3 lands.
- `source_execution` stands for the module M7 cases patched (`codex_harness.adapters.source_execution`): a facade over
  `research.adapters.source_execution`. `bounded_command` and `run_process` assignments install M7's two-argument
  callables: `bounded_command` behind a wrapper taking the moved function's keyword-only `processes`, and `run_process` as
  the `run_process` port the runner built here calls at call time (default: the production `run_process`). The case patches
  `m7_evidence.source_execution.<name>`. `DockerSourceRunner(root, artifacts, docker="docker")` is the moved class with
  `processes` (host_os's `ChokepointProcesses`), `run_process` (that port) and `classify`
  (`review.domain.check_results.classify_isolated_run`) injected (R-se2).
- `identity` (M7 `adapters.operation_cli.identity`) and the executor/bootstrap names are NOT here (S10): only tests
  skipped whole, with the owning slice, name them.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import m7_containers
import pytest
from m7_coordination import Workflow, organization, unavailable  # noqa: F401
from m7_delivery import Releases

from codex_harness.coordination.application import execution_recovery
from codex_harness.coordination.application.decisions import PendingDecisions
from codex_harness.coordination.application.outbox import Outbox
from codex_harness.evidence.adapters import evidence_inspection as _ei
from codex_harness.evidence.adapters import isolated_evidence as _ie
from codex_harness.evidence.adapters import project_evidence as _pe
from codex_harness.evidence.application.completion import (  # noqa: F401
    BUCKET as COMPLETION_BUCKET,
)
from codex_harness.evidence.application.completion import (  # noqa: F401
    EVALUATION_KIND,
    REJECTIONS,
    STATES,
    CompletionAuthority,
)
from codex_harness.evidence.application.evidence_inspection import (  # noqa: F401
    BUCKET,
    NOTICES,
    EvidenceInspections,
)
from codex_harness.evidence.domain import evidence as domain_evidence  # noqa: F401
from codex_harness.evidence.domain.project_evidence import (  # noqa: F401
    CONTAINER_INTERPRETER,
    SCHEMA,
    SCHEMA_V2,
    observed_checks,
    parse_profile,
    requires_container,
    worker_schema,
)
from codex_harness.execution.adapters.containers import cleanup_ledger
from codex_harness.execution.adapters.containers.evidence_replay import ContainerEvidenceReplay
from codex_harness.execution.domain import container_spec
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters.process_tree import ProcessTree
from codex_harness.intake.application.tickets import ticket_binding
from codex_harness.kernel.errors import ContractError  # noqa: F401
from codex_harness.kernel.ids import SYSTEM_CLOCK, SYSTEM_IDS, canonical, digest  # noqa: F401
from codex_harness.kernel.message import envelope
from codex_harness.research.adapters import source_execution as _source_execution
from codex_harness.research.adapters.source_verification import GitSourceVerifier
from codex_harness.research.application import audit_gate
from codex_harness.research.application.research import ResearchAudits
from codex_harness.research.domain.research import (
    AdaptationProposal,
    ExecutionReceipt,
    InventoryEntry,
    PartitionCheckpoint,
    PathDisposition,
    SourceIdentity,
    SubsystemAnalysis,
)
from codex_harness.review.application import sdd as _sdd
from codex_harness.review.domain.check_results import classify_isolated_run
from codex_harness.storage.adapters.file_artifacts import FileArtifacts
from codex_harness.storage.adapters.memory_store import MemoryStore


def _real_capture(*args, **kwargs):
    return _ei._capture(*args, process_tree=ProcessTree, **kwargs)


class _Module:
    """A module as the M7 suites saw it: names read from the moved module and an assignment lands on it, except the
    names the shim rewraps (`own`: name -> value)."""

    def __init__(self, module, **own):
        object.__setattr__(self, "_module", module)
        object.__setattr__(self, "_own", own)

    def __getattr__(self, name):
        own = object.__getattribute__(self, "_own")
        if name in own:
            return own[name]
        return getattr(object.__getattribute__(self, "_module"), name)

    def __setattr__(self, name, value):
        own = object.__getattribute__(self, "_own")
        if name in own:
            own[name] = value
        else:
            setattr(object.__getattribute__(self, "_module"), name, value)


ei = _Module(_ei, ProcessTree=ProcessTree, _capture=_real_capture)


def _attached_capture(*args, **kwargs):
    return ie._capture(*args, **kwargs)  # read at call time: a case replaces `ie._capture`


class _Attached:
    """The attached capture of the container replay: M7's `_capture` module global, looked up when called."""

    @property
    def _capture_fn(self):
        return _attached_capture

    @_capture_fn.setter
    def _capture_fn(self, value):  # the moved constructor binds the default; the module-global lookup above replaces it
        pass


class _Root:
    """`root` lives on the container replay in the target; a case that moves the inspector's root moves it there too."""

    @property
    def root(self):
        return self._root

    @root.setter
    def root(self, value):
        self._root = Path(value)
        containers = getattr(self, "containers", None)
        if containers is not None:
            containers.root = Path(value)


class EvidenceInspector(_ei.EvidenceInspector):
    def __init__(self, artifacts, policy=None, interpreter=None):
        super().__init__(artifacts, policy, interpreter, process_tree=ProcessTree)


class ProjectEvidenceInspector(_pe.ProjectEvidenceInspector):
    def __init__(self, artifacts, profile, policy=None, interpreter=None):
        super().__init__(artifacts, profile, policy, interpreter, process_tree=ProcessTree)


class DockerEvidenceInspector(_Root, _Attached, _ie.DockerEvidenceInspector):
    def __init__(self, artifacts, isolation, root, docker="docker", policy=None):
        super().__init__(artifacts, isolation, root, docker, policy, process_tree=ProcessTree,
                         containers=ContainerEvidenceReplay(isolation, root, docker, runner=process_groups.run_process))


class IsolatedProjectEvidenceInspector(_Root, _Attached, _ie.IsolatedProjectEvidenceInspector):
    def __init__(self, artifacts, profile, isolation, root, docker="docker", policy=None):
        super().__init__(artifacts, profile, isolation, root, docker, policy, process_tree=ProcessTree,
                         containers=ContainerEvidenceReplay(isolation, root, docker, runner=process_groups.run_process))


ie = _Module(_ie, _capture=_real_capture, DockerEvidenceInspector=DockerEvidenceInspector,
             IsolatedProjectEvidenceInspector=IsolatedProjectEvidenceInspector)

def SDD(store, artifacts, human_provider=None):  # noqa: N802 - the M7 constructor name
    return _sdd.SDD(store, artifacts, human_provider, ticket_binding=ticket_binding, clock=SYSTEM_CLOCK)


SOURCE = {"mode": "working_tree_draft", "repository": "contract-test", "revision": None, "path": "spec.json"}
spec_data = unavailable("S8", "test_sdd.spec_data (review.adapters.sdd.load_json has no target implementation yet)")


PROCESSES = process_groups.ChokepointProcesses()


def research_audits(store, verifier, artifacts, workflow, runner=None):
    """`ResearchAudits(store, verifier, artifacts, workflow, runner)` with its V3 ports, as `s8_audit_core.py` wires them."""
    recovery = execution_recovery.ExecutionRecovery(store, workflow.org, artifacts, audit_binding=audit_gate.binding,
                                                    ticket_binding=ticket_binding, clock=SYSTEM_CLOCK, ids=SYSTEM_IDS)
    return ResearchAudits(store, verifier, artifacts, workflow, runner, decision_validation=recovery,
                          outbox=Outbox(), pending_decisions=PendingDecisions())


@pytest.fixture
def audit(tmp_path):
    repo = tmp_path / 'source'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args]).decode().strip()
    git('init', '-q')
    git('config', 'user.email', 'fixture@example.com')
    git('config', 'user.name', 'Fixture')
    git('remote', 'add', 'origin', 'https://github.com/fixture/repo.git')
    (repo / 'normal').write_text('source')
    git('add', '.')
    # INV-GRAPH-001: Git paths need not be representable on the host filesystem.
    raw_name = b'space and name' if os.name == 'nt' else b'space\tand\nnewline'
    for mode, name, body in [('100644', raw_name, b'\xff\x00\xfe'),
                             ('120000', b'link', b'normal')]:
        oid = subprocess.check_output(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'],
                                      input=body).strip()
        subprocess.run(['git', '-C', str(repo), 'update-index', '-z', '--index-info'],
                       input=mode.encode() + b' ' + oid + b'\t' + name + b'\0', check=True)
    git('commit', '-qm', 'fixture')
    artifacts = FileArtifacts(str(tmp_path / 'artifacts'))
    verifier = GitSourceVerifier(repo, artifacts, processes=PROCESSES)
    source = SourceIdentity('https://github.com/fixture/repo', git('rev-parse', 'HEAD'),
                            git('rev-parse', 'HEAD^{tree}'), 'sha256:' + '0' * 64)
    entries = verifier.inventory(source)
    manifest = {'version': 1, 'repository': source.repository, 'commit': source.commit,
                'tree': source.tree, 'entries': entries}
    source = replace(source, manifest_ref=artifacts.put(canonical(manifest), 'fixture')['ref'])
    entries = [InventoryEntry(**e) for e in entries]
    store = MemoryStore()
    workflow = Workflow(store, organization())
    service = research_audits(store, verifier, artifacts, workflow)
    record = service.import_audit(source, entries, ['core'])
    return service, record, source, entries, git



class FixtureRunner:
    """Injected fixture receipts; these are not actual isolated or Codex verification."""
    def __init__(self, artifacts, blocked=False, passed=None, outcome=None):
        self.artifacts, self.blocked = artifacts, blocked
        self.passed = (not blocked) if passed is None else passed
        self.outcome = outcome or ('isolation_unavailable' if blocked else 'executed')

    def execute(self, source, command):
        output = self.artifacts.put('fixture inspection output', 'test-fixture')['ref']
        return ExecutionReceipt(source, 'fixture-env', command, 'fixture-isolation',
                                125 if self.blocked else 0, output, 'fixture-runner', self.blocked,
                                passed=self.passed, outcome=self.outcome)

    def execute_assigned(self, source, command, task, workflow):
        return self.execute(source, command)


def activate_fixture(service, revision='audit', expected=None, enabled=True):
    releases = Releases(service.store, service.workflow.org)
    candidate = {'revision': revision, 'tree': 'fixture-tree', 'base': 'fixture-base',
                 'author': 'worker:implementation'}
    if enabled:
        candidate['audit_lifecycle_version'] = 1
    release = releases.propose(candidate, {'checks': ['tests', 'cli_start', 'cli_file_task']})
    for actor in ('lead:improvement', 'conductor'):
        releases.review(release['id'], actor, revision, True, 'fixture-review')
    releases.verify(release['id'], revision, release['policy_hash'], {
        k: {'passed': True, 'evidence': 'fixture-canary-not-production'}
        for k in release['policy']['checks']})
    releases.promote(release['id'], expected)
    return releases, release


def complete_fixture_audit(service, record, source):
    service.runner = FixtureRunner(service.artifacts)
    for part in service.partition(record['id'], 1):
        message = envelope('task.assign', 'lead:research', 'worker:github', 'audit_partition',
            {'audit_id': record['id'], 'partition_id': part['partition_id']}, 'fixture')
        service.workflow.submit(message)
        task = service.workflow.claim('worker:github', 'fixture')
        receipt = service.execute(task, record['id'], ['fixture-inspection'])
        ref = receipt['receipt']['output_ref']
        paths = [PathDisposition(p, 'binary' if base64.b64decode(p).startswith(b'space') else 'semantic',
                    [ref], ['symbol'], 'fixture trace', [], 'fixture-inspection', [receipt['id']])
                 for p in part['paths']]
        systems = [SubsystemAnalysis(name, [e['path'] for e in record['inventory']], ['contract'],
            ['main'], ['impl'], ['caller'], ['config'], ['git'], ['failure'], [json.dumps(['fixture-inspection'])],
            [receipt['id']], [ref], [], [], []) for name in part['subsystems']]
        saved = service.checkpoint(task, replace(PartitionCheckpoint(**part), remaining_paths=[],
                                   remaining_subsystems=[], cursor='done'), paths, systems)
        service.workflow.complete(task, saved)
    return AdaptationProposal(source, [e['path'] for e in record['inventory']], ['source:symbol'],
        'behavior', 'failures', ['harness:symbol'], 'overlap', 'boundaries', 'git/postgres',
        'six-w.v1', 'graph', 'attribution', 'license', 'dependencies', 'adapt', 'reason', 'worker:github')


def lease_review(service, actor):
    with service.store.transaction() as tx:
        row = next(r for r in tx.scan('decisions_pending') if r['actor'] == actor and r['status'] == 'pending')
        row.update(status='running', generation=1, lease_owner='fixture', owner='fixture',
                   lease_until=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat())
        tx.put('decisions_pending', row['id'], row)
        return {**row, '_bucket': 'decisions_pending'}


_REAL_BOUNDED = _source_execution.bounded_command


class _SourceExecution(_Module):
    """`run_process` and `bounded_command` as M7 cases replaced them (two-argument callables)."""

    def __getattr__(self, name):
        if name == "bounded_command":
            return getattr(super().__getattr__(name), "__wrapped__", super().__getattr__(name))
        return super().__getattr__(name)

    def __setattr__(self, name, value):
        if name == "bounded_command" and value is not _REAL_BOUNDED:
            replacement = value

            def bounded(argv, timeout, *, processes=None):
                return replacement(argv, timeout)
            bounded.__wrapped__ = value
            value = bounded
        super().__setattr__(name, value)


source_execution = _SourceExecution(_source_execution, run_process=process_groups.run_process)


def DockerSourceRunner(root, artifacts, docker="docker"):  # noqa: N802 - the M7 constructor name
    return _source_execution.DockerSourceRunner(
        root, artifacts, docker, processes=PROCESSES,
        run_process=lambda *args, **kwargs: source_execution.run_process(*args, **kwargs), classify=classify_isolated_run)


class _IsolatedWorker:
    """`iw` of the S3 ported suites (`m7_containers.iw`) with the two names the M7 isolated-evidence cases reach for that
    it does not hold: the container id pattern, and `_write_record` (a module global of the run ledger, `cleanup_ledger`,
    which a case replaces and the ledger's own calls then see)."""

    def __getattr__(self, name):
        if name == "_write_record":
            return cleanup_ledger._write_record
        if name == "CONTAINER_ID":
            return container_spec.CONTAINER_ID
        return getattr(m7_containers.iw, name)

    def __setattr__(self, name, value):
        setattr(cleanup_ledger if name == "_write_record" else m7_containers.iw, name, value)


iw = _IsolatedWorker()

packaged_policy = _ei.packaged_policy
replay_environment = _ei.replay_environment
replay_argv = _ei.replay_argv
trusted_interpreter = _ei.trusted_interpreter
KEEP_ENV = _ei.KEEP_ENV
POLICY_FILE = _ei.POLICY_FILE
load_profile, resolve_profile = _pe.load_profile, _pe.resolve_profile
execution_instructions = _pe.execution_instructions
authorized, parse_policy = domain_evidence.authorized, domain_evidence.parse_policy
classify_replays, denominator = domain_evidence.classify_replays, domain_evidence.denominator
parse_claim, verdict = domain_evidence.parse_claim, domain_evidence.verdict
