"""Resource facts (the USE method's utilization, saturation and errors) read from documented kernel files.

Every value is read through injected roots: cgroup v2 files (`memory.*`, `cpu.stat`, `pids.*`, `*.pressure`), `/proc/pressure/*`,
`/proc/net/dev` and `statvfs`. Only configured NAMES (a unit, a mount, an interface) or `host` ever become a label; a path never becomes a
label or an output value. Unavailable is never zero: a missing or unreadable file, a disabled controller, PSI switched off, a `statvfs`
failure, an absent interface or a malformed line leaves the value series of that fact ABSENT and sets
`zeus_resource_fact_available{scope,fact}` to 0. No file text reaches the output and nothing here raises on a bad file.

Layer: adapters
Context: observation
Owns: `ResourceFacts` and its row families (cgroup CPU, memory and pids, PSI, filesystems, network interfaces, availability); raw facts only, ratios are recording rules
Does not own: the renderer (the X2 metric renderer consumes `rows()`), PostgreSQL and Redis facts (X3b, injected callables), wiring (S10), alert rules (X4)
Entry points: ResourceFacts
Contracts: INV-OBSERVATION-001
"""
import os
import re
from pathlib import PurePosixPath

_READ_LIMIT = 1 << 20
_PSI_LINE = re.compile(r"(some|full) avg10=(\d+\.\d+) avg60=(\d+\.\d+) avg300=(\d+\.\d+) total=(\d+)", re.ASCII)
_PSI_WINDOWS = ("10s", "60s", "300s")
_PSI_RESOURCES = ("cpu", "memory", "io")
_MEMORY_EVENTS = ("low", "high", "max", "oom", "oom_kill", "oom_group_kill")
_UNLIMITED = "max"
_DIRECTIONS = (("receive", 0), ("transmit", 8))

_FAMILIES = {
    "zeus_cgroup_cpu_usage_seconds_total": ("counter", ("unit",), "Total CPU time used by the cgroup in seconds, from usage_usec in cpu.stat."),
    "zeus_cgroup_cpu_throttled_seconds_total": ("counter", ("unit",), "Total time the cgroup was throttled in seconds, from throttled_usec in cpu.stat."),
    "zeus_cgroup_cpu_throttled_periods_total": ("counter", ("unit",), "Number of throttled enforcement periods of the cgroup, from nr_throttled in cpu.stat."),
    "zeus_cgroup_memory_current_bytes": ("gauge", ("unit",), "Memory currently used by the cgroup in bytes, from memory.current."),
    "zeus_cgroup_memory_max_bytes": ("gauge", ("unit",), "Memory limit of the cgroup in bytes, from memory.max, absent when the limit is max."),
    "zeus_cgroup_memory_limited": ("gauge", ("unit",), "1 when memory.max holds a number and 0 when it holds max."),
    "zeus_cgroup_memory_events_total": ("counter", ("unit", "event"), "Memory events of the cgroup by event, from memory.events."),
    "zeus_cgroup_pids_current": ("gauge", ("unit",), "Number of processes in the cgroup, from pids.current."),
    "zeus_cgroup_pids_max": ("gauge", ("unit",), "Process limit of the cgroup, from pids.max, absent when the limit is max."),
    "zeus_cgroup_pids_limit_hits_total": ("counter", ("unit",), "Number of times the cgroup process limit was hit, from max in pids.events."),
    "zeus_pressure_waiting_seconds_total": ("counter", ("scope", "resource", "kind"), "Total time tasks stalled in seconds, from total in the PSI files under /proc/pressure and the cgroup *.pressure files."),
    "zeus_pressure_stall_ratio": ("gauge", ("scope", "resource", "kind", "window"), "Share of time tasks stalled over a window, from the avg10, avg60 and avg300 values of the PSI files divided by 100."),
    "zeus_filesystem_size_bytes": ("gauge", ("mount",), "Size of the filesystem in bytes, from f_frsize times f_blocks of statvfs."),
    "zeus_filesystem_available_bytes": ("gauge", ("mount",), "Bytes available to unprivileged users, from f_frsize times f_bavail of statvfs."),
    "zeus_filesystem_files": ("gauge", ("mount",), "Number of inodes of the filesystem, from f_files of statvfs."),
    "zeus_filesystem_files_available": ("gauge", ("mount",), "Number of inodes available to unprivileged users, from f_favail of statvfs."),
    "zeus_network_bytes_total": ("counter", ("interface", "direction"), "Bytes received and transmitted by the interface, from /proc/net/dev."),
    "zeus_network_errors_total": ("counter", ("interface", "direction"), "Errors on receive and transmit of the interface, from the errs columns of /proc/net/dev."),
    "zeus_network_drops_total": ("counter", ("interface", "direction"), "Packets dropped on receive and transmit of the interface, from the drop columns of /proc/net/dev."),
    "zeus_resource_fact_available": ("gauge", ("scope", "fact"), "1 when the fact was read and 0 when its source file was missing, disabled or malformed."),
}


