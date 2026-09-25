"""Host migration policy: one manifest, one resumable state machine, verified comparisons.

@invariant INV-HOST-MIGRATION-001

A host migration moves the Zeus control plane (PostgreSQL documents, Redis delivery state and
artifact bodies) from one host to another under one `migration_id`
(docs/zeus/operations/aibox-migration-001/RUNBOOK.md). Everything here is pure policy over
dictionaries: no store, process, Docker, socket or filesystem access, and no value ever reaches an
error message - only a fixed reason code and a field name do.

* The manifest (`urn:zeus:host-migration-manifest:1`) is strict versioned JSON. It carries
  identities, counts and digests and never a credential: a DSN with a password, or any field named
  like a secret, is refused before anything else is read.
* The state machine is fixed. Every transition is compare-and-swap on the stated current state and
  the manifest digest, carries its actor, host, UTC, config/commit/image/profile identity and its
  input/output evidence digests, and is idempotent on the identical request.
* Restore steps are checkpoints keyed by (migration_id, step): the same input digest replays, a
  different one refuses, so an interrupted restore resumes and never restores twice.
* Rollback is decided from the recorded history, never from a caller's word. Before the target
  ever became a writer (`limited_active`) the source snapshot may be resumed (R0). After it, only
  a reverse migration of the target's newest state is allowed (R1): restarting the old source
  snapshot would lose the target's records and repeat its external effects.
* Comparisons carry the whole denominator. A missing bucket, key, group or file is a difference,
  never an empty match, and an expiry that passed during the downtime is reported apart from one
  that was lost.
"""
from __future__ import annotations

import posixpath
import re

from codex_harness.domain.model import ContractError, digest

MANIFEST_SCHEMA = "urn:zeus:host-migration-manifest:1"
TRANSITION_SCHEMA = "urn:zeus:host-migration-transition:1"
CHECKPOINT_SCHEMA = "urn:zeus:host-migration-checkpoint:1"
UNIT_SCHEMA = "urn:zeus:systemd-service:1"

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
# The evidence a transition INTO a state must name. Names only: the adapter produces the digests,
# the coordinator records them, and nothing here believes a claim that a check passed.
GATES = {
    NETWORK_READY: ("network_receipt",),
    STAGED: ("target_layout", "staging_restore"),
    DRAINING: ("admission_pause",),
    SOURCE_FENCED: ("writer_inventory", "restart_refusal"),
    SNAPSHOT_SEALED: ("pg_inventory", "redis_inventory", "artifact_inventory"),
    RESTORED_PAUSED: ("pg_comparison", "redis_comparison", "artifact_comparison",
                      "registry_relocation"),
    LIMITED_ACTIVE: ("host_activation", "canary_admission"),
    QUALIFIED: ("acceptance_a", "acceptance_b"),
    FAILED: ("failure",),
    ROLLBACK_REQUIRED: ("failure",),
    ROLLED_BACK: ("rollback_receipt",),
}
STEPS = ("pg_restore", "redis_restore", "artifact_copy", "registry_relocation",
         "reverse_pg_restore", "reverse_redis_restore", "reverse_artifact_copy")
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
        if value == "public" or key == "public":
            raise MigrationRefused("public_schema", "schema_map." + key)
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
        if record["to"] == FAILED:
            return record["from"]
    return None


def target_written(history: list) -> bool:
    """Whether the target ever became an authoritative writer (canary admission onward)."""
    return any(record["to"] in (LIMITED_ACTIVE, QUALIFIED) for record in history)


def rollback_mode(history: list) -> str:
    """R0 before the target wrote anything; R1 (reverse migration of the target) after."""
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
    evidence = document["evidence"]
    if not (isinstance(evidence, dict) and len(evidence) <= MAX_ENTRIES):
        raise MigrationRefused("transition_invalid", "evidence")
    for name, value in evidence.items():
        _match(name, re.compile(r"^[a-z][a-z0-9_]{0,63}$"), "evidence")
        _match(value, HEX64, "evidence." + name)
    missing = [gate for gate in GATES.get(document["to"], ()) if gate not in evidence]
    if missing:
        raise MigrationRefused("gate_evidence_missing", "evidence." + missing[0])
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
            "evidence": dict(sorted(evidence.items())), "exit_code": document["exit_code"],
            "reason_code": document["reason_code"]}


