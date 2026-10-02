"""Target driver: `effects.s8_units` on the target tree (the V8 homes of the §2.9 units: `research.application.research_program`,
`intake.application.frontdesk`, `delivery.adapters.deployment`). The API is the three reused worlds' target APIs over ONE scripted
clock and id source (the S5 composition's `CLOCK`/`IDS`, reset per case, as the reference resets its patched sources), each the same
wiring as that world's own target driver (`research.program_records`, `intake.frontdesk`, `delivery.release_runner`), plus the
reference's `backend(name)`, `reset()` and `recording(store)`: the S0 RecordingStore over a fresh target MemoryStore.

The kernel's default clock and id port are the composition's (`ids.SYSTEM_CLOCK`, `message.SYSTEM_IDS`); the research program's and
the front desk's default owner token (`uuid4`) and the desk runner's `datetime.now` are the harness's, as the reference run
installed them."""

import hashlib
import json
import os
import shutil
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("target")

from types import SimpleNamespace  # noqa: E402

import recorder as rec  # noqa: E402
import s5_coordination_composition as composition  # noqa: E402
import s8_units  # noqa: E402
from codex_harness.composition.release_verification import (  # noqa: E402
    ExecutionContainerNaming,
    release_runner,
)
from codex_harness.coordination.application import (  # noqa: E402
    desk_runner,
    execution_fence,
    outbox_relay,
)
from codex_harness.coordination.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.coordination.application.fleet.state import BUCKET_JOBS  # noqa: E402
from codex_harness.coordination.application.outbox import Outbox  # noqa: E402
from codex_harness.coordination.application.research_launch_facts import (  # noqa: E402
    ResearchLaunchFacts,
)
from codex_harness.coordination.domain import owner_actions  # noqa: E402
from codex_harness.delivery.adapters import deployment  # noqa: E402
from codex_harness.host_os.adapters import process_groups  # noqa: E402
from codex_harness.host_os.adapters.git_workspace import GitWorkspace  # noqa: E402
from codex_harness.intake.application import frontdesk as desk_application  # noqa: E402
from codex_harness.intake.application.portfolio import Portfolio, family_id  # noqa: E402
from codex_harness.intake.domain import frontdesk as desk_domain  # noqa: E402
from codex_harness.intake.domain.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    RESEARCH_REQUIRED,
)
from codex_harness.kernel import ids, message  # noqa: E402
from codex_harness.kernel.errors import ContractError  # noqa: E402
from codex_harness.kernel.ids import canonical, digest  # noqa: E402
from codex_harness.research.application import audit_progress as progress_application  # noqa: E402
from codex_harness.research.application import research_program as application  # noqa: E402
from codex_harness.research.domain.audit_progress import LOW_YIELD, candidate_row  # noqa: E402
from codex_harness.research.domain.research_hold import attempt_scope_id  # noqa: E402
from codex_harness.research.domain.research_program import (  # noqa: E402
    ProgramRefused,
    validate_config,
)
from codex_harness.review.domain import check_results  # noqa: E402
from codex_harness.routing.adapters.organization_source import packaged_organization  # noqa: E402
from codex_harness.routing.adapters.provider_policy import packaged_policy  # noqa: E402
from codex_harness.storage.adapters.file_artifacts import FileArtifacts  # noqa: E402
from codex_harness.storage.adapters.memory_store import MemoryStore  # noqa: E402
from codex_harness.storage.adapters.message_schema import validate_message  # noqa: E402
from codex_harness.storage.adapters.postgres_store import PostgresStore  # noqa: E402
from codex_harness.storage.ports import MessageDeliveryError  # noqa: E402

CLOCK, IDS, PORT = composition.CLOCK, composition.IDS, composition.PORT
ids.SYSTEM_CLOCK = PORT
message.SYSTEM_IDS = composition.IDPORT
application.uuid4 = IDS.uuid4   # the default cycle owner token: the harness id source, as the reference run installed it
desk_application.uuid4 = IDS.uuid4   # the default desk owner token
desk_runner.datetime = SimpleNamespace(now=CLOCK.now)   # `datetime.now(timezone.utc)` reads the scripted clock


