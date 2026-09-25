"""Host migration policy: one manifest, one resumable state machine, typed evidence receipts.

@invariant INV-HOST-MIGRATION-001

A host migration moves the Zeus control plane (PostgreSQL documents, Redis delivery state and
artifact bodies) from one host to another under one `migration_id`
(docs/zeus/operations/aibox-migration-001/RUNBOOK.md). Everything here is pure policy over
dictionaries: no store, process, Docker, socket or filesystem access, and no value ever reaches an
error message - only a fixed reason code and a field name do.

The coordinator built on this policy is a RECEIPT RECORDER. A recorded state is never itself proof
that a source was fenced, a target activated or an acceptance passed; it is proof that typed
evidence receipts with exit code 0 and a passing typed result were presented for that state.

* The manifest (`urn:zeus:host-migration-manifest:1`) is strict versioned JSON with identities,
  counts and digests and never a credential. A source schema named `public` (the Windows control
  ledger) is accepted only when it is explicitly inventoried and mapped to `zeus_aibox_control`; a
  target schema named `public` is always refused.
* Every non-failure transition carries, per gate, typed evidence receipts
  (`urn:zeus:host-migration-evidence:1`) of an allowed check kind, each with exit code 0 and
  `ok: true`. A mismatch, an unknown or a non-zero exit is never promoted to a pass.
* Restore steps are checkpoints keyed by (migration_id, step): the same input digest replays, a
  different one refuses, so an interrupted restore resumes and never restores twice.
* Activation is intent-first. A durable activation intent is recorded BEFORE any target writer is
  enabled; from that moment rollback is R1 (reverse migration of the target), whether or not a
  `limited_active` receipt was ever written, because an interruption between the intent and that
  receipt leaves the target's effects unknown. R0 (resume the retained source) is only for a
  migration whose target never had an activation intent.
* The activation receipt (`urn:zeus:aibox-host-activation:1`) is derived from the recorded intent
  and is exactly what the Linux launcher (deploy/aibox) checks: host id, release revision, state.
"""
from __future__ import annotations

import re

from codex_harness.domain.model import ContractError, digest

MANIFEST_SCHEMA = "urn:zeus:host-migration-manifest:1"
TRANSITION_SCHEMA = "urn:zeus:host-migration-transition:1"
CHECKPOINT_SCHEMA = "urn:zeus:host-migration-checkpoint:1"
EVIDENCE_SCHEMA = "urn:zeus:host-migration-evidence:1"
INTENT_SCHEMA = "urn:zeus:host-migration-activation-intent:1"
# The launcher contract of deploy/aibox (INTEGRATION-CONTRACT.md s2.1); the schema, field names and
# states must stay identical to `zeus_aibox_service.check_activation`.
ACTIVATION_SCHEMA = "urn:zeus:aibox-host-activation:1"
CONTROL_SCHEMA = "zeus_aibox_control"
SOURCE_PUBLIC = "public"
# The only source->target binding a PG comparison may accept as a delta: the Fleet registry row of
# the source control ledger, rewritten by `Fleet.relocate`. Every other schema and bucket compares
# unchanged.
REGISTRY_DELTA_BUCKETS = ("fleet_registry",)

PLANNED = "planned"
NETWORK_READY = "network_ready"
STAGED = "staged"
DRAINING = "draining"
SOURCE_FENCED = "source_fenced"
SNAPSHOT_SEALED = "snapshot_sealed"
RESTORED_PAUSED = "restored_paused"
LIMITED_ACTIVE = "limited_active"
QUALIFIED = "qualified"
FAILED = "failed"
ROLLBACK_REQUIRED = "rollback_required"
ROLLED_BACK = "rolled_back"

FORWARD = (PLANNED, NETWORK_READY, STAGED, DRAINING, SOURCE_FENCED, SNAPSHOT_SEALED,
           RESTORED_PAUSED, LIMITED_ACTIVE, QUALIFIED)
STATES = FORWARD + (FAILED, ROLLBACK_REQUIRED, ROLLED_BACK)
TERMINAL = frozenset({QUALIFIED, ROLLED_BACK})
# `failed` is a recorded stop with its reason; it is resumed only by the explicit rollback path or
# by re-entering the SAME forward state it failed in, never by skipping ahead.
# Per target state: gate name -> the evidence check kinds that may satisfy it. The kinds are the
# canonical offline data tooling commands (scripts/aibox_data), the per-schema PG coverage
# aggregate, and observations the owner records from host receipts. A kind names what produced the
# receipt; it never makes a hand-typed claim true, which is why the result digest is kept.
OBSERVATION = "observation"
GATES = {
    NETWORK_READY: {"network_receipt": (OBSERVATION,)},
    STAGED: {"target_layout": (OBSERVATION,), "staging_restore": ("pg-coverage",)},
    DRAINING: {"admission_pause": (OBSERVATION,)},
    SOURCE_FENCED: {"writer_inventory": (OBSERVATION,), "restart_refusal": (OBSERVATION,)},
    SNAPSHOT_SEALED: {"pg_inventory": ("pg-inventory",), "redis_inventory": ("redis-inventory",),
                      "artifact_inventory": ("inventory",)},
    RESTORED_PAUSED: {"pg_comparison": ("pg-coverage",), "pg_catalog": ("pg-catalog",),
                      "redis_comparison": ("compare-redis",),
                      "pel_owners": ("pel-owners",), "artifact_comparison": ("verify-staged",),
                      "registry_relocation": ("fleet-relocation",), "admission_paused": (OBSERVATION,)},
    LIMITED_ACTIVE: {"host_activation": ("host-activation",), "service_consumption": ("service-startup",),
                     "canary_admission": (OBSERVATION,)},
    QUALIFIED: {"acceptance_a": ("independent-review",), "acceptance_b": ("independent-review",)},
    FAILED: {"failure": None},
    ROLLBACK_REQUIRED: {"failure": None},
    ROLLED_BACK: {"rollback_gate": ("gate-r0", "gate-r1")},
}
CHECKS = frozenset({OBSERVATION, "pg-coverage", "pg-catalog", "pg-inventory", "redis-inventory", "inventory",
                    "compare-redis", "pel-owners", "verify-staged", "stage", "compare-pg",
                    "fleet-relocation", "host-activation", "service-startup", "independent-review",
                    "gate-r0", "gate-r1", "gate-c", "verify-artifacts"})
