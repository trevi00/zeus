"""host_os ports: Git workspaces, candidate inspection and publication (the M7 `SourceControl` split).

Layer: ports
Context: host_os
Owns: the Protocols only; `host_os.adapters.git_workspace.GitWorkspace` implements all three
Does not own: who may publish or merge (review), release policy
Entry points: Workspaces, CandidateInspection, Publication
Contracts: INV-RELEASE-001, INV-SESSION-001

Shared infrastructure ports (`SP` in the §3.6 table). The five unrelated M7 `SourceControl` methods
are split by consumer (design §2.5) with their signatures unchanged.
"""

from __future__ import annotations

from typing import Protocol


class Workspaces(Protocol):
    def prepare(self, task_id: str, base: str) -> dict: ...
    def capture(self, workspace: dict) -> dict: ...


class CandidateInspection(Protocol):
    def inspect(self, revision: str, base: str) -> dict: ...


class Publication(Protocol):
    def publish(self, candidate: dict, title: str, body: str) -> dict: ...
    def merge(self, candidate: dict) -> dict: ...
