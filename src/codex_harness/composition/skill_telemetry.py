"""The skill-telemetry composition: the builders `entry.cli.skill_import` and `entry.cli.skill_audit` call (S11 R-S7).

Layer: composition
Owns: store, artifacts, and the re-exports import_file, project_identity, render_text, SkillHistory and SkillImport
Does not own: the argument shape or the exit codes (entry.cli.skill_import and entry.cli.skill_audit), the import and audit rules (context.application) and the import of one file (context.adapters.skill_import)
Entry points: store, artifacts, import_file, project_identity, render_text, SkillHistory, SkillImport
Contracts: INV-SKILL-IMPORT-001, INV-SKILL-HISTORY-001

Replaces the adapter constructions of M7 `adapters/skill_import.py:main` (SOURCE e38aa722:60-61) and `adapters/skill_audit.py:main` (SOURCE e38aa722:84): `PostgresStore(database_url())` and `FileArtifacts(args.artifacts)`.
"""
from codex_harness.context.adapters.skill_audit import render_text
from codex_harness.context.adapters.skill_history import project_identity
from codex_harness.context.adapters.skill_import import import_file
from codex_harness.context.application.skill_history import SkillHistory
from codex_harness.context.application.skill_import import SkillImport

__all__ = ["SkillHistory", "SkillImport", "artifacts", "import_file", "project_identity", "render_text", "store"]


def store():
    from codex_harness.composition import database_url
    from codex_harness.storage.adapters.postgres_store import PostgresStore
    return PostgresStore(database_url())


def artifacts(path):
    from codex_harness.storage.adapters.file_artifacts import FileArtifacts
    return FileArtifacts(path)