MAX_RECEIPTS = 128
STEPS = ("pg_restore", "redis_restore", "artifact_copy", "registry_relocation",
         "reverse_pg_restore", "reverse_redis_restore", "reverse_artifact_copy")
REVERSE_STEPS = ("reverse_pg_restore", "reverse_redis_restore", "reverse_artifact_copy")
ROLLBACK_R0 = "R0"
ROLLBACK_R1 = "R1"

TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|\+00:00)$")
STREAM_ID = re.compile(r"^\d{1,20}-\d{1,20}$")
# Key names that must never carry a value in a manifest, a transition or a receipt.
SECRET_NAMES = re.compile(r"(pass(word)?|secret|token|credential|api[_-]?key|private[_-]?key|auth)",
                          re.IGNORECASE)
# A URL with userinfo carrying a password, or a libpq keyword/value password.
SECRET_VALUES = re.compile(r"(://[^/\s:@]*:[^/\s@]+@|\bpassword\s*=|\bsslpassword\s*=)", re.IGNORECASE)
MAX_ENTRIES = 64
MAX_TEXT = 400

MANIFEST_FIELDS = {"schema", "migration_id", "created_at", "source", "target", "schema_map",
                   "path_map", "repository", "artifact_roots", "pg_buckets", "redis_keys",
                   "writers", "fence", "rollback"}
HOST_FIELDS = {"host_id", "platform", "postgres", "redis"}
PG_FIELDS = {"image", "image_digest", "major", "database", "endpoint", "extensions"}
REDIS_FIELDS = {"image", "image_digest", "major", "instance", "endpoint", "namespaces"}
ENDPOINT_FIELDS = {"kind", "name"}
ENDPOINT_KINDS = ("unix_socket", "loopback", "docker_service", "docker_exec")
REDIS_INSTANCES = ("dedicated", "shared")
PLATFORMS = ("windows", "linux")
PATH_FIELDS = {"id", "from", "to"}
REPOSITORY_FIELDS = {"commit", "dirty_count", "dirty_sha256", "ignored_preserved"}
ARTIFACT_FIELDS = {"id", "path_id", "entries", "bytes", "tree_sha256"}
BUCKET_FIELDS = {"schema", "bucket", "count", "sha256"}
KEY_FIELDS = {"key", "type", "sha256", "expires_at_ms", "stream"}
STREAM_FIELDS = {"length", "last_generated_id", "groups"}
GROUP_FIELDS = {"name", "last_delivered_id", "pending", "consumers"}
WRITER_FIELDS = {"id", "kind", "owner", "zeus_owned", "disposition"}
WRITER_KINDS = ("scheduled_task", "systemd_unit", "container", "process", "timer", "web_writer",
                "observer", "cli_helper")
DISPOSITIONS = ("stop_and_fence", "absorb_on_target", "leave_untouched_not_zeus")
FENCE_FIELDS = {"kind", "marker_id"}
FENCE_KINDS = ("admission_pause_and_marker",)
ROLLBACK_FIELDS = {"location_id", "reverse_supported", "source_retained"}
REDIS_TYPES = ("stream", "string", "hash", "set", "zset", "list")


class MigrationRefused(ContractError):
    """A fixed reason code and at most a field name; a value never reaches the message."""

    def __init__(self, reason_code: str, field: str | None = None):
        self.reason_code, self.field = reason_code, field
        super().__init__(reason_code if field is None else reason_code + ": " + field)


# ----- secrets never enter a document -----------------------------------------------------------
def refuse_secrets(document, name: str = "root") -> None:
    """Walk a document; a secret-named key or a credential-shaped value refuses by field name."""
    pending = [(name, document)]
    while pending:
        path, value = pending.pop()
        if isinstance(value, dict):
            for key, item in value.items():
                if type(key) is not str:
                    raise MigrationRefused("manifest_invalid", path)
                if SECRET_NAMES.search(key):
                    raise MigrationRefused("secret_field", path + "." + key)
                pending.append((path + "." + key, item))
        elif isinstance(value, list):
            pending.extend((path + "[" + str(i) + "]", item) for i, item in enumerate(value))
        elif isinstance(value, str) and SECRET_VALUES.search(value):
            raise MigrationRefused("secret_value", path)


# ----- small validators ---------------------------------------------------------------------------
def _fields(document, expected, name: str) -> dict:
    if not isinstance(document, dict):
        raise MigrationRefused("manifest_invalid", name)
    if set(document) != set(expected):
        raise MigrationRefused("manifest_fields", name)
    return document


def _match(value, pattern, name: str) -> str:
    if not (type(value) is str and pattern.fullmatch(value)):
        raise MigrationRefused("manifest_invalid", name)
    return value


def _count(value, name: str) -> int:
    if type(value) is not int or value < 0:
        raise MigrationRefused("manifest_invalid", name)
    return value


def _list(value, name: str, *, minimum: int = 0, maximum: int = MAX_ENTRIES) -> list:
    if not (isinstance(value, list) and minimum <= len(value) <= maximum):
        raise MigrationRefused("manifest_invalid", name)
    return value


