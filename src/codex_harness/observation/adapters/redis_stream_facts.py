"""Redis stream facts (pending, lag, oldest pending idle, dead letters, memory) as X2 rows.

REDIS-STREAMS G3. Per configured agent the entries, pending and lag come from `collectors.redis_facts` (reused, not re-read); the oldest pending idle
time is the largest idle of the first `pending_sample` entries of `XPENDING <stream> workers - + <pending_sample>`, so it is a bounded sample. The server
scope reads the XLEN of `<namespace>:dead-letter` (0 when the key does not exist) and INFO memory (`used_memory`, `maxmemory`). Only the configured agent
names and `server` become label values. Unavailable is never zero: a connection or command error makes `zeus_redis_facts_available{scope}` 0 and leaves
the value series of that scope ABSENT (an unknown lag, nothing pending and an unlimited `maxmemory` are absent too, with `available` still 1). No
exception text, key name, URL, entry id or payload reaches the output and nothing here raises.

Layer: adapters
Context: observation
Owns: `RedisStreamFacts` and its row families; raw facts only, ratios and thresholds are recording and alert rules
Does not own: the Redis bus and the per-agent reads (`collectors.redis_facts`, injected through `bus_factory`), the renderer (X2 consumes `rows()`), wiring (S10), alert rules (X4)
Entry points: RedisStreamFacts
Contracts: INV-OBSERVATION-001
"""
from codex_harness.observation.adapters.collectors import redis_facts

GROUP = "workers"
SERVER = "server"

_FAMILIES = {
    "zeus_redis_dead_letter_entries": ("gauge", (), "Number of entries in the namespace dead-letter stream, 0 when the stream does not exist."),
    "zeus_redis_facts_available": ("gauge", ("scope",), "1 when the Redis reads of the scope (an agent or server) succeeded and 0 when a connection or command failed."),
    "zeus_redis_memory_max_bytes": ("gauge", (), "Redis maxmemory in bytes from INFO memory, absent when maxmemory is 0 (unlimited)."),
    "zeus_redis_memory_used_bytes": ("gauge", (), "Redis used_memory in bytes from INFO memory."),
    "zeus_redis_pending_oldest_idle_seconds": ("gauge", ("agent",), "Longest idle time in seconds since last delivery over the first N pending entries of the workers group (a bounded sample), absent when nothing is pending."),
    "zeus_redis_stream_entries": ("gauge", ("agent",), "Number of entries in the agent stream (XLEN)."),
    "zeus_redis_stream_lag": ("gauge", ("agent",), "Entries of the agent stream not yet delivered to the groups (XINFO GROUPS lag), absent when Redis cannot determine it."),
    "zeus_redis_stream_pending": ("gauge", ("agent",), "Entries delivered to the workers group and not yet acknowledged, summed over the groups."),
}


def _count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("not a count")
    return value


class RedisStreamFacts:
    """`agents` is the closed roster of agent names; `bus_factory(url)` builds a RedisBus as `CollectorPorts.bus_factory` does."""

    def __init__(self, *, url, agents, bus_factory, pending_sample=100):
        if isinstance(pending_sample, bool) or not isinstance(pending_sample, int) or pending_sample < 1:
            raise ValueError("the pending sample is a positive integer")
        if SERVER in agents:
            raise ValueError("`server` is the scope of the Redis server and cannot name an agent")
        self._url = url
        self._agents = tuple(agents)
        self._bus_factory = bus_factory
        self._sample = pending_sample

    def rows(self):
        series = {name: [] for name in _FAMILIES}

        def add(metric, labels, value):
            series[metric].append({"labels": list(labels), "value": value})

        try:
            bus = self._bus_factory(self._url)
        except Exception:
            bus = None
        for agent in self._agents:
            values = self._agent(bus, agent) if bus is not None else None
            add("zeus_redis_facts_available", (agent,), 0 if values is None else 1)
            for metric, value in (values or {}).items():
                add(metric, (agent,), value)
        values = self._server(bus) if bus is not None else None
        add("zeus_redis_facts_available", (SERVER,), 0 if values is None else 1)
        for metric, value in (values or {}).items():
            add(metric, (), value)
        rows = []
        for name in sorted(_FAMILIES):
            kind, labels, help_text = _FAMILIES[name]
            rows.append({"metric": name, "type": kind, "help": help_text, "labels": list(labels), "buckets": [],
                         "series": sorted(series[name], key=lambda item: item["labels"])})
        return rows

    def _agent(self, bus, agent):
        """The value series of one agent, or None when any read of it failed (then none of them is emitted)."""
        try:
            fact = redis_facts(self._url, [agent], bus_factory=lambda _url: bus)[0]
            values = {"zeus_redis_stream_entries": _count(fact["entries"]), "zeus_redis_stream_pending": _count(fact["pending"])}
            if fact["lag"] is not None:
                values["zeus_redis_stream_lag"] = _count(fact["lag"])
            if values["zeus_redis_stream_pending"] > 0:
                entries = bus.client.xpending_range(bus.stream(agent), GROUP, min="-", max="+", count=self._sample)
                idle = [_count(entry["time_since_delivered"]) for entry in entries]
                if idle:
                    values["zeus_redis_pending_oldest_idle_seconds"] = max(idle) / 1000
            return values
        except Exception:
            return None

    def _server(self, bus):
        """The dead-letter and memory series, or None when either read failed."""
        try:
            key = f"{bus.namespace}:dead-letter"
            values = {"zeus_redis_dead_letter_entries": _count(bus.client.xlen(key)) if bus.client.exists(key) else 0}
            memory = bus.client.info("memory")
            values["zeus_redis_memory_used_bytes"] = _count(memory["used_memory"])
            if _count(memory.get("maxmemory", 0)) > 0:
                values["zeus_redis_memory_max_bytes"] = memory["maxmemory"]
            return values
        except Exception:
            return None
