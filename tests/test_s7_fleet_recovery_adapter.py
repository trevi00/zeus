"""S7 pilot 48: the moved fleet recovery collectors' required injected collaborators (V6): `state`, `run_records`,
`git_source` and `budget` carry no default, and the one lazy default (`verify_schema`) keeps M7's form."""
import inspect

import pytest

from codex_harness.coordination.adapters import fleet_recovery

REQUIRED = {
    "docker_state": ("call",),
    "_run_record": ("run_records",),
    "listed_runs": ("run_records",),
    "_active_runs": ("run_records",),
    "checkout_identity": ("git_source",),
    "_independent": ("git_source",),
    "_queued_bindings": ("git_source",),
    "collect_recovery_proof": ("budget", "state", "run_records"),
    "collect_relocation_proof": ("state", "run_records", "git_source"),
    "collect_host_migration_proof": ("state", "run_records", "git_source"),
}


@pytest.mark.parametrize("function", sorted(REQUIRED))
def test_the_injected_names_are_required_keywords(function):
    parameters = inspect.signature(getattr(fleet_recovery, function)).parameters
    for name in REQUIRED[function]:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty


def test_the_lazy_schema_check_default_is_unchanged():
    parameters = inspect.signature(fleet_recovery.collect_host_migration_proof).parameters
    assert parameters["verify_schema"].default is None
    assert inspect.signature(fleet_recovery._schema_provisioned).parameters["verify"].default is None


def test_a_missing_injection_is_a_type_error_not_a_default():
    with pytest.raises(TypeError):
        fleet_recovery.checkout_identity("/x")
    with pytest.raises(TypeError):
        fleet_recovery.docker_state("c")
    with pytest.raises(TypeError):
        fleet_recovery.listed_runs("/x", "f")


def test_the_injected_call_answers_docker_state():
    seen = []

    def call(docker, args, *, timeout):
        seen.append((docker, args[0], timeout))
        return type("Shown", (), {"stdout": "exited 3\n", "returncode": 0})()

    assert fleet_recovery.docker_state("c1", "dk", call=call) == {"status": "exited", "exit_code": 3}
    assert seen == [("dk", "inspect", fleet_recovery.LIMITS["docker_command_seconds"])]