def _path(value, name: str) -> str:
    """An absolute host path as text: POSIX absolute or a Windows drive path, never relative."""
    if not (type(value) is str and 0 < len(value) <= MAX_TEXT and "\x00" not in value):
        raise MigrationRefused("manifest_invalid", name)
    windows = re.fullmatch(r"[A-Za-z]:[\\/].*", value) is not None
    if not (windows or value.startswith("/")) or ".." in re.split(r"[\\/]", value):
        raise MigrationRefused("manifest_invalid", name)
    return value


def _utc(value, name: str) -> str:
    return _match(value, UTC, name)


def _endpoint(document, name: str) -> dict:
    _fields(document, ENDPOINT_FIELDS, name)
    if document["kind"] not in ENDPOINT_KINDS:
        raise MigrationRefused("manifest_invalid", name + ".kind")
    if not (type(document["name"]) is str and 0 < len(document["name"]) <= MAX_TEXT):
        raise MigrationRefused("manifest_invalid", name + ".name")
    return {"kind": document["kind"], "name": document["name"]}


def _postgres(document, name: str) -> dict:
    _fields(document, PG_FIELDS, name)
    extensions = _list(document["extensions"], name + ".extensions")
    for index, extension in enumerate(extensions):
        _match(extension, IDENT, name + ".extensions[" + str(index) + "]")
    return {"image": _match(document["image"], re.compile(r"^[a-z0-9./_:-]{1,200}$"), name + ".image"),
            "image_digest": _match(document["image_digest"], IMAGE_DIGEST, name + ".image_digest"),
            "major": _count(document["major"], name + ".major"),
            "database": _match(document["database"], IDENT, name + ".database"),
            "endpoint": _endpoint(document["endpoint"], name + ".endpoint"),
            "extensions": sorted(extensions)}


