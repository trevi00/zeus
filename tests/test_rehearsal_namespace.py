"""Cutover RH-1b: the declarative namespace (namespace.json -> bwrap argv), spec validation, the in-namespace self-test,
the absolute-path preflight and the volatile staging (`compare/rehearsal/`, never shipped).

Expected results come from the task spec and the rehearsal design ("Namespace spec", "Spec validation", "Namespace
self-test", "Path preflight") with critiques #2/#4/#5/#6/#13, not from the implementation: the expected argv is written
out below, the refusal codes are the spec's named errors, and every in-namespace row is observed from a real bwrap run.
bwrap being unavailable is a FAILURE here (no skip). The real-Docker row (SHOW search_path on a live copy) needs
ZEUS_TEST_DOCKER=1. All inputs are fixtures under a temp ROOT; no production path is read.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from _layout import REPO

sys.path.insert(0, str(REPO / "compare"))
from rehearsal import Refused  # noqa: E402
from rehearsal import copies as cp
from rehearsal import namespace as ns  # noqa: E402
from rehearsal.evidence import Evidence  # noqa: E402
from rehearsal.preflight import path_preflight, scan_text  # noqa: E402
from rehearsal.sweep import open_dirs  # noqa: E402

RUN8, B_REV, R0_REV = "1b2c3d4e", "bb000001", "aa000002"
ART_SRC = "/srv/zeus/artifacts"
DOCKER = os.environ.get(cp.provider_guard.DOCKER_OPT_IN_ENV) == "1"


def make_release(base: Path, rev: str, *, pth_target: str) -> None:
    """A tiny fake release: its own `codex_harness` package and an editable-style venv whose `.pth` holds a path."""
    package = base / "src" / "codex_harness"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("MARK = 'fake-release'\n", encoding="ascii")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(base / ".venv")], check=True,
                   capture_output=True)
    site = next((base / ".venv" / "lib").glob("python*/site-packages"))
    (site / "_editable_fake.pth").write_text(pth_target + "\n", encoding="ascii")


def uv_python_dir() -> str:
    prefix = Path(sys.base_prefix)
    for parent in (prefix, *prefix.parents):
        if parent.name == "python" and parent.parent.name == "uv":
            return str(parent)
    return str(prefix)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("rh1b") / "root"
    root.mkdir()
    make_release(root / "rel" / B_REV, B_REV, pth_target=f"/srv/zeus/releases/{B_REV}/src")
    make_release(root / "r0" / R0_REV, R0_REV, pth_target=f"/srv/zeus/releases/{R0_REV}/src")
    make_release(root / "rel" / "cc000004", "cc000004", pth_target=str(root / "rel" / "cc000004" / "src"))
    for name in ("avenv", "uvcache"):
        (root / name).mkdir()
    (root / "mocks").mkdir()
    for name in ("systemctl", "journalctl"):
        mock = root / "mocks" / name
        mock.write_text(f"#!/bin/sh\necho mock-{name}\nexit 3\n", encoding="ascii")
        mock.chmod(0o755)
    (root / "cfg").mkdir()
    config = root / "cfg" / "nonsecret.json"
    config.write_text(json.dumps({"pg_dbname": "zeus_aibox", "pg_user": "zeus",
                                  "search_path": "zeus_aibox_control,public", "redis_db": 3}), encoding="ascii")
    (root / "art-src").mkdir()
    (root / "art-src" / "lower.txt").write_text("lower\n", encoding="ascii")
    yield {"root": root, "config": config}
    open_dirs(root)  # the overlay work dirs a namespace run leaves are mode 000 and would defeat pytest's cleanup


def build(world, *, b_rev=B_REV, with_config=False, sockets=False, **extra):
    root = world["root"]
    kwargs = dict(
        a_venv=str(root / "avenv"), uv_python=uv_python_dir(), uv_cache=str(root / "uvcache"),
        releases_r0={R0_REV: str(root / "r0" / R0_REV)}, b_rev=b_rev,
        mocks={"/usr/bin/systemctl": str(root / "mocks" / "systemctl"),
               "/usr/bin/journalctl": str(root / "mocks" / "journalctl")},
        env_names=["ZEUS_RUNTIME_MARK", "ZEUS_OTHER_NAME"], artifacts_src=str(root / "art-src"))
    if with_config:
        kwargs |= {"config_copy": world["config"], "recorded_search_path": "zeus_aibox_control,public"}
    if sockets:
        for name in ("pgsock", "redsock"):
            (root / "p" / name).mkdir(parents=True, exist_ok=True)
        kwargs |= {"pg_socket_dir": root / "p" / "pgsock", "redis_socket_dir": root / "p" / "redsock"}
    kwargs |= extra
    spec = ns.default_spec(RUN8, root, "S", **kwargs)
    ns.prepare_dirs(spec)
    return spec


def swap(spec, tag, **changes):
    """The spec with the first mount of `tag` changed (a disposable mutation of one mount)."""
    mounts, done = [], False
    for mount in spec.mounts:
        if mount.tag == tag and not done:
            mount, done = dataclasses.replace(mount, **changes), True
        mounts.append(mount)
    assert done
    return dataclasses.replace(spec, mounts=tuple(mounts))


def codes(spec):
    with pytest.raises(ns.SpecRefused) as info:
        ns.validate_spec(spec)
    return {code for code, _ in info.value.errors}


# ---- the argv: the design's order, written out independently of the builder -------------------------------------

def test_the_argv_follows_the_design_order_with_root_backed_tmp_and_home(world):
    spec = build(world)
    root, x = str(world["root"]), str(world["root"] / "S")
    uvp, av, uc = uv_python_dir(), f"{root}/avenv", f"{root}/uvcache"
    expected = [
        "bwrap", "--die-with-parent", "--unshare-net", "--unshare-pid", "--unshare-ipc",
        "--ro-bind", "/", "/", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/run",
        "--bind", f"{x}/tmp", "/tmp", "--bind", f"{x}/home", "/home/trevi", "--tmpfs", "/var/log/journal",
        "--ro-bind", uvp, uvp, "--ro-bind", av, av, "--ro-bind", uc, uc,
        "--tmpfs", "/srv/zeus", "--perms", "0700", "--dir", "/srv/zeus/secrets",
        "--ro-bind", f"{root}/r0/{R0_REV}", f"/srv/zeus/releases/{R0_REV}",
        "--ro-bind", f"{root}/rel/{B_REV}", f"/srv/zeus/releases/{B_REV}",
        "--bind", f"{x}/runtime", "/srv/zeus/runtime", "--bind", f"{x}/managed-fleet", "/srv/zeus/managed-fleet",
        "--bind", f"{x}/repo", "/srv/zeus/repo", "--bind", f"{x}/worktrees", "/srv/zeus/worktrees",
        "--bind", f"{x}/zeus-tmp", "/srv/zeus/tmp",
        "--overlay-src", f"{root}/art-src", "--overlay", f"{x}/art-up", f"{x}/art-wk", "/srv/zeus/artifacts",
        "--ro-bind", f"{root}/mocks/systemctl", "/usr/bin/systemctl",
        "--ro-bind", f"{root}/mocks/journalctl", "/usr/bin/journalctl",
        "--chdir", "/home/trevi", "--clearenv", "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/home/trevi",
        "--setenv", "ZEUS_COMPOSITION_PROFILE", "production", "--setenv", "ZEUS_REHEARSAL_RUN", RUN8,
        "--setenv", "ZEUS_RUNTIME_MARK", f"rehearsal-{RUN8}", "--setenv", "ZEUS_OTHER_NAME", f"rehearsal-{RUN8}",
    ]
    assert ns.bwrap_argv(spec) == expected
    assert oct(os.stat(x + "/home").st_mode & 0o777) == "0o700"


def test_the_json_roundtrip_is_the_same_argv(world, tmp_path):
    spec = build(world, with_config=True, sockets=True)
    path = tmp_path / "namespace.json"
    path.write_text(json.dumps(spec.to_json()), encoding="ascii")
    assert ns.bwrap_argv(ns.load_spec(path)) == ns.bwrap_argv(spec)
    bad = json.loads(path.read_text())
    bad["surprise"] = 1
    path.write_text(json.dumps(bad), encoding="ascii")
    with pytest.raises(Refused) as info:
        ns.load_spec(path)
    assert info.value.code == "spec_malformed"


def test_the_env_is_closed_and_reproduces_the_non_secret_dsn_components(world, monkeypatch):
    monkeypatch.setenv("ZEUS_LIVE_SENTINEL", "live-sentinel-value-1234")
    spec = build(world, with_config=True, sockets=True)
    env, root = spec.env_dict(), str(world["root"])
    assert list(env) == ["PATH", "HOME", "HARNESS_DATABASE_URL", "HARNESS_REDIS_URL", "ZEUS_COMPOSITION_PROFILE",
                         "ZEUS_REHEARSAL_RUN", "ZEUS_RUNTIME_MARK", "ZEUS_OTHER_NAME"]
    assert env["HARNESS_DATABASE_URL"] == (f"host={root}/p/pgsock dbname=zeus_aibox user=zeus "
                                           "options='-c search_path=zeus_aibox_control,public'")
    assert env["HARNESS_REDIS_URL"] == f"unix://{root}/p/redsock/redis.sock?db=3"
    assert env["ZEUS_COMPOSITION_PROFILE"] == "production" and env["ZEUS_REHEARSAL_RUN"] == RUN8
    assert "live-sentinel-value-1234" not in " ".join(ns.bwrap_argv(spec))


def test_a_config_with_a_password_or_an_unknown_key_is_refused(world, tmp_path):
    for extra in ({"password": "x"}, {"dsn": "an-unknown-key"}):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"pg_dbname": "d", "pg_user": "u", "search_path": "s", "redis_db": 0, **extra}))
        with pytest.raises(Refused) as info:
            ns.load_nonsecret_config(bad)
        assert info.value.code == "config_malformed"
    bad.write_text(json.dumps({"pg_dbname": "d p", "pg_user": "u", "search_path": "s", "redis_db": 0}))
    with pytest.raises(Refused):
        ns.load_nonsecret_config(bad)


# ---- spec validation: each failure has a named error -----------------------------------------------------------

def test_an_rw_bind_sourced_outside_root_is_refused_and_no_argv_exists(world):
    spec = swap(build(world), "rw", src="/srv/zeus/runtime")  # the spec's Example 1
    assert "rw_bind_outside_root" in codes(spec)
    with pytest.raises(ns.SpecRefused) as info:
        ns.bwrap_argv(spec)
    assert info.value.code == "rw_bind_outside_root"


def test_an_rw_source_through_a_symlink_is_refused_even_when_it_resolves_under_root(world):
    spec = build(world)
    link = world["root"] / "S" / "link-to-runtime"
    if not link.is_symlink():
        link.symlink_to(world["root"] / "S" / "runtime")
    assert "rw_bind_symlink" in codes(swap(spec, "rw", src=str(link)))
    outside = world["root"].parent / "outside"
    outside.mkdir(exist_ok=True)
    escape = world["root"] / "S" / "link-out"
    if not escape.is_symlink():
        escape.symlink_to(outside)
    assert "rw_bind_symlink" in codes(swap(spec, "rw", src=str(escape)))


def test_overlay_upper_and_work_outside_root_are_refused(world):
    outside = world["root"].parent / "outside"
    outside.mkdir(exist_ok=True)
    spec = build(world)
    assert "overlay_upper_outside_root" in codes(swap(spec, "overlay", upper=str(outside)))
    assert "overlay_work_outside_root" in codes(swap(spec, "overlay", work=str(outside)))


def test_ro_binds_must_be_listed_ro_and_modes_must_match_the_kind(world):
    spec = build(world)
    assert "ro_bind_not_listed_ro" in codes(swap(spec, "ro", mode="rw"))
    assert "mode_mismatch" in codes(swap(spec, "rw", mode="ro"))
    assert "mode_missing" in codes(swap(spec, "rw", mode=None))


def test_the_secrets_dir_is_never_bound_and_credential_dirs_are_refused(world):
    spec = build(world)
    assert "secrets_bound" in codes(swap(spec, "rw", dest="/srv/zeus/secrets"))
    assert "secrets_bound" in codes(swap(spec, "ro", src="/srv/zeus/secrets/x"))
    assert "credential_path_bound" in codes(swap(spec, "rw", dest="/home/trevi/.codex"))


def test_a_production_socket_or_dsn_port_in_the_spec_is_refused(world):
    spec = build(world)
    assert "production_socket" in codes(swap(spec, "rw", dest="/run/docker.sock"))
    assert "production_socket" in codes(swap(spec, "rw", dest="/run/systemd/private"))
    for value in ("host=127.0.0.1:55432 dbname=x", "redis://127.0.0.1:56379/0"):
        mutated = dataclasses.replace(spec, env=(*spec.env, ("ZEUS_PROD_DSN", value)))
        assert "production_socket" in codes(mutated)


def test_a_mount_that_hides_an_earlier_one_is_refused_which_is_why_proc_follows_the_base(world):
    spec = build(world)
    literal = [m for m in spec.mounts if m.kind in ("proc", "dev")] + [m for m in spec.mounts if m.kind not in ("proc", "dev")]
    found = codes(dataclasses.replace(spec, mounts=tuple(literal)))
    assert {"base_not_first", "mount_shadowed"} <= found


def test_the_design_literal_order_really_shows_the_host_pid_one(world):
    """The measured reason for the deviation: `--proc` before `--ro-bind / /` is hidden by it (host pid 1 visible)."""
    argv = ["bwrap", "--die-with-parent", "--unshare-pid", "--proc", "/proc", "--dev", "/dev", "--ro-bind", "/", "/",
            "/usr/bin/cat", "/proc/1/comm"]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.strip() != "bwrap"


def test_a_config_digest_mismatch_and_a_missing_recorded_search_path_are_refused(world):
    spec = build(world, with_config=True, sockets=True)
    assert "config_sha_mismatch" in codes(dataclasses.replace(spec, config_sha256="0" * 64))
    assert "search_path_not_recorded" in codes(dataclasses.replace(spec, expected_search_path=None))
    assert "release_b_outside_root_rel" in codes(swap(spec, "release-b", src=str(world["root"] / "r0" / R0_REV)))


# ---- the in-namespace self-test --------------------------------------------------------------------------------

def test_a_write_into_a_srv_root_lands_under_root_and_the_secrets_dir_is_empty(world):
    spec = build(world)
    script = ("echo hi > /srv/zeus/runtime/probe; echo t > /tmp/probe-t; echo h > /home/trevi/probe-h; "
              "ls -A /srv/zeus/secrets | wc -l; docker version >/dev/null 2>&1; echo docker=$?; "
              "cat /usr/bin/systemctl | head -2 | tail -1")
    run = ns.run_in_namespace(spec, ["/usr/bin/sh", "-c", script])
    assert run.returncode == 0, run.stderr
    lines = run.stdout.split("\n")
    assert lines[0] == "0" and lines[1] != "docker=0" and lines[2] == "echo mock-systemctl"
    x = world["root"] / "S"
    assert (x / "runtime" / "probe").read_text() == "hi\n"
    assert (x / "tmp" / "probe-t").exists() and (x / "home" / "probe-h").exists()
    assert not Path("/srv/zeus/runtime/probe").exists()


def test_the_selftest_passes_every_row_and_records_them_with_the_peak_memory(world, tmp_path, monkeypatch):
    monkeypatch.setenv("ZEUS_LIVE_SENTINEL", "live-sentinel-value-1234")
    spec = build(world)
    evidence = Evidence(RUN8, tmp_path / "evidence")
    evidence.start({"unit": "RH-1b"})
    result = ns.selftest(spec, evidence)
    evidence.finish("done")
    assert result.ok, {k: v for k, v in result.rows.items() if not v["ok"]}
    assert result.maxrss_kb > 0
    for row in ("secrets_empty", "credentials_absent", "unreachable_55432", "unreachable_56379", "net_isolated",
                "sockets_absent", "docker_fails", "journal_empty", "pid1_bwrap", "env_closed", "mock_systemctl",
                "mock_journalctl", f"release_origin_{B_REV}", f"release_origin_{R0_REV}", "write_tmp_tmp",
                "write_home_home_trevi", "write_rw_srv_zeus_runtime", "write_rw_srv_zeus_managed_fleet",
                "write_rw_srv_zeus_repo", "write_rw_srv_zeus_worktrees", "write_rw_srv_zeus_tmp",
                "write_overlay_srv_zeus_artifacts", f"write_release-b_srv_zeus_releases_{B_REV}".replace("-", "-")):
        assert row in result.rows and result.rows[row]["ok"], row
    assert result.rows["pid1_bwrap"]["comm"] == "bwrap"
    assert result.rows[f"write_release-r0_srv_zeus_releases_{R0_REV}"]["result"] == "errno_EROFS"
    steps = [json.loads(line) for line in (tmp_path / "evidence" / "steps.jsonl").read_text().splitlines()]
    by_step = {s["step"]: s for s in steps}
    assert by_step["selftest_pid1_bwrap"]["status"] == "pass"
    assert by_step["selftest_run"]["facts"]["maxrss_kb"] == result.maxrss_kb
    x = world["root"] / "S"
    assert list((x / "art-up").iterdir()) == [] and not (x / "runtime" / f"{ns.PROBE_NAME}-{RUN8}").exists()


def test_a_release_whose_pth_holds_the_build_path_fails_the_origin_row(world):
    """Critique #2 mutation: built under ROOT with its ROOT path in the .pth, it cannot import inside the namespace."""
    run = ns.selftest(build(world, b_rev="cc000004"))
    assert not run.ok
    assert run.rows["release_origin_cc000004"]["ok"] is False
    assert run.rows[f"release_origin_{R0_REV}"]["ok"] is True


