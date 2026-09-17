import json
from importlib.resources import files

from codex_harness.adapters.configuration import repository_root, runtime_dir, settings
from codex_harness.adapters.store import PostgresStore
from codex_harness.application.service import Harness
from codex_harness.domain.model import Agent, Organization


def organization() -> Organization:
    data = json.loads(files("codex_harness.resources").joinpath("organization.json").read_text())
    org = Organization({a["id"]: Agent(**a) for a in data["agents"]})
    org.validate()
    return org


def database_url() -> str:
    value = settings().get("HARNESS_DATABASE_URL")
    if not value:
        raise RuntimeError("Run scripts/setup.py or set HARNESS_DATABASE_URL")
    return value


def build() -> Harness:
    return Harness(PostgresStore(database_url()), organization())


def redis_url() -> str:
    return settings().get("HARNESS_REDIS_URL", "redis://127.0.0.1:56379/0")


def observation_root():
    return runtime_dir() / "observations"


def build_observer(store, component: str, role: str | None = None):
    """One durable observer per process: spool, health and termination records under the runtime dir."""
    from codex_harness.adapters.observation_spool import FileSpool, SpoolDirectory
    from codex_harness.application.observations import Observer
    from codex_harness.domain.observation import new_process_run_id
    from codex_harness.domain.policy import POLICY

    root = observation_root()
    spool = FileSpool(root, new_process_run_id(), max_bytes=POLICY.observation_spool_bytes)
    return Observer(store, spool, component=component, directory=SpoolDirectory(root), role=role)


def build_collector(store, observer=None):
    from codex_harness.adapters.contracts import validate_observation
    from codex_harness.adapters.observation_spool import SpoolDirectory
    from codex_harness.application.observations import Collector

    return Collector(store, SpoolDirectory(observation_root()), validate=validate_observation, observer=observer)


HOST_PROFILE = "host"


def host_evidence_profile():
    """INV-PROJECT-EVIDENCE-001: the host-selected project evidence profile, or None when the host
    configured none. A configured profile that is missing or invalid raises; it never falls back."""
    from codex_harness.adapters.project_evidence import load_profile

    return load_profile(settings())


def build_executor(service=None, observer=None, execution_policy=None, knowledge=True, evidence_profile=HOST_PROFILE):
    """`knowledge=False` builds the executor without any knowledge adapter: no hybrid query and no
    index_python/project_runtime write on rotate. The default (writable PostgresKnowledge) is
    unchanged for every other caller. `evidence_profile` is the profile an entry point already
    loaded (or None) so identity and executor share one load; by default it is read from the host
    settings here, before the executor exists and so before any provider entry."""
    profile = host_evidence_profile() if evidence_profile == HOST_PROFILE else evidence_profile
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.audit_runner import AuditRunner
    from codex_harness.adapters.executor import Executor
    from codex_harness.adapters.git import GitWorkspace
    from codex_harness.adapters.research import ResearchSources

    repository = str(repository_root())
    runtime = runtime_dir()
    artifacts = FileArtifacts(str(runtime / "artifacts"))
    remote = settings().get("HARNESS_GITHUB_REPO")
    git = GitWorkspace(repository, str(runtime / "workspaces"), remote)
    service = service or build()
    adapter = None
    if knowledge:
        from codex_harness.adapters.knowledge import PostgresKnowledge
        adapter = PostgresKnowledge(database_url())
    return Executor(service, git, artifacts, adapter,
                    ResearchSources(artifacts),
                    audit_runner=AuditRunner(runtime / "audit-sources", artifacts, host_execution=True),
                    observer=observer or build_observer(service.store, "executor"),
                    execution_policy=execution_policy, evidence_profile=profile)