def _redis(document, name: str) -> dict:
    _fields(document, REDIS_FIELDS, name)
    if document["instance"] not in REDIS_INSTANCES:
        raise MigrationRefused("manifest_invalid", name + ".instance")
    namespaces = _list(document["namespaces"], name + ".namespaces", minimum=1)
    for index, namespace in enumerate(namespaces):
        if not (type(namespace) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", namespace)):
            raise MigrationRefused("manifest_invalid", name + ".namespaces[" + str(index) + "]")
    return {"image": _match(document["image"], re.compile(r"^[a-z0-9./_:-]{1,200}$"), name + ".image"),
            "image_digest": _match(document["image_digest"], IMAGE_DIGEST, name + ".image_digest"),
            "major": _count(document["major"], name + ".major"),
            "instance": document["instance"],
            "endpoint": _endpoint(document["endpoint"], name + ".endpoint"),
            "namespaces": sorted(set(namespaces))}


def _host(document, name: str) -> dict:
    _fields(document, HOST_FIELDS, name)
    if document["platform"] not in PLATFORMS:
        raise MigrationRefused("manifest_invalid", name + ".platform")
    return {"host_id": _match(document["host_id"], TOKEN, name + ".host_id"),
            "platform": document["platform"],
            "postgres": _postgres(document["postgres"], name + ".postgres"),
            "redis": _redis(document["redis"], name + ".redis")}


def _stream(document, name: str) -> dict:
    _fields(document, STREAM_FIELDS, name)
    groups = []
    for index, group in enumerate(_list(document["groups"], name + ".groups")):
        label = name + ".groups[" + str(index) + "]"
        _fields(group, GROUP_FIELDS, label)
        groups.append({"name": _match(group["name"], re.compile(r"^[A-Za-z0-9._:-]{1,64}$"), label + ".name"),
                       "last_delivered_id": _match(group["last_delivered_id"], STREAM_ID, label + ".last_delivered_id"),
                       "pending": _count(group["pending"], label + ".pending"),
                       "consumers": _count(group["consumers"], label + ".consumers")})
    if len({g["name"] for g in groups}) != len(groups):
        raise MigrationRefused("manifest_duplicate", name + ".groups")
    return {"length": _count(document["length"], name + ".length"),
            "last_generated_id": _match(document["last_generated_id"], STREAM_ID, name + ".last_generated_id"),
            "groups": sorted(groups, key=lambda g: g["name"])}


def validate_manifest(document) -> dict:
    """Strict validation of `urn:zeus:host-migration-manifest:1`; returns the canonical copy.

    The manifest states what the SOURCE snapshot is and how the target maps it. It authorizes
    nothing: every count and digest in it is compared again against what the adapter observes on
    each side, and a manifest that names a secret is refused before any of that.
    """
    refuse_secrets(document)
    if not isinstance(document, dict) or document.get("schema") != MANIFEST_SCHEMA:
        raise MigrationRefused("manifest_schema")
    _fields(document, MANIFEST_FIELDS, "root")
    source = _host(document["source"], "source")
    target = _host(document["target"], "target")
    if source["host_id"] == target["host_id"]:
        raise MigrationRefused("manifest_same_host", "target.host_id")
    for engine in ("postgres", "redis"):
        # INV-HOST-MIGRATION-001: no major upgrade rides along with a host move.
        if source[engine]["major"] != target[engine]["major"]:
            raise MigrationRefused("major_version_mismatch", "target." + engine + ".major")
    if source["postgres"]["extensions"] != target["postgres"]["extensions"]:
        raise MigrationRefused("extension_mismatch", "target.postgres.extensions")
    if source["redis"]["namespaces"] != target["redis"]["namespaces"]:
        # The first move preserves the source namespaces so no stream key or payload is rewritten.
        raise MigrationRefused("namespace_rewrite", "target.redis.namespaces")
    if target["redis"]["instance"] != "dedicated":
        raise MigrationRefused("target_redis_shared", "target.redis.instance")
    schema_map = document["schema_map"]
    if not (isinstance(schema_map, dict) and 1 <= len(schema_map) <= MAX_ENTRIES):
        raise MigrationRefused("manifest_invalid", "schema_map")
    for key, value in schema_map.items():
        _match(key, IDENT, "schema_map")
        _match(value, IDENT, "schema_map." + key)
        if value == "public":
            raise MigrationRefused("public_schema", "schema_map." + key)
        if key == SOURCE_PUBLIC and value != CONTROL_SCHEMA:
            # The source control ledger lives in `public`; it has exactly one reviewed destination.
            raise MigrationRefused("source_public_mapping", "schema_map.public")
    if len(set(schema_map.values())) != len(schema_map):
        raise MigrationRefused("map_not_bijective", "schema_map")
    paths = []
    for index, entry in enumerate(_list(document["path_map"], "path_map", minimum=1)):
        name = "path_map[" + str(index) + "]"
        _fields(entry, PATH_FIELDS, name)
        paths.append({"id": _match(entry["id"], TOKEN, name + ".id"),
                      "from": _path(entry["from"], name + ".from"), "to": _path(entry["to"], name + ".to")})
    if len({p["id"] for p in paths}) != len(paths) or len({p["to"] for p in paths}) != len(paths) \
            or len({p["from"] for p in paths}) != len(paths):
        raise MigrationRefused("map_not_bijective", "path_map")
    for left in paths:
        for right in paths:
            if left is not right and _nested(left["to"], right["to"]):
                raise MigrationRefused("path_overlap", "path_map." + left["id"])
    path_ids = {p["id"] for p in paths}
    repository = _fields(document["repository"], REPOSITORY_FIELDS, "repository")
    ignored = _list(repository["ignored_preserved"], "repository.ignored_preserved", maximum=4096)
    for index, entry in enumerate(ignored):
        if not (type(entry) is str and 0 < len(entry) <= MAX_TEXT and not entry.startswith("/")
                and ".." not in entry.split("/")):
            raise MigrationRefused("manifest_invalid", "repository.ignored_preserved[" + str(index) + "]")
    artifacts = []
    for index, entry in enumerate(_list(document["artifact_roots"], "artifact_roots", minimum=1)):
        name = "artifact_roots[" + str(index) + "]"
        _fields(entry, ARTIFACT_FIELDS, name)
        if entry["path_id"] not in path_ids:
            raise MigrationRefused("artifact_root_unmapped", name + ".path_id")
        artifacts.append({"id": _match(entry["id"], TOKEN, name + ".id"), "path_id": entry["path_id"],
                          "entries": _count(entry["entries"], name + ".entries"),
                          "bytes": _count(entry["bytes"], name + ".bytes"),
                          "tree_sha256": _match(entry["tree_sha256"], HEX64, name + ".tree_sha256")})
    buckets = []
    for index, entry in enumerate(_list(document["pg_buckets"], "pg_buckets", minimum=1, maximum=4096)):
        name = "pg_buckets[" + str(index) + "]"
        _fields(entry, BUCKET_FIELDS, name)
        if entry["schema"] not in schema_map:
            raise MigrationRefused("schema_unmapped", name + ".schema")
        buckets.append({"schema": entry["schema"],
                        "bucket": _match(entry["bucket"], re.compile(r"^[a-z0-9_.:-]{1,120}$"), name + ".bucket"),
                        "count": _count(entry["count"], name + ".count"),
                        "sha256": _match(entry["sha256"], HEX64, name + ".sha256")})
    if len({(b["schema"], b["bucket"]) for b in buckets}) != len(buckets):
        raise MigrationRefused("manifest_duplicate", "pg_buckets")
    if SOURCE_PUBLIC in schema_map and not any(b["schema"] == SOURCE_PUBLIC for b in buckets):
        # Mapping `public` is allowed only for an explicitly inventoried source public schema.
        raise MigrationRefused("source_public_not_inventoried", "pg_buckets")
    keys = []
    for index, entry in enumerate(_list(document["redis_keys"], "redis_keys", maximum=100000)):
        name = "redis_keys[" + str(index) + "]"
        _fields(entry, KEY_FIELDS, name)
        key = entry["key"]
        if not (type(key) is str and 0 < len(key) <= 512
                and any(key == ns or key.startswith(ns + ":") for ns in source["redis"]["namespaces"])):
            raise MigrationRefused("redis_key_outside_namespace", name + ".key")
        if entry["type"] not in REDIS_TYPES:
            raise MigrationRefused("manifest_invalid", name + ".type")
        expiry = entry["expires_at_ms"]
        if expiry is not None:
            _count(expiry, name + ".expires_at_ms")
        stream = entry["stream"]
        if (entry["type"] == "stream") != (stream is not None):
            raise MigrationRefused("manifest_invalid", name + ".stream")
        keys.append({"key": key, "type": entry["type"], "sha256": _match(entry["sha256"], HEX64, name + ".sha256"),
                     "expires_at_ms": expiry, "stream": None if stream is None else _stream(stream, name + ".stream")})
    if len({k["key"] for k in keys}) != len(keys):
        raise MigrationRefused("manifest_duplicate", "redis_keys")
    writers = []
    for index, entry in enumerate(_list(document["writers"], "writers", minimum=1, maximum=256)):
        name = "writers[" + str(index) + "]"
        _fields(entry, WRITER_FIELDS, name)
        if entry["kind"] not in WRITER_KINDS or entry["disposition"] not in DISPOSITIONS \
                or type(entry["zeus_owned"]) is not bool:
            raise MigrationRefused("manifest_invalid", name)
        if entry["zeus_owned"] == (entry["disposition"] == "leave_untouched_not_zeus"):
            # A Zeus writer is always fenced or absorbed; a foreign one is never touched.
            raise MigrationRefused("writer_disposition", name + ".disposition")
        writers.append({"id": _match(entry["id"], TOKEN, name + ".id"), "kind": entry["kind"],
                        "owner": _match(entry["owner"], TOKEN, name + ".owner"),
                        "zeus_owned": entry["zeus_owned"], "disposition": entry["disposition"]})
    if len({w["id"] for w in writers}) != len(writers):
        raise MigrationRefused("manifest_duplicate", "writers")
    fence = _fields(document["fence"], FENCE_FIELDS, "fence")
    if fence["kind"] not in FENCE_KINDS:
        raise MigrationRefused("manifest_invalid", "fence.kind")
    rollback = _fields(document["rollback"], ROLLBACK_FIELDS, "rollback")
    if rollback["location_id"] not in path_ids:
        raise MigrationRefused("rollback_location_unmapped", "rollback.location_id")
    if rollback["reverse_supported"] is not True or rollback["source_retained"] is not True:
        # A migration without a verified reverse path and a retained source is not plannable.
        raise MigrationRefused("rollback_unsupported", "rollback")
    return {"schema": MANIFEST_SCHEMA, "migration_id": _match(document["migration_id"], TOKEN, "migration_id"),
            "created_at": _utc(document["created_at"], "created_at"), "source": source, "target": target,
            "schema_map": dict(sorted(schema_map.items())), "path_map": sorted(paths, key=lambda p: p["id"]),
            "repository": {"commit": _match(repository["commit"], COMMIT, "repository.commit"),
                           "dirty_count": _count(repository["dirty_count"], "repository.dirty_count"),
                           "dirty_sha256": _match(repository["dirty_sha256"], HEX64, "repository.dirty_sha256"),
                           "ignored_preserved": sorted(set(ignored))},
            "artifact_roots": sorted(artifacts, key=lambda a: a["id"]),
            "pg_buckets": sorted(buckets, key=lambda b: (b["schema"], b["bucket"])),
            "redis_keys": sorted(keys, key=lambda k: k["key"]),
            "writers": sorted(writers, key=lambda w: w["id"]),
            "fence": {"kind": fence["kind"], "marker_id": _match(fence["marker_id"], TOKEN, "fence.marker_id")},
            "rollback": {"location_id": rollback["location_id"], "reverse_supported": True, "source_retained": True}}


def _nested(left: str, right: str) -> bool:
    a = left.replace("\\", "/").rstrip("/").lower() + "/"
    b = right.replace("\\", "/").rstrip("/").lower() + "/"
    return a.startswith(b) or b.startswith(a)


def manifest_digest(manifest: dict) -> str:
    return digest(["host-migration-manifest-v1", manifest])


def reverse_maps(manifest: dict) -> dict:
    """The schema and path maps of the reverse (R1) migration: exact inverses, never guessed."""
    schemas = {target: source for source, target in manifest["schema_map"].items()}
    paths = [{"id": p["id"], "from": p["to"], "to": p["from"]} for p in manifest["path_map"]]
    return {"schema_map": dict(sorted(schemas.items())), "path_map": paths}


# ----- typed evidence receipts --------------------------------------------------------------------
EVIDENCE_FIELDS = {"schema", "check", "subject", "exit_code", "ok", "result_sha256"}
SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:=/-]{0,199}$")