def test_the_search_path_row_fails_closed_when_no_copy_answers(world):
    root = world["root"]
    spec = build(world, with_config=True, sockets=True, probe_python=sys.executable, extra_ro=(sys.prefix,))
    result = ns.selftest(spec)
    assert not result.ok and result.rows["search_path"]["ok"] is False
    assert [k for k, v in result.rows.items() if not v["ok"]] == ["search_path"], result.rows
    assert not (root / "p" / "pgsock" / f"{ns.PROBE_NAME}-{RUN8}").exists() or True


def test_a_row_the_probe_never_reported_is_a_failure_not_a_skip(world, monkeypatch):
    monkeypatch.setattr(ns, "PROBE_SOURCE", "print('{}')")
    result = ns.selftest(build(world))
    assert not result.ok and result.rows["pid1_bwrap"] == {"ok": False, "result": "missing"}


@pytest.mark.skipif(not DOCKER, reason="needs ZEUS_TEST_DOCKER=1 (real Docker)")
def test_show_search_path_on_a_live_copy_equals_the_recorded_value(tmp_path):
    root = tmp_path / "r"
    handles = cp.Copies(RUN8, root)
    try:
        copy = handles.start("S")
        world_ = {"root": root, "config": None}
        cfg = root / "nonsecret.json"
        cfg.write_text(json.dumps({"pg_dbname": "postgres", "pg_user": "zeus", "search_path": "zeus_aibox_control,public",
                                   "redis_db": 0}), encoding="ascii")
        for name in ("avenv", "uvcache", "art-src"):
            (root / name).mkdir()
        mocks = {}
        for name in ("systemctl", "journalctl"):
            (root / name).write_text("#!/bin/sh\nexit 3\n")
            (root / name).chmod(0o755)
            mocks[f"/usr/bin/{name}"] = str(root / name)
        make_release(root / "rel" / B_REV, B_REV, pth_target=f"/srv/zeus/releases/{B_REV}/src")
        spec = ns.default_spec(
            RUN8, root, "S", a_venv=str(root / "avenv"), uv_python=uv_python_dir(), uv_cache=str(root / "uvcache"),
            releases_r0={}, b_rev=B_REV, mocks=mocks, env_names=[], config_copy=cfg,
            recorded_search_path="zeus_aibox_control,public", pg_socket_dir=copy.pg_socket,
            redis_socket_dir=copy.redis_socket, artifacts_src=str(root / "art-src"), probe_python=sys.executable,
            extra_ro=(sys.prefix,))
        ns.prepare_dirs(spec)
        result = ns.selftest(spec)
        assert result.rows["search_path"]["ok"], result.rows["search_path"]
        wrong = dataclasses.replace(spec, expected_search_path="something_else")
        assert ns.selftest(wrong).rows["search_path"]["ok"] is False
        del world_
    finally:
        handles.copies and [handles.docker("rm", "-f", h.pg_name) for h in handles.copies.values()]
        [handles.docker("rm", "-f", h.redis_name) for h in handles.copies.values()]


