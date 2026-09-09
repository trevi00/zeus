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


def build_executor(service=None):
    from codex_harness.adapters.artifacts import FileArtifacts
    from codex_harness.adapters.audit_runner import AuditRunner
    from codex_harness.adapters.executor import Executor
    from codex_harness.adapters.git import GitWorkspace
    from codex_harness.adapters.knowledge import PostgresKnowledge
    from codex_harness.adapters.research import ResearchSources

    repository = str(repository_root())
    runtime = runtime_dir()
    artifacts = FileArtifacts(str(runtime / "artifacts"))
    remote = settings().get("HARNESS_GITHUB_REPO")
    git = GitWorkspace(repository, str(runtime / "workspaces"), remote)
    return Executor(service or build(), git, artifacts, PostgresKnowledge(database_url()),
                    ResearchSources(artifacts),
                    audit_runner=AuditRunner(runtime / "audit-sources", artifacts, host_execution=True))