def transition_id(transition: dict) -> str:
    return digest(["host-migration-transition-v1", transition["migration_id"], transition["from"],
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
    """Forward restore steps run only between the sealed snapshot and the paused target; reverse
    steps only once a rollback is required AND the target had written (R1)."""
    if step.startswith("reverse_"):
        return state == ROLLBACK_REQUIRED and rollback_mode(history) == ROLLBACK_R1
    return state == SNAPSHOT_SEALED


# ----- comparisons -------------------------------------------------------------------------------
def compare_buckets(source: list, target: list, schema_map: dict, allowed_delta=()) -> dict:
    """Bucket-by-bucket count and digest after the schema map; nothing missing reads as empty.

    `allowed_delta` names the (target schema, bucket) pairs a reviewed binding change may alter,
    e.g. the Fleet registry after a relocation receipt; each still has to be present on both sides
    and is reported, never silently accepted.
    """
    mapped = {(schema_map.get(row["schema"], "<unmapped>"), row["bucket"]): row for row in source}
    observed = {(row["schema"], row["bucket"]): row for row in target}
    allowed_pairs = {tuple(pair) for pair in allowed_delta}
    rows = []
    for key in sorted(set(mapped) | set(observed)):
        left, right = mapped.get(key), observed.get(key)
        if left is None or right is None:
            status = "missing_on_target" if right is None else "unexpected_on_target"
        elif left["count"] == right["count"] and left["sha256"] == right["sha256"]:
            status = "equal"
        else:
            status = "allowed_delta" if key in allowed_pairs else "different"
        rows.append({"schema": key[0], "bucket": key[1], "status": status,
                     "source": None if left is None else {"count": left["count"], "sha256": left["sha256"]},
                     "target": None if right is None else {"count": right["count"], "sha256": right["sha256"]}})
    failed = [row for row in rows if row["status"] not in ("equal", "allowed_delta")]
    return {"equal": not failed, "buckets": len(rows), "failed": len(failed), "rows": rows}


def compare_redis(source: list, target: list, *, restored_at_ms: int) -> dict:
    """Keys, types, value digests, stream ids, groups, PEL counts and absolute expiry.

    A key whose absolute expiry had already passed when the restore ran is `expired_in_downtime`:
    it is reported apart from a key that was lost, and its TTL is never extended to keep it.
    """
    left = {row["key"]: row for row in source}
    right = {row["key"]: row for row in target}
    rows = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key), right.get(key)
        if b is None:
            expired = a["expires_at_ms"] is not None and a["expires_at_ms"] <= restored_at_ms
            status = "expired_in_downtime" if expired else "missing_on_target"
        elif a is None:
            status = "unexpected_on_target"
        elif a["type"] != b["type"] or a["sha256"] != b["sha256"]:
            status = "value_different"
        elif a["expires_at_ms"] != b["expires_at_ms"]:
            status = "expiry_different"
        elif a["stream"] != b["stream"]:
            status = "stream_state_different"
        else:
            status = "equal"
        rows.append({"key": key, "status": status})
    failed = [row for row in rows if row["status"] not in ("equal", "expired_in_downtime")]
    pending = sum(g["pending"] for row in source if row["stream"] for g in row["stream"]["groups"])
    return {"equal": not failed, "keys": len(rows), "failed": len(failed), "pending_total": pending,
            "rows": rows}


def compare_trees(source: dict, target: dict) -> dict:
    """Two artifact inventories (relative path -> {sha256, bytes}); every file on both sides."""
    rows, failed = [], 0
    for name in sorted(set(source["files"]) | set(target["files"])):
        a, b = source["files"].get(name), target["files"].get(name)
        status = ("missing_on_target" if b is None else "unexpected_on_target" if a is None
                  else "equal" if a == b else "different")
        failed += status != "equal"
        if status != "equal":
            rows.append({"path": name, "status": status})
    anomalies = sorted(set(source.get("anomalies", [])) | set(target.get("anomalies", [])))
    return {"equal": failed == 0 and not anomalies, "files": len(set(source["files"]) | set(target["files"])),
            "failed": failed, "differences": rows[:200], "anomalies": anomalies}


def tree_digest(files: dict) -> str:
    return digest(["artifact-tree-v1", sorted((name, row["sha256"], row["bytes"]) for name, row in files.items())])


# ----- the Linux service descriptor ---------------------------------------------------------------
UNIT_FIELDS = {"schema", "unit", "description", "user", "group", "working_directory", "exec_start",
               "path", "environment", "stop_timeout_seconds", "restart_seconds",
               "start_limit_burst", "start_limit_interval_seconds"}
UNIT_NAME = re.compile(r"^zeus-[a-z0-9][a-z0-9-]{0,48}$")
ENV_NAME = re.compile(r"^(ZEUS|HARNESS)_[A-Z0-9_]{1,60}$")


def _absolute_posix(value, name: str) -> str:
    if not (type(value) is str and value.startswith("/") and len(value) <= MAX_TEXT
            and posixpath.normpath(value) == value and re.fullmatch(r"[A-Za-z0-9/._@+-]+", value)):
        raise MigrationRefused("unit_invalid", name)
    return value


def validate_unit(document) -> dict:
    """A systemd service for one Zeus component: absolute paths, explicit UID, no login shell.

    ExecStart is an argv of absolute or plain tokens, never a shell string; the environment is an
    allowlist of non-secret ZEUS_/HARNESS_ settings, so a credential cannot be placed in a unit.
    """
    refuse_secrets(document, "unit")
    if not isinstance(document, dict) or document.get("schema") != UNIT_SCHEMA:
        raise MigrationRefused("unit_schema")
    _fields(document, UNIT_FIELDS, "unit")
    _match(document["unit"], UNIT_NAME, "unit.unit")
    if not (type(document["description"]) is str and re.fullmatch(r"[A-Za-z0-9 ._()/-]{1,120}", document["description"])):
        raise MigrationRefused("unit_invalid", "unit.description")
    for key in ("user", "group"):
        if not (type(document[key]) is str and re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", document[key])) \
                or document[key] == "root":
            raise MigrationRefused("unit_invalid", "unit." + key)
    _absolute_posix(document["working_directory"], "unit.working_directory")
    argv = _list(document["exec_start"], "unit.exec_start", minimum=1)
    _absolute_posix(argv[0], "unit.exec_start[0]")
    for index, arg in enumerate(argv[1:], 1):
        if not (type(arg) is str and re.fullmatch(r"[A-Za-z0-9/._=:@+-]{1,200}", arg)):
            raise MigrationRefused("unit_invalid", "unit.exec_start[" + str(index) + "]")
    path = document["path"]
    if not (type(path) is str and all(_absolute_posix(p, "unit.path") for p in path.split(":"))):
        raise MigrationRefused("unit_invalid", "unit.path")
    environment = document["environment"]
    if not isinstance(environment, dict) or len(environment) > 32:
        raise MigrationRefused("unit_invalid", "unit.environment")
    for key, value in environment.items():
        _match(key, ENV_NAME, "unit.environment")
        if not (type(value) is str and re.fullmatch(r"[A-Za-z0-9/._=:@+,-]{0,200}", value)):
            raise MigrationRefused("unit_invalid", "unit.environment." + key)
    bounds = {"stop_timeout_seconds": (1, 900), "restart_seconds": (1, 600),
              "start_limit_burst": (1, 10), "start_limit_interval_seconds": (10, 3600)}
    for key, (low, high) in bounds.items():
        if type(document[key]) is not int or not low <= document[key] <= high:
            raise MigrationRefused("unit_invalid", "unit." + key)
    return {key: document[key] for key in sorted(UNIT_FIELDS)}


def render_unit(document) -> str:
    """The unit file text. KillMode=control-group ends every process of the service; Docker
    containers the service created are NOT in that cgroup and are reconciled separately by label."""
    unit = validate_unit(document)
    environment = [f"Environment={key}={value}" for key, value in sorted(unit["environment"].items())]
    lines = ["# Generated from " + UNIT_SCHEMA + "; do not edit by hand.",
             "[Unit]", "Description=" + unit["description"],
             "After=network-online.target docker.service", "Wants=network-online.target",
             "StartLimitIntervalSec=" + str(unit["start_limit_interval_seconds"]),
             "StartLimitBurst=" + str(unit["start_limit_burst"]), "",
             "[Service]", "Type=simple", "User=" + unit["user"], "Group=" + unit["group"],
             "WorkingDirectory=" + unit["working_directory"],
             "ExecStart=" + " ".join(unit["exec_start"]),
             "Environment=PATH=" + unit["path"], *environment,
             "KillMode=control-group", "KillSignal=SIGTERM",
             "TimeoutStopSec=" + str(unit["stop_timeout_seconds"]),
             "Restart=on-failure", "RestartSec=" + str(unit["restart_seconds"]),
             "NoNewPrivileges=yes", "UMask=0027", "",
             "[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lines)


__all__ = ["CHECKPOINT_SCHEMA", "FAILED", "FORWARD", "GATES", "LIMITED_ACTIVE", "MANIFEST_SCHEMA",
           "MigrationRefused", "PLANNED", "QUALIFIED", "ROLLBACK_R0", "ROLLBACK_R1", "ROLLBACK_REQUIRED",
           "ROLLED_BACK", "SNAPSHOT_SEALED", "STATES", "STEPS", "TRANSITION_SCHEMA", "UNIT_SCHEMA",
           "allowed", "compare_buckets", "compare_redis", "compare_trees", "manifest_digest",
           "refuse_secrets", "render_unit", "resume_state", "reverse_maps", "rollback_mode",
           "step_allowed", "target_written", "transition_id", "tree_digest", "validate_checkpoint",
           "validate_manifest", "validate_transition", "validate_unit"]