# ---- the path preflight ----------------------------------------------------------------------------------------

def test_an_unmounted_srv_prefix_in_a_redis_hash_fails_as_unclassified(world, tmp_path):
    spec = build(world)
    evidence = Evidence(RUN8, tmp_path / "ev")
    evidence.start()
    result = path_preflight(spec, redis_values=[{"dump": "/srv/zeus/backups/x.dump"}], evidence=evidence)
    assert not result.ok
    assert result.prefixes == [{"prefix": "/srv/zeus/backups", "count": 1, "class": "unclassified"}]
    assert result.failures == [{"code": "unclassified_prefix", "subject": "/srv/zeus/backups"}]
    row = json.loads((tmp_path / "ev" / "steps.jsonl").read_text())
    assert row["status"] == "fail" and row["facts"]["failure_codes"] == ["unclassified_prefix"]


def test_prefixes_are_counted_at_depth_four_and_classified_against_the_spec(world):
    spec = build(world)
    texts = {"export.json": json.dumps({
        "a": "/srv/zeus/runtime/control/observations/health/x.json", "b": "/srv/zeus/runtime/control/observations/y",
        "c": "/srv/zeus/releases/aa000002/src/mod.py", "d": f"/srv/zeus/releases/{B_REV}/.venv/bin/python",
        "e": "/srv/zeus/artifacts/one/two/three/f.txt", "f": "/srv/zeus/secrets/token", "g": "/usr/lib/x/y",
        "h": "/home/trevi/workspaces/zeus/worktrees/w1/file.py", "i": "C:\\Users\\trevi\\zeus\\a\\b\\c.py",
        "j": "http://example.com/a/b and 1/2 and 2026/10/06 and file:///srv/zeus/repo/r.py",
        "k": "PATH=/usr/bin:/bin", "l": "/run/docker-ish/x"})}
    got = {p["prefix"]: (p["count"], p["class"]) for p in path_preflight(spec, texts=texts).prefixes}
    assert got == {
        "/srv/zeus/runtime/control": (2, "rw-under-ROOT"),
        "/srv/zeus/releases/aa000002": (1, "ro"), f"/srv/zeus/releases/{B_REV}": (1, "ro"),
        "/srv/zeus/artifacts/one": (1, "overlay"), "/srv/zeus/secrets/token": (1, "masked"),
        "/usr/lib/x/y": (1, "ro"), "/home/trevi/workspaces/zeus": (1, "rw-under-ROOT"),
        "C:/Users/trevi/zeus/a": (1, "windows-drive"), "/srv/zeus/repo": (1, "rw-under-ROOT"),
        "/usr/bin": (1, "ro"), "/bin": (1, "ro"), "/run/docker-ish/x": (1, "masked"),
    }
    assert scan_text("a/b http://h/p 3/4") == {}


