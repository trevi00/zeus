"""The container contract evidence shares with execution (S8 V26 rules E-3 and E-5): the constants and the container environment, declared once.

Layer: adapters
Context: evidence
Owns: MODE, IMAGE (the isolation image id pattern, NOT anchored: `fullmatch` is the caller's), TRUSTED_PYTHON (the image's interpreter), WORKSPACE (the
    mounted candidate root), CONTAINER_ENVIRONMENT and container_environment (the fixed environment of a replay in the image; it reads the candidate's `src`)
Does not own: the isolation configuration, the container argv and the control rule (execution.domain.container_spec: the V9 published language these values
    equal, tested for equality), the anchored image pattern of a project profile's declaration (evidence.domain.project_evidence.IMAGE, a different constant)
Entry points: MODE, IMAGE, TRUSTED_PYTHON, WORKSPACE, CONTAINER_ENVIRONMENT, container_environment
Contracts: INV-ISOLATED-WORKER-001, INV-PROJECT-EVIDENCE-001

Why an adapter module: `container_environment` looks at the candidate directory, and both evidence adapters (`isolated_evidence`, `project_evidence`) read these
names; declaring them here, once, keeps the two adapters free of an import cycle (S8 V26 E-5, DESIGN-s8 §27.3). Evidence may not import execution names, so the
constants are restated and an equality test against `execution.domain.container_spec` guards the copy. `CONTAINER_ENVIRONMENT` and `container_environment` are
M7 `adapters/isolated_evidence.py`'s statements, verbatim (SOURCE e38aa722).
"""
import re
from pathlib import Path

MODE = "docker"
IMAGE = re.compile(r"sha256:[0-9a-f]{64}")
TRUSTED_PYTHON = "/opt/zeus/bin/python"
WORKSPACE = "/workspace"

CONTAINER_ENVIRONMENT = {"HOME": "/tmp", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                         "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": WORKSPACE}


def container_environment(cwd=None) -> dict:
    env = dict(CONTAINER_ENVIRONMENT)
    if cwd is not None and (Path(cwd) / "src").is_dir():
        env["PYTHONPATH"] = WORKSPACE + "/src"  # the candidate's src, as the host replay binds it
    return env
