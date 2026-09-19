"""Readiness of the monitor's current observation delivery (monitor-readiness-001).

Liveness (`/health`) answers whether the process responds and `/api/status` serves the last
sanitized snapshot even when it is old; both keep their contracts. The missing dimension, and the
only one implemented here, is a machine-readable answer to "is the observation being delivered now
fresh?". This is not task progress, job acceptance, system-wide health, an SLO or restart
authority: a not-ready answer never asks anyone to restart or reject work.

The assessment is pure and bounded. One call opens the snapshot once, reads at most
`MAX_SNAPSHOT_BYTES + 1` bytes, computes every state at one UTC instant, retains nothing between
calls and writes nothing; it makes no network, database, Docker, process or provider call. Every
malformed input is a fixed state and reason code, never an exception to the caller and never an
echo of a raw value, key, path or collector error. The freshness rules (20 s window, >5 s future
timestamps invalid) are the accepted frontend rules in `frontend/monitor/src/lib/snapshot.ts`,
restated here for the server, not new tuning. Data payloads inside an envelope are never read:
a paused fleet, an empty task list or a stopped container is not a freshness fact.
"""
import json
from datetime import datetime, timezone

SCHEMA = 'urn:zeus:monitor-readiness:1'
SERVICE = 'harness-monitor'
BASIS = 'observation_freshness'
SNAPSHOT_SCHEMA = 'harness-monitor.v1'      # produced by adapters/monitoring.py collect()
MAX_SNAPSHOT_BYTES = 5_000_000
FRESH_SECONDS = 20
FUTURE_TOLERANCE_SECONDS = 5
REQUIRED_SOURCES = ('database', 'docker', 'redis')
OPTIONAL_SOURCES = ('observations', 'fleet', 'research_programs')

# Fixed reason codes. `state` carries the answer; `reason` says which rule produced it. Both are
# chosen from these closed sets, so no input value can reach a client through them.
SNAPSHOT_REASONS = ('current', 'older_than_window', 'timestamp_missing', 'timestamp_unparsable',
                    'timestamp_naive', 'timestamp_in_future', 'file_missing', 'file_unreadable',
                    'too_large', 'undecodable', 'not_an_object', 'schema_unexpected',
                    'sources_unexpected')
SOURCE_REASONS = ('current', 'older_than_window', 'timestamp_missing', 'timestamp_unparsable',
                  'timestamp_naive', 'timestamp_in_future', 'envelope_missing', 'envelope_invalid',
                  'collection_failed')


def state(name, reason, age_seconds=None):
    return {'state': name, 'reason': reason, 'age_seconds': age_seconds}


def parse(body):
    """Strict JSON from bytes: UTF-8 only (a BOM is not a prefix we accept), duplicate object keys
    and NaN/Infinity refused. `sdd.load_json` is the sibling reader but decodes `utf-8-sig` under a
    1 MiB budget, so this boundary keeps its own strict decode. Raises ValueError (including
    UnicodeDecodeError) or RecursionError; deep nesting is refused by the interpreter's recursion
    guard rather than being parsed."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def constant(_value):
        raise ValueError('Non-finite JSON number')
    return json.loads(body.decode('utf-8'), object_pairs_hook=unique, parse_constant=constant)


def elapsed(value, now):
    """(state, reason, age) for one timestamp. Aware ISO 8601 only: absent, malformed, naive or
    more than the tolerance in the future is invalid; a small future skew clamps to zero age. The
    age is neither rounded nor truncated, so the returned state and age always agree."""
    if not isinstance(value, str) or not value:
        return 'invalid', 'timestamp_missing', None
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return 'invalid', 'timestamp_unparsable', None
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        return 'invalid', 'timestamp_naive', None
    try:
        age = (now - moment).total_seconds()
    except (OverflowError, ValueError, OSError):
        return 'invalid', 'timestamp_unparsable', None
    if age < -FUTURE_TOLERANCE_SECONDS:
        return 'invalid', 'timestamp_in_future', None
    # Classify the clamped age itself: rounding first would push 19.9996 s over the window and
    # report a stale state beside a fresh age. State and reported age must come from one number.
    age = max(0.0, age)
    return ('fresh', 'current', age) if age < FRESH_SECONDS else ('stale', 'older_than_window', age)


def envelope_state(envelope, present, now):
    """One collector envelope under the accepted rules: a failed collection is unavailable whatever
    its timestamp says, and only an `ok` envelope is assessed for freshness."""
    if not present:
        return state('unavailable', 'envelope_missing')
    if not isinstance(envelope, dict):
        return state('unavailable', 'envelope_invalid')
    if envelope.get('status') != 'ok':
        return state('unavailable', 'collection_failed')
    return state(*elapsed(envelope.get('observed_at'), now))


def source_states(sources, now):
    """The three required envelopes always, each known optional envelope only when present.
    Unknown names are ignored: forward compatibility, and no snapshot key reaches the client."""
    assessed = {name: envelope_state(sources.get(name), name in sources, now)
                for name in REQUIRED_SOURCES}
    for name in OPTIONAL_SOURCES:
        if name in sources:
            assessed[name] = envelope_state(sources[name], True, now)
    return assessed


def snapshot_state(snapshot_path, now):
    """(snapshot state, source states) from one bounded read. A snapshot that cannot be decoded
    structurally has no trustworthy source names, so its source map is empty; a structurally valid
    snapshot with a broken `collected_at` still has every envelope assessed independently."""
    try:
        with open(snapshot_path, 'rb') as stream:
            # One opened stream, one bounded read: the extra byte only detects an oversized file.
            body = stream.read(MAX_SNAPSHOT_BYTES + 1)
    except FileNotFoundError:
        return state('unavailable', 'file_missing'), {}
    except OSError:
        return state('unavailable', 'file_unreadable'), {}
    if len(body) > MAX_SNAPSHOT_BYTES:
        return state('invalid', 'too_large'), {}
    try:
        document = parse(body)
    except (ValueError, RecursionError):
        return state('invalid', 'undecodable'), {}
    if not isinstance(document, dict):
        return state('invalid', 'not_an_object'), {}
    if document.get('schema') != SNAPSHOT_SCHEMA:
        return state('invalid', 'schema_unexpected'), {}
    sources = document.get('sources')
    if not isinstance(sources, dict):
        return state('invalid', 'sources_unexpected'), {}
    return state(*elapsed(document.get('collected_at'), now)), source_states(sources, now)


def readiness(snapshot_path, *, now=None):
    """The fixed `urn:zeus:monitor-readiness:1` answer for one snapshot file.

    Ready means the snapshot itself is fresh and every assessed envelope is fresh; every component
    is computed even when another already failed. `checked_at` is our clock, never a snapshot
    value. The result contains only fixed strings, booleans, numbers and null, so the caller can
    serialize it without any further sanitizing. `now` must be an aware datetime when supplied;
    passing a naive one is a caller error, not snapshot input, and raises.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif not isinstance(now, datetime) or now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        raise ValueError('readiness(now=...) requires a timezone-aware datetime')
    snapshot, sources = snapshot_state(snapshot_path, now)
    ready = snapshot['state'] == 'fresh' and all(
        source['state'] == 'fresh' for source in sources.values())
    return {'schema': SCHEMA, 'service': SERVICE, 'ready': ready, 'basis': BASIS,
            'checked_at': now.astimezone(timezone.utc).isoformat(),
            'freshness_seconds': FRESH_SECONDS,
            'future_tolerance_seconds': FUTURE_TOLERANCE_SECONDS,
            'snapshot': snapshot, 'sources': sources}