def test_a_prefix_reaching_a_writable_mount_outside_root_fails(world):
    outside = world["root"].parent / "outside"
    outside.mkdir(exist_ok=True)
    spec = swap(build(world), "rw", src=str(outside))  # not validated: the preflight must still fail closed
    result = path_preflight(spec, texts={"x": "/srv/zeus/runtime/a/b"})
    assert not result.ok and result.failures[0]["code"] == "writable_outside_root"


def test_a_cleanup_target_outside_root_fails_and_one_inside_passes(world):
    spec = build(world)
    inside = str(world["root"] / "S" / "pgdata")
    assert path_preflight(spec, cleanup_targets=[inside]).ok
    outside = path_preflight(spec, cleanup_targets=[str(world["root"].parent), "/srv/zeus/runtime", "rel/path",
                                                    str(world["root"] / ".." / "x")])
    assert [f["code"] for f in outside.failures] == ["cleanup_outside_root"] * 4


def test_the_preflight_evidence_never_carries_a_secrets_path(world, tmp_path):
    evidence = Evidence(RUN8, tmp_path / "ev")
    evidence.start()
    result = path_preflight(build(world), texts={"t": "/srv/zeus/secrets/token /srv/zeus/runtime/a"}, evidence=evidence)
    assert result.ok
    assert "secrets" not in (tmp_path / "ev" / "steps.jsonl").read_text()


