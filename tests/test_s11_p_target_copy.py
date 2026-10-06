"""S11 unit P (owner): the comparison's target side runs from a byte-identical, non-checkout copy of the target
distribution (compare/run.py `target_tree_copy`), because the product reads the runtime revision of its package's own
root (`delivery.adapters.deployment`, M7's `codex_harness.__file__` parents[2] rule): after the promotion that root is
the repository checkout, while the reference side runs from an installed wheel. The copy restores equal conditions."""

import importlib.util

from _layout import REPO

from codex_harness.delivery.adapters.host_delivery import checkout_revision


def _run_module():
    spec = importlib.util.spec_from_file_location("compare_run_for_target_copy", REPO / "compare" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_run_copy_is_byte_identical_and_is_no_checkout(tmp_path):
    run = _run_module()
    copy, digest = run.target_tree_copy(tmp_path)
    assert digest == run.tree_digest(run.TARGET_SRC) == run.tree_digest(copy / "src")
    assert {p.name for p in copy.iterdir()} == set(run.TARGET_COPY_PATHS)
    assert checkout_revision(copy) is None  # the reference wheel's condition: no revision at the package root
    assert checkout_revision(REPO) is not None  # the promoted checkout itself would answer one


def test_a_copy_that_differs_from_the_target_tree_is_refused(tmp_path, monkeypatch):
    run = _run_module()
    real = run.tree_digest
    monkeypatch.setattr(run, "tree_digest", lambda root: "0" * 64 if root == run.TARGET_SRC else real(root))
    try:
        run.target_tree_copy(tmp_path)
    except RuntimeError as error:
        assert "differs" in str(error)
    else:
        raise AssertionError("a differing copy was accepted")