def _read(path):
    try:
        with open(path, "r", encoding="ascii") as handle:
            text = handle.read(_READ_LIMIT + 1)
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return text if len(text) <= _READ_LIMIT else None


def _read_int(path):
    text = _read(path)
    if text is None or not text.strip().isdecimal():
        return None
    return int(text.strip())


def _read_limit(path):
    text = _read(path)
    if text is None:
        return None
    word = text.strip()
    return word if word == _UNLIMITED else (int(word) if word.isdecimal() else None)


def _read_pairs(path):
    """`key value` lines as a dict, or None when the file is missing, empty or has any malformed or repeated line."""
    text = _read(path)
    if text is None:
        return None
    pairs = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].isdecimal() or parts[0] in pairs:
            return None
        pairs[parts[0]] = int(parts[1])
    return pairs or None


def _read_pressure(path, full_required):
    """{kind: (avg10, avg60, avg300, total)} from a PSI file, or None when it is missing or malformed."""
    text = _read(path)
    if text is None:
        return None
    kinds = {}
    for line in text.splitlines():
        match = _PSI_LINE.fullmatch(line.strip())
        if match is None or match.group(1) in kinds:
            return None
        kinds[match.group(1)] = (float(match.group(2)), float(match.group(3)), float(match.group(4)), int(match.group(5)))
    if "some" not in kinds or (full_required and "full" not in kinds):
        return None
    return kinds


def _read_network(path):
    """{interface: [16 counters]} for every well-formed row; a malformed row is left out, so its interface reads as absent."""
    text = _read(path)
    if text is None:
        return {}
    interfaces = {}
    for line in text.splitlines()[2:]:
        name, separator, rest = line.partition(":")
        fields = rest.split()
        if separator and len(fields) == 16 and all(field.isdecimal() for field in fields):
            interfaces[name.strip()] = [int(field) for field in fields]
    return interfaces


class _Rows:
    def __init__(self):
        self.series = {name: [] for name in _FAMILIES}

    def add(self, metric, labels, value):
        self.series[metric].append({"labels": list(labels), "value": value})

    def available(self, scope, fact, ok):
        self.add("zeus_resource_fact_available", (scope, fact), 1 if ok else 0)

    def rows(self):
        rows = []
        for name in sorted(_FAMILIES):
            kind, labels, help_text = _FAMILIES[name]
            series = sorted(self.series[name], key=lambda item: item["labels"])
            rows.append({"metric": name, "type": kind, "help": help_text, "labels": list(labels), "buckets": [], "series": series})
        return rows


