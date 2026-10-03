"""M7 review, verification and release-suite surface over the S8 target, for the ported M7 review suites.

Layer: harness (never shipped). A TEST shim: it lets M7 `tests/test_code_tutor_pack.py`, `test_host_interruption.py`,
`test_release_environment_reverification.py`, `test_release_suite.py`, `test_release_verifier.py`, `test_sdd.py` and
`test_verification.py` run, with their assertions unchanged, against the objects DESIGN-s8 §29 moved. The wiring mirrors
`compare/drivers/target/s8_release_suite.py`, `s8_verification_services.py`, `s8_release_verifier.py`, `s8_sdd.py`,
`s8_sdd_adapter.py` and `s8_releases_audits.py`. Ids and clocks are NOT scripted here: as in M7 the real clock and uuid4
are used (kernel `utcnow`, SYSTEM_CLOCK).

Named adaptations (each is a construction/import/patch-target adaptation, never a behaviour change):
- `VerificationServices`, `ATTEMPTS`, `RECLAIM_SECONDS`, `UNRECLAIMED_LIMIT` and `DIAGNOSIS_SECONDS` are
  `host_os.adapters.verification` (batch B7a; M7 `adapters.verification`); `verification_environment` is
  `composition.release_verification`'s (moved ahead in S7). `ENVIRONMENT_KEYS` has ONE definition, in
  `host_os.adapters.verification` (R-v1): it is never copied here, a suite that names it imports it from there.
- `ReleaseVerifier`, `CancellationBoundary`, `EvaluationCancelled`, `FenceLost`, `FenceUnobservable` and `bounded_fence` are
  `composition.release_verifier` (batch B7b; M7 `adapters.release_verifier`), passed through as the compare driver passes
  them; `HostFacts` is `host_os.adapters.host_facts` (never redefined). The suite's scripted `docker` is the fixture
  executable `verification_fixtures.fake_docker` first on PATH, so the real `run_process` the module imports reaches it.
- `ReleaseSuite(artifacts, fence, batch_nodes=..)` is `review.adapters.release_suite.ReleaseSuite` with the three
  production injections closed over, as composition passes them (R-rs1): `run_logged_process` is
  `host_os.adapters.process_groups.run_logged_process`, `redact` and `redact_value` are observation's `redact_text` and
  `redact_value`. `release_suite` is the moved module; `commands` (M7 `adapters.commands`, the patch target of
  `_kill_tree`/`REAP_SECONDS`, and the home of `run_process`, `run_logged_process`, `_announce`) is
  `host_os.adapters.process_groups`; `ProcessCancelled` is `host_os.ports`'.
- `SDD(store, artifacts, human_provider=None, **ports)` is `review.application.sdd.SDD` with its two injected ports
  wired as composition wires them: intake's `ticket_binding` (R-sdd1) and the system clock (R-sdd2).
  `Tickets(store, organization)` and `organization()` are the shims' of `m7_intake`/`m7_coordination`.
- `read_spec(path, revision=None)` and `device_probe()` are `review.adapters.sdd`'s with the keyword-only bindings S10
  composition supplies (R-sd1, R-sd2): `root=composition.configuration.repository_root()` (resolved per call, as M7 did)
  and `run_process=host_os.adapters.process_groups.run_process`, as `s8_sdd_adapter.py` binds them. `load_json`,
  `write_export`, `render_review`, `adb_inventory` and `replay_source` are the module's own (the SDD domain rules
  `validate_spec`, `gate_report`, `propose_scenarios`, `ENVIRONMENT_FIELDS` are `review.domain.sdd`).
- `project_context(git, artifacts, cwd, revision, objective=None)` is `context.adapters.project_skills.project_context`
  with the packaged threshold definition (`conftest.NATIVE_THRESHOLDS`) as its `thresholds` source, as `m7_executor` wires
  it; `parse_profile`, `frontmatter` and `eligible_paths` are context's; `GitWorkspace` is
  `host_os.adapters.git_workspace` (M7 `adapters.git`); `select_model` is `routing.domain.model_selection`.
- `attempt_resources(attempt_id)` is `delivery.adapters.deployment.attempt_resources` with `ExecutionContainerNaming()`
  closed over, as composition passes it; `RETRY_*` and `deployment` are `delivery.adapters.deployment`; `ReleaseRunner`,
  `ProcessHostTarget`, `ReleaseQueue` and `Releases` are `m7_delivery`'s; the BUCKET_* names and the
  delivery domain names come from `delivery.application.host_delivery.state` and `delivery.domain.host_delivery`.
- `HostDelivery` is `m7_delivery.HostDelivery` with three more routes for M7 private methods the verifier suite reads or
  patches, each to the split object that owns it (an unrouted name still raises AttributeError, never a fallback):
  `_open_attempts` is `Verification._open_attempts`, `_predecessor` is `DeliveryState.predecessor`, and `_resumed` is
  `Resumption.resumed` (a read, and an assignment installed on the `Resumption` object, which both `resume` and the
  recovery paths call, as M7's `self._resumed(...)` was reached).
- `unavailable(slice_, name)` is `m7_coordination.unavailable`: a name whose owner is in a later slice (the operator
  CLIs, bootstrap) imports as a placeholder that raises on use, and only tests skipped whole (with the owning slice)
  name it.
"""