def validate_evidence(document, name: str) -> dict:
    """One typed receipt: which check ran, over what, its exit code, its typed result and digest."""
    _fields(document, EVIDENCE_FIELDS, name)
    if document.get("schema") != EVIDENCE_SCHEMA:
        raise MigrationRefused("evidence_schema", name)
    if document["check"] not in CHECKS:
        raise MigrationRefused("evidence_check_unknown", name + ".check")
    if document["subject"] is not None:
        _match(document["subject"], SUBJECT, name + ".subject")
    if type(document["exit_code"]) is not int or type(document["ok"]) is not bool:
        raise MigrationRefused("evidence_invalid", name)
    if document["ok"] != (document["exit_code"] == 0):
        # A wrapper that reports a pass beside a failing exit (or the reverse) is inconsistent;
        # neither side is believed.
        raise MigrationRefused("evidence_inconsistent", name)
    return {"schema": EVIDENCE_SCHEMA, "check": document["check"], "subject": document["subject"],
            "exit_code": document["exit_code"], "ok": document["ok"],
            "result_sha256": _match(document["result_sha256"], HEX64, name + ".result_sha256")}


def evidence_receipt(check: str, subject, exit_code: int, ok: bool, result_sha256: str) -> dict:
    return validate_evidence({"schema": EVIDENCE_SCHEMA, "check": check, "subject": subject,
                              "exit_code": exit_code, "ok": ok, "result_sha256": result_sha256}, "evidence")


def _gate_evidence(to: str, evidence) -> dict:
    gates = GATES.get(to, {})
    if not isinstance(evidence, dict) or set(evidence) != set(gates):
        raise MigrationRefused("gate_evidence_fields", "evidence")
    canonical = {}
    for gate, kinds in sorted(gates.items()):
        value = evidence[gate]
        receipts = value if isinstance(value, list) else [value]
        if not 1 <= len(receipts) <= MAX_RECEIPTS:
            raise MigrationRefused("gate_evidence_missing", "evidence." + gate)
        checked = [validate_evidence(r, "evidence." + gate + "[" + str(i) + "]") for i, r in enumerate(receipts)]
        for receipt in checked:
            if kinds is not None and receipt["check"] not in kinds:
                raise MigrationRefused("gate_evidence_kind", "evidence." + gate)
            if kinds is not None and not receipt["ok"]:
                raise MigrationRefused("gate_evidence_failed", "evidence." + gate)
        canonical[gate] = sorted(checked, key=lambda r: (r["check"], r["subject"] or "", r["result_sha256"]))
    return canonical


