"""The observed-asset registration composition: the builders `entry.cli.observed_assets` calls (V27, DESIGN-s8 section 26).

Layer: composition
Owns: observed_assets_store, observed_assets_audits, observed_assets_artifacts
Does not own: the argument shape, the manifest rules or the exit codes (entry.cli.observed_assets) and the audit rules (research.application.research.ResearchAudits)
Entry points: observed_assets_store, observed_assets_audits, observed_assets_artifacts
Contracts: INV-RESEARCH-001

Replaces the adapter constructions of M7 `adapters/observed_assets.py:main` (SOURCE e38aa722): `PostgresStore(database_url())`,
`FileArtifacts(args.artifacts)` and `ResearchAudits(store, None, artifacts, Workflow(store, organization()))`. The audits are the ones
`composition.cli.research_audits` builds over a `ServiceHandle(store, packaged_organization())`.
"""


def observed_assets_store():
    from codex_harness.composition import database_url
    from codex_harness.storage.adapters.postgres_store import PostgresStore
    return PostgresStore(database_url())


def observed_assets_artifacts(path):
    from codex_harness.composition import cli
    return cli.artifacts(path)


def observed_assets_audits(store, artifacts):
    from codex_harness.composition import ServiceHandle, cli
    from codex_harness.routing.adapters.organization_source import packaged_organization
    return cli.research_audits(ServiceHandle(store, packaged_organization()), artifacts)
