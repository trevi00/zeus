"""Cutover G2-W2: the root `Dockerfile` is the release CLI-canary image (INV-RELEASE-FILE-CANARY-001).

Expected results come from the g2 design (step 4) and the contracts, not from the file under test: the CLI pins equal
`Dockerfile.worker`'s and the credential domain's (INV-ROLE-CONTAINER-001), the default user is root (the canary's
chown handoff) and the entrypoint is `codex`. The file is parsed as text, since there is no image build here (the
owner builds it in G2-R2). Each check is a function of the text, and each has a negative control: a mutated in-memory
copy of the text must fail the same function.
"""

import re

import pytest
from _layout import REPO as ROOT

from codex_harness.credentials.domain.codex_credential import CODEX_CLI_SHA256, CODEX_CLI_VERSION

ROOT_TEXT = (ROOT / "Dockerfile").read_text(encoding="utf-8")
WORKER_TEXT = (ROOT / "Dockerfile.worker").read_text(encoding="utf-8")


def _instructions(text):
    """Instruction lines (comments and blanks dropped), with backslash continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [line.strip() for line in joined.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _arg(text, name):
    found = re.findall(rf"^ARG {name}=(\S+)$", text, re.MULTILINE)
    assert len(found) == 1, (name, found)
    return found[0]


def _codex_stage(text):
    lines = _instructions(text)
    start = next(i for i, line in enumerate(lines) if line.startswith("FROM ") and line.endswith(" AS codex"))
    stage = []
    for line in lines[start:]:
        if stage and line.startswith("FROM "):
            break
        stage.append(line)
    return stage


def check_pins(text):
    assert _arg(text, "CODEX_CLI_VERSION") == _arg(WORKER_TEXT, "CODEX_CLI_VERSION") == CODEX_CLI_VERSION
    assert _arg(text, "CODEX_CLI_SHA256") == _arg(WORKER_TEXT, "CODEX_CLI_SHA256") == CODEX_CLI_SHA256


def check_codex_stage(text):
    assert _codex_stage(text) == _codex_stage(WORKER_TEXT)
    assert len(_codex_stage(text)) == 2


def check_runs_as_root(text):
    assert not [line for line in _instructions(text) if line.split()[0] == "USER"]


def check_no_package_or_build_context(text):
    assert "codex_harness" not in text and "container_main" not in text
    copies = [line for line in _instructions(text) if line.split()[0] == "COPY"]
    assert copies and all(line.startswith("COPY --from=codex ") for line in copies), copies


def check_entrypoint(text):
    entrypoints = [line for line in _instructions(text) if line.split()[0] == "ENTRYPOINT"]
    assert entrypoints == ['ENTRYPOINT ["codex"]']


CHECKS = {"pins": check_pins, "codex_stage": check_codex_stage, "runs_as_root": check_runs_as_root,
          "no_package_or_build_context": check_no_package_or_build_context, "entrypoint": check_entrypoint}


def _flip_last_hex(text):
    digest = CODEX_CLI_SHA256
    return text.replace(digest, digest[:-1] + ("0" if digest[-1] != "0" else "1"))


MUTATIONS = {
    "pins": [_flip_last_hex, lambda t: t.replace("ARG CODEX_CLI_VERSION=0.156.1", "ARG CODEX_CLI_VERSION=0.156.2")],
    "codex_stage": [lambda t: t.replace("@openai/codex@0.156.1", "@openai/codex@latest"),
                    lambda t: t.replace("node:22-bookworm-slim AS codex", "node:20-bookworm-slim AS codex")],
    "runs_as_root": [lambda t: t + "USER zeus\n", lambda t: t.replace("ENTRYPOINT", "USER 10001:10001\nENTRYPOINT")],
    "no_package_or_build_context": [lambda t: t + "COPY src ./src\n", lambda t: t + "# codex_harness\n",
                                    lambda t: t + "RUN python -m container_main\n"],
    "entrypoint": [lambda t: t.replace('ENTRYPOINT ["codex"]', 'ENTRYPOINT ["/bin/sh"]'),
                   lambda t: t.replace('ENTRYPOINT ["codex"]', "")],
}


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_root_dockerfile_satisfies_the_release_canary_image_contract(name):
    """INV-RELEASE-FILE-CANARY-001: the real root Dockerfile passes every contract fact."""
    CHECKS[name](ROOT_TEXT)


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_each_check_fails_on_a_mutated_copy(name):
    """Negative controls: every mutation of the text fails the same check function."""
    for mutate in MUTATIONS[name]:
        mutated = mutate(ROOT_TEXT)
        assert mutated != ROOT_TEXT
        with pytest.raises(AssertionError):
            CHECKS[name](mutated)
