"""Owner-only recovery and lane relocation policy for a paused fleet (INV-FLEET-001).

Two bounded owner operations exist here as pure policy over dictionaries, with no store, process,
git, Docker or filesystem access:

* RECONCILE. An interrupted job whose external effects are already proven dead is settled once, as
  a terminal `failed` with the fixed `interrupted_unknown` reason. The evidence document names the
  job, the exact lane operation and task, the exact owned container, the closed invocation
  reservation and the settled machine call slot; the adapter's observation (`proof`) must repeat
  those identities exactly and must show the call slot bound to that operation by a record the
  host wrote itself. Nothing here retries, resumes, grants budget, invents usage or turns an
  unknown outcome into a success: the job's frozen manifest, goal, call counts and history stay as
  they are and only that one reservation is cleared.
* RELOCATE. Lane repository and runtime PATHS move to already-copied targets. The lane id, team,
  PostgreSQL schema, Redis namespace, concurrency, budget and provider authority are compared field
  by field and must be unchanged, the resulting configuration is re-validated by the existing
  `validate_config`, and the relocation is refused unless something actually moves.

Values never reach an error message; the field name does. Both operations are compare-and-swap on
the caller's stated expectations, and both are idempotent on the identical document.
"""
from __future__ import annotations

import re

from codex_harness.domain.fleet import (
    FAILED,
    LANE_FIELDS,
    RESERVING,
    TOKEN,
    FleetRefused,
    absolute_resolved,
    config_digest,
    nested,
    normalize_path,
    repository_identity,
    validate_config,
)
from codex_harness.domain.fleet import _aware_timestamp as _aware
from codex_harness.domain.model import digest

EVIDENCE_SCHEMA = "urn:zeus:fleet-recovery-evidence:1"
PROOF_SCHEMA = "urn:zeus:fleet-recovery-proof:1"
RECEIPT_SCHEMA = "urn:zeus:fleet-recovery-receipt:1"
REQUEST_SCHEMA = "urn:zeus:fleet-relocation:1"
RELOCATION_PROOF_SCHEMA = "urn:zeus:fleet-relocation-proof:1"
RELOCATION_RECEIPT_SCHEMA = "urn:zeus:fleet-relocation-receipt:1"
COPY_MANIFEST_SCHEMA = "urn:zeus:copy-manifest:1"
# How the adapter states it established copy ownership: every move root and both ends of every
# manifest entry were resolved concretely and had to be their own root's file at the stated relative
# path. A proof that cannot say this has only compared names, which a junction or symlink below a
# root satisfies while the destination IS the source, so the commit refuses it.
COPY_OWNERSHIP = "resolved_paths"

# The one terminal reason an owner recovery may write. It is a failure, never an acceptance, and it
# says the outcome of the interrupted work itself is unknown.
INTERRUPTED = "interrupted_unknown"
RECOVERY_AUTHORITY = ("owner_recovery; paused fleet, worker services stopped; a re-read cross-store "
                      "observation, not a distributed atomic transaction")
RELOCATION_AUTHORITY = ("owner_relocation; lane repository and runtime paths only; history, goal "
                        "identity and provider authority unchanged")

EVIDENCE_FIELDS = {"schema", "job_id", "operator", "expected", "lane_operation", "container",
                   "invocation", "machine_slot", "recorded_at"}
EXPECTED_FIELDS = {"status", "owner_token", "lane", "config_sha256"}
OPERATION_FIELDS = {"id", "correlation_id", "task_id", "generation"}
CONTAINER_FIELDS = {"run_id", "role", "name", "id"}
INVOCATION_FIELDS = {"reservation_id", "status"}
SLOT_FIELDS = {"id", "outcome"}

REQUEST_FIELDS = {"schema", "fleet", "operator", "expected_config_sha256", "moves", "copy_manifest",
                  "recorded_at"}
MOVE_FIELDS = {"lane", "repository", "runtime"}
PATH_FIELDS = {"from", "to"}
COPY_FIELDS = {"path", "sha256", "entries"}
MOVABLE = ("repository", "runtime")

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")
# A Docker state that cannot still be producing effects. `running`, `paused` and `restarting` are
# live; anything this module does not recognize is refused rather than read as stopped.
STOPPED_STATES = frozenset({"exited", "dead", "created"})
# An invocation reservation that no longer holds capacity. `reserved` is still open.
CLOSED_INVOCATIONS = frozenset({"settled", "unsettled_unknown"})
SETTLED_SLOT = "used"
# How a machine call slot may be bound to the interrupted operation. Both are records the host
# already wrote for its own reasons: the ledger slot's own `purpose` (`operation:<id>:<kind>`,
# written when the slot was taken) and the lane `operations` row's recorded `calls.slots[]`. A
# caller's assertion that a slot belongs to this job is not one of them.
SLOT_BINDINGS = frozenset({"ledger_purpose", "operation_calls"})
MAX_MOVES = 4
MAX_COPY_ENTRIES = 100000