# ----- PostgreSQL: one schema per comparison, exact coverage -------------------------------------
def schema_comparison(schema_map: dict, source_schema: str, delta) -> dict:
    """Policy of ONE per-schema PG comparison: which target schema, and whether a delta may apply.

    Only the source control ledger (`public` -> `zeus_aibox_control`) may carry a binding delta,
    and only for the registry buckets `Fleet.relocate` rewrites. Every other schema - lanes and all
    historical schemas - must compare unchanged, with no delta at all.
    """
    if source_schema not in schema_map:
        raise MigrationRefused("schema_unmapped", "source_schema")
    target = schema_map[source_schema]
    if target == "public":
        raise MigrationRefused("public_schema", "schema_map." + source_schema)
    if delta is not None:
        if source_schema != SOURCE_PUBLIC or target != CONTROL_SCHEMA:
            raise MigrationRefused("delta_not_allowed", "source_schema")
        changes = delta.get("changes") if isinstance(delta, dict) else None
        if not isinstance(changes, list) or not changes:
            raise MigrationRefused("delta_invalid", "delta.changes")
        if any(not isinstance(c, dict) or c.get("bucket") not in REGISTRY_DELTA_BUCKETS for c in changes):
            raise MigrationRefused("delta_bucket_not_allowed", "delta.changes")
    return {"source_schema": source_schema, "target_schema": target, "delta": delta is not None}


def schema_subject(source_schema: str) -> str:
    return "schema=" + source_schema


def pg_coverage(schema_map: dict, receipts: list) -> dict:
    """Aggregate: every mapped source schema compared exactly once, each comparison passing."""
    checked = [validate_evidence(r, "receipts[" + str(i) + "]") for i, r in enumerate(receipts)]
    wanted = {schema_subject(name) for name in schema_map}
    seen: dict = {}
    for receipt in checked:
        if receipt["check"] != "compare-pg":
            raise MigrationRefused("coverage_kind", "receipts")
        seen[receipt["subject"]] = seen.get(receipt["subject"], 0) + 1
    duplicated = sorted(subject for subject, count in seen.items() if count > 1)
    missing = sorted(wanted - set(seen))
    extra = sorted(set(seen) - wanted)
    failed = sorted(r["subject"] for r in checked if not r["ok"])
    return {"schemas": len(wanted), "covered": len(set(seen) & wanted), "missing": missing,
            "duplicated": duplicated, "extra": extra, "failed": failed,
            "ok": not (missing or duplicated or extra or failed)}


# ----- PostgreSQL whole-database restore: rename plan, catalog comparison, receipt ----------------
RESTORE_SCHEMA = "urn:zeus:host-migration-pg-restore:1"
CATALOG_SCHEMA = "urn:zeus:host-migration-pg-catalog:1"
EXTENSION_HOME = "public"
# The one temporary schema the rename transaction creates and drops again; never a source name.
EXTENSION_PARKING = "zeus_migration_extensions"
RESTORE_STATES = ("created", "restore_failed", "restored", "renamed")
CATALOG_SECTIONS = ("relations", "indexes", "constraints", "sequences", "views", "functions", "triggers")


def _schema_empty(schema: dict) -> bool:
    return not any(schema.get(section) for section in CATALOG_SECTIONS)


def catalog_schemas(catalog: dict) -> list:
    """The schemas a restore must account for: every non-empty schema, and `public` even when
    empty only if it is not the bare extension home (an empty public is template furniture)."""
    return sorted(name for name, body in catalog["schemas"].items()
                  if not (name == EXTENSION_HOME and _schema_empty(body)))


def rename_plan(catalog: dict, schema_map: dict, *, reverse: bool = False) -> dict:
    """The renames of one whole-database restore, over EXACTLY the catalog's schemas.

    Forward, `public` may only become `zeus_aibox_control`; reverse (R1), only `zeus_aibox_control`
    may become `public`. Every other source schema either keeps its name or is renamed to a name no
    other source schema holds. The map is total: a restored schema nobody mapped is a refusal.
    """
    if not isinstance(schema_map, dict) or not schema_map:
        raise MigrationRefused("rename_map_invalid", "schema_map")
    for key, value in schema_map.items():
        _match(key, IDENT, "schema_map")
        _match(value, IDENT, "schema_map." + key)
        if value == EXTENSION_PARKING or key == EXTENSION_PARKING:
            raise MigrationRefused("rename_map_reserved", "schema_map." + key)
        if not reverse and value == SOURCE_PUBLIC:
            raise MigrationRefused("public_schema", "schema_map." + key)
        if not reverse and key == SOURCE_PUBLIC and value != CONTROL_SCHEMA:
            raise MigrationRefused("source_public_mapping", "schema_map.public")
        if reverse and value == SOURCE_PUBLIC and key != CONTROL_SCHEMA:
            raise MigrationRefused("source_public_mapping", "schema_map." + key)
    if len(set(schema_map.values())) != len(schema_map):
        raise MigrationRefused("map_not_bijective", "schema_map")
    schemas = catalog_schemas(catalog)
    if sorted(schema_map) != schemas:
        missing = sorted(set(schemas) - set(schema_map)) or sorted(set(schema_map) - set(schemas))
        raise MigrationRefused("rename_map_not_total", "schema_map." + missing[0])
    renames = sorted((k, v) for k, v in schema_map.items() if k != v)
    if any(target in schemas for _, target in renames):
        # A target that is any source schema name - kept or itself renamed - would need an ordered
        # chain of renames through an occupied name; that is refused rather than sequenced.
        raise MigrationRefused("rename_target_occupied", "schema_map")
    return {"renames": [list(pair) for pair in renames], "reverse": reverse,
            "extension_home": EXTENSION_HOME, "parking": EXTENSION_PARKING}