# ---- volatile staging (critique #5) -----------------------------------------------------------------------------

def make_source(tmp_path):
    src = tmp_path / "src"
    health = src / "runtime" / "control" / "observations" / "health"
    health.mkdir(parents=True)
    (health / "h1.json").write_text('{"n": 1}', encoding="ascii")
    (src / "runtime" / "control" / "monitoring.json").write_text('{"m": 1}', encoding="ascii")
    (src / "runtime" / "tokobs").mkdir()
    (src / "runtime" / "tokobs" / "ledger.sqlite3").write_bytes(b"tokobs-ledger")
    (src / "runtime" / "managed-fleet").mkdir()
    (src / "runtime" / "managed-fleet" / "heartbeat.json").write_text("beat", encoding="ascii")
    return src


def test_a_file_added_after_the_snapshot_is_not_in_the_copy_and_copy_edits_never_reach_the_source(tmp_path):
    src, dst = make_source(tmp_path), tmp_path / "dst"
    manifest = cp.snapshot_volatile(src, dst)
    (src / "runtime" / "control" / "observations" / "health" / "late.json").write_text("late", encoding="ascii")
    assert not (dst / "runtime" / "control" / "observations" / "health" / "late.json").exists()
    copy = dst / "runtime" / "control" / "monitoring.json"
    assert copy.read_text() == '{"m": 1}'
    copy.write_text('{"m": "changed in the copy"}', encoding="ascii")
    assert (src / "runtime" / "control" / "monitoring.json").read_text() == '{"m": 1}'
    assert os.stat(copy).st_ino != os.stat(src / "runtime" / "control" / "monitoring.json").st_ino
    assert {e["path"] for e in manifest["files"]} == {
        "runtime/control/observations/health/h1.json", "runtime/control/monitoring.json",
        "runtime/managed-fleet/heartbeat.json"}
    assert all(len(e["sha256"]) == 64 and e["mtime_ns"] > 0 for e in manifest["files"]) and manifest["skew_ns"] >= 0


