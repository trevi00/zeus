"""SYNTHETIC HOST FIXTURES for the host-delivery verification tests (INV-HOST-DELIVERY-VERIFY-001).

Everything here is a labelled stand-in; none of it is evidence about an actual host:

* `fake_docker` installs an executable named `docker` first on PATH. It is a small Python program
  with NO daemon behind it: a JSON file under `$DOCKER_CONFIG` models the containers and images a
  daemon would hold, every argv is appended to `fake-docker.log` so a test can assert exactly which
  names were ever touched, and `fail` / `hang` entries inject the labelled faults (an unavailable
  daemon; a `docker run` client that blocks while its container keeps running, as a real
  daemon-owned container does after its client is killed). It never reads a mounted file other than
  the canary's own `input.txt`, and never the mounted auth file.
* `fake_uv` installs `uv`: `uv sync --frozen` writes `.venv/bin/python` as an exec wrapper of THIS interpreter, so the
  candidate's incumbent and candidate suites are then run for real by the real `ReleaseSuite`.
* `FixtureServices` replaces the compose-backed `VerificationServices` for the evaluator: it
  records its exact project and its enter/exit and starts nothing.
* `source_repository` builds a real disposable Git repository with a base and a candidate commit.

Ported SOURCE M7 helper `tests/verification_fixtures.py` (e38aa722), a helper module with no tests (DESIGN-s8 §29); every
statement is M7's with ONE adaptation: `fake_docker` also sets `ZEUS_TEST_PROVIDER_FIXTURES` to its fixture-bin directory,
because the target test harness's spawn guard (R-P, `compare/guard/provider_guard.py`) refuses any `docker` executable that
does not resolve into the configured fixture directory; the executable is this module's own stand-in, never a real docker.

The real parts are the Git repository and workspaces, the `ReleaseRunner` evaluator and its
`ReleaseSuite`, every child process (git, pytest, the docker stand-in), the verifier port and its
records, the store and the CLI parser.
"""
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

FAKE_DOCKER = r'''#!{python}
"""SYNTHETIC HOST FIXTURE: the labelled Docker CLI stand-in (tests/verification_fixtures.py)."""
import fcntl, hashlib, json, os, sys, time
root = os.environ["DOCKER_CONFIG"]
argv = sys.argv[1:]
with open(os.path.join(root, "fake-docker.log"), "a", encoding="utf-8") as log:
    log.write(json.dumps(argv) + "\n")
lock = open(os.path.join(root, "fake-daemon.lock"), "w")
fcntl.flock(lock, fcntl.LOCK_EX)
path = os.path.join(root, "fake-daemon.json")
state = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
for key, empty in (("containers", {}), ("images", {}), ("fail", []), ("hang", [])):
    state.setdefault(key, empty)

def save():
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(state, stream)
    os.replace(temporary, path)

def done(code=0, out=""):
    save()
    fcntl.flock(lock, fcntl.LOCK_UN)
    sys.stdout.write(out)
    sys.exit(code)

command = argv[0] if argv else ""
word = argv[1] if command in ("image", "compose") and len(argv) > 1 else command
if command in state["fail"] or ("down" in argv and "compose" in state["fail"]):
    fcntl.flock(lock, fcntl.LOCK_UN)
    sys.stderr.write("Cannot connect to the Docker daemon at unix:///fixture.sock. Is the docker daemon running?\n")
    sys.exit(1)

def find(ref):
    for cid, row in state["containers"].items():
        if cid == ref or row["name"] == ref:
            return cid
    return None

if command == "ps":
    filters = [argv[i + 1] for i, a in enumerate(argv) if a == "--filter"]
    rows = []
    for cid, row in state["containers"].items():
        keep = True
        for item in filters:
            key, _, value = item.partition("=")
            if key == "name":
                keep = keep and value == "^/" + row["name"] + "$"
            elif key == "label":
                name, _, expected = value.partition("=")
                keep = keep and row["labels"].get(name) == expected
        if keep:
            rows.append(cid)
    done(0, "".join(cid + "\n" for cid in rows))
if command == "inspect":
    cid = find(argv[-1])
    if cid is None:
        done(1)
    done(0, state["containers"][cid]["status"] + " 0 false\n")
if command == "kill":
    cid = find(argv[-1])
    if cid is None:
        done(1)
    state["containers"][cid]["status"] = "exited"
    done(0, cid + "\n")
if command == "rm":
    cid = find(argv[-1])
    if cid is None:
        done(1)
    if "-f" not in argv and state["containers"][cid]["status"] == "running":
        done(1)
    del state["containers"][cid]
    done(0, cid + "\n")
if command == "build":
    tag = argv[argv.index("-t") + 1]
    state["images"][tag] = "sha256:" + hashlib.sha256((tag + argv[-1]).encode()).hexdigest()
    done(0, "built\n")
if command == "image" and word == "inspect":
    image = state["images"].get(argv[2])
    if image is None:
        done(1)
    done(0, image + "\n")
if command == "compose":
    project = argv[argv.index("--project-name") + 1]
    if "down" in argv:
        for cid in [c for c, row in state["containers"].items()
                    if row["labels"].get("com.docker.compose.project") == project]:
            del state["containers"][cid]
    done(0)
if command == "run":
    rest, name, labels, mounts, index = argv[1:], None, {}, [], 0
    while index < len(rest):
        item = rest[index]
        if item == "--rm":
            index += 1
            continue
        if item in ("--name", "--label", "--mount", "--memory", "--cpus", "--entrypoint"):
            value = rest[index + 1]
            if item == "--name":
                name = value
            elif item == "--label":
                key, _, label = value.partition("=")
                labels[key] = label
            elif item == "--mount":
                mounts.append(dict(part.split("=", 1) for part in value.split(",") if "=" in part))
            index += 2
            continue
        break
    args = rest[index + 1:]
    cid = hashlib.sha256(((name or "anonymous") + str(time.time())).encode() + os.urandom(8)).hexdigest()
    state["containers"][cid] = {"name": name or "fixture-" + cid[:12], "labels": labels, "status": "running"}
    if labels.get("zeus.isolated.role") in state["hang"]:
        save()
        fcntl.flock(lock, fcntl.LOCK_UN)
        time.sleep(3600)
        sys.exit(0)
    out = ""
    if "--version" in args:
        out = "codex-cli 0.0-fixture\n"
    elif "exec" in args:
        source = [m["source"] for m in mounts if m.get("target") == "/canary"][0]
        token = open(os.path.join(source, "input.txt"), encoding="utf-8").read()
        open(os.path.join(source, "output.txt"), "w", encoding="utf-8").write(token)
        json.dump({"value": token}, open(os.path.join(source, "result.json"), "w", encoding="utf-8"))
    del state["containers"][cid]
    done(0, out)
done(0, "fixture\n")
'''