def _token(value) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


def _hex(value, pattern) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _timestamp(value, field: str) -> str:
    try:
        return _aware(value)
    except FleetRefused as exc:
        raise FleetRefused("recovery_invalid", field) from exc


def _shape(document, expected, name: str, reason: str) -> dict:
    if not isinstance(document, dict):
        raise FleetRefused(reason, name)
    if set(document) != expected:
        raise FleetRefused(reason + "_fields", name)
    return document


# ----- reconcile: the owner's evidence document --------------------------------------------
def validate_recovery_evidence(document) -> dict:
    """Strict validation of `urn:zeus:fleet-recovery-evidence:1`; returns the canonical copy.

    This is what the owner STATES was proven dead. It authorizes nothing by itself: the adapter
    must observe the same identities in the lane store, in Docker and in the machine call ledger,
    and the application re-reads that observation inside the committing transaction.
    """
    if not isinstance(document, dict) or document.get("schema") != EVIDENCE_SCHEMA:
        raise FleetRefused("recovery_schema")
    _shape(document, EVIDENCE_FIELDS, "root", "recovery_invalid")
    if not _token(document["job_id"]):
        raise FleetRefused("recovery_invalid", "job_id")
    if not _token(document["operator"]):
        raise FleetRefused("recovery_invalid", "operator")
    expected = _shape(document["expected"], EXPECTED_FIELDS, "expected", "recovery_invalid")
    if expected["status"] not in RESERVING:
        raise FleetRefused("recovery_invalid", "expected.status")
    if not _hex(expected["owner_token"], HEX32):
        raise FleetRefused("recovery_invalid", "expected.owner_token")
    if not _token(expected["lane"]):
        raise FleetRefused("recovery_invalid", "expected.lane")
    if not _hex(expected["config_sha256"], HEX64):
        raise FleetRefused("recovery_invalid", "expected.config_sha256")
    operation = _shape(document["lane_operation"], OPERATION_FIELDS, "lane_operation", "recovery_invalid")
    if not (_token(operation["id"]) and _token(operation["task_id"])):
        raise FleetRefused("recovery_invalid", "lane_operation.id/task_id")
    if operation["correlation_id"] != "operation:" + operation["id"]:
        raise FleetRefused("recovery_invalid", "lane_operation.correlation_id")
    if type(operation["generation"]) is not int or type(operation["generation"]) is bool or operation["generation"] < 1:
        # A cancellation ADVANCES the generation, so a fenced task is never at generation zero.
        raise FleetRefused("recovery_invalid", "lane_operation.generation")
    container = _shape(document["container"], CONTAINER_FIELDS, "container", "recovery_invalid")
    if not (_hex(container["run_id"], HEX32) and _token(container["role"])):
        raise FleetRefused("recovery_invalid", "container.run_id/role")
    if container["name"] != "zeus-" + container["role"] + "-" + container["run_id"]:
        raise FleetRefused("recovery_invalid", "container.name")
    if not _hex(container["id"], HEX64):
        raise FleetRefused("recovery_invalid", "container.id")
    invocation = _shape(document["invocation"], INVOCATION_FIELDS, "invocation", "recovery_invalid")
    if not _hex(invocation["reservation_id"], HEX64):
        raise FleetRefused("recovery_invalid", "invocation.reservation_id")
    if invocation["status"] not in CLOSED_INVOCATIONS:
        raise FleetRefused("recovery_invalid", "invocation.status")
    slot = _shape(document["machine_slot"], SLOT_FIELDS, "machine_slot", "recovery_invalid")
    if not _hex(slot["id"], HEX32):
        raise FleetRefused("recovery_invalid", "machine_slot.id")
    if not _token(slot["outcome"]):
        raise FleetRefused("recovery_invalid", "machine_slot.outcome")
    return {"schema": EVIDENCE_SCHEMA, "job_id": document["job_id"], "operator": document["operator"],
            "expected": {k: expected[k] for k in sorted(EXPECTED_FIELDS)},
            "lane_operation": {k: operation[k] for k in sorted(OPERATION_FIELDS)},
            "container": {k: container[k] for k in sorted(CONTAINER_FIELDS)},
            "invocation": {k: invocation[k] for k in sorted(INVOCATION_FIELDS)},
            "machine_slot": {k: slot[k] for k in sorted(SLOT_FIELDS)},
            "recorded_at": _timestamp(document["recorded_at"], "recorded_at")}