def test_tokobs_is_excluded_and_a_declared_path_inside_the_exclusion_is_refused(tmp_path):
    src, dst = make_source(tmp_path), tmp_path / "dst"
    manifest = cp.snapshot_volatile(src, dst, volatile=("runtime/control/monitoring.json",))
    assert not (dst / "runtime" / "tokobs").exists() and manifest["excluded"] == ["runtime/tokobs"]
    with pytest.raises(Refused) as info:
        cp.snapshot_volatile(src, tmp_path / "dst2", volatile=("runtime/tokobs/ledger.sqlite3",))
    assert info.value.code == "volatile_excluded"
    with pytest.raises(Refused) as info:
        cp.snapshot_volatile(src, tmp_path / "dst3", volatile=("runtime",))  # a parent of the excluded path
    assert info.value.code == "volatile_excluded"


def test_the_snapshot_succeeds_while_a_writer_keeps_touching_a_volatile_file_and_records_what_it_wrote(tmp_path):
    src, dst = make_source(tmp_path), tmp_path / "dst"
    target, stop = src / "runtime" / "control" / "monitoring.json", threading.Event()

    def writer():
        n = 0
        while not stop.is_set():
            n += 1
            target.write_text(json.dumps({"m": n}), encoding="ascii")

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        manifest = cp.snapshot_volatile(src, dst)
    finally:
        stop.set()
        thread.join()
    entry = next(e for e in manifest["files"] if e["path"] == "runtime/control/monitoring.json")
    import hashlib

    data = (dst / "runtime" / "control" / "monitoring.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"] and entry["size"] == len(data)


