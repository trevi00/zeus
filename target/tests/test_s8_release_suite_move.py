"""S8 pilot 95 (DESIGN-s8 §14 V19): M7 `adapters/release_suite.py` moves to `review.adapters.release_suite`, and `host_os` owns the exception
class its callers catch (`ProcessCancelled`, moved verbatim into `host_os.ports`) and the `LoggedProcessRunner` call shape.

This file holds the V19 host_os identity tests; the move tests (rules, AST, first-use refusals, consumer construction) follow in the move commits."""

from __future__ import annotations

import inspect

from codex_harness.host_os import ports
from codex_harness.host_os.adapters import process_groups


def test_process_cancelled_is_one_class_defined_in_host_os_ports():
    assert process_groups.ProcessCancelled is ports.ProcessCancelled
    assert ports.ProcessCancelled.__module__ == "codex_harness.host_os.ports"
    assert issubclass(ports.ProcessCancelled, KeyboardInterrupt) and not issubclass(ports.ProcessCancelled, Exception)
    error = ports.ProcessCancelled({"exit_code": None, "cancelled": True})
    assert error.observation == {"exit_code": None, "cancelled": True} and str(error) == "process cancelled"
    assert error.args == ("process cancelled",)


def test_logged_process_runner_is_the_call_shape_of_run_logged_process():
    wanted = inspect.signature(ports.LoggedProcessRunner.__call__)
    actual = inspect.signature(process_groups.run_logged_process)
    parameters = [(p.name, p.kind, p.default) for p in wanted.parameters.values() if p.name != "self"]
    assert parameters == [(p.name, p.kind, p.default) for p in actual.parameters.values()]
    assert [name for name, *_ in parameters] == ["argv", "stdout_path", "stderr_path", "cwd", "timeout", "env"]
    assert wanted.return_annotation == actual.return_annotation
