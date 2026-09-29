"""S3 labelled Docker fixture suite (REBUILD-DESIGN-v2 §5.3 S3 slice exit: "labelled Docker fixture suite
green (fixture binaries, --network none)").

The target's ONE docker create composer (`execution.domain.container_spec.container_args`) builds the
controls of each role-profile mount layout; the fixture container runs a shell probe from the admitted
fixture image instead of a provider CLI, under a guard-admitted name and the owned-fixture label, with
`--network none`, binds only under the fixture bind root, and is removed by name. The kernel's and the
daemon's view is then checked: non-root, no capabilities, no-new-privileges, read-only rootfs, exactly
the declared bind modes, no socket, no host network, no operator home, and the inspected controls pass the
target's forbidden-control rule. No provider, credential or network is used; DUMMY bytes only.

Runs only when the default-deny guard admits Docker (`ZEUS_TEST_DOCKER=1`, a bind root, the fixture
image present): `python compare/run.py docker-fixture` (and the CI integration job) sets that up.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from codex_harness.execution.adapters.containers import owned_container as oc
from codex_harness.execution.domain import container_spec as spec

IMAGE = os.environ.get("ZEUS_TEST_S3_FIXTURE_IMAGE", "redis:7.4-alpine")
BIND_ROOT = os.environ.get("ZEUS_TEST_DOCKER_BIND_ROOT", "")
FIXTURE_LABEL = "zeus.test.fixture=1"


def _image_present() -> bool:
    if os.environ.get("ZEUS_TEST_DOCKER") != "1" or not BIND_ROOT or shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE], capture_output=True,
                              text=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _image_present(),
                                reason="needs ZEUS_TEST_DOCKER=1, ZEUS_TEST_DOCKER_BIND_ROOT and the fixture image "
                                       "(python compare/run.py docker-fixture)")

PROBE = r'''
out() { printf '%s=%s\n' "$1" "$2"; }
out uid "$(id -u)"
out cap_eff "$(awk '/^CapEff/ {print $2}' /proc/self/status)"
out no_new_privs "$(awk '/^NoNewPrivs/ {print $2}' /proc/self/status)"
(echo x > /rootfs-probe) 2>/dev/null && out rootfs_write allowed || out rootfs_write denied
(echo x > /tmp/probe) 2>/dev/null && out tmp_write allowed || out tmp_write denied
(echo x > /workspace/probe) 2>/dev/null && out workspace_write allowed || out workspace_write denied
(echo x > "$WRITABLE/probe") 2>/dev/null && out writable_write allowed || out writable_write denied
(echo x > "$READONLY/probe") 2>/dev/null && out readonly_write allowed || out readonly_write denied
[ -S /var/run/docker.sock ] || [ -S /run/docker.sock ] && out socket present || out socket absent
out interfaces "$(ls /sys/class/net | tr '\n' ',')"
[ -e "$HOST_HOME" ] && out host_home visible || out host_home absent
cat /workspace/dummy.txt >/dev/null 2>&1 && out workspace_read allowed || out workspace_read denied
'''


def _argv(config, name, run_id, mounts, environment):
    argv = spec.container_args(config, name=name, run_id=run_id, role="codex", network="none", mounts=mounts,
                               environment=environment, pass_names=(), entry=["/bin/sh", "-c", PROBE], workdir="/",
                               user=oc.host_user())
    assert argv[0] == "create"
    # A fixture run: the same controls, under the guard's owned-fixture name and label, attached.
    return ["run", "--label", FIXTURE_LABEL, *argv[1:]]


def _run_probe(tmp_path, layout):
    root = Path(BIND_ROOT).resolve()
    work = root / ("s3-" + uuid.uuid4().hex[:12])
    (work / "checkout").mkdir(parents=True)
    (work / "checkout" / "dummy.txt").write_text("DUMMY\n", encoding="utf-8")
    (work / "writable").mkdir()
    (work / "readonly").mkdir()
    for path in (work / "checkout", work / "writable", work / "readonly"):
        path.chmod(0o777 if path.name == "writable" else 0o755)
    config = oc.load_host_isolation({"ZEUS_WORKER_ISOLATION": "docker", "ZEUS_WORKER_IMAGE": "sha256:" + "0" * 64})
    config = {**config, "image": IMAGE}
    run_id = uuid.uuid4().hex
    name = "zeus-test-fixture-s3-" + run_id[:16]
    checkout_ro = layout == "checkout_ro"
    mounts = [(str(work / "checkout"), spec.WORKSPACE, True) if checkout_ro else (str(work / "checkout"), spec.WORKSPACE),
              (str(work / "writable"), "/rw"), (str(work / "readonly"), "/ro", True)]
    expected = {spec.WORKSPACE: not checkout_ro, "/rw": True, "/ro": False}
    environment = {"HOME": spec.CONTAINER_HOME, "WRITABLE": "/rw", "READONLY": "/ro", "HOST_HOME": str(Path.home())}
    argv = _argv(config, name, run_id, mounts, environment)
    try:
        shown = subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=180,
                               stdin=subprocess.DEVNULL)
        assert shown.returncode == 0, shown.stderr[-2000:]
        seen = dict(line.split("=", 1) for line in shown.stdout.splitlines() if "=" in line)
        inspected = subprocess.run(["docker", "inspect", "--format", spec.INSPECT_FORMAT, name], capture_output=True,
                                   text=True, timeout=60)
        assert inspected.returncode == 0, inspected.stderr[-2000:]
        observed = json.loads(inspected.stdout)
    finally:
        removed = subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, timeout=60)
    assert removed.returncode == 0
    gone = subprocess.run(["docker", "inspect", "--format", "{{.Id}}", name], capture_output=True, text=True, timeout=60)
    assert gone.returncode != 0, "the fixture container must be gone"
    return seen, observed, expected


@pytest.mark.parametrize("layout", ["checkout_ro", "staging_rw"])
def test_the_composed_controls_hold_in_a_real_container(tmp_path, layout):
    seen, observed, expected = _run_probe(tmp_path, layout)
    assert seen["uid"] == oc.host_user().split(":")[0] and seen["uid"] != "0"
    assert int(seen["cap_eff"], 16) == 0 and seen["no_new_privs"] == "1"
    assert seen["rootfs_write"] == "denied" and seen["tmp_write"] == "allowed"
    assert seen["workspace_write"] == ("denied" if layout == "checkout_ro" else "allowed")
    assert seen["workspace_read"] == "allowed" and seen["writable_write"] == "allowed"
    assert seen["readonly_write"] == "denied" and seen["socket"] == "absent" and seen["host_home"] == "absent"
    assert seen["interfaces"].strip(",").split(",") == ["lo"]
    # The daemon applied exactly what the composer declared; the target's rule finds nothing forbidden.
    mounts = [{key: mount.get(key) for key in ("Type", "Source", "Destination", "RW")} for mount in observed["mounts"]]
    assert {m["Destination"]: m["RW"] for m in mounts if m["Type"] == "bind"} == expected
    assert spec.forbidden_controls({**observed, "mounts": mounts}, home=oc.operator_home()) == []
    assert observed["read_only"] is True and observed["network"] == "none" and observed["privileged"] is False
    assert [str(cap).upper() for cap in observed["cap_drop"]] == ["ALL"] and not observed["cap_add"]
    assert "no-new-privileges" in observed["security_opt"] and observed["pids_limit"] == spec.LIMITS["pids"]
    assert observed["labels"][spec.LABEL] and observed["labels"]["zeus.test.fixture"] == "1"
