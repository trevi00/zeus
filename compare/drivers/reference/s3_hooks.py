"""Reference driver: `hooks.native_container` on SOURCE M7 (REBUILD-DESIGN-v2 §5.3 S3b, §5.4, R-C first).

M7 `adapters.executor.Executor._role_profile` (the isolation refusal) is called unbound on a minimal
owner object whose only fields are the ones it reads (`isolation`, `service`, `git`, `artifacts`), with
`adapters.executor.NativeHooks` replaced by a stub reporting the scenario's configuration. M7
`adapters.hooks.NativeHooks.configuration` runs over in-memory hook store/Git/artifact fakes, and M7
`adapters.app_server.AppServer`/`toml_literal` are used with their process boundary scripted by the
scenario. No Codex or hook process is spawned.
"""

import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE.parent / "harness"), str(HERE / "common")]

import driver  # noqa: E402

driver.start("reference")

from types import SimpleNamespace  # noqa: E402

import s3_hooks  # noqa: E402
from s1_common import outcome  # noqa: E402

from codex_harness.adapters import app_server, executor, hooks  # noqa: E402
from codex_harness.adapters.isolated_worker import IsolationError  # noqa: E402
from codex_harness.domain.model import ContractError  # noqa: E402


def role_profile(config, provider, transport, action, read_only, configured):
    class Stub:
        def __init__(self, *args):
            pass

        def configuration(self):
            return configured

    executor.NativeHooks = Stub
    owner = SimpleNamespace(isolation=None if config is None else SimpleNamespace(config=config),
                            service=None, git=None, artifacts=None)
    assignment = SimpleNamespace(provider=provider, transport=transport)
    return outcome(lambda: executor.Executor._role_profile(owner, assignment, action, read_only))


def configuration(active, scripts, root):
    class Git:
        def _git(self, *args, strip=True):
            revision, path = args[1].split(":", 1)
            return scripts[path]

    class Artifacts:
        def __init__(self):
            self.root = Path(root)

        def put(self, text, source):
            ref = "sha256:" + hashlib.sha256(text.encode()).hexdigest()
            (self.root / (ref[7:] + ".txt")).write_text(text, encoding="utf-8")
            return {"ref": ref}

    service = SimpleNamespace(active_hooks=lambda: active)
    return hooks.NativeHooks(service, Git(), Artifacts()).configuration()


API = SimpleNamespace(role_profile=role_profile, configuration=configuration, AppServer=app_server.AppServer,
                      toml_literal=app_server.toml_literal, IsolationError=IsolationError,
                      ContractError=ContractError, python_executable=sys.executable)

if __name__ == "__main__":
    driver.finish("reference", "hooks.native_container", s3_hooks.run(API))
