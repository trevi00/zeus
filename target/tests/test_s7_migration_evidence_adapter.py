"""S7 pilot 46: the moved migration evidence adapter's required `facts` and `processes` (V6) and its spawn route."""
import inspect
import sys

import pytest

from codex_harness.delivery.adapters import host_migration_evidence as evidence
from codex_harness.host_os.adapters.host_facts import HostFacts
from codex_harness.host_os.adapters.process_groups import ChokepointProcesses


def test_host_reader_requires_facts_and_processes():
    parameters = inspect.signature(evidence.HostReader.__init__).parameters
    for name in ("facts", "processes"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        evidence.HostReader(processes=ChokepointProcesses())
    with pytest.raises(TypeError):
        evidence.HostReader(facts=HostFacts())


def test_bounded_run_requires_processes():
    assert inspect.signature(evidence.bounded_run).parameters["processes"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        evidence.bounded_run([sys.executable, "-c", "pass"], timeout=5, env={}, limit=10)


def test_the_default_runner_spawns_through_the_injected_processes():
    seen = []

    class Recording(ChokepointProcesses):
        def popen(self, argv, **kwargs):
            seen.append((argv, kwargs))
            return super().popen(argv, **kwargs)

    reader = evidence.HostReader(facts=HostFacts(), processes=Recording())
    result = reader.runner([sys.executable, "-c", "print('x')"], timeout=10, env={}, limit=100)
    assert result.stdout == b"x\n" and result.returncode == 0
    assert [argv[0] for argv, _ in seen] == [sys.executable]
    assert seen[0][1]["start_new_session"] is True and seen[0][1]["env"] == {}


def test_a_runner_the_caller_supplies_wins():
    reader = evidence.HostReader(facts=HostFacts(), processes=ChokepointProcesses(), runner=print)
    assert reader.runner is print


def test_the_cli_carries_are_not_in_the_adapter():
    for name in ("cli_ports", "observe_command", "_archive", "_lane_dsn", "_named_env", "_schema"):
        assert not hasattr(evidence, name), name