def proof_binding(proof) -> dict:
    """The identities of one cross-store observation, without its clock.

    The adapter observes this before the transaction and again inside it; the two bindings must be
    equal, so a container that came back to life, a reopened reservation or a replaced task between
    the two reads refuses instead of committing.
    """
    if not isinstance(proof, dict):
        raise FleetRefused("proof_invalid", "root")
    return {key: value for key, value in sorted(proof.items()) if key != "observed_at"}


def check_recovery_proof(evidence: dict, proof) -> dict:
    """The adapter's observation must repeat the stated evidence exactly, and prove it dead.

    This is the second, independent gate: the adapter refuses with its own precise reason first,
    and nothing commits unless this check agrees on every identity.
    """
    if not isinstance(proof, dict) or proof.get("schema") != PROOF_SCHEMA:
        raise FleetRefused("proof_schema")
    operation = proof.get("lane_operation")
    if not isinstance(operation, dict) or operation.get("id") != evidence["lane_operation"]["id"] \
            or operation.get("correlation_id") != evidence["lane_operation"]["correlation_id"]:
        raise FleetRefused("proof_mismatch", "lane_operation")
    task = proof.get("task")
    if not isinstance(task, dict) or task.get("id") != evidence["lane_operation"]["task_id"] \
            or task.get("generation") != evidence["lane_operation"]["generation"]:
        raise FleetRefused("proof_mismatch", "task")
    if task.get("status") != "cancelled":
        raise FleetRefused("task_not_cancelled", "task.status")
    if task.get("lease_live") is not False:
        raise FleetRefused("task_lease_live", "task.lease_live")
    container = proof.get("container")
    if not isinstance(container, dict) or any(container.get(k) != evidence["container"][k]
                                              for k in ("run_id", "name", "id")):
        raise FleetRefused("proof_mismatch", "container")
    if container.get("bound_worktree") is not True:
        # A container NAME with no recorded task/run binding is not proof that this job owned it.
        raise FleetRefused("container_binding_missing", "container.bound_worktree")
    if container.get("state") not in STOPPED_STATES:
        raise FleetRefused("container_not_stopped", "container.state")
    invocation = proof.get("invocation")
    if not isinstance(invocation, dict) or invocation.get("reservation_id") != evidence["invocation"]["reservation_id"] \
            or invocation.get("status") != evidence["invocation"]["status"]:
        raise FleetRefused("proof_mismatch", "invocation")
    if invocation.get("status") not in CLOSED_INVOCATIONS:
        raise FleetRefused("invocation_open", "invocation.status")
    slot = proof.get("machine_slot")
    if not isinstance(slot, dict) or slot.get("id") != evidence["machine_slot"]["id"] \
            or slot.get("outcome") != evidence["machine_slot"]["outcome"]:
        raise FleetRefused("proof_mismatch", "machine_slot")
    if slot.get("bound_by") not in SLOT_BINDINGS \
            or slot.get("bound_operation") != evidence["lane_operation"]["id"]:
        # The slot id alone says nothing: a settled slot of unrelated work carries the same shape.
        # Only a record the host wrote itself binds this slot to this operation, and a slot whose
        # ledger row predates that record (no purpose, not in the operation's recorded calls) is
        # incomplete evidence, never an assumed match.
        raise FleetRefused("machine_slot_unbound", "machine_slot.id")
    if slot.get("status") != SETTLED_SLOT:
        raise FleetRefused("machine_slot_open", "machine_slot.status")
    return proof_binding(proof)


def recovery_receipt_id(evidence: dict) -> str:
    return digest(["fleet-recovery-v1", evidence])


def recovery_receipt(evidence: dict, proof: dict, fleet: str, config_sha256: str, now: str) -> dict:
    """The immutable record of one owner recovery. It is evidence, never an authority to resume."""
    return {"id": recovery_receipt_id(evidence), "schema": RECEIPT_SCHEMA, "job_id": evidence["job_id"],
            "fleet": fleet, "config_sha256": config_sha256, "operator": evidence["operator"],
            "authority": RECOVERY_AUTHORITY, "evidence": evidence, "proof": proof,
            "binding": proof_binding(proof),
            "outcome": {"status": FAILED, "reason_code": INTERRUPTED,
                        "calls": "preserved_as_recorded", "usage": "unknown"},
            "recorded_at": now}