def _normalizer(renames: list, members: list):
    """Text normalization of catalog definitions: a qualified `<from>.` becomes `<to>.`, except a
    reference to an extension member (e.g. `public.vector`), which lives in the extension home on
    both sides and so keeps its spelling."""
    if not renames:
        return lambda text: text
    keep = "|".join(sorted(re.escape(name) for name in members))
    patterns = [(re.compile(r"\b" + re.escape(old) + r"\." + (r"(?!(?:" + keep + r")\b)" if keep else "")), new + ".")
                for old, new in renames]

    def normalize(text):
        if not isinstance(text, str):
            return text
        for pattern, replacement in patterns:
            text = pattern.sub(replacement, text)
        return text
    return normalize


def _mapped(value, normalize):
    if isinstance(value, dict):
        return {k: _mapped(v, normalize) for k, v in value.items()}
    if isinstance(value, list):
        return [_mapped(v, normalize) for v in value]
    return normalize(value)


def compare_catalogs(source: dict, target: dict, schema_map: dict) -> dict:
    """Source catalog through the schema map against the target catalog, section by section.

    Row counts and row digests of every table (documents, knowledge_nodes/edges, schema_migrations
    and anything else), columns with their types, indexes, constraints, sequences, views,
    functions, triggers, schema owner/ACL/comment and the extension list (name, version, schema)
    must all be equal. Missing and extra schemas are differences, never silently accepted.
    """
    for name, document in (("source", source), ("target", target)):
        if not isinstance(document, dict) or document.get("schema") != CATALOG_SCHEMA:
            raise MigrationRefused("catalog_schema", name)
    renames = [[k, v] for k, v in sorted(schema_map.items()) if k != v]
    normalize = _normalizer(renames, source.get("extension_members") or [])
    diffs = []
    if source["extensions"] != target["extensions"]:
        diffs.append({"schema": None, "section": "extensions"})
    expected = {schema_map.get(name, name): _mapped(source["schemas"][name], normalize)
                for name in catalog_schemas(source)}
    observed = {name: target["schemas"][name] for name in catalog_schemas(target)}
    if set(schema_map) != set(catalog_schemas(source)):
        diffs.append({"schema": None, "section": "map_not_total"})
    for name in sorted(set(expected) | set(observed)):
        left, right = expected.get(name), observed.get(name)
        if left is None or right is None:
            diffs.append({"schema": name, "section": "missing_on_target" if right is None else "extra_on_target"})
            continue
        for section in ("owner", "acl", "comment") + CATALOG_SECTIONS:
            if left.get(section) != right.get(section):
                diffs.append({"schema": name, "section": section})
    tables = sum(len(body.get("relations") or {}) for body in observed.values())
    rows = sum(rel.get("rows") or 0 for body in observed.values() for rel in (body.get("relations") or {}).values())
    return {"match": not diffs, "schemas": len(expected), "tables": tables, "rows": rows,
            "diffs": diffs[:200], "diff_count": len(diffs)}


def restore_id(database: str, archive_sha256: str, catalog_sha256: str, plan: dict) -> str:
    return digest(["host-migration-pg-restore-v1", database, archive_sha256, catalog_sha256, plan])


# ----- the state machine --------------------------------------------------------------------------
def allowed(current: str, to: str) -> bool:
    """Forward one step; `failed`/`rollback_required` from any non-terminal state; a failed
    migration re-enters only through `rollback_required` or the forward state it failed in."""
    if current in TERMINAL:
        return False
    if to == FAILED:
        return current != FAILED
    if to == ROLLBACK_REQUIRED:
        return current != ROLLBACK_REQUIRED
    if to == ROLLED_BACK:
        return current == ROLLBACK_REQUIRED
    if current in (FAILED, ROLLBACK_REQUIRED):
        # A failed migration re-enters its own forward state through `resume_state`, which needs
        # the history and is therefore decided by the coordinator, never here.
        return False
    if current in FORWARD and to in FORWARD:
        return FORWARD.index(to) == FORWARD.index(current) + 1
    return False


def resume_state(history: list) -> str | None:
    """The forward state a `failed` migration may re-enter: the one it failed from."""
    for record in reversed(history):
        if record.get("to") == FAILED:
            return record["from"]
    return None


def target_written(history: list) -> bool:
    """Whether the target may have become a writer: an activation intent exists or the target
    reached limited_active. The intent alone is enough; its effects are unknown until reconciled."""
    return any(record.get("event") == "activation_intent" or record.get("to") in (LIMITED_ACTIVE, QUALIFIED)
               for record in history)


def rollback_mode(history: list) -> str:
    """R0 only while the target never had an activation intent; R1 (reverse migration) after."""
    return ROLLBACK_R1 if target_written(history) else ROLLBACK_R0


def validate_transition(document) -> dict:
    """Strict validation of `urn:zeus:host-migration-transition:1`; returns the canonical copy."""
    refuse_secrets(document, "transition")
    fields = {"schema", "migration_id", "manifest_sha256", "from", "to", "actor", "host", "at",
              "identity", "evidence", "exit_code", "reason_code"}
    if not isinstance(document, dict) or document.get("schema") != TRANSITION_SCHEMA:
        raise MigrationRefused("transition_schema")
    _fields(document, fields, "transition")
    if document["from"] not in STATES or document["to"] not in STATES:
        raise MigrationRefused("transition_invalid", "from/to")
    identity = _fields(document["identity"], {"config_sha256", "commit", "image", "profile_sha256"},
                       "transition.identity")
    _match(identity["config_sha256"], HEX64, "identity.config_sha256")
    _match(identity["commit"], COMMIT, "identity.commit")
    if identity["image"] is not None:
        _match(identity["image"], IMAGE_DIGEST, "identity.image")
    if identity["profile_sha256"] is not None:
        _match(identity["profile_sha256"], HEX64, "identity.profile_sha256")
    evidence = _gate_evidence(document["to"], document["evidence"])
    if type(document["exit_code"]) is not int:
        raise MigrationRefused("transition_invalid", "exit_code")
    failing = document["to"] in (FAILED, ROLLBACK_REQUIRED)
    if failing != (document["reason_code"] is not None) or (
            failing and not (type(document["reason_code"]) is str and TOKEN.fullmatch(document["reason_code"]))):
        raise MigrationRefused("transition_invalid", "reason_code")
    if not failing and document["exit_code"] != 0:
        raise MigrationRefused("transition_nonzero_exit", "exit_code")
    return {"schema": TRANSITION_SCHEMA,
            "migration_id": _match(document["migration_id"], TOKEN, "migration_id"),
            "manifest_sha256": _match(document["manifest_sha256"], HEX64, "manifest_sha256"),
            "from": document["from"], "to": document["to"],
            "actor": _match(document["actor"], TOKEN, "actor"), "host": _match(document["host"], TOKEN, "host"),
            "at": _utc(document["at"], "at"),
            "identity": {k: identity[k] for k in sorted(identity)},
            "evidence": evidence, "exit_code": document["exit_code"],
            "reason_code": document["reason_code"]}


