"""Scenario body `storage.redis` (REBUILD-DESIGN-v2 §5.3 S1: Redis incarnation/dead-letter on a
labelled disposable Redis, one key namespace per case).

Layer: harness (never shipped). `api` provides: bus(url, namespace), for_run(url, run_id, namespace),
run_namespace, TRANSPORT_SCHEMA, digest, envelope, MessageDeliveryError, TransportChanged,
ContractError. Stream entry ids and the server's own run id are chosen by the Redis server: they
are compared as relations (format, equality, presence), never as values.
"""

from __future__ import annotations

import re

from s1_common import outcome

ENTRY = re.compile(r"^\d+-\d+$")


def _entry(value) -> str:
    return "entry-id" if isinstance(value, str) and ENTRY.match(value) else repr(value)


def _message(api, sender="lead:improvement", recipient="worker:implementation"):
    return api.envelope("task.assign", sender, recipient, "implement", {"n": 1}, "correlation")


def run(api, url: str, socket_path: str, clock, ids) -> dict:
    out: dict = {}
    clock.reset()
    ids.reset()
    out["run_namespace"] = [outcome(lambda: api.run_namespace("prefix", "run-1")),
                            outcome(lambda: api.run_namespace("prefix", "")),
                            outcome(lambda: api.run_namespace("", "run-1")),
                            outcome(lambda: api.run_namespace("prefix", 7))]
    out["transport_schema"] = api.TRANSPORT_SCHEMA

    bus = api.bus(url, "s1-incarnation")
    out["names"] = [bus.stream("worker:implementation"), bus.incarnation_key(), bus.route]
    probe = bus.transport(create=False)
    # The endpoint digest covers the per-run socket path: compared as a relation, like the server id.
    local = ("server", "endpoint_sha256")
    out["probe_before_create"] = {k: v for k, v in probe.items() if k not in local}
    out["probe_server_present"] = isinstance(probe["server"], str) and bool(probe["server"])
    out["endpoint_is_socket_digest"] = probe["endpoint_sha256"] == api.digest({"path": socket_path})
    identity = bus.transport()
    out["identity"] = {k: v for k, v in identity.items() if k not in local}
    again = bus.transport()
    out["identity_stable"] = again == identity
    out["probe_after_create_equal"] = bus.transport(create=False) == identity

    message = _message(api)
    out["publish_unbound"] = _entry(bus.publish(message))
    out["publish_bound"] = _entry(bus.publish(message, transport=identity))
    changed_namespace = dict(identity, namespace="other")
    out["publish_refusals"] = {
        "namespace": outcome(lambda: bus.publish(message, transport=changed_namespace)),
        "missing_storage": outcome(lambda: bus.publish(message, transport=dict(identity, storage=None))),
        "not_a_dict": outcome(lambda: bus.publish(message, transport="identity")),
        "server": outcome(lambda: bus.publish(message, transport=dict(identity, server="another-run"))),
        "invalid_message": outcome(lambda: bus.publish({"type": "task.assign"}, transport=identity)),
    }
    bus.client.set(bus.incarnation_key(), "replaced-token")
    out["publish_refusals"]["storage_replaced"] = outcome(lambda: bus.publish(message, transport=identity))
    out["stream_length_after_refusals"] = bus.client.xlen(bus.stream("worker:implementation"))
    out["identity_after_replacement"] = {k: v for k, v in bus.transport().items() if k not in local}

    # Consumer group delivery, acknowledgement, reclaim of an abandoned entry, dead-letter.
    work = api.bus(url, "s1-delivery")
    agent = "worker:implementation"
    published = [_message(api) for _ in range(3)]
    for item in published:
        work.publish(item)
    first = work.receive(agent, "consumer-a")
    out["first_delivery"] = {"id": _entry(first[0]), "decoded_is_first": work.decode(first[1]) == published[0]}
    work.ack(agent, first[0])
    second = work.receive(agent, "consumer-a")
    reclaimed = work.receive(agent, "consumer-b", idle_ms=0)
    out["reclaim_same_entry"] = reclaimed[0] == second[0]
    pending = work.client.xpending(work.stream(agent), "workers")
    out["pending_before_dead_letter"] = pending["pending"]
    work.dead_letter(agent, reclaimed[0], reclaimed[1], "fixture_reason")
    letters = work.client.xrange(f"{work.namespace}:dead-letter")
    out["dead_letters"] = [{"source": f["source"], "entry_is_reclaimed": f["entry_id"] == reclaimed[0],
                            "body_equal": f["body"] == reclaimed[1]["body"], "reason": f["reason"],
                            "fields": sorted(f)} for _, f in letters]
    out["pending_after_dead_letter"] = work.client.xpending(work.stream(agent), "workers")["pending"]
    third = work.receive(agent, "consumer-a")
    work.ack(agent, third[0])
    out["empty_receive"] = work.receive(agent, "consumer-a")
    work.ensure_group(agent)
    out["decode_invalid"] = outcome(lambda: work.decode({"body": '{"type": "task.assign"}'}))

    # Compaction keeps the newest `retain` entries and every group's undelivered/pending payloads.
    compact = api.bus(url, "s1-compact")
    stream = compact.stream(agent)
    compact.publish(_message(api))
    out["compact_without_group"] = compact.compact(agent, 0)
    compact.ensure_group(agent)
    for n in range(5):
        compact.publish(_message(api))
    delivered = [compact.receive(agent, "c") for _ in range(4)]
    for entry in delivered[:3]:
        compact.ack(agent, entry[0])
    out["compact"] = {"length_before": compact.client.xlen(stream),
                      "trimmed_retain_1": compact.compact(agent, 1),
                      "length_after": compact.client.xlen(stream),
                      "pending_kept": compact.client.xrange(stream)[0][0] == delivered[3][0],
                      "invalid_retain": [outcome(lambda: compact.compact(agent, -1)),
                                         outcome(lambda: compact.compact(agent, True))]}

    # One run's bus: its own namespace and route, derived from the run id and nothing else.
    scoped = api.for_run(url, "run-7", "s1-scoped")
    again_scoped = api.for_run(url, "run-7", "s1-scoped")
    out["for_run"] = {"namespace": scoped.namespace, "route": scoped.route,
                      "same_run_same_streams": again_scoped.stream(agent) == scoped.stream(agent),
                      "other_run": api.for_run(url, "run-8", "s1-scoped").namespace != scoped.namespace}

    # A different database index is a different transport identity.
    other_db = api.bus(url.replace("db=0", "db=1"), "s1-incarnation")
    out["database_changes_identity"] = {"database": other_db.transport(create=False)["database"],
                                        "storage": other_db.transport(create=False)["storage"]}
    for name in ("s1-incarnation", "s1-delivery", "s1-compact", scoped.namespace):
        for key in bus.client.scan_iter(match=name + ":*"):
            bus.client.delete(key)
    out["keys_left"] = sorted(bus.client.scan_iter(match="s1-*"))
    return out