def recovery_view(receipt: dict) -> dict:
    """The safe projection: identities, the fixed outcome and the authority label; no paths."""
    return {"schema": RECEIPT_SCHEMA, "id": receipt["id"], "job_id": receipt["job_id"],
            "fleet": receipt["fleet"], "operator": receipt["operator"],
            "authority": receipt["authority"], "outcome": dict(receipt["outcome"]),
            "lane_operation": dict(receipt["evidence"]["lane_operation"]),
            "container": {"run_id": receipt["evidence"]["container"]["run_id"],
                          "state": receipt["proof"]["container"].get("state")},
            "invocation": dict(receipt["evidence"]["invocation"]),
            "machine_slot": dict(receipt["evidence"]["machine_slot"]),
            "recorded_at": receipt["recorded_at"]}


# ----- relocate: the owner's path map ------------------------------------------------------
def _move(move, index: int) -> dict:
    name = "moves[" + str(index) + "]"
    _shape(move, MOVE_FIELDS, name, "relocation_invalid")
    if not _token(move["lane"]):
        raise FleetRefused("relocation_invalid", name + ".lane")
    canonical = {"lane": move["lane"], "repository": None, "runtime": None}
    for key in MOVABLE:
        change = move[key]
        if change is None:
            continue
        _shape(change, PATH_FIELDS, name + "." + key, "relocation_invalid")
        for side in ("from", "to"):
            if not absolute_resolved(change[side]):
                raise FleetRefused("relocation_invalid", name + "." + key + "." + side)
        if normalize_path(change["from"]) == normalize_path(change["to"]):
            raise FleetRefused("relocation_unchanged", name + "." + key)
        if nested(normalize_path(change["to"]), normalize_path(change["from"])) or \
                nested(normalize_path(change["from"]), normalize_path(change["to"])):
            raise FleetRefused("relocation_overlap", name + "." + key)
        canonical[key] = {"from": change["from"], "to": change["to"]}
    if canonical["repository"] is None and canonical["runtime"] is None:
        raise FleetRefused("relocation_empty", name)
    return canonical


def validate_relocation_request(document) -> dict:
    """Strict validation of `urn:zeus:fleet-relocation:1`; returns the canonical copy."""
    if not isinstance(document, dict) or document.get("schema") != REQUEST_SCHEMA:
        raise FleetRefused("relocation_schema")
    _shape(document, REQUEST_FIELDS, "root", "relocation_invalid")
    if not (_token(document["fleet"]) and _token(document["operator"])):
        raise FleetRefused("relocation_invalid", "fleet/operator")
    if not _hex(document["expected_config_sha256"], HEX64):
        raise FleetRefused("relocation_invalid", "expected_config_sha256")
    moves = document["moves"]
    if not (isinstance(moves, list) and 1 <= len(moves) <= MAX_MOVES):
        raise FleetRefused("relocation_invalid", "moves")
    moves = [_move(move, index) for index, move in enumerate(moves)]
    if len({move["lane"] for move in moves}) != len(moves):
        raise FleetRefused("relocation_duplicate", "moves[].lane")
    copy = _shape(document["copy_manifest"], COPY_FIELDS, "copy_manifest", "relocation_invalid")
    if not absolute_resolved(copy["path"]):
        raise FleetRefused("relocation_invalid", "copy_manifest.path")
    if not _hex(copy["sha256"], HEX64):
        raise FleetRefused("relocation_invalid", "copy_manifest.sha256")
    if type(copy["entries"]) is not int or type(copy["entries"]) is bool \
            or not 1 <= copy["entries"] <= MAX_COPY_ENTRIES:
        raise FleetRefused("relocation_invalid", "copy_manifest.entries")
    return {"schema": REQUEST_SCHEMA, "fleet": document["fleet"], "operator": document["operator"],
            "expected_config_sha256": document["expected_config_sha256"], "moves": moves,
            "copy_manifest": {k: copy[k] for k in sorted(COPY_FIELDS)},
            "recorded_at": _timestamp(document["recorded_at"], "recorded_at")}