def transition_id(transition: dict) -> str:
    return digest(["host-migration-transition-v2", transition["migration_id"], transition["from"],
                   transition["to"], transition["manifest_sha256"], transition["evidence"]])


def validate_checkpoint(document) -> dict:
    """One restore step's durable checkpoint: which step, over which input, with which output."""
    refuse_secrets(document, "checkpoint")
    fields = {"schema", "migration_id", "step", "input_sha256", "output_sha256", "at"}
    if not isinstance(document, dict) or document.get("schema") != CHECKPOINT_SCHEMA:
        raise MigrationRefused("checkpoint_schema")
    _fields(document, fields, "checkpoint")
    if document["step"] not in STEPS:
        raise MigrationRefused("checkpoint_invalid", "step")
    return {"schema": CHECKPOINT_SCHEMA, "migration_id": _match(document["migration_id"], TOKEN, "migration_id"),
            "step": document["step"], "input_sha256": _match(document["input_sha256"], HEX64, "input_sha256"),
            "output_sha256": _match(document["output_sha256"], HEX64, "output_sha256"),
            "at": _utc(document["at"], "at")}


def step_allowed(step: str, state: str, history: list) -> bool:
    """Forward restore steps run only between the sealed snapshot and the paused target, and never
    once an activation intent exists; reverse steps only once a rollback is required under R1."""
    if step in REVERSE_STEPS:
        return state == ROLLBACK_REQUIRED and rollback_mode(history) == ROLLBACK_R1
    return state == SNAPSHOT_SEALED and not target_written(history)


# ----- activation: intent first, then the launcher receipt -------------------------------------------
HOST_ID = re.compile(r"^machine-id-sha256:[0-9a-f]{64}$")
INTENT_FIELDS = {"schema", "migration_id", "host_id", "release_revision", "image", "profile_sha256",
                 "actor", "at"}


def validate_intent(document) -> dict:
    """The durable activation intent, recorded BEFORE any target writer is enabled."""
    refuse_secrets(document, "intent")
    if not isinstance(document, dict) or document.get("schema") != INTENT_SCHEMA:
        raise MigrationRefused("intent_schema")
    _fields(document, INTENT_FIELDS, "intent")
    return {"schema": INTENT_SCHEMA, "migration_id": _match(document["migration_id"], TOKEN, "migration_id"),
            "host_id": _match(document["host_id"], HOST_ID, "intent.host_id"),
            "release_revision": _match(document["release_revision"], COMMIT, "intent.release_revision"),
            "image": _match(document["image"], IMAGE_DIGEST, "intent.image"),
            "profile_sha256": _match(document["profile_sha256"], HEX64, "intent.profile_sha256"),
            "actor": _match(document["actor"], TOKEN, "intent.actor"), "at": _utc(document["at"], "intent.at")}


def intent_id(intent: dict) -> str:
    return digest(["host-migration-activation-intent-v1", intent])


def activation_receipt(intent: dict, manifest_sha256: str, state: str) -> dict:
    """The launcher's `host-activation.json`, derived from the recorded intent and nothing else."""
    if state not in (RESTORED_PAUSED, LIMITED_ACTIVE, QUALIFIED):
        raise MigrationRefused("activation_state", "state")
    return {"schema": ACTIVATION_SCHEMA, "migration_id": intent["migration_id"], "host_id": intent["host_id"],
            "state": state, "release_revision": intent["release_revision"], "intent_id": intent_id(intent),
            "manifest_sha256": manifest_sha256}


__all__ = ["ACTIVATION_SCHEMA", "CHECKPOINT_SCHEMA", "CONTROL_SCHEMA", "EVIDENCE_SCHEMA", "FAILED", "FORWARD",
           "GATES", "INTENT_SCHEMA", "LIMITED_ACTIVE", "MANIFEST_SCHEMA", "MigrationRefused", "OBSERVATION",
           "PLANNED", "QUALIFIED", "REGISTRY_DELTA_BUCKETS", "RESTORED_PAUSED", "REVERSE_STEPS", "ROLLBACK_R0",
           "ROLLBACK_R1", "ROLLBACK_REQUIRED", "ROLLED_BACK", "SNAPSHOT_SEALED", "SOURCE_PUBLIC", "STATES",
           "STEPS", "TRANSITION_SCHEMA", "activation_receipt", "allowed", "evidence_receipt", "intent_id",
           "catalog_schemas", "compare_catalogs", "manifest_digest", "pg_coverage", "rename_plan", "restore_id", "refuse_secrets", "schema_comparison", "schema_subject", "resume_state", "reverse_maps", "rollback_mode", "step_allowed",
           "target_written", "transition_id", "validate_checkpoint", "validate_evidence", "validate_intent",
           "validate_manifest", "validate_transition"]
