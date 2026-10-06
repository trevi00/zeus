"""S7 pilot 47: the moved release runner's required injected collaborators (V6), `naming` and the verification root."""
import inspect
from types import SimpleNamespace

import pytest

from codex_harness.delivery.adapters import deployment
from codex_harness.kernel.errors import ContractError

INJECTED = ("releases", "ticket_binding", "ticket_superseded", "runner", "release_suite", "verification_services",
            "verification_environment", "hooks", "request_rebase", "compose_environment", "naming", "release_queue")
POSITIONAL = ["self", "service", "git", "artifacts", "auth", "auto_merge", "fence", "verification_root"]


def collaborators():
    return {name: object() for name in INJECTED}


def test_the_injected_collaborators_are_required_keywords_and_clock_is_optional():
    parameters = inspect.signature(deployment.ReleaseRunner.__init__).parameters
    assert list(parameters)[:len(POSITIONAL)] == POSITIONAL
    for name in INJECTED:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty
    assert parameters["clock"].kind is inspect.Parameter.KEYWORD_ONLY and parameters["clock"].default is None
    service = SimpleNamespace(store=object(), org=object())
    with pytest.raises(TypeError):
        deployment.ReleaseRunner(service, object(), object(), "auth")
    for name in INJECTED:
        given = {key: value for key, value in collaborators().items() if key != name}
        with pytest.raises(TypeError):
            deployment.ReleaseRunner(service, object(), object(), "auth", **given)


def test_attempt_resources_requires_naming():
    assert inspect.signature(deployment.attempt_resources).parameters["naming"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        deployment.attempt_resources("a" * 32)

    class Naming:
        def name(self, run_id, role):
            return role + "/" + run_id

        def labels(self, run_id, role):
            return ["l=" + run_id, "r=" + role]

    resources = deployment.attempt_resources("a" * 32, naming=Naming())
    assert resources["containers"] == {"release-start": "release-start/" + "a" * 32,
                                       "release-canary": "release-canary/" + "a" * 32}
    assert resources["labels"]["release-start"] == ["l=" + "a" * 32, "r=release-start"]


@pytest.mark.parametrize("root", [None, ""])
def test_a_falsy_verification_root_refuses_before_any_service_is_built(root, tmp_path):
    built = []
    given = collaborators()
    given["verification_services"] = lambda *args, **kwargs: built.append(args)
    git = SimpleNamespace(inspect=lambda revision, base: {"tree": "t", "diff": "", "revision": revision},
                          target_identity=lambda: None, review_workspace=lambda revision, name: tmp_path)
    runner = deployment.ReleaseRunner(SimpleNamespace(store=object(), org=object()), git, object(), "auth",
                                      verification_root=root, **given)
    runner._test_source = lambda release, revision: "base"
    runner._check = lambda *args, **kwargs: {"passed": True, "evidence": "ref", "outcome": "executed"}
    release = {"id": "r" * 32, "candidate": {"revision": "x", "base": "base", "tree": "t"}, "policy": {"checks": {}}}
    with pytest.raises(ContractError, match="verification root is required"):
        runner._evaluate(release, None)
    assert built == []