class ResourceFacts:
    """`units` maps a unit NAME to its cgroup path relative to `cgroup_root`, `mounts` a mount NAME to a path, `interfaces` is a tuple of names."""

    def __init__(self, *, cgroup_root, proc_root, units, mounts, interfaces, statvfs=os.statvfs):
        for relative in units.values():
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("a unit cgroup path is relative to the cgroup root and never leaves it")
        if "host" in units:
            raise ValueError("`host` is the scope of /proc/pressure and cannot name a unit")
        self._cgroup_root = str(cgroup_root)
        self._proc_root = str(proc_root)
        self._units = dict(units)
        self._mounts = dict(mounts)
        self._interfaces = tuple(interfaces)
        self._statvfs = statvfs

    def rows(self):
        out = _Rows()
        for unit in sorted(self._units):
            self._unit(out, unit, os.path.join(self._cgroup_root, self._units[unit]))
        for resource in _PSI_RESOURCES:
            self._pressure(out, "host", resource, os.path.join(self._proc_root, "pressure", resource))
        for mount in sorted(self._mounts):
            self._filesystem(out, mount, self._mounts[mount])
        self._network(out)
        return out.rows()

    def _unit(self, out, unit, base):
        labels = (unit,)
        stat = _read_pairs(os.path.join(base, "cpu.stat"))
        usage = stat is not None and "usage_usec" in stat
        throttling = stat is not None and "nr_throttled" in stat and "throttled_usec" in stat
        if usage:
            out.add("zeus_cgroup_cpu_usage_seconds_total", labels, stat["usage_usec"] / 1e6)
        if throttling:
            out.add("zeus_cgroup_cpu_throttled_seconds_total", labels, stat["throttled_usec"] / 1e6)
            out.add("zeus_cgroup_cpu_throttled_periods_total", labels, stat["nr_throttled"])
        out.available(unit, "cpu_stat", usage)
        out.available(unit, "cpu_throttling", throttling)

        current = _read_int(os.path.join(base, "memory.current"))
        limit = _read_limit(os.path.join(base, "memory.max"))
        if current is not None:
            out.add("zeus_cgroup_memory_current_bytes", labels, current)
        if limit is not None:
            out.add("zeus_cgroup_memory_limited", labels, 0 if limit == _UNLIMITED else 1)
            if limit != _UNLIMITED:
                out.add("zeus_cgroup_memory_max_bytes", labels, limit)
        out.available(unit, "memory", current is not None and limit is not None)

        events = _read_pairs(os.path.join(base, "memory.events"))
        if events is not None:
            for event in _MEMORY_EVENTS:
                if event in events:
                    out.add("zeus_cgroup_memory_events_total", (unit, event), events[event])
        out.available(unit, "memory_events", events is not None)

        processes = _read_int(os.path.join(base, "pids.current"))
        process_limit = _read_limit(os.path.join(base, "pids.max"))
        process_events = _read_pairs(os.path.join(base, "pids.events"))
        hits = process_events.get("max") if process_events is not None else None
        if processes is not None:
            out.add("zeus_cgroup_pids_current", labels, processes)
        if process_limit not in (None, _UNLIMITED):
            out.add("zeus_cgroup_pids_max", labels, process_limit)
        if hits is not None:
            out.add("zeus_cgroup_pids_limit_hits_total", labels, hits)
        out.available(unit, "pids", processes is not None and process_limit is not None and hits is not None)

        for resource in _PSI_RESOURCES:
            self._pressure(out, unit, resource, os.path.join(base, resource + ".pressure"))

    def _pressure(self, out, scope, resource, path):
        # Per-resource full is optional for cpu only (absent on old kernels, zero since 5.13): INV-OBSERVATION-001.
        kinds = _read_pressure(path, resource != "cpu")
        if kinds is not None:
            for kind, (avg10, avg60, avg300, total) in kinds.items():
                out.add("zeus_pressure_waiting_seconds_total", (scope, resource, kind), total / 1e6)
                for window, average in zip(_PSI_WINDOWS, (avg10, avg60, avg300)):
                    out.add("zeus_pressure_stall_ratio", (scope, resource, kind, window), average / 100)
        out.available(scope, "pressure_" + resource, kinds is not None)

    def _filesystem(self, out, mount, path):
        try:
            stat = self._statvfs(path)
            size = stat.f_frsize * stat.f_blocks
            available = stat.f_frsize * stat.f_bavail
            files, files_available = stat.f_files, stat.f_favail
        except (OSError, ValueError, AttributeError, TypeError):
            out.available(mount, "filesystem", False)
            return
        out.add("zeus_filesystem_size_bytes", (mount,), size)
        out.add("zeus_filesystem_available_bytes", (mount,), available)
        out.add("zeus_filesystem_files", (mount,), files)
        out.add("zeus_filesystem_files_available", (mount,), files_available)
        out.available(mount, "filesystem", True)

    def _network(self, out):
        table = _read_network(os.path.join(self._proc_root, "net", "dev"))
        for interface in sorted(self._interfaces):
            counters = table.get(interface)
            if counters is not None:
                for direction, offset in _DIRECTIONS:
                    out.add("zeus_network_bytes_total", (interface, direction), counters[offset])
                    out.add("zeus_network_errors_total", (interface, direction), counters[offset + 2])
                    out.add("zeus_network_drops_total", (interface, direction), counters[offset + 3])
            out.available(interface, "network", counters is not None)
