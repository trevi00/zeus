"""S3 target units (REBUILD-DESIGN-v2 §5.3 S3): the static half of `containers.profiles` against the committed
reference golden, and focused checks of the moved container spec and credential custody.

The static half (constants, profile shapes, environments, configuration parse, `container_args` under
both uid branches, forbidden-control probes and preflight refusals over a scripted docker runner) runs
the SAME scenario body as the reference driver, in-process, and must equal the reference golden's keys
exactly; the golden is never rewritten (R-C). The profile runs (the four transports) stay pending until
the launcher moves (evidence/rebuild/s3/pending.json).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from _layout import REPO as ROOT

sys.path[:0] = [str(ROOT / "compare" / "drivers" / "common")]

import s3_containers  # noqa: E402

from codex_harness.credentials.domain import codex_credential as cc  # noqa: E402
from codex_harness.execution.adapters.containers import owned_container as oc  # noqa: E402
from codex_harness.execution.domain import container_spec as spec  # noqa: E402
from codex_harness.kernel.errors import ContractError, IsolationError  # noqa: E402
from codex_harness.routing.domain import profiles  # noqa: E402

GOLDEN = ROOT / "compare" / "goldens" / "reference" / "containers.profiles.json"


def target_api(monkeypatch) -> SimpleNamespace:
    current = {}

    def runner(argv, cwd=None, timeout=120, input_text=None, env=None):
        code, stdout = current["fake"](list(argv[1:]), env)
        return subprocess.CompletedProcess(argv, code, stdout, "")

    def set_ids(uid, gid):
        monkeypatch.setattr(os, "getuid", lambda: uid)
        monkeypatch.setattr(os, "getgid", lambda: gid)

    return SimpleNamespace(
        load_isolation=oc.load_host_isolation,
        container_args=lambda config, **fields: spec.container_args(config, user=oc.host_user(), **fields),
        forbidden_controls=lambda observed: spec.forbidden_controls(observed, home=oc.operator_home()),
        worker_environment=spec.worker_environment, codex_environment=spec.codex_environment,
        read_only_mounts=spec.read_only_mounts, PROFILES=spec.PROFILES, LIMITS=spec.LIMITS,
        INSPECT_FORMAT=spec.INSPECT_FORMAT, FORBIDDEN_SOURCES=spec.FORBIDDEN_SOURCES, CODEX_CONFIG=cc.CODEX_CONFIG,
        CODEX_CONFIG_SHA256=cc.CODEX_CONFIG_SHA256, CODEX_CLI_VERSION=cc.CODEX_CLI_VERSION,
        TOKEN_NAME=spec.TOKEN_NAME, DOCKER_CLIENT_ENVIRONMENT=spec.DOCKER_CLIENT_ENVIRONMENT,
        preflight=lambda config, environment, token: oc.preflight(config, "docker", environment, token=token,
                                                                  runner=runner),
        install_docker=lambda fake: current.__setitem__("fake", fake), set_ids=set_ids,
        set_uuid=lambda prefix: None, IsolationError=IsolationError, ContractError=ContractError)


def test_static_half_equals_the_reference_golden(monkeypatch):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    result = json.loads(json.dumps(s3_containers.run_static(target_api(monkeypatch)), sort_keys=True))
    expected = {key: value for key, value in golden.items() if key != "profile_runs"}
    assert result == expected


def test_one_isolation_error_type_across_routing_credentials_and_execution():
    assert profiles.IsolationError is IsolationError
    with pytest.raises(IsolationError) as refused:
        profiles.select_profile("codex", "app_server", "implement", False, codex_enabled=False)
    assert refused.value.reason_code == "codex_profile_disabled"


def test_container_user_is_never_root():
    assert spec.container_user(1000, 1000) == "1000:1000"
    assert spec.container_user(0, 0) == spec.FALLBACK_USER
    assert spec.container_user(None, None) == spec.FALLBACK_USER


def test_resolved_run_states_have_one_definition():
    assert spec.RESOLVED is cc.SETTLED_RUN_STATES == ("removed", "refused")


def test_token_value_never_reaches_the_argv_and_passes_by_name_only(monkeypatch):
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(os, "getgid", lambda: 1000)
    config = oc.load_host_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "a" * 64})
    argv = spec.container_args(config, name="n", run_id="0" * 32, role="worker", network="bridge", mounts=[],
                               environment=spec.worker_environment(), pass_names=(spec.TOKEN_NAME,),
                               entry=[spec.TRUSTED_PYTHON], workdir="/", user=oc.host_user())
    assert argv[argv.index(spec.TOKEN_NAME) - 1] == "-e"
    env = oc.docker_environment({"PATH": "/bin", spec.TOKEN_NAME: "secret-value", "ANTHROPIC_API_KEY": "k"},
                                token=True)
    assert env == {"PATH": "/bin", spec.TOKEN_NAME: "secret-value"}
    assert oc.docker_environment({spec.TOKEN_NAME: "secret-value"}) == {}


def test_controls_mismatch_refuses_privileged_and_keeps_the_characterized_seccomp_disposition():
    observed = {"image": "sha256:" + "a" * 64, "user": "1000:1000", "network": "none", "read_only": True,
                "cap_drop": ["ALL"], "security_opt": ["no-new-privileges"], "memory": 1, "pids_limit": 1,
                "privileged": False, "ports": {}, "labels": {spec.LABEL: "r"}, "cap_add": None, "devices": [],
                "mounts": [{"Type": "bind", "Source": "/srv/w", "Destination": "/workspace", "RW": True}]}
    fields = {"image": observed["image"], "run_id": "r", "expected": {"/workspace": True}, "network": "none",
              "home": "/home/operator"}
    assert spec.controls_mismatch(observed, **fields) is False
    assert spec.controls_mismatch({**observed, "privileged": True}, **fields) is True
    assert spec.controls_mismatch({**observed, "security_opt": []}, **fields) is True
    # RESEARCH-S3 F-R1, preserved as characterized on SOURCE (a change would be a declared one).
    unconfined = {**observed, "security_opt": ["no-new-privileges", "seccomp=unconfined"]}
    assert spec.controls_mismatch(unconfined, **fields) is False
