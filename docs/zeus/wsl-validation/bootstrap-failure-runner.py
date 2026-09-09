"""Isolated native WSL validation; no original working-tree execution."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

EVIDENCE = Path(__file__).resolve().parent
REVISION = "4cb7d02df13d7621d47f0324ae121649982db7b2"
ROOT = Path(tempfile.mkdtemp(prefix="zeus-wsl-"))
REPO = ROOT / "repo"
for name in ("home", "tmp", "cache"):
    (ROOT / name).mkdir()
ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": str(ROOT / "home"),
    "TMPDIR": str(ROOT / "tmp"),
    "LANG": "C.UTF-8",
    "PYTHONIOENCODING": "utf-8",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.hooksPath",
    "GIT_CONFIG_VALUE_0": "/dev/null",
    "UV_CACHE_DIR": str(ROOT / "cache"),
    "UV_PROJECT_ENVIRONMENT": str(ROOT / "project-venv"),
    "UV_PYTHON": "/usr/bin/python3",
    "UV_PYTHON_DOWNLOADS": "never",
}
RECEIPT = {"revision": REVISION, "root": str(ROOT), "runner_pid": os.getpid(),
           "environment": ENV, "platform": platform.platform(),
           "python": platform.python_version(), "stages": [],
           "scope": "Native Ubuntu WSL2 ordinary suite; no integration services"}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save():
    (EVIDENCE / "receipt.json").write_text(json.dumps(RECEIPT, indent=2), encoding="utf-8")


def run(name, argv, cwd=ROOT):
    item = {"name": name, "argv": argv, "cwd": str(cwd), "start": now()}
    RECEIPT["stages"].append(item)
    with (EVIDENCE / (name + ".stdout")).open("wb") as out, (EVIDENCE / (name + ".stderr")).open("wb") as err:
        process = subprocess.Popen(argv, cwd=cwd, env=ENV, stdout=out, stderr=err)
        item["pid"] = process.pid
        save()
        print(json.dumps({"stage": name, "pid": process.pid, "start": item["start"]}), flush=True)
        item["exit_code"] = process.wait()
    item["end"] = now()
    for stream in ("stdout", "stderr"):
        path = EVIDENCE / (name + "." + stream)
        item[stream] = {"path": path.name, "sha256": digest(path), "bytes": path.stat().st_size}
    save()
    print(json.dumps({"stage": name, "exit_code": item["exit_code"], "end": item["end"]}), flush=True)
    return item["exit_code"]


RECEIPT["start"] = now()
save()
setup = [
    ("clone", ["git", "clone", "--no-local", "/mnt/c/Users/rudtn/zeus", str(REPO)], ROOT),
    ("checkout", ["git", "checkout", "--detach", REVISION], REPO),
    ("history", ["git", "rev-parse", "HEAD", "--is-shallow-repository", "09c1d58^{commit}"], REPO),
    ("bootstrap", ["/usr/bin/python3", "-m", "venv", str(ROOT / "bootstrap")], ROOT),
    ("install-uv", [str(ROOT / "bootstrap/bin/python"), "-m", "pip", "install", "--disable-pip-version-check", "uv==0.12.2"], ROOT),
]
for name, argv, cwd in setup:
    if run(name, argv, cwd):
        RECEIPT["setup_failure"] = name
        RECEIPT["end"] = now()
        save()
        raise SystemExit(1)
UV = str(ROOT / "bootstrap/bin/uv")
RECEIPT["lock_before"] = digest(REPO / "uv.lock")
run("uv-version", [UV, "--version"], REPO)
if run("sync", [UV, "sync", "--frozen"], REPO) == 0:
    for name, args in [
        ("ruff", ["run", "--frozen", "ruff", "check", "."]),
        ("pytest", ["run", "--frozen", "pytest", "-q", "-ra"]),
        ("build", ["build"]),
        ("version", ["run", "--frozen", "zeus", "--version"]),
        ("ticket-help", ["run", "--frozen", "python", "-m", "zeus", "ticket", "--help"]),
        ("supervisor-help", ["run", "--frozen", "harness-supervisor", "--help"]),
        ("monitor-help", ["run", "--frozen", "zeus-monitor", "--help"]),
    ]:
        run(name, [UV, *args], REPO)
RECEIPT["lock_after"] = digest(REPO / "uv.lock")
run("final-status", ["git", "status", "--porcelain"], REPO)
RECEIPT["end"] = now()
RECEIPT["runner_sha256"] = digest(Path(__file__))
save()
