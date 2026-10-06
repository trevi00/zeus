"""S9 X3a: the resource facts adapter reads cgroup v2, PSI, statvfs and /proc/net/dev through injected roots.

Fixture trees under `fixtures/s9_x3a/` hold documented kernel file formats with distinct numbers; variants are copied to `tmp_path` and edited.
Unavailable is never zero: the value series is absent and `zeus_resource_fact_available` is 0.
"""
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.observation.adapters.resource_facts import ResourceFacts

FIXTURES = Path(__file__).parent / "fixtures" / "s9_x3a"
UNIT_DIR = "system.slice/zeus-worker.service"
ROW_KEYS = {"metric", "type", "help", "labels", "buckets", "series"}


def statvfs_stub(path):
    return SimpleNamespace(f_frsize=4096, f_blocks=1000, f_bavail=400, f_files=5000, f_favail=3000)


def tree(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(FIXTURES, root)
    return root


def facts(root, statvfs=statvfs_stub, mounts=None):
    return ResourceFacts(cgroup_root=root / "cgroup", proc_root=root / "proc", units={"worker": UNIT_DIR},
                         mounts={"data": str(root / "data")} if mounts is None else mounts, interfaces=("eth0",), statvfs=statvfs)


def table(rows):
    return {row["metric"]: {tuple(item["labels"]): item["value"] for item in row["series"]} for row in rows}


def available(rows):
    return table(rows)["zeus_resource_fact_available"]


def unit_file(root, name):
    return root / "cgroup" / UNIT_DIR / name


def test_full_tree_exact_values(tmp_path):
    rows = facts(tree(tmp_path)).rows()
    assert [row["metric"] for row in rows] == sorted(row["metric"] for row in rows)
    expected = {
        "zeus_cgroup_cpu_usage_seconds_total": {("worker",): 7.5},
        "zeus_cgroup_cpu_throttled_seconds_total": {("worker",): 3.25},
        "zeus_cgroup_cpu_throttled_periods_total": {("worker",): 56},
        "zeus_cgroup_memory_current_bytes": {("worker",): 123456789},
        "zeus_cgroup_memory_max_bytes": {("worker",): 2147483648},
        "zeus_cgroup_memory_limited": {("worker",): 1},
        "zeus_cgroup_memory_events_total": {("worker", "low"): 1, ("worker", "high"): 2, ("worker", "max"): 3, ("worker", "oom"): 4,
                                            ("worker", "oom_kill"): 5, ("worker", "oom_group_kill"): 6},
        "zeus_cgroup_pids_current": {("worker",): 17},
        "zeus_cgroup_pids_max": {("worker",): 512},
        "zeus_cgroup_pids_limit_hits_total": {("worker",): 9},
        "zeus_pressure_waiting_seconds_total": {
            ("worker", "cpu", "some"): 2.5, ("worker", "cpu", "full"): 1.5,
            ("worker", "memory", "some"): 4.0, ("worker", "memory", "full"): 3.0,
            ("worker", "io", "some"): 6.0, ("worker", "io", "full"): 5.0,
            ("host", "cpu", "some"): 11.0,
            ("host", "memory", "some"): 22.0, ("host", "memory", "full"): 13.0,
            ("host", "io", "some"): 33.0, ("host", "io", "full"): 17.0},
        "zeus_pressure_stall_ratio": {},
        "zeus_filesystem_size_bytes": {("data",): 4096 * 1000},
        "zeus_filesystem_available_bytes": {("data",): 4096 * 400},
        "zeus_filesystem_files": {("data",): 5000},
        "zeus_filesystem_files_available": {("data",): 3000},
        "zeus_network_bytes_total": {("eth0", "receive"): 1000001, ("eth0", "transmit"): 9000009},
        "zeus_network_errors_total": {("eth0", "receive"): 3, ("eth0", "transmit"): 11},
        "zeus_network_drops_total": {("eth0", "receive"): 4, ("eth0", "transmit"): 12},
        "zeus_resource_fact_available": {(scope, fact): 1 for scope in ("worker",) for fact in (
            "cpu_stat", "cpu_throttling", "memory", "memory_events", "pids", "pressure_cpu", "pressure_memory", "pressure_io")},
    }
    ratios = {("worker", "cpu", "some"): (1.50, 0.75, 0.25), ("worker", "cpu", "full"): (0.50, 0.40, 0.30),
              ("worker", "memory", "some"): (2.00, 1.00, 0.50), ("worker", "memory", "full"): (1.00, 0.50, 0.25),
              ("worker", "io", "some"): (3.00, 2.00, 1.00), ("worker", "io", "full"): (2.50, 1.50, 0.75),
              ("host", "cpu", "some"): (10.0, 8.0, 6.0),
              ("host", "memory", "some"): (20.0, 18.0, 16.0), ("host", "memory", "full"): (12.0, 11.0, 9.0),
              ("host", "io", "some"): (30.0, 28.0, 26.0), ("host", "io", "full"): (14.0, 13.0, 7.0)}
    for key, averages in ratios.items():
        for window, average in zip(("10s", "60s", "300s"), averages):
            expected["zeus_pressure_stall_ratio"][key + (window,)] = pytest.approx(average / 100)
    for scope, fact in (("host", "pressure_cpu"), ("host", "pressure_memory"), ("host", "pressure_io"), ("data", "filesystem"), ("eth0", "network")):
        expected["zeus_resource_fact_available"][(scope, fact)] = 1
    got = table(rows)
    assert got == expected
    # Example 1 of the spec: exact text of the first stall ratio.
    assert got["zeus_pressure_stall_ratio"][("worker", "cpu", "some", "10s")] == 0.015


def test_controller_off_has_no_throttling_series(tmp_path):
    root = tree(tmp_path)
    unit_file(root, "cpu.stat").write_text("usage_usec 7500000\nuser_usec 5000000\nsystem_usec 2500000\n")
    rows = facts(root).rows()
    got = table(rows)
    assert got["zeus_cgroup_cpu_usage_seconds_total"] == {("worker",): 7.5}
    assert got["zeus_cgroup_cpu_throttled_seconds_total"] == {}
    assert got["zeus_cgroup_cpu_throttled_periods_total"] == {}
    assert available(rows)[("worker", "cpu_throttling")] == 0
    assert available(rows)[("worker", "cpu_stat")] == 1


def test_no_limits_omit_max_gauges(tmp_path):
    root = tree(tmp_path)
    unit_file(root, "memory.max").write_text("max\n")
    unit_file(root, "pids.max").write_text("max\n")
    rows = facts(root).rows()
    got = table(rows)
    assert got["zeus_cgroup_memory_max_bytes"] == {}
    assert got["zeus_cgroup_pids_max"] == {}
    assert got["zeus_cgroup_memory_limited"] == {("worker",): 0}
    assert got["zeus_cgroup_memory_current_bytes"] == {("worker",): 123456789}
    assert got["zeus_cgroup_pids_current"] == {("worker",): 17}
    assert available(rows)[("worker", "memory")] == 1
    assert available(rows)[("worker", "pids")] == 1


def test_psi_off_leaves_no_pressure_series(tmp_path):
    root = tree(tmp_path)
    shutil.rmtree(root / "proc" / "pressure")
    for resource in ("cpu", "memory", "io"):
        unit_file(root, resource + ".pressure").unlink()
    rows = facts(root).rows()
    got = table(rows)
    assert got["zeus_pressure_waiting_seconds_total"] == {}
    assert got["zeus_pressure_stall_ratio"] == {}
    for scope in ("host", "worker"):
        for resource in ("cpu", "memory", "io"):
            assert available(rows)[(scope, "pressure_" + resource)] == 0


def test_contained_oom_counters(tmp_path):
    root = tree(tmp_path)
    unit_file(root, "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 1\noom_kill 1\noom_group_kill 0\n")
    got = table(facts(root).rows())["zeus_cgroup_memory_events_total"]
    assert got == {("worker", "low"): 0, ("worker", "high"): 0, ("worker", "max"): 0, ("worker", "oom"): 1,
                   ("worker", "oom_kill"): 1, ("worker", "oom_group_kill"): 0}


def test_malformed_files_are_unavailable_and_carry_no_text(tmp_path):
    root = tree(tmp_path)
    unit_file(root, "memory.events").write_text("low 0\nSECRET-GARBAGE-LINE here now\n")
    unit_file(root, "memory.current").write_text("SECRET-NOT-A-NUMBER\n")
    (root / "proc" / "net" / "dev").write_text(
        "Inter-|   Receive\n face |bytes\n  eth0: 1000001 2002 3\n")
    rows = facts(root).rows()
    got = table(rows)
    assert got["zeus_cgroup_memory_events_total"] == {}
    assert got["zeus_cgroup_memory_current_bytes"] == {}
    assert got["zeus_network_bytes_total"] == {}
    assert got["zeus_network_errors_total"] == {} and got["zeus_network_drops_total"] == {}
    flags = available(rows)
    assert flags[("worker", "memory_events")] == 0
    assert flags[("worker", "memory")] == 0
    assert flags[("eth0", "network")] == 0
    assert flags[("worker", "cpu_stat")] == 1
    assert "SECRET" not in repr(rows)


def test_statvfs_failure_and_absent_interface_are_unavailable(tmp_path):
    root = tree(tmp_path)

    def failing(path):
        raise OSError("boom " + str(path))

    rows = ResourceFacts(cgroup_root=root / "cgroup", proc_root=root / "proc", units={}, mounts={"data": "/x"}, interfaces=("nope",),
                         statvfs=failing).rows()
    got = table(rows)
    assert got["zeus_filesystem_size_bytes"] == {} and got["zeus_network_bytes_total"] == {}
    assert available(rows) == {("data", "filesystem"): 0, ("nope", "network"): 0, ("host", "pressure_cpu"): 1,
                               ("host", "pressure_memory"): 1, ("host", "pressure_io"): 1}
    assert "boom" not in repr(rows)


def test_a_missing_unit_directory_is_unavailable_never_zero(tmp_path):
    root = tree(tmp_path)
    shutil.rmtree(root / "cgroup")
    rows = facts(root).rows()
    got = table(rows)
    for metric in ("zeus_cgroup_cpu_usage_seconds_total", "zeus_cgroup_memory_current_bytes", "zeus_cgroup_memory_events_total",
                   "zeus_cgroup_pids_current", "zeus_cgroup_pids_limit_hits_total", "zeus_cgroup_memory_limited"):
        assert got[metric] == {}
    assert all(value == 0 for (scope, _), value in available(rows).items() if scope == "worker")


def test_no_path_reaches_a_label_or_value(tmp_path):
    root = tree(tmp_path)
    rows = facts(root).rows()
    text = repr(rows)
    for fragment in (str(tmp_path), str(root), "system.slice", "zeus-worker.service", "pressure/", "/data"):
        assert fragment not in text
    for row in rows:
        for item in row["series"]:
            assert all(isinstance(label, str) and "/" not in label for label in item["labels"])
            assert isinstance(item["value"], (int, float))


def test_row_shape(tmp_path):
    rows = facts(tree(tmp_path)).rows()
    assert len(rows) == 20
    for row in rows:
        assert set(row) == ROW_KEYS
        assert row["type"] in ("counter", "gauge")
        assert row["buckets"] == []
        assert row["help"].endswith(".") and row["help"].count(". ") == 0
        for item in row["series"]:
            assert set(item) == {"labels", "value"}
            assert len(item["labels"]) == len(row["labels"])
        keys = [item["labels"] for item in row["series"]]
        assert keys == sorted(keys)


def test_unit_paths_cannot_leave_the_root(tmp_path):
    for bad in ("/etc", "../x", "a/../../x"):
        with pytest.raises(ValueError):
            ResourceFacts(cgroup_root=tmp_path, proc_root=tmp_path, units={"u": bad}, mounts={}, interfaces=())
    with pytest.raises(ValueError):
        ResourceFacts(cgroup_root=tmp_path, proc_root=tmp_path, units={"host": "x"}, mounts={}, interfaces=())


@pytest.mark.skipif(not os.path.isdir("/proc/pressure"), reason="PSI is not exposed on this host")
def test_real_host_shape_only():
    rows = ResourceFacts(cgroup_root="/sys/fs/cgroup", proc_root="/proc", units={}, mounts={"root": "/"}, interfaces=()).rows()
    for row in rows:
        assert set(row) == ROW_KEYS and row["type"] in ("counter", "gauge")
        for item in row["series"]:
            assert len(item["labels"]) == len(row["labels"])
    flags = available(rows)
    for resource in ("cpu", "memory", "io"):
        assert flags[("host", "pressure_" + resource)] in (0, 1)