def relocated_config(config: dict, request: dict) -> dict:
    """The registered configuration with ONLY the stated lane paths replaced.

    Every stated source path must be exactly what is registered now, no target may be or contain a
    path this fleet already uses, and the result is re-validated by `validate_config`, so the
    existing nesting, overlap, duplicate and grammar rules decide the new paths as well. Every
    other field of the fleet and of every lane is compared afterwards and must be identical.
    """
    lanes = {lane["id"]: lane for lane in config["lanes"]}
    occupied = {normalize_path(lane[key]) for lane in config["lanes"] for key in MOVABLE}
    revised = []
    for index, move in enumerate(request["moves"]):
        name = "moves[" + str(index) + "]"
        lane = lanes.get(move["lane"])
        if lane is None:
            raise FleetRefused("lane_unknown", name + ".lane")
        updated = dict(lane)
        for key in MOVABLE:
            change = move[key]
            if change is None:
                continue
            if lane[key] != change["from"]:
                raise FleetRefused("source_path_mismatch", name + "." + key + ".from")
            target = normalize_path(change["to"])
            if any(nested(target, used) or nested(used, target) for used in occupied):
                raise FleetRefused("target_path_in_use", name + "." + key + ".to")
            updated[key] = change["to"]
        revised.append(updated)
    moved = {lane["id"]: lane for lane in revised}
    document = {**config, "lanes": [moved.get(lane["id"], lane) for lane in config["lanes"]]}
    new = validate_config(document)
    for old_lane, new_lane in zip(config["lanes"], new["lanes"]):
        if any(old_lane[key] != new_lane[key] for key in sorted(LANE_FIELDS - set(MOVABLE))):
            raise FleetRefused("relocation_changes_identity", "lanes[]." + old_lane["id"])
    if any(config[key] != new[key] for key in ("schema", "id", "max_parallel")) or config["budget"] != new["budget"]:
        raise FleetRefused("relocation_changes_identity", "root")
    if config_digest(new) == config_digest(config):
        raise FleetRefused("relocation_unchanged", "moves")
    return new


def repository_aliases(config: dict, new: dict) -> dict:
    """Old lane repository identity -> new one, for the lanes whose repository moved.

    Frozen job rows are never rewritten, so a job enqueued before the move keeps the identity of
    the repository it was bound to. This is ONE receipt's edges; `canonical_repositories` folds
    every receipt into the equivalence a reader may use.
    """
    aliases = {}
    for old_lane, new_lane in zip(config["lanes"], new["lanes"]):
        if old_lane["repository"] != new_lane["repository"]:
            aliases[repository_identity(old_lane["repository"])] = repository_identity(new_lane["repository"])
    return aliases


def canonical_repositories(alias_maps) -> dict:
    """One canonical identity per repository, folded over the relocation receipts in their order.

    Repeated moves and rollbacks make the receipts' `old -> new` edges a graph, not a chain: A->B
    followed by B->A is a cycle, and walking it from A and from B answers differently, which would
    silently split one repository into two for the admission path exclusion. The equivalence CLASS
    is the invariant instead. Every identity a lane repository has ever had joins one class, and
    the whole class resolves to the destination of the LAST recorded move of that class - the path
    the lane actually uses now. A job frozen at any older identity and a job enqueued now therefore
    compare equal, in either direction and after any number of moves.

    Nothing here rewrites a receipt or a job: the receipts are the input, and the answer is a map
    (`domain.fleet.resolve_repository` reads it).
    """
    parent: dict[str, str] = {}

    def find(identity: str) -> str:
        # `parent` is only ever pointed from one class root at another, so this walk terminates.
        while parent.get(identity, identity) != identity:
            identity = parent[identity]
        return identity

    current: dict[str, str] = {}
    for mapping in alias_maps:
        for old, new in sorted((mapping or {}).items()):
            parent.setdefault(old, old)
            parent.setdefault(new, new)
            left, right = find(old), find(new)
            if left != right:
                parent[left] = right
            current[find(new)] = new
    return {identity: current[find(identity)] for identity in sorted(parent)}