from __future__ import annotations

from conftest import NATIVE_THRESHOLDS
from m7_coordination import organization, unavailable  # noqa: F401
from m7_delivery import HostDelivery as _HostDelivery
from m7_delivery import (  # noqa: F401
    ProcessHostTarget,
    ReleaseQueue,
    ReleaseRunner,
    Releases,
)
from m7_intake import Tickets  # noqa: F401

from codex_harness.composition import configuration
from codex_harness.composition.release_verification import (  # noqa: F401
    ExecutionContainerNaming,
    verification_environment,
)
from codex_harness.composition.release_verifier import (  # noqa: F401
    CancellationBoundary,
    EvaluationCancelled,
    FenceLost,
    FenceUnobservable,
    ReleaseVerifier,
    bounded_fence,
)
from codex_harness.context.adapters import project_skills as _project_skills
from codex_harness.context.adapters.project_skills import parse_profile  # noqa: F401
from codex_harness.context.adapters.skill_routing import frontmatter  # noqa: F401
from codex_harness.context.domain.project_skills import eligible_paths  # noqa: F401
from codex_harness.delivery.adapters import deployment  # noqa: F401
from codex_harness.delivery.adapters.deployment import (  # noqa: F401
    RETRY_AUTH,
    RETRY_ISOLATION,
    RETRY_WORKSPACE,
)
from codex_harness.host_os.adapters import process_groups
from codex_harness.host_os.adapters import process_groups as commands  # noqa: F401
from codex_harness.host_os.adapters.git_workspace import GitWorkspace  # noqa: F401
from codex_harness.host_os.adapters.host_facts import HostFacts  # noqa: F401
from codex_harness.host_os.adapters.process_groups import (  # noqa: F401
    _announce,
    run_logged_process,
    run_process,
)
from codex_harness.host_os.adapters.verification import (  # noqa: F401
    ATTEMPTS,
    DIAGNOSIS_SECONDS,
    RECLAIM_SECONDS,
    UNRECLAIMED_LIMIT,
    VerificationServices,
)
from codex_harness.host_os.ports import ProcessCancelled  # noqa: F401
from codex_harness.intake.application import tickets as _tickets
from codex_harness.kernel.errors import ContractError  # noqa: F401
from codex_harness.kernel.ids import SYSTEM_CLOCK, digest, utcnow  # noqa: F401
from codex_harness.observation.domain.observation import redact_text, redact_value
from codex_harness.review.adapters import release_suite  # noqa: F401
from codex_harness.review.adapters import sdd as _sdd_adapter
from codex_harness.review.adapters.release_suite import REPORT_ENV, SELECT_ENV  # noqa: F401
from codex_harness.review.adapters.release_suite import ReleaseSuite as _ReleaseSuite
from codex_harness.review.adapters.sdd import (  # noqa: F401
    adb_inventory,
    load_json,
    render_review,
    replay_source,
    write_export,
)
from codex_harness.review.application.sdd import SDD as _SDD
from codex_harness.review.domain.sdd import (  # noqa: F401
    ENVIRONMENT_FIELDS,
    gate_report,
    propose_scenarios,
    validate_spec,
)
from codex_harness.routing.domain.model_selection import select_model  # noqa: F401
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: F401
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: F401

EXTRA_ROUTES = {"_open_attempts": ("verification", "_open_attempts"), "_predecessor": ("state", "predecessor"),
                "_resumed": ("resumption", "resumed")}


class HostDelivery(_HostDelivery):
    def __getattr__(self, name):
        if name in EXTRA_ROUTES:
            owner, attribute = EXTRA_ROUTES[name]
            return getattr(self.objects[owner], attribute)
        return super().__getattr__(name)

    def __setattr__(self, name, value):
        if name in EXTRA_ROUTES:
            owner, attribute = EXTRA_ROUTES[name]
            setattr(self.objects[owner], attribute, value)
            return
        super().__setattr__(name, value)


def attempt_resources(attempt_id):
    return deployment.attempt_resources(attempt_id, naming=ExecutionContainerNaming())


class ReleaseSuite(_ReleaseSuite):
    def __init__(self, artifacts, fence, *args, **ports):
        ports.setdefault("run_logged_process", process_groups.run_logged_process)
        ports.setdefault("redact", redact_text)
        ports.setdefault("redact_value", redact_value)
        super().__init__(artifacts, fence, *args, **ports)


class SDD(_SDD):
    def __init__(self, store, artifacts, human_provider=None, **ports):
        ports.setdefault("clock", SYSTEM_CLOCK)
        super().__init__(store, artifacts, human_provider, ticket_binding=_tickets.ticket_binding, **ports)


def read_spec(path, revision=None):
    return _sdd_adapter.read_spec(path, revision, root=configuration.repository_root(),
                                  run_process=process_groups.run_process)


def device_probe():
    return _sdd_adapter.device_probe(run_process=process_groups.run_process)


def project_context(git, artifacts, cwd, revision, objective=None):
    return _project_skills.project_context(git, artifacts, cwd, revision, objective, thresholds=NATIVE_THRESHOLDS)
