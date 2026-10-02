"""Reference driver: the S8 atomic units (REBUILD-DESIGN-v2 §2.9) of M7 research, intake and the release evaluator, scenario family
`effects.s8_units` (M7 `MemoryStore` only; the PostgreSQL variant is recorded separately): `ResearchProgram.record_collection` and
`fail_cycle`, `FrontDesk.submit` and `ReleaseRunner`'s completion unit.

The API is three reused worlds' reference APIs over ONE scripted clock and id source (`determinism.install`, reset per case):
`program` (`research.program_records`: `ResearchProgram` and its bucket names), `desk` (`intake.frontdesk`: `FrontDesk`, `Harness`,
`organization`) and `runner` (`delivery.release_runner`: `ReleaseRunner`, `FileArtifacts`, the seams), each the plain M7 objects or
lambdas over them, plus the s6_units one (`backend(name)`, `reset()` and `recording(store)`: the S0 RecordingStore over a fresh
`MemoryStore`, its stored rows readable)."""

import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import determinism  # noqa: E402
import recorder as rec  # noqa: E402
import s8_units  # noqa: E402

from codex_harness.adapters import deployment  # noqa: E402
from codex_harness.adapters.artifacts import FileArtifacts  # noqa: E402
from codex_harness.adapters.contracts import validate_message  # noqa: E402
from codex_harness.adapters.git import GitWorkspace  # noqa: E402
from codex_harness.adapters.providers import packaged_policy  # noqa: E402
from codex_harness.adapters.store import MemoryStore, PostgresStore  # noqa: E402
from codex_harness.application import audit_progress as progress_application  # noqa: E402
from codex_harness.application import execution_time  # noqa: E402,F401
from codex_harness.application import frontdesk as desk_application  # noqa: E402
from codex_harness.application import research_program as application  # noqa: E402
from codex_harness.application.autonomous import BUCKET as RUNS  # noqa: E402
from codex_harness.application.fleet import BUCKET_JOBS  # noqa: E402
from codex_harness.application.portfolio import (  # noqa: E402
    BUCKET_INVESTIGATIONS,
    RESEARCH_REQUIRED,
    Portfolio,
    family_id,
)
from codex_harness.application.service import Harness  # noqa: E402
from codex_harness.application.workflow import ClaimGuardRefused, Workflow  # noqa: E402
from codex_harness.bootstrap import organization  # noqa: E402
from codex_harness.domain import (  # noqa: E402
    check_results,
    owner_actions,
)
from codex_harness.domain import frontdesk as desk_domain  # noqa: E402
from codex_harness.domain.audit_progress import LOW_YIELD, candidate_row  # noqa: E402
from codex_harness.domain.continuation import attempt_scope_id  # noqa: E402
from codex_harness.domain.model import ContractError, canonical, digest  # noqa: E402
from codex_harness.domain.research_program import ProgramRefused, validate_config  # noqa: E402
from codex_harness.ports import MessageDeliveryError  # noqa: E402

CLOCK, IDS = determinism.FakeClock(), determinism.FakeIds()
# M7 draws `execution_time.DOMAIN` (this process's clock-domain identity) at import: pinned, as the S8 frontdesk driver pins it
determinism.install(CLOCK, IDS, constants={
    "codex_harness.application.execution_time": {"DOMAIN": "00000000-0000-4000-8000-00000000e5e5"}})


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


PROGRAM = SimpleNamespace(
    MemoryStore=MemoryStore, ResearchProgram=application.ResearchProgram, application=application,
    BUCKET_PROGRAMS=application.BUCKET_PROGRAMS, BUCKET_CANDIDATES=application.BUCKET_CANDIDATES,
    BUCKET_CYCLES=application.BUCKET_CYCLES, BUCKET_DISPATCHES=application.BUCKET_DISPATCHES,
    BUCKET_RECOVERIES=application.BUCKET_RECOVERIES, BUCKET_SUCCESSORS=application.BUCKET_SUCCESSORS,
    BUCKET_HEADS=application.BUCKET_HEADS, RUNS=RUNS, BUCKET_INVESTIGATIONS=BUCKET_INVESTIGATIONS, BUCKET_JOBS=BUCKET_JOBS,
    BUCKET_PROGRESS_STATE=progress_application.BUCKET_STATE, BUCKET_PROGRESS_WINDOWS=progress_application.BUCKET_WINDOWS,
    RESEARCH_REQUIRED=RESEARCH_REQUIRED, Portfolio=Portfolio, family_id=family_id, LOW_YIELD=LOW_YIELD,
    progress_candidate_row=candidate_row, owner_actions=owner_actions, attempt_scope_id=attempt_scope_id, digest=digest,
    ContractError=ContractError, ProgramRefused=ProgramRefused, validate_config=validate_config, POLICY=packaged_policy())

DESK = SimpleNamespace(
    MemoryStore=MemoryStore, FrontDesk=desk_application.FrontDesk, DeskRunner=desk_application.DeskRunner,
    LEAD=desk_application.LEAD, SUMMARY_TURNS=desk_application.SUMMARY_TURNS,
    correlation_of=desk_application.correlation_of, message_id_of=desk_application.message_id_of,
    Harness=Harness, Workflow=Workflow, ClaimGuardRefused=ClaimGuardRefused, organization=organization, domain=desk_domain,
    validate_message=validate_message, canonical=canonical, MessageDeliveryError=MessageDeliveryError,
    advance=CLOCK.advance, reset=reset)

SEAMS = {
    "VerificationServices": (deployment, "VerificationServices"),
    "controller_code_revision": (deployment, "controller_code_revision"),
    "rmtree": (deployment.shutil, "rmtree"),
    "request_rebase": (Workflow, "request_rebase")}


def install_seam(name, value):
    owner, attribute = SEAMS[name]
    original = getattr(owner, attribute)
    setattr(owner, attribute, value)
    return lambda: setattr(owner, attribute, original)


def install_process_double(fn):
    original = deployment.run_process
    deployment.run_process = fn
    return lambda: setattr(deployment, "run_process", original)


RUNNER = SimpleNamespace(
    ReleaseRunner=deployment.ReleaseRunner, Harness=Harness, MemoryStore=MemoryStore, FileArtifacts=FileArtifacts,
    GitWorkspace=GitWorkspace, organization=organization, ContractError=ContractError, digest=digest,
    canonical=canonical, Workflow=Workflow, EvaluatorPinMismatch=deployment.EvaluatorPinMismatch,
    EvaluatorCodeMismatch=deployment.EvaluatorCodeMismatch, canary_handoff_script=deployment.canary_handoff_script,
    canary_postcondition=deployment.canary_postcondition, inspect_canary_file=deployment.inspect_canary_file,
    attempt_resources=deployment.attempt_resources, evaluator_patch_sha256=deployment.evaluator_patch_sha256,
    resolve_evaluator_pin=deployment.resolve_evaluator_pin, uv_command=deployment.uv_command,
    pytest_summary=check_results.pytest_summary, classify_test_run=check_results.classify_test_run,
    is_test_run=check_results.is_test_run, bind_revision=check_results.bind_revision, OUTCOMES=check_results.OUTCOMES,
    install_process_double=install_process_double, install_seam=install_seam, reset_ids=IDS.reset)

API = SimpleNamespace(program=PROGRAM, desk=DESK, runner=RUNNER, backend=Backend, reset=reset,
                      recording=lambda store: rec.RecordingStore(store))

if __name__ == "__main__":
    driver.finish("reference", SCENARIO, s8_units.run(API))