def check_relocation_proof(request: dict, proof, queued: dict) -> dict:
    """The adapter's host observation must show an idle fleet and verified, usable targets.

    `queued` is lane id -> the queued job ids read in the committing transaction: every one of them
    must appear with its pinned base commit and goal blob present in the TARGET repository, so a
    relocation can never leave queued work pointing at a base the new checkout does not have.
    """
    if not isinstance(proof, dict) or proof.get("schema") != RELOCATION_PROOF_SCHEMA:
        raise FleetRefused("proof_schema")
    runner = proof.get("runner")
    if not isinstance(runner, dict) or runner.get("state") != "stopped":
        raise FleetRefused("runner_not_stopped", "runner.state")
    copy = proof.get("copy_manifest")
    if not isinstance(copy, dict) or copy.get("sha256") != request["copy_manifest"]["sha256"] \
            or copy.get("entries") != request["copy_manifest"]["entries"] \
            or copy.get("verified") != request["copy_manifest"]["entries"] \
            or copy.get("bound") is not True or copy.get("ownership") != COPY_OWNERSHIP:
        # `bound` is the adapter's statement that every entry was read and that each one belongs to
        # a path this request actually moves: an unrelated manifest cannot certify this cutover.
        # `ownership` is its statement that each one physically IS that path's own file rather than
        # a name redirected there by a link, which equal bytes alone cannot distinguish.
        raise FleetRefused("copy_unverified", "copy_manifest")
    observed = {lane.get("id"): lane for lane in proof.get("lanes") or [] if isinstance(lane, dict)}
    for move in request["moves"]:
        lane = observed.get(move["lane"])
        if lane is None:
            raise FleetRefused("proof_mismatch", "lanes[]." + move["lane"])
        if lane.get("active_runs") != 0:
            raise FleetRefused("lane_run_active", "lanes[]." + move["lane"])
        if move["repository"] is not None:
            repository = lane.get("repository")
            if not isinstance(repository, dict) or repository.get("independent") is not True:
                raise FleetRefused("target_not_independent", "lanes[]." + move["lane"] + ".repository")
            if repository.get("source_identity") != repository.get("target_identity") \
                    or not repository.get("target_identity"):
                raise FleetRefused("repository_identity_mismatch", "lanes[]." + move["lane"] + ".repository")
        if move["runtime"] is not None:
            runtime = lane.get("runtime")
            if not isinstance(runtime, dict) or runtime.get("writable") is not True:
                raise FleetRefused("runtime_unwritable", "lanes[]." + move["lane"] + ".runtime")
        bindings = {row.get("job_id"): row for row in lane.get("queued_bindings") or [] if isinstance(row, dict)}
        if set(bindings) != set(queued.get(move["lane"], ())):
            raise FleetRefused("queued_binding_incomplete", "lanes[]." + move["lane"])
        for job_id, row in sorted(bindings.items()):
            if row.get("base_present") is not True or row.get("goal_matches") is not True:
                raise FleetRefused("queued_base_missing", "lanes[]." + move["lane"])
    return proof_binding(proof)


def relocation_receipt_id(request: dict) -> str:
    return digest(["fleet-relocation-v1", request])


def relocation_receipt(request: dict, proof: dict, prior: dict, new: dict, now: str) -> dict:
    """The immutable record of one relocation: what the registry was, and what it became."""
    return {"id": relocation_receipt_id(request), "schema": RELOCATION_RECEIPT_SCHEMA,
            "fleet": prior["id"], "operator": request["operator"], "authority": RELOCATION_AUTHORITY,
            "prior_config": prior["config"], "prior_config_sha256": prior["config_sha256"],
            "config": new, "config_sha256": config_digest(new),
            "repository_aliases": repository_aliases(prior["config"], new),
            "request": request, "proof": proof, "binding": proof_binding(proof), "recorded_at": now}


def relocation_view(receipt: dict) -> dict:
    """The safe projection: identities and counts, never a repository, runtime or manifest path."""
    return {"schema": RELOCATION_RECEIPT_SCHEMA, "id": receipt["id"], "fleet": receipt["fleet"],
            "operator": receipt["operator"], "authority": receipt["authority"],
            "prior_config_sha256": receipt["prior_config_sha256"], "config_sha256": receipt["config_sha256"],
            "lanes": [{"id": move["lane"], "repository": move["repository"] is not None,
                       "runtime": move["runtime"] is not None} for move in receipt["request"]["moves"]],
            "copy_manifest_sha256": receipt["request"]["copy_manifest"]["sha256"],
            "recorded_at": receipt["recorded_at"]}


# ----- host migration: the registry binding of a whole-fleet move to another host -------------
# `relocate` above moves paths on ONE host and reads both ends of every move. A move to another
# host cannot read the source paths (they are on the source host) and must also rename the lane
# schemas the target database restored under new names (INV-HOST-MIGRATION-001). This is that
# operation: every lane moves at once, only repository/runtime/schema change, and the source
# repository is identified by its root commits (`checkout_identity`), never by its old path.
HOST_MIGRATION_SCHEMA = "urn:zeus:fleet-host-migration:1"
HOST_MIGRATION_PROOF_SCHEMA = "urn:zeus:fleet-host-migration-proof:1"
HOST_MIGRATION_RECEIPT_SCHEMA = "urn:zeus:fleet-host-migration-receipt:1"
HOST_MIGRATION_AUTHORITY = ("owner_host_migration; lane repository, runtime and schema bindings only; "
                            "lane/team identity, Redis namespaces, history and provider authority unchanged")
HOST_MIGRATION_FIELDS = {"schema", "fleet", "operator", "migration_id", "manifest_sha256",
                         "expected_config_sha256", "source_repository_identity", "lanes", "recorded_at"}
HOST_LANE_FIELDS = {"lane", "repository", "runtime", "schema"}
HOST_MOVABLE = ("repository", "runtime", "schema")
SCHEMA_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:\\[^\x00]*$|^[A-Za-z]:/[^\x00]*$")