def digest_of(body) -> str:
    text = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


PG_DSN = os.environ.get("ZEUS_REBUILD_PG_DSN")
SCENARIO = "effects.s8_units.pg" if PG_DSN else "effects.s8_units"


class Backend:
    """A fresh MemoryStore, or (`effects.s8_units.pg`) a fresh schema on the labelled disposable PostgreSQL migrated by this
    side's PostgresStore; its stored rows are readable as [bucket, key, status, body digest]."""

    def __init__(self, name: str):
        assert name == "memory", name
        self.schema = None
        if not PG_DSN:
            self.store = MemoryStore()
            return
        import psycopg
        from psycopg.conninfo import make_conninfo

        self.psycopg = psycopg
        self.schema = "s8_units"
        with psycopg.connect(PG_DSN, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            conn.execute(f'CREATE SCHEMA "{self.schema}"')
        self.dsn = make_conninfo(PG_DSN, options=f"-c search_path={self.schema},public")
        self.store = PostgresStore(self.dsn)
        self.store.migrate()

    def rows(self) -> list:
        if self.schema is None:
            return sorted([b, k, (v or {}).get("status") or "", digest_of(v)] for (b, k), v in self.store.data.items())
        with self.psycopg.connect(self.dsn) as conn:
            return sorted([b, k, (v or {}).get("status") or "", digest_of(v)] for b, k, v in conn.execute(
                "SELECT bucket, id, body FROM documents").fetchall())

    def drop(self) -> None:
        if self.schema is not None:
            with self.psycopg.connect(PG_DSN, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA "{self.schema}" CASCADE')


def reset():
    CLOCK.reset()
    IDS.reset()


class ResearchProgram(application.ResearchProgram):
    """The moved class with its three composition ports wired (a subclass: the scenario also reads class attributes)."""

    def __init__(self, store, **kwargs):
        super().__init__(store, launch_facts=ResearchLaunchFacts(), fences=execution_fence, outbox_quarantine=outbox_relay,
                         **kwargs)


PROGRAM = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=ResearchProgram, application=application,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES,
    BUCKET_RECOVERIES=application.BUCKET_RECOVERIES, BUCKET_SUCCESSORS=application.BUCKET_SUCCESSORS,
    BUCKET_HEADS=application.BUCKET_HEADS, RUNS=RUNS, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS,
    BUCKET_PROGRESS_STATE=progress_application.BUCKET_STATE, BUCKET_PROGRESS_WINDOWS=progress_application.BUCKET_WINDOWS,
    RESEARCH_REQUIRED=RESEARCH_REQUIRED, Portfolio=Portfolio, family_id=family_id, LOW_YIELD=LOW_YIELD,
    progress_candidate_row=candidate_row, owner_actions=owner_actions, attempt_scope_id=attempt_scope_id, digest=digest,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config, POLICY=packaged_policy())


class FrontDesk(desk_application.FrontDesk):
    """The moved class with its outbox port wired (a subclass: the scenario builds it from the service and revision alone)."""

    def __init__(self, service, base_revision, *args, **kwargs):
        super().__init__(service, base_revision, *args, outbox=Outbox(), **kwargs)


DESK = SimpleNamespace(
    MemoryStore=MemoryStore, FrontDesk=FrontDesk, DeskRunner=desk_runner.DeskRunner, LEAD=desk_domain.LEAD,
    SUMMARY_TURNS=desk_runner.SUMMARY_TURNS, correlation_of=desk_application.correlation_of,
    message_id_of=desk_application.message_id_of, Harness=lambda store, org: composition.Service(store),
    Workflow=lambda store, org: composition.WorkflowAndMessages(store), ClaimGuardRefused=composition.ClaimGuardRefused,
    organization=lambda: composition.ORG, domain=desk_domain, validate_message=validate_message, canonical=canonical,
    MessageDeliveryError=MessageDeliveryError, advance=CLOCK.advance, reset=reset)


class Holder:
    """A swappable collaborator: calls go to `value`, which `install_seam`/`install_process_double` replace."""

    def __init__(self, value):
        self.value = value

    def __call__(self, *args, **kwargs):
        return self.value(*args, **kwargs)

    def swap(self, value):
        original, self.value = self.value, value
        return lambda: setattr(self, "value", original)


def refusal(label):
    def refuse(*args, **kwargs):
        raise AssertionError("target driver: " + label)
    return refuse


PROCESS = Holder(process_groups.run_process)
SERVICES = Holder(refusal("VerificationServices reached without install_seam('VerificationServices')"))
REBASE = Holder(refusal("request_rebase reached without install_seam('request_rebase')"))
SUITE_REFUSAL = refusal("ReleaseSuite never reached: probe run 001")
HOOKS_REFUSAL = refusal("NativeHooks never reached: probe run 001")


class Harness:
    """M7 `Harness` as the release-runner family uses it: validate the organization, hold `.store` and `.org`."""

    def __init__(self, store, organization):
        organization.validate()
        self.store, self.org = store, organization


def ReleaseRunner(service, git, artifacts, auth, auto_merge=True, fence=None, verification_root=None):
    handler = SimpleNamespace(store=service.store, org=service.org)   # the MessageHandler-shaped `self` of the seam
    return release_runner(
        service, git, artifacts, auth, auto_merge, fence, verification_root, runner=PROCESS,
        release_suite=SUITE_REFUSAL, verification_services=SERVICES, hooks=HOOKS_REFUSAL,
        request_rebase=lambda task_id, new_base: REBASE.value(handler, task_id, new_base), clock=PORT,
        ids=composition.IDPORT)


ReleaseRunner._require_controller_code = deployment.ReleaseRunner._require_controller_code


def install_seam(name, value):
    if name == "VerificationServices":
        return SERVICES.swap(value)
    if name == "request_rebase":
        return REBASE.swap(value)
    owner, attribute = {"controller_code_revision": (deployment, "controller_code_revision"),
                        "rmtree": (shutil, "rmtree")}[name]
    original = getattr(owner, attribute)
    setattr(owner, attribute, value)
    return lambda: setattr(owner, attribute, original)


RUNNER = SimpleNamespace(
    ReleaseRunner=ReleaseRunner, Harness=Harness, MemoryStore=MemoryStore,
    FileArtifacts=lambda root: FileArtifacts(root, clock=PORT), GitWorkspace=GitWorkspace,
    organization=packaged_organization, ContractError=ContractError, digest=digest, canonical=canonical,
    EvaluatorPinMismatch=deployment.EvaluatorPinMismatch, EvaluatorCodeMismatch=deployment.EvaluatorCodeMismatch,
    canary_handoff_script=deployment.canary_handoff_script, canary_postcondition=deployment.canary_postcondition,
    inspect_canary_file=deployment.inspect_canary_file,
    attempt_resources=partial(deployment.attempt_resources, naming=ExecutionContainerNaming()),
    evaluator_patch_sha256=deployment.evaluator_patch_sha256, resolve_evaluator_pin=deployment.resolve_evaluator_pin,
    uv_command=deployment.uv_command, pytest_summary=check_results.pytest_summary,
    classify_test_run=check_results.classify_test_run, is_test_run=check_results.is_test_run,
    bind_revision=check_results.bind_revision, OUTCOMES=check_results.OUTCOMES,
    install_process_double=PROCESS.swap, install_seam=install_seam, reset_ids=IDS.reset)

API = SimpleNamespace(program=PROGRAM, desk=DESK, runner=RUNNER, backend=Backend, reset=reset,
                      recording=lambda store: rec.RecordingStore(store))

if __name__ == "__main__":
    driver.finish("target", SCENARIO, s8_units.run(API))