def test_a_symlinked_volatile_path_is_refused(tmp_path):
    src = make_source(tmp_path)
    (src / "runtime" / "link.json").symlink_to(src / "runtime" / "control" / "monitoring.json")
    with pytest.raises(Refused) as info:
        cp.snapshot_volatile(src, tmp_path / "dst", volatile=("runtime/link.json",))
    assert info.value.code == "volatile_symlink"


def test_the_sweep_removes_a_root_that_holds_an_overlay_work_dir_left_by_a_namespace_run(tmp_path):
    from rehearsal.sweep import sweep

    root = tmp_path / "swroot"
    root.mkdir()
    (root / cp.MARKER).write_text(RUN8, encoding="ascii")
    for name in ("avenv", "uvcache", "art-src", "mocks"):
        (root / name).mkdir()
    for name in ("systemctl", "journalctl"):
        (root / "mocks" / name).write_text("#!/bin/sh\n")
    (root / "r0").mkdir()
    (root / "rel" / B_REV).mkdir(parents=True)
    spec = ns.default_spec(RUN8, root, "S", a_venv=str(root / "avenv"), uv_python=uv_python_dir(),
                           uv_cache=str(root / "uvcache"), releases_r0={}, b_rev=B_REV, env_names=[],
                           mocks={"/usr/bin/systemctl": str(root / "mocks" / "systemctl"),
                                  "/usr/bin/journalctl": str(root / "mocks" / "journalctl")},
                           artifacts_src=str(root / "art-src"))
    ns.prepare_dirs(spec)
    assert ns.run_in_namespace(spec, ["/usr/bin/true"]).returncode == 0
    work = root / "S" / "art-wk" / "work"
    assert work.is_dir() and (work.stat().st_mode & 0o700) == 0  # the residue that defeats a plain rmtree
    quiet = lambda *args, timeout=120: subprocess.CompletedProcess(args, 0, "", "")  # noqa: E731
    assert sweep(RUN8, root, docker=quiet)["root_removed"] is True and not root.exists()
