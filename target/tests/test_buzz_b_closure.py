"""Buzz Batch B: the bridge never imports provider or credential adapters (Buzz DESIGN §5, §8; DESIGN-B §1 closure test).

The `buzz_bridge` composition itself is Batch D. Until it exists this tests the import closure of the modules that do:
Batch B (remote control and the projection, both layers) and Batch A's transport (relay, signer, verifier, outbox,
inbound pass, bridge lease, remote inbox). The closure follows every static import, `from pkg import module` and each
package `__init__` on the way, so one transitive edge into a provider is found.
"""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
ROOT = "codex_harness"
BATCH_B = ("coordination.domain.remote_control", "coordination.application.remote_control",
           "observation.domain.buzz_projection", "observation.application.buzz_projection")
BATCH_A_TRANSPORT = ("observation.adapters.buzz_relay", "observation.adapters.event_signer",
                     "observation.adapters.nostr_verify", "observation.application.buzz_outbox",
                     "observation.application.buzz_inbound", "coordination.application.bridge_lease",
                     "coordination.application.remote_inbox", "credentials.adapters.role_keys")
FORBIDDEN_PREFIXES = (f"{ROOT}.execution.adapters.providers",)
ALLOWED_CREDENTIAL_ADAPTER = f"{ROOT}.credentials.adapters.role_keys"


def module_path(name: str) -> Path | None:
    base = SRC.joinpath(*name.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    return base / "__init__.py" if (base / "__init__.py").is_file() else None


def imports_of(name: str) -> set[str]:
    path = module_path(name)
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return {m for m in found if m == ROOT or m.startswith(ROOT + ".")}


def closure(entry: str) -> set[str]:
    seen, todo = set(), [f"{ROOT}.{entry}"]
    while todo:
        name = todo.pop()
        if name in seen or module_path(name) is None:
            continue
        seen.add(name)
        todo += [m for m in imports_of(name)]
        parts = name.split(".")
        todo += [".".join(parts[:i]) for i in range(1, len(parts))]  # the package __init__ chain runs too
    return seen


def violations(modules: set[str]) -> list[str]:
    return sorted(m for m in modules
                  if m.startswith(FORBIDDEN_PREFIXES)
                  or (m.startswith(f"{ROOT}.credentials.adapters.") and m != ALLOWED_CREDENTIAL_ADAPTER
                      and not m.startswith(ALLOWED_CREDENTIAL_ADAPTER + ".")))


@pytest.mark.parametrize("entry", BATCH_B + BATCH_A_TRANSPORT)
def test_the_import_closure_has_no_provider_and_no_credential_adapter_but_role_keys(entry):
    modules = closure(entry)
    assert f"{ROOT}.{entry}" in modules and len(modules) >= 2
    assert violations(modules) == []


def test_the_walker_finds_a_planted_transitive_edge(tmp_path, monkeypatch):
    """The check is not vacuous: a forbidden module two imports away is reported."""
    package = tmp_path / ROOT
    (package / "execution" / "adapters" / "providers").mkdir(parents=True)
    (package / "credentials" / "adapters").mkdir(parents=True)
    for directory in (package, package / "execution", package / "execution" / "adapters",
                      package / "execution" / "adapters" / "providers", package / "credentials",
                      package / "credentials" / "adapters"):
        (directory / "__init__.py").write_text("")
    (package / "execution" / "adapters" / "providers" / "claude.py").write_text("")
    (package / "credentials" / "adapters" / "codex_custody.py").write_text("")
    (package / "mid.py").write_text("from codex_harness.execution.adapters.providers import claude\n")
    (package / "entry.py").write_text("import codex_harness.mid\nfrom codex_harness.credentials.adapters import codex_custody\n")
    monkeypatch.setitem(globals(), "SRC", tmp_path)
    assert violations(closure("entry")) == [f"{ROOT}.credentials.adapters.codex_custody",
                                            f"{ROOT}.execution.adapters.providers",
                                            f"{ROOT}.execution.adapters.providers.claude"]