FAKE_UV = r'''#!{python}
"""SYNTHETIC HOST FIXTURE: `uv sync --frozen` points the candidate venv at the test interpreter."""
import os, sys
if sys.argv[1:3] != ["sync", "--frozen"]:
    sys.exit(2)
os.makedirs(".venv/bin", exist_ok=True)
target = os.path.join(".venv", "bin", "python")
with open(target, "w", encoding="utf-8") as stream:
    stream.write("#!/bin/sh\nexec " + {python!r} + ' "$@"\n')
os.chmod(target, 0o755)
'''


def _executable(path: Path, text: str) -> None:
    path.write_text(text.replace("{python}", sys.executable, 1).replace("{python!r}", repr(sys.executable)),
                    encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class FakeDaemon:
    """The labelled view of the docker stand-in's state and argv log."""

    def __init__(self, root: Path):
        self.root = root
        self.state_path, self.log_path = root / "fake-daemon.json", root / "fake-docker.log"

    def state(self) -> dict:
        if not self.state_path.exists():
            return {"containers": {}, "images": {}, "fail": [], "hang": []}
        return json.loads(self.state_path.read_text("utf-8"))

    def update(self, **changes) -> None:
        state = self.state()
        state.update(changes)
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def add_container(self, cid: str, name: str, labels: dict, status: str = "running") -> None:
        state = self.state()
        state["containers"][cid] = {"name": name, "labels": labels, "status": status}
        self.update(containers=state["containers"])

    def calls(self) -> list:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text("utf-8").splitlines() if line]


def fake_docker(tmp_path: Path, monkeypatch) -> FakeDaemon:
    bin_dir = tmp_path / "fixture-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    _executable(bin_dir / "docker", FAKE_DOCKER)
    _executable(bin_dir / "uv", FAKE_UV)
    daemon_root = tmp_path / "fixture-daemon"
    daemon_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("ZEUS_TEST_PROVIDER_FIXTURES", str(bin_dir))  # adapted: the target R-P spawn guard's fixture directory
    # DOCKER_CONFIG is one of the names the docker client environment allow-list forwards.
    monkeypatch.setenv("DOCKER_CONFIG", str(daemon_root))
    return FakeDaemon(daemon_root)


class FixtureServices:
    """SYNTHETIC: the evaluator's isolated PostgreSQL/Redis pair, with nothing started."""

    entered: list = []

    def __init__(self, root, artifacts, project=None):
        self.root, self.project = Path(root), project or "zeus-verify-" + "0" * 32

    def __enter__(self):
        FixtureServices.entered.append(("enter", self.project))
        return {"database_url": "postgresql://fixture/isolated", "redis_url": "redis://fixture/0"}

    def __exit__(self, *args):
        FixtureServices.entered.append(("exit", self.project))
        return False


def git(root, *argv) -> str:
    return subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True,
                          text=True).stdout.strip()


def source_repository(root: Path, *, failing_candidate: bool = False) -> dict:
    """A real disposable repository: a base with a tiny real suite, and one candidate commit."""
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    for key, value in (("core.autocrlf", "false"), ("user.name", "Fixture"),
                       ("user.email", "fixture@localhost")):
        git(root, "config", "--local", key, value)
    (root / "tests").mkdir()
    # As in any real candidate repository, the evaluator's own venv is ignored; otherwise the
    # evaluator correctly refuses the workspace as dirty.
    (root / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "fixture-candidate"\nversion = "0"\n',
                                         encoding="utf-8")
    (root / "tests" / "test_fixture.py").write_text("def test_incumbent_fixture():\n    assert True\n",
                                                   encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    base = git(root, "rev-parse", "HEAD")
    (root / "feature.txt").write_text("candidate\n", encoding="utf-8")
    if failing_candidate:
        (root / "tests" / "test_candidate.py").write_text("def test_candidate():\n    assert False\n",
                                                          encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "candidate")
    revision = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "--detach", base)
    return {"root": root, "base": base, "revision": revision, "tree": git(root, "rev-parse", revision + "^{tree}")}