def _any_absolute(value) -> bool:
    """The FROM side is the source host's spelling: a Windows drive path or a POSIX path."""
    return type(value) is str and 0 < len(value) <= 400 and (
        absolute_resolved(value) or (WINDOWS_ABSOLUTE.fullmatch(value) is not None
                                     and ".." not in value.replace("\\", "/").split("/")))


def validate_host_migration_request(document) -> dict:
    """Strict validation of `urn:zeus:fleet-host-migration:1`; returns the canonical copy."""
    if not isinstance(document, dict) or document.get("schema") != HOST_MIGRATION_SCHEMA:
        raise FleetRefused("host_migration_schema")
    _shape(document, HOST_MIGRATION_FIELDS, "root", "host_migration_invalid")
    for key in ("fleet", "operator", "migration_id"):
        if not _token(document[key]):
            raise FleetRefused("host_migration_invalid", key)
    for key in ("manifest_sha256", "expected_config_sha256", "source_repository_identity"):
        if not _hex(document[key], HEX64):
            raise FleetRefused("host_migration_invalid", key)
    lanes = document["lanes"]
    if not (isinstance(lanes, list) and 1 <= len(lanes) <= 16):
        raise FleetRefused("host_migration_invalid", "lanes")
    canonical = []
    for index, lane in enumerate(lanes):
        name = "lanes[" + str(index) + "]"
        _shape(lane, HOST_LANE_FIELDS, name, "host_migration_invalid")
        if not _token(lane["lane"]):
            raise FleetRefused("host_migration_invalid", name + ".lane")
        row = {"lane": lane["lane"]}
        for key in HOST_MOVABLE:
            change = _shape(lane[key], PATH_FIELDS, name + "." + key, "host_migration_invalid")
            if key == "schema":
                if not all(type(change[side]) is str and SCHEMA_IDENT.fullmatch(change[side]) for side in PATH_FIELDS):
                    raise FleetRefused("host_migration_invalid", name + ".schema")
            else:
                if not _any_absolute(change["from"]):
                    raise FleetRefused("host_migration_invalid", name + "." + key + ".from")
                if not absolute_resolved(change["to"]):
                    raise FleetRefused("host_migration_invalid", name + "." + key + ".to")
            row[key] = {"from": change["from"], "to": change["to"]}
        canonical.append(row)
    if len({row["lane"] for row in canonical}) != len(canonical):
        raise FleetRefused("host_migration_duplicate", "lanes[].lane")
    return {"schema": HOST_MIGRATION_SCHEMA, "fleet": document["fleet"], "operator": document["operator"],
            "migration_id": document["migration_id"], "manifest_sha256": document["manifest_sha256"],
            "expected_config_sha256": document["expected_config_sha256"],
            "source_repository_identity": document["source_repository_identity"],
            "lanes": sorted(canonical, key=lambda row: row["lane"]),
            "recorded_at": _timestamp(document["recorded_at"], "recorded_at")}


def host_migrated_config(config: dict, request: dict) -> dict:
    """The registered configuration with EVERY lane's repository, runtime and schema rebound.

    Every configured lane must be named exactly once and each `from` must be what is registered
    now. Lane id, team and Redis namespace, and the root id, concurrency and budget are compared
    afterwards and must be identical; the result is re-validated by `validate_config`.
    """
    lanes = {lane["id"]: lane for lane in config["lanes"]}
    moves = {row["lane"]: row for row in request["lanes"]}
    if set(moves) != set(lanes):
        raise FleetRefused("host_migration_lanes_incomplete", "lanes")
    revised = []
    for lane in config["lanes"]:
        move, updated = moves[lane["id"]], dict(lane)
        for key in HOST_MOVABLE:
            if lane[key] != move[key]["from"]:
                raise FleetRefused("source_binding_mismatch", "lanes[]." + lane["id"] + "." + key)
            updated[key] = move[key]["to"]
        revised.append(updated)
    new = validate_config({**config, "lanes": revised})
    for old_lane, new_lane in zip(config["lanes"], new["lanes"]):
        if any(old_lane[key] != new_lane[key] for key in ("id", "team", "redis_namespace")):
            raise FleetRefused("host_migration_changes_identity", "lanes[]." + old_lane["id"])
    if any(config[key] != new[key] for key in ("schema", "id", "max_parallel")) or config["budget"] != new["budget"]:
        raise FleetRefused("host_migration_changes_identity", "root")
    if config_digest(new) == config_digest(config):
        raise FleetRefused("host_migration_unchanged", "lanes")
    return new


def check_host_migration_proof(request: dict, proof, queued: dict) -> dict:
    """The TARGET host observation: runner stopped, lanes quiet, the target checkout is the same
    repository as the source (root commits) and carries every queued job's base and goal, every
    runtime is writable and every target schema is provisioned under the lane search-path rule."""
    if not isinstance(proof, dict) or proof.get("schema") != HOST_MIGRATION_PROOF_SCHEMA:
        raise FleetRefused("proof_schema")
    runner = proof.get("runner")
    if not isinstance(runner, dict) or runner.get("state") != "stopped":
        raise FleetRefused("runner_not_stopped", "runner.state")
    observed = {lane.get("id"): lane for lane in proof.get("lanes") or [] if isinstance(lane, dict)}
    for move in request["lanes"]:
        name = "lanes[]." + move["lane"]
        lane = observed.get(move["lane"])
        if lane is None:
            raise FleetRefused("proof_mismatch", name)
        if lane.get("active_runs") != 0:
            raise FleetRefused("lane_run_active", name)
        repository = lane.get("repository")
        if not isinstance(repository, dict) or repository.get("independent") is not True:
            raise FleetRefused("target_not_independent", name + ".repository")
        if repository.get("target_identity") != request["source_repository_identity"]:
            raise FleetRefused("repository_identity_mismatch", name + ".repository")
        runtime = lane.get("runtime")
        if not isinstance(runtime, dict) or runtime.get("writable") is not True:
            raise FleetRefused("runtime_unwritable", name + ".runtime")
        schema = lane.get("schema")
        if not isinstance(schema, dict) or schema.get("name") != move["schema"]["to"] \
                or schema.get("provisioned") is not True:
            raise FleetRefused("target_schema_unprovisioned", name + ".schema")
        bindings = {row.get("job_id"): row for row in lane.get("queued_bindings") or [] if isinstance(row, dict)}
        if set(bindings) != set(queued.get(move["lane"], ())):
            raise FleetRefused("queued_binding_incomplete", name)
        if any(row.get("base_present") is not True or row.get("goal_matches") is not True
               for row in bindings.values()):
            raise FleetRefused("queued_base_missing", name)
    return proof_binding(proof)


def host_migration_receipt_id(request: dict) -> str:
    return digest(["fleet-host-migration-v1", request])


def host_migration_receipt(request: dict, proof: dict, prior: dict, new: dict, now: str) -> dict:
    """What the registry was and what it became; the prior configuration is kept verbatim."""
    return {"id": host_migration_receipt_id(request), "schema": HOST_MIGRATION_RECEIPT_SCHEMA,
            "fleet": prior["id"], "operator": request["operator"], "authority": HOST_MIGRATION_AUTHORITY,
            "migration_id": request["migration_id"], "manifest_sha256": request["manifest_sha256"],
            "prior_config": prior["config"], "prior_config_sha256": prior["config_sha256"],
            "config": new, "config_sha256": config_digest(new),
            "repository_aliases": repository_aliases(prior["config"], new),
            "request": request, "proof": proof, "binding": proof_binding(proof), "recorded_at": now}


def host_migration_view(receipt: dict) -> dict:
    return {"schema": HOST_MIGRATION_RECEIPT_SCHEMA, "id": receipt["id"], "fleet": receipt["fleet"],
            "operator": receipt["operator"], "authority": receipt["authority"],
            "migration_id": receipt["migration_id"], "prior_config_sha256": receipt["prior_config_sha256"],
            "config_sha256": receipt["config_sha256"],
            "lanes": [{"id": row["lane"], "schema": row["schema"]["to"]} for row in receipt["request"]["lanes"]],
            "recorded_at": receipt["recorded_at"]}


__all__ = ["COPY_MANIFEST_SCHEMA", "COPY_OWNERSHIP", "HOST_MIGRATION_PROOF_SCHEMA", "HOST_MIGRATION_RECEIPT_SCHEMA",
           "HOST_MIGRATION_SCHEMA", "check_host_migration_proof", "host_migrated_config", "host_migration_receipt",
           "host_migration_receipt_id", "host_migration_view", "validate_host_migration_request", "EVIDENCE_SCHEMA", "INTERRUPTED", "PROOF_SCHEMA",
           "RECEIPT_SCHEMA", "RELOCATION_PROOF_SCHEMA", "RELOCATION_RECEIPT_SCHEMA", "REQUEST_SCHEMA",
           "SLOT_BINDINGS", "canonical_repositories",
           "check_recovery_proof", "check_relocation_proof", "proof_binding", "recovery_receipt",
           "recovery_receipt_id", "recovery_view", "relocated_config", "relocation_receipt",
           "relocation_receipt_id", "relocation_view", "repository_aliases",
           "validate_recovery_evidence", "validate_relocation_request"]
