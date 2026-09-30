"""Shared S7 scenario steps (`delivery.canaries`): the module-level functions of M7 `adapters/host_delivery.py` other
than the targets and `GitHubDelivery` (pilot 33) and the composition/CLI (the S10 carry), recorded BEFORE the move
(DESIGN-s7 §2 row `delivery.canaries_runner`, the `host_delivery.py` remainder; INV-HOST-DELIVERY-001,
INV-HOST-DELIVERY-FIRST-ACTIVATION-001, INV-OWNER-ACTIONS-001).

Nine case groups, each case labelled in the result (`mirrors` names the M7 test it copies; a case without `mirrors` is
built from the source):
- `files`: the module constants, `canary_request_file`, `canary_receipt_file`, `_plan_token` (valid and refused
  tokens) and `configured_enabled`.
- `state_json`: `_read_json` (valid, missing, malformed, the size bound, non-UTF-8, a directory, a `str` path) and
  `_write_json` (parent creation, sorted keys, the temporary name and the `os.replace`, overwrite, the failures and
  the temporary file they leave behind). G4 is recorded, not fixed: `os.fsync` is never called.
- `revisions`: `_git_directory`, `_ref_directories`, `checkout_revision` and `runtime_revision` over REAL git
  repositories (plain, packed refs, detached, linked worktree, worktree branch through `commondir`) and hand-written
  git directories, `loaded_runtime`.
- `profile`: `effective_worker_image` (explicit config and a LABELLED environment), `_host_settings`,
  `effective_profile_digest` and `committed_profile_digest` (a real committed repository and a LABELLED
  `GitSource` double, with each tamper).
- `first_activation`: `first_activation_facts` over a labelled docker double and the committed profile resources.
- `plan`: `load_plan` over fixture repositories (pin, exact bytes, every refusal, size and shape).
- `checks`: `normalize_checks`.
- `ports`: `host_ports` per target kind and `systemd_control_dir`.
- `canaries`: `startup_identity_canary`, `collect_monitor_canary`, `owner_qualified_canary` and `canary_checks`.

**Fixtures (all LABELLED).**
- Git repositories are real, built under the pinned environment of `s7_host_targets.pinned_environment` (author and
  committer identity and dates, empty git configuration files), so every revision is deterministic and recorded
  literally. A worktree or packed-refs variant uses the same environment.
- The environment-dependent readers never read the host: `effective_worker_image(config)` and
  `first_activation_facts(lane, host, ...)` take their settings as parameters; `_host_settings` and
  `effective_worker_image()` are fed a LABELLED settings file (`<root>/settings-N/.env`, found through
  `ZEUS_REPOSITORY`) and LABELLED environment keys that a case sets; the whole environment is restored after the
  case. The settings dictionary is never recorded whole, only the fixed keys `SETTING_KEYS`.
- The docker call of `first_activation_facts` is a recording double (argv, timeout); nothing reaches docker.
- The monitor store is the side's `MemoryStore` (`SerialStore`, `BrokenStore` of `s7_delivery`), holding the
  descriptor rows the M7 test writes.
- Live processes are LABELLED sleepers (`Fixture.sleeper`); a sweep at the end of the group fails the run on a leak.

**Normalization is explicit, done here and identical on both sides:** pilot 33's rules, imported and used
unchanged (`s7_host_targets.Fixture.n`: `sys.executable`, the run's root, the package directory, pids,
`instance_id`, ISO times, a fixture-built descriptor digest). The one added rule is the temporary file name of
`_write_json`: `.tmp-` and 8 hex → `.tmp-<8hex>` (`uuid4`). Revisions of the pinned fixture repositories stay literal.

`api` supplies every name the cases use: see the reference driver."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace

import s7_host_targets as T
from s7_delivery import BrokenStore, SerialStore

IMAGE_ID = "sha256:" + "d" * 64
IMAGE_ID_OTHER = "sha256:" + "9" * 64
SOURCE_REVISION = "ab12cd34ef" * 4
REVISION = "a" * 40
TREE = "c" * 64
POLICY_HASH = "1" * 64
CHECK = "ci / required"
PLAN_PATH = "docs/zeus/operations/delivery.json"
H1, H2 = "own-" + "a" * 24, "own-" + "b" * 24
INSTANCE_ONE, INSTANCE_TWO = "1" * 32, "2" * 32
SETTING_KEYS = ("ZEUS_WORKER_IMAGE", "HARNESS_WORKER_IMAGE", "ZEUS_HOST_DELIVERY_ENABLED",
                "HARNESS_HOST_DELIVERY_ENABLED", "ZEUS_AIBOX_ROOT")
IMAGE_KEYS = ("ZEUS_WORKER_IMAGE", "HARNESS_WORKER_IMAGE", "ZEUS_HOST_DELIVERY_ENABLED",
              "HARNESS_HOST_DELIVERY_ENABLED", "ZEUS_AIBOX_ROOT", "ZEUS_REPOSITORY", "HARNESS_REPOSITORY")
TMP_NAME = re.compile(r"\.tmp-[0-9a-f]{8}$")
TMP_NAME_ANY = re.compile(r"\.tmp-[0-9a-f]{8}")
NORMALIZATION = {"core.autocrlf": "false", "core.eol": "lf", "core.safecrlf": "false"}


class Env:
    """One run: the pinned git environment, the repositories built so far and the labelled settings directories."""

    def __init__(self, api, base: Path):
        self.api, self.base = api, base
        self.fx = T.Fixture(api, base)
        self.git_env = T.pinned_environment(base)
        self.serial = 0

    def n(self, value):
        return self.tmp(self.fx.n(value))

    def tmp(self, value):
        """The one rule added to pilot 33's: a `_write_json` temporary name `.tmp-<8 hex>` (a uuid4 draw)."""
        if isinstance(value, dict):
            return {self.tmp(key): self.tmp(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.tmp(item) for item in value]
        return TMP_NAME_ANY.sub(".tmp-<8hex>", value) if isinstance(value, str) else value

    def attempt(self, call):
        return self.tmp(self.fx.attempt(call))

    def rec(self, call, mirrors=None, **extra):
        """One case: the attempt (what returned, or the named refusal), its mirror and recorded facts."""
        out = {"result": self.attempt(call)}
        if mirrors:
            out["mirrors"] = mirrors
        out.update(self.n(extra))
        return out

    def directory(self, name: str) -> Path:
        self.serial += 1
        path = self.base / "cases" / f"{self.serial:03d}-{name}"
        path.mkdir(parents=True)
        return path

    # --- real git, pinned ----------------------------------------------------------------------------
    def git(self, root, *args) -> str:
        return T.pinned_git(Path(root), self.git_env, *args)

    def repository(self, name: str, files: dict | None = None, commit: bool = True, links: dict | None = None):
        """LABELLED: a git repository under the pinned environment; `files` are committed once when `commit`."""
        root = self.directory(name)
        self.git(root, "init", "-q", "-b", "main")
        for key, value in NORMALIZATION.items():
            self.git(root, "config", "--local", key, value)
        for path, data in (files or {}).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        for path, destination in (links or {}).items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            os.symlink(destination, root / path)
        revision = None
        if commit:
            self.git(root, "add", "--all")
            self.git(root, "commit", "-q", "--no-verify", "-m", "fixture")
            revision = self.git(root, "rev-parse", "HEAD")
        return root, revision

    def commit_file(self, root, path: str, text: str, message: str) -> str:
        (Path(root) / path).write_text(text, encoding="utf-8")
        self.git(root, "add", "--all")
        self.git(root, "commit", "-q", "--no-verify", "-m", message)
        return self.git(root, "rev-parse", "HEAD")

    # --- the labelled settings ---------------------------------------------------------------------------
    @contextlib.contextmanager
    def settings(self, dotenv: str | None = None, **environment):
        """LABELLED settings: `ZEUS_REPOSITORY` names a fixture directory (its `.env` is `dotenv`) and only the keys
        the case names are set among `IMAGE_KEYS`. The whole environment is restored on exit."""
        root = self.directory("settings")
        if dotenv is not None:
            (root / ".env").write_text(dotenv, encoding="utf-8")
        saved = dict(os.environ)
        for key in IMAGE_KEYS:
            os.environ.pop(key, None)
        os.environ["ZEUS_REPOSITORY"] = os.environ["HARNESS_REPOSITORY"] = str(root)
        os.environ.update(environment)
        try:
            yield root
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def view(self, settings) -> dict:
        """The fixed keys of a settings dictionary; never the whole dictionary."""
        return {key: settings[key] for key in SETTING_KEYS if key in settings}


# ===== files ================================================================================================
TOKENS = {"plan-1": "plan-1", "single-letter": "A", "sixty-four": "a" * 64, "owner-action": H1,
          "dots-underscores-dashes": "a.b_c-d", "digit-first": "1abc"}
BAD_TOKENS = {"parent-traversal": "../x", "slash": "a/b", "empty": "", "leading-dot": ".hidden", "none": None,
              "sixty-five": "a" * 65, "integer": 5, "leading-dash": "-a", "space": "a b",
              "trailing-newline": "a\n", "non-ascii": "äa", "bytes": b"plan", "backslash": "a\\b"}


def group_files(env: Env) -> dict:
    A, out = env.api, {}
    out["constants"] = {
        "DESCRIPTOR_FILE": A.DESCRIPTOR_FILE, "RECEIPT_FILE": A.RECEIPT_FILE, "STATE_FILE": A.STATE_FILE,
        "WORK_FILE": A.WORK_FILE, "PAUSE_FILE": A.PAUSE_FILE, "STOP_FILE": A.STOP_FILE, "LOCK_DIR": A.LOCK_DIR,
        "RUNTIME_FILE": A.RUNTIME_FILE, "MAX_PLAN_BYTES": A.MAX_PLAN_BYTES, "MAX_STATE_BYTES": A.MAX_STATE_BYTES,
        "ENABLED_SETTING": A.ENABLED_SETTING, "TRUE_VALUES": sorted(A.TRUE_VALUES),
        "PROFILE_RESOURCES": A.PROFILE_RESOURCES, "IMAGE_REVISION_LABEL": A.IMAGE_REVISION_LABEL,
        "IMAGE_INSPECT_TIMEOUT": A.IMAGE_INSPECT_TIMEOUT}
    for label, token in TOKENS.items():
        out["token_" + label] = {"request": env.attempt(lambda t=token: A.canary_request_file(t)),
                                 "receipt": env.attempt(lambda t=token: A.canary_receipt_file(t)),
                                 "plan_token": env.attempt(lambda t=token: A.plan_token(t))}
    out["token_plan_1_names"] = {
        "mirrors": "tests/test_owner_canary_plan.py::test_plan_scoped_file_names_accept_only_plan_tokens",
        "request": A.canary_request_file(H1) == "owner-canary-request." + H1 + ".json",
        "receipt": A.canary_receipt_file(H1) == "owner-canary-receipt." + H1 + ".json"}
    for label, token in BAD_TOKENS.items():
        out["refused_" + label] = {
            "mirrors": ("tests/test_owner_canary_plan.py::test_plan_scoped_file_names_accept_only_plan_tokens"
                        if label in {"parent-traversal", "slash", "empty", "leading-dot", "none"} else None),
            "request": env.attempt(lambda t=token: A.canary_request_file(t)),
            "receipt": env.attempt(lambda t=token: A.canary_receipt_file(t)),
            "plan_token": env.attempt(lambda t=token: A.plan_token(t))}
        if out["refused_" + label]["mirrors"] is None:
            del out["refused_" + label]["mirrors"]
    enabled = {"empty-settings": {}, "none": None,
               "zero": {A.ENABLED_SETTING: "0"}, "maybe": {A.ENABLED_SETTING: "maybe"},
               "padded-upper-true": {A.ENABLED_SETTING: " TRUE "}, "one": {A.ENABLED_SETTING: "1"},
               "yes": {A.ENABLED_SETTING: "yes"}, "on": {A.ENABLED_SETTING: "On"},
               "true-lower": {A.ENABLED_SETTING: "true"}, "empty-value": {A.ENABLED_SETTING: ""},
               "false": {A.ENABLED_SETTING: "false"}, "integer-one": {A.ENABLED_SETTING: 1},
               "boolean-true": {A.ENABLED_SETTING: True}, "none-value": {A.ENABLED_SETTING: None},
               "other-key": {"HARNESS_HOST_DELIVERY_ENABLED": "1"}, "enabled-word": {A.ENABLED_SETTING: "enabled"}}
    mirrored = {"empty-settings", "none", "zero", "maybe", "padded-upper-true", "one"}
    for label, settings in enabled.items():
        case = {"enabled": env.attempt(lambda s=settings: A.configured_enabled(s))}
        if label in mirrored:
            case["mirrors"] = "tests/test_host_delivery_cli.py::test_delivery_is_opt_in_through_one_explicit_host_setting"
        out["enabled_" + label] = case
    # The setting read from a LABELLED settings file through the real `settings()`.
    for label, dotenv, environment in (
            ("from-file", "ZEUS_HOST_DELIVERY_ENABLED=yes\n", {}),
            ("environment-overrides-file", "ZEUS_HOST_DELIVERY_ENABLED=yes\n", {"ZEUS_HOST_DELIVERY_ENABLED": "no"}),
            ("harness-alias", "HARNESS_HOST_DELIVERY_ENABLED=1\n", {}), ("no-file", None, {})):
        with env.settings(dotenv, **environment):
            out["enabled_labelled_settings_" + label] = {
                "settings": env.view(A.host_settings()),
                "enabled": A.configured_enabled(A.host_settings())}
    return out


# ===== state_json ==============================================================================================
@contextlib.contextmanager
def spied(env: Env):
    """LABELLED spy over `os.replace` and `os.fsync`: what `_write_json` replaces, from where, and whether it syncs."""
    calls = {"replace": [], "fsync": 0}
    real_replace, real_fsync = os.replace, os.fsync

    def replace(source, destination, *args, **kwargs):
        calls["replace"].append({"from": TMP_NAME.sub(".tmp-<8hex>", Path(source).name),
                                 "to": Path(destination).name, "text": Path(source).read_text("utf-8"),
                                 "destination_existed": Path(destination).exists()})
        return real_replace(source, destination, *args, **kwargs)

    def fsync(descriptor):
        calls["fsync"] += 1
        return real_fsync(descriptor)

    os.replace, os.fsync = replace, fsync
    try:
        yield calls
    finally:
        os.replace, os.fsync = real_replace, real_fsync


def names(directory: Path) -> list:
    return sorted(TMP_NAME.sub(".tmp-<8hex>", path.name) for path in Path(directory).iterdir())


def group_state_json(env: Env) -> dict:
    A, out = env.api, {}
    root = env.directory("state")
    limit = A.MAX_STATE_BYTES

    def put(name, data):
        path = root / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return path

    document = {"a": 1, "b": [1, 2], "c": None}
    body = json.dumps(document)
    out["valid_document"] = env.rec(lambda: A.read_json(put("valid.json", body)))
    out["valid_list_document"] = env.rec(lambda: A.read_json(put("list.json", "[1, 2]")))
    out["valid_scalar_documents"] = {
        label: env.attempt(lambda data=data: A.read_json(put("scalar.json", data)))
        for label, data in (("null", "null"), ("number", "7"), ("string", '"text"'), ("true", "true"))}
    out["missing_file"] = env.rec(lambda: A.read_json(root / "absent.json"))
    out["missing_directory"] = env.rec(lambda: A.read_json(root / "no-dir" / "absent.json"))
    out["malformed"] = env.rec(lambda: A.read_json(put("bad.json", "{not json")))
    out["empty_file"] = env.rec(lambda: A.read_json(put("empty.json", "")))
    out["truncated_document"] = env.rec(lambda: A.read_json(put("truncated.json", body[:-2])))
    out["byte_order_mark"] = env.rec(lambda: A.read_json(put("bom.json", b"\xef\xbb\xbf" + body.encode())))
    out["non_utf8"] = env.rec(lambda: A.read_json(put("latin.json", b'{"a": "\xff\xfe"}')))
    out["directory_path"] = env.rec(lambda: A.read_json(root))
    out["str_path_is_not_a_path"] = env.rec(lambda: A.read_json(str(root / "valid.json")))
    padded = body + " " * (limit - len(body))
    out["exactly_at_the_bound"] = {
        "size": len(padded), "result": env.attempt(lambda: A.read_json(put("at-limit.json", padded)))}
    over = body + " " * (limit + 1 - len(body))
    out["one_over_the_bound"] = {
        "size": len(over), "result": env.attempt(lambda: A.read_json(put("over-limit.json", over)))}
    out["oversized_is_never_a_partial_document"] = env.rec(
        lambda: A.read_json(put("large.json", json.dumps({"k": "x" * (limit + 10)}))))
    out["custom_limit_reads"] = env.rec(lambda: A.read_json(root / "valid.json", len(body)))
    out["custom_limit_one_under"] = env.rec(lambda: A.read_json(root / "valid.json", len(body) - 1))
    out["zero_limit"] = env.rec(lambda: A.read_json(root / "valid.json", 0))
    # --- _write_json ---------------------------------------------------------------------------------------
    target = root / "write" / "nested" / "descriptor.json"
    with spied(env) as calls:
        env.attempt(lambda: A.write_json(target, {"b": 2, "a": {"z": 1, "y": [3]}}))
    out["write_creates_parents_and_replaces_atomically"] = {
        "text": target.read_text("utf-8"), "directory": names(target.parent), "replace": calls["replace"],
        "fsync_calls": calls["fsync"], "g4_no_fsync": calls["fsync"] == 0,
        "parents_created": (root / "write" / "nested").is_dir()}
    with spied(env) as calls:
        A.write_json(target, {"replaced": True})
    out["write_overwrites_an_existing_file"] = {
        "text": target.read_text("utf-8"), "directory": names(target.parent), "replace": calls["replace"],
        "fsync_calls": calls["fsync"]}
    with spied(env) as calls:
        A.write_json(root / "write" / "scalars.json", [1, "two", None, True, 1.5])
    out["write_serializes_any_json_value"] = {
        "text": (root / "write" / "scalars.json").read_text("utf-8"), "fsync_calls": calls["fsync"]}
    out["write_then_read_round_trips"] = {
        "read": env.attempt(lambda: A.read_json(target)),
        "non_ascii_text": (lambda p: (A.write_json(p, {"k": "ä☃"}), p.read_text("utf-8"))[1])(
            root / "write" / "unicode.json")}
    out["write_unserializable_leaves_nothing"] = env.rec(
        lambda: A.write_json(root / "write" / "set.json", {"a": {1, 2}}),
        directory=names(root / "write"))
    out["write_over_a_directory_fails_and_leaks_the_temporary_file"] = {
        "result": env.attempt(lambda: (root / "asdir.json").mkdir() or A.write_json(root / "asdir.json", {"a": 1})),
        "directory": [name for name in names(root) if name.startswith("asdir.json")]}
    blocker = put("blocker", "a file where a directory is needed")
    out["write_parent_is_a_file"] = env.rec(lambda: A.write_json(blocker / "child.json", {"a": 1}))
    out["write_with_a_str_path"] = env.rec(lambda: A.write_json(str(root / "str.json"), {"a": 1}))
    return out


# ===== revisions ================================================================================================
def group_revisions(env: Env) -> dict:
    A, out = env.api, {}
    out["loaded_runtime"] = {
        "mirrors": "tests/test_host_delivery.py (receipt['module_root'] == loaded_runtime()['module_root'])",
        "value": env.n(A.loaded_runtime()),
        "keys": sorted(A.loaded_runtime()),
        "module_root_is_the_package": A.loaded_runtime()["module_root"] == str(Path(A.PACKAGE_DIR).resolve())}
    # --- a plain repository (mirrors the attest test) -------------------------------------------------
    empty, _ = env.repository("no-commit", {"README.md": "fixture\n"}, commit=False)
    out["branch_with_no_commit"] = env.rec(lambda: A.checkout_revision(empty),
                                           mirrors="test_a_runtime_root_attests_its_own_revision_from_its_own_refs",
                                           runtime=env.attempt(lambda: A.runtime_revision(empty)))
    plain, revision = env.repository("plain", {"README.md": "fixture\n"})
    out["plain_repository"] = env.rec(
        lambda: A.checkout_revision(plain), mirrors="test_a_runtime_root_attests_its_own_revision_from_its_own_refs",
        runtime=env.attempt(lambda: A.runtime_revision(plain)))
    out["plain_repository"]["git_directory"] = env.attempt(lambda: A.git_directory(plain))
    out["plain_repository"]["ref_directories"] = env.attempt(lambda: A.ref_directories(plain / ".git"))
    # A packed ref, exactly as the M7 test writes it (a hand-written packed-refs file, the loose ref removed).
    packed, packed_revision = env.repository("packed", {"README.md": "fixture\n"})
    (packed / ".git" / "packed-refs").write_text("# pack-refs with: peeled\n" + packed_revision + " refs/heads/main\n",
                                                 encoding="utf-8")
    (packed / ".git" / "refs" / "heads" / "main").unlink()
    out["packed_refs_hand_written"] = env.rec(
        lambda: A.checkout_revision(packed), mirrors="test_a_runtime_root_attests_its_own_revision_from_its_own_refs")
    # The same repository with the packed refs git itself writes.
    gc, gc_revision = env.repository("pack-refs", {"README.md": "fixture\n"})
    env.git(gc, "pack-refs", "--all", "--prune")
    out["packed_refs_written_by_git"] = env.rec(
        lambda: A.checkout_revision(gc), loose_ref_left=(gc / ".git" / "refs" / "heads" / "main").exists(),
        packed_refs_present=(gc / ".git" / "packed-refs").is_file())
    # A detached HEAD names the commit directly.
    (packed / ".git" / "HEAD").write_text(packed_revision + "\n", encoding="utf-8")
    out["detached_head"] = env.rec(lambda: A.checkout_revision(packed),
                                   mirrors="test_a_runtime_root_attests_its_own_revision_from_its_own_refs")
    # --- HEAD and ref defects on hand-written git directories -------------------------------------------------
    def fake(name, head=None, loose=None, packed_refs=None, reference="refs/heads/main"):
        root = env.directory(name)
        (root / ".git").mkdir()
        if head is not None:
            (root / ".git" / "HEAD").write_text(head, encoding="utf-8")
        if loose is not None:
            (root / ".git" / reference).parent.mkdir(parents=True, exist_ok=True)
            (root / ".git" / reference).write_text(loose, encoding="utf-8")
        if packed_refs is not None:
            (root / ".git" / "packed-refs").write_text(packed_refs, encoding="utf-8")
        return root

    ref = "ref: refs/heads/main\n"
    sha = "a1b2c3d4e5" * 4
    other = "f0e1d2c3b4" * 4
    defects = {
        "missing_head_file": fake("no-head"),
        "head_not_a_ref_nor_a_hash": fake("head-garbage", head="garbage\n"),
        "head_short_hash": fake("head-short", head="abc123\n"),
        "head_uppercase_hash": fake("head-upper", head=sha.upper() + "\n"),
        "head_empty": fake("head-empty", head=""),
        "head_hash_with_spaces_around": fake("head-spaces", head="  " + sha + "  \n"),
        "head_ref_loose": fake("loose", head=ref, loose=sha + "\n"),
        "head_ref_no_space_after_colon": fake("ref-tight", head="ref:refs/heads/main\n", loose=sha + "\n"),
        "head_ref_loose_invalid_hash": fake("loose-invalid", head=ref, loose="not-a-hash\n"),
        "head_ref_loose_short_hash": fake("loose-short", head=ref, loose="abc\n"),
        "invalid_loose_ref_does_not_fall_through_to_packed": fake(
            "loose-invalid-packed", head=ref, loose="zzz\n", packed_refs=sha + " refs/heads/main\n"),
        "head_ref_unresolved_anywhere": fake("unresolved", head=ref),
        "loose_ref_wins_over_packed": fake("loose-wins", head=ref, loose=sha + "\n",
                                           packed_refs=other + " refs/heads/main\n"),
        "packed_refs_peeled_and_comment_lines": fake(
            "packed-peeled", head=ref, packed_refs="# pack-refs with: peeled fully-peeled sorted\n" + other +
            " refs/heads/other\n^" + sha + "\n" + sha + " refs/heads/main\n^" + other + "\n"),
        "packed_refs_other_ref_only": fake("packed-other", head=ref, packed_refs=other + " refs/heads/other\n"),
        "packed_refs_invalid_hash": fake("packed-bad", head=ref, packed_refs="nothash refs/heads/main\n"),
        "packed_refs_three_fields_do_not_match": fake("packed-extra", head=ref,
                                                 packed_refs=sha + " refs/heads/main extra\n"),
        "packed_refs_crlf": fake("packed-crlf", head=ref, packed_refs=sha + " refs/heads/main\r\n"),
        "head_names_a_ref_with_a_path": fake("nested-ref", head="ref: refs/heads/feature/x\n",
                                             loose=sha + "\n", reference="refs/heads/feature/x"),
        "head_ref_traversal_reads_outside_refs": fake("traversal", head="ref: ../outside\n"),
    }
    (defects["head_ref_traversal_reads_outside_refs"] / ".git" / "outside").write_text(sha + "\n", encoding="utf-8")
    for label, root in defects.items():
        out["git_directory_" + label] = {"checkout_revision": env.attempt(lambda r=root: A.checkout_revision(r)),
                                         "runtime_revision": env.attempt(lambda r=root: A.runtime_revision(r))}
    out["root_is_not_a_checkout"] = env.rec(lambda: A.checkout_revision(env.directory("bare")),
                                            runtime=env.attempt(lambda: A.runtime_revision(env.directory("bare2"))))
    out["root_does_not_exist"] = env.rec(lambda: A.checkout_revision(env.base / "nowhere"),
                                         runtime=env.attempt(lambda: A.runtime_revision(env.base / "nowhere")))
    out["root_given_as_a_str"] = env.rec(lambda: A.checkout_revision(str(plain)),
                                         runtime=env.attempt(lambda: A.runtime_revision(str(plain))))
    # --- the `.git` pointer file (a worktree or a submodule) ------------------------------------------------------
    linked_pointer = env.directory("pointer-linked")
    (linked_pointer / ".git").write_text("gitdir: " + str(plain / ".git") + "\n", encoding="utf-8")
    out["worktree_pointer_to_the_git_directory"] = env.rec(
        lambda: A.checkout_revision(linked_pointer),
        mirrors="test_a_worktree_pointer_resolves_to_the_git_directory_it_names",
        git_directory=env.attempt(lambda: A.git_directory(linked_pointer)))
    relative = env.directory("pointer-relative")
    (relative / ".git").write_text("gitdir: ../" + plain.name + "/.git\n", encoding="utf-8")
    out["pointer_relative_to_the_root"] = env.rec(lambda: A.checkout_revision(relative),
                                                  git_directory=env.attempt(lambda: A.git_directory(relative)))
    pointers = {
        "not_gitdir_text": "some text\n", "gitdir_without_space": "gitdir:" + str(plain / ".git") + "\n",
        "gitdir_to_a_missing_directory": "gitdir: " + str(env.base / "missing-git") + "\n",
        "gitdir_to_a_file": "gitdir: " + str(plain / "README.md") + "\n", "gitdir_empty": "gitdir:\n",
        "gitdir_with_extra_spaces": "gitdir:    " + str(plain / ".git") + "   \n",
        "leading_whitespace_before_gitdir": " gitdir: " + str(plain / ".git") + "\n",
        "empty_pointer_file": ""}
    for label, text in pointers.items():
        root = env.directory("pointer-" + label)
        (root / ".git").write_text(text, encoding="utf-8")
        out["pointer_" + label] = {"git_directory": env.attempt(lambda r=root: A.git_directory(r)),
                                   "checkout_revision": env.attempt(lambda r=root: A.checkout_revision(r))}
    # --- a real linked worktree, through `commondir` ------------------------------------------------------------
    main, main_revision = env.repository("main-for-worktrees", {"README.md": "fixture\n"})
    linked = env.directory("linked-branch")
    linked.rmdir()
    env.git(main, "worktree", "add", "-q", "-b", "feature", str(linked))
    feature_revision = env.commit_file(linked, "feature.txt", "feature\n", "feature commit")
    worktree_git = Path((linked / ".git").read_text("utf-8").split(":", 1)[1].strip())
    out["linked_worktree_branch_resolves_through_commondir"] = env.rec(
        lambda: A.checkout_revision(linked),
        mirrors="tests/test_host_delivery_cli.py::test_a_worktree_pointer_resolves_to_the_git_directory_it_names "
                "(a real `git worktree add`, which the M7 test only approximates with a pointer to the main git dir)",
        main_head=main_revision, feature_head=feature_revision,
        git_directory=env.attempt(lambda: A.git_directory(linked)),
        commondir=(worktree_git / "commondir").read_text("utf-8").strip(),
        ref_directories=env.attempt(lambda: A.ref_directories(worktree_git)),
        runtime=env.attempt(lambda: A.runtime_revision(linked)),
        main_checkout=env.attempt(lambda: A.checkout_revision(main)))
    env.git(main, "pack-refs", "--all", "--prune")
    out["linked_worktree_branch_after_the_main_repository_packs_its_refs"] = env.rec(
        lambda: A.checkout_revision(linked), loose_ref_left=(main / ".git" / "refs" / "heads" / "feature").exists())
    detached = env.directory("linked-detached")
    detached.rmdir()
    env.git(main, "worktree", "add", "-q", "--detach", str(detached))
    out["linked_worktree_detached"] = env.rec(lambda: A.checkout_revision(detached),
                                              head_text=(Path((detached / ".git").read_text("utf-8").split(
                                                  ":", 1)[1].strip()) / "HEAD").read_text("utf-8").strip())
    # The worktree's own directory is searched before the common directory.
    (worktree_git / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (worktree_git / "refs" / "heads" / "feature").write_text("7" * 40 + "\n", encoding="utf-8")
    out["worktree_own_directory_shadows_the_common_one"] = env.rec(lambda: A.checkout_revision(linked))
    (worktree_git / "refs" / "heads" / "feature").write_text("not a hash\n", encoding="utf-8")
    out["worktree_own_invalid_ref_does_not_fall_back_to_the_common_one"] = env.rec(
        lambda: A.checkout_revision(linked))
    # --- _ref_directories on hand-written git directories -----------------------------------------------------------
    for label, text in (("absolute_existing", str(main / ".git")), ("relative_existing", "../../"),
                        ("empty", ""), ("missing_directory", str(env.base / "missing-common")),
                        ("whitespace_only", "   \n"), ("padded", "  " + str(main / ".git") + "  \n")):
        directory = env.directory("commondir-" + label)
        (directory / "commondir").write_text(text, encoding="utf-8")
        out["ref_directories_commondir_" + label] = env.attempt(lambda d=directory: A.ref_directories(d))
    bare_directory = env.directory("commondir-none")
    out["ref_directories_no_commondir_file"] = env.attempt(lambda: A.ref_directories(bare_directory))
    # --- runtime_revision: the checkout, else the owner's attestation -------------------------------------------------
    prepared = env.directory("prepared")
    out["no_checkout_no_attestation"] = env.rec(
        lambda: A.runtime_revision(prepared),
        mirrors="test_a_root_that_is_no_checkout_uses_the_owners_attestation_and_nothing_else",
        checkout=env.attempt(lambda: A.checkout_revision(prepared)))

    def attest(root, value=None, *, raw=None):
        (Path(root) / A.RUNTIME_FILE).write_text(raw if raw is not None else json.dumps(value), encoding="utf-8")

    attest(prepared, {"revision": "not a revision"})
    out["attestation_malformed_revision"] = env.rec(
        lambda: A.runtime_revision(prepared),
        mirrors="test_a_root_that_is_no_checkout_uses_the_owners_attestation_and_nothing_else")
    attest(prepared, {"revision": REVISION})
    out["attestation_valid"] = env.rec(
        lambda: A.runtime_revision(prepared),
        mirrors="test_a_root_that_is_no_checkout_uses_the_owners_attestation_and_nothing_else")
    for label, value in (("list_document", [REVISION]), ("revision_missing", {"other": 1}),
                         ("revision_integer", {"revision": 5}), ("revision_uppercase", {"revision": REVISION.upper()}),
                         ("revision_short", {"revision": "a" * 39}), ("revision_long", {"revision": "a" * 41}),
                         ("revision_null", {"revision": None}), ("scalar", "abc"),
                         ("extra_fields_ignored", {"revision": REVISION, "note": "x"})):
        attest(prepared, value)
        out["attestation_" + label] = env.attempt(lambda: A.runtime_revision(prepared))
    attest(prepared, raw="{not json")
    out["attestation_malformed_json"] = env.attempt(lambda: A.runtime_revision(prepared))
    attest(prepared, raw=json.dumps({"revision": REVISION}) + " " * A.MAX_STATE_BYTES)
    out["attestation_over_the_bound"] = env.attempt(lambda: A.runtime_revision(prepared))
    (prepared / A.RUNTIME_FILE).unlink()
    (prepared / A.RUNTIME_FILE).mkdir()
    out["attestation_is_a_directory"] = env.attempt(lambda: A.runtime_revision(prepared))
    both, both_revision = env.repository("checkout-and-attestation", {"README.md": "fixture\n"})
    attest(both, {"revision": "9" * 40})
    out["the_checkout_wins_over_the_attestation"] = env.rec(lambda: A.runtime_revision(both),
                                                            checkout_revision=both_revision)
    uncommitted, _ = env.repository("uncommitted-and-attestation", {"README.md": "fixture\n"}, commit=False)
    attest(uncommitted, {"revision": "8" * 40})
    out["a_checkout_with_no_commit_falls_back_to_the_attestation"] = env.rec(lambda: A.runtime_revision(uncommitted))
    out["the_running_checkout"] = {
        "mirrors": "tests/test_evaluator_code_guard.py::test_the_running_revision_is_this_checkout_by_the_runtime_"
                   "revision_ssot",
        "unreachable": ("the running checkout is the side's own tree (the reference wheel has no .git, the target a "
                        "worktree), so its revision differs per side by construction; its `runtime_revision` is "
                        "compared with `controller_code_revision` in `delivery.release_runner` (pin group), and the "
                        "function itself is recorded over fixture checkouts above")}
    return out


# ===== profile ===================================================================================================
def profile_files(env: Env) -> dict:
    """LABELLED: the three committed `worker-v1` resources as bytes (from the SOURCE archive's package)."""
    resources = Path(env.api.SOURCE_PACKAGE) / "resources"
    names = ("worker-profile-v1.json", "worker-profile-v1.md", "worker_profile_hook.py")
    return {env.api.PROFILE_RESOURCES + name: (resources / name).read_bytes() for name in names}


class Blobs:
    """LABELLED GitSource double (M7 `tests/test_host_delivery_first_activation.py::Blobs`): committed bytes by path."""

    def __init__(self, files):
        self.files, self.asked = files, []

    def blob(self, revision, path):
        self.asked.append(path)
        data = self.files.get(path)
        return (None, b"") if data is None else ("100644", data)


def group_profile(env: Env) -> dict:
    A, out = env.api, {}
    configs = {"empty": {}, "harness_alias": {"HARNESS_WORKER_IMAGE": T.IMAGE},
               "zeus_name": {"ZEUS_WORKER_IMAGE": T.IMAGE},
               "zeus_beats_harness": {"ZEUS_WORKER_IMAGE": "zeus-first", "HARNESS_WORKER_IMAGE": "harness-second"},
               "empty_zeus_falls_to_harness": {"ZEUS_WORKER_IMAGE": "", "HARNESS_WORKER_IMAGE": "harness-second"},
               "none_zeus_falls_to_harness": {"ZEUS_WORKER_IMAGE": None, "HARNESS_WORKER_IMAGE": "harness-second"},
               "whitespace_only": {"ZEUS_WORKER_IMAGE": "   "}, "padded_value": {"ZEUS_WORKER_IMAGE": "  img  "},
               "integer_value": {"ZEUS_WORKER_IMAGE": 5}, "both_blank": {"ZEUS_WORKER_IMAGE": "",
                                                                        "HARNESS_WORKER_IMAGE": ""},
               "unrelated_keys": {"ZEUS_REPOSITORY": "/x"}, "explicit_none_config_is_the_host": None}
    for label, config in configs.items():
        if config is None and label.startswith("explicit_none"):
            continue
        case = {"image": env.attempt(lambda c=config: A.effective_worker_image(c))}
        if label in {"empty", "harness_alias", "zeus_name"}:
            case["mirrors"] = "test_the_effective_worker_image_is_configuration_and_never_a_claim"
        out["image_config_" + label] = case
    out["image_config_empty_mapping_is_not_the_host"] = {
        "note": "`{}` is an explicit empty configuration: it does not fall back to the host settings",
        "image": env.attempt(lambda: A.effective_worker_image({}))}
    # `config=None` reads the host settings: fed by a LABELLED settings file and environment, never the host's.
    cases = {
        "nothing_configured": (None, {}), "file_zeus": ("ZEUS_WORKER_IMAGE=" + T.IMAGE + "\n", {}),
        "file_harness_alias": ("HARNESS_WORKER_IMAGE=" + T.IMAGE + "\n", {}),
        "environment_zeus": (None, {"ZEUS_WORKER_IMAGE": T.IMAGE}),
        "environment_harness": (None, {"HARNESS_WORKER_IMAGE": T.IMAGE}),
        "environment_overrides_file": ("ZEUS_WORKER_IMAGE=from-file\n", {"ZEUS_WORKER_IMAGE": T.IMAGE}),
        "file_quoted_and_commented": ('ZEUS_WORKER_IMAGE="quoted-image"  # note\n', {}),
        "file_export_prefix": ("export ZEUS_WORKER_IMAGE=exported\n", {}),
        "file_blank_value_with_environment_harness": ("ZEUS_WORKER_IMAGE=\n", {"HARNESS_WORKER_IMAGE": "h"}),
        "malformed_file_discards_the_environment": ("this is not an assignment\n", {"ZEUS_WORKER_IMAGE": T.IMAGE}),
        "malformed_quoting_discards_the_file": ('ZEUS_WORKER_IMAGE="unterminated\n', {}),
    }
    for label, (dotenv, environment) in cases.items():
        with env.settings(dotenv, **environment):
            settings = A.host_settings()
            out["image_labelled_settings_" + label] = {
                "host_settings": env.view(settings), "effective_worker_image": A.effective_worker_image(),
                "repository_is_the_labelled_directory": settings.get("ZEUS_REPOSITORY") == os.environ[
                    "ZEUS_REPOSITORY"]}
            if label == "environment_zeus":
                out["image_labelled_settings_" + label]["mirrors"] = (
                    "test_the_effective_worker_image_is_configuration_and_never_a_claim (monkeypatch.setenv)")
    with env.settings(None, ZEUS_WORKER_IMAGE=T.IMAGE):
        out["host_settings_failure_is_empty"] = {
            "note": "a malformed host configuration yields {} (M7 `_host_settings`), not an invented one",
            "well_formed": sorted(set(env.view(A.host_settings()))),
            "configuration_raises": env.attempt(lambda: A.host_settings_with(lambda: (_ for _ in ()).throw(
                ValueError("injected malformed configuration"))))}
    # --- the packaged profile digest -------------------------------------------------------------------------------
    digest = A.effective_profile_digest()
    out["effective_profile_digest"] = {"digest": digest, "is_sha256_hex": bool(re.fullmatch(r"[0-9a-f]{64}", digest or ""))}
    out["effective_profile_digest_when_the_profile_cannot_load"] = {
        "seam": "codex_harness.adapters.worker_profile.load_profile replaced by a raising function, then restored",
        "result": env.attempt(lambda: A.profile_digest_with_failing_load(RuntimeError("injected")))}
    # --- the committed digest at a revision --------------------------------------------------------------------------
    files = profile_files(env)
    root, revision = env.repository("profile-resources", files)
    committed = env.attempt(lambda: A.committed_profile_digest(A.GitSource(root), revision))
    out["committed_digest_from_a_real_repository"] = {
        "mirrors": ("tests/test_host_delivery_first_activation.py::test_the_committed_profile_digest_equals_the_"
                    "incumbent_packaged_digest (the fixture commits the SOURCE archive's resources, not the "
                    "checkout's, so the case is reproducible)"),
        "revision": revision, "result": committed, "equals_the_packaged_digest": (
            committed.get("returned") == digest)}
    out["committed_digest_unknown_revision"] = env.rec(
        lambda: A.committed_profile_digest(A.GitSource(root), "a" * 40))
    bare_root, bare_revision = env.repository("no-resources", {"x": "y"})
    out["committed_digest_resources_absent_at_the_revision"] = env.rec(
        lambda: A.committed_profile_digest(A.GitSource(bare_root), bare_revision))
    out["committed_digest_empty_blobs"] = env.rec(
        lambda: A.committed_profile_digest(Blobs({}), "a" * 40),
        mirrors="test_the_committed_profile_digest_equals_the_incumbent_packaged_digest (the Blobs({}) refusal)")
    out["committed_digest_blobs_double_is_the_same_digest"] = env.rec(
        lambda: A.committed_profile_digest(Blobs(dict(files)), "a" * 40))
    manifest_path = A.PROFILE_RESOURCES + "worker-profile-v1.json"
    document_path = A.PROFILE_RESOURCES + "worker-profile-v1.md"
    hook_path = A.PROFILE_RESOURCES + "worker_profile_hook.py"
    manifest = json.loads(files[manifest_path])

    def tampered(**changes):
        def build():
            copy = dict(files)
            document = {**manifest, **changes}
            copy[manifest_path] = json.dumps(document).encode("utf-8")
            return A.committed_profile_digest(Blobs(copy), "a" * 40)
        return build

    def with_files(**replace):
        def build():
            copy = dict(files)
            for key, value in replace.items():
                path = {"manifest": manifest_path, "document": document_path, "hook": hook_path}[key]
                if value is None:
                    copy.pop(path)
                else:
                    copy[path] = value
            return A.committed_profile_digest(Blobs(copy), "a" * 40)
        return build

    tampers = {
        "manifest_missing": with_files(manifest=None), "document_missing": with_files(document=None),
        "hook_missing": with_files(hook=None), "manifest_not_json": with_files(manifest=b"{nope"),
        "manifest_not_an_object": with_files(manifest=b"[1]"), "manifest_not_utf8": with_files(manifest=b"\xff\xfe"),
        "manifest_other_id": tampered(id="worker-v2"),
        "manifest_without_version": (lambda: A.committed_profile_digest(
            Blobs({**files, manifest_path: json.dumps({k: v for k, v in manifest.items() if k != "version"}).encode()}),
            "a" * 40)),
        "manifest_without_hook_sha": (lambda: A.committed_profile_digest(
            Blobs({**files, manifest_path: json.dumps({k: v for k, v in manifest.items() if k != "hook_sha256"}
                                                      ).encode()}), "a" * 40)),
        "document_changed": with_files(document=files[document_path] + b"\nextra line\n"),
        "document_crlf_is_normalized": with_files(document=files[document_path].replace(b"\n", b"\r\n")),
        "document_too_long": (lambda: A.committed_profile_digest(Blobs({
            **files, document_path: b"x" * (A.profile_character_limit() + 1),
            manifest_path: json.dumps({**manifest, "document_sha256": hashlib.sha256(
                b"x" * (A.profile_character_limit() + 1)).hexdigest()}).encode()}), "a" * 40)),
        "document_not_utf8": with_files(document=b"\xff\xfe\xfd"), "hook_changed": with_files(hook=files[hook_path] + b"#"),
        "permission_not_bash": tampered(permissions={"allow": ["Read(*)"]}),
        "permission_not_a_string": tampered(permissions={"allow": [5]}),
        "permissions_absent_is_allowed": (lambda: A.committed_profile_digest(
            Blobs({**files, manifest_path: json.dumps({k: v for k, v in manifest.items() if k != "permissions"}
                                                      ).encode()}), "a" * 40)),
        "document_name_is_a_path": tampered(document="../worker-profile-v1.md"),
        "document_name_empty": tampered(document=""), "document_name_not_a_string": tampered(document=5),
        "version_is_stringified": tampered(version=1),
    }
    for label, build in tampers.items():
        out["committed_digest_" + label] = env.rec(build)
    return out


# ===== first_activation ============================================================================================
class Docker:
    """LABELLED recording double of the docker image inspect call: argv, timeout; it never runs a process."""

    def __init__(self, returncode=0, stdout="", raises=None):
        self.returncode, self.stdout, self.raises, self.calls = returncode, stdout, raises, []

    def __call__(self, argv, timeout=None):
        self.calls.append({"argv": list(argv), "timeout": timeout})
        if self.raises:
            raise self.raises
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr="")


def group_first_activation(env: Env) -> dict:
    A, out = env.api, {}
    files = profile_files(env)
    root, revision = env.repository("activation-resources", files)
    lane = {"repository": str(root)}
    host = {"ZEUS_WORKER_IMAGE": IMAGE_ID}
    answer = IMAGE_ID + " " + SOURCE_REVISION + "\n"

    def run(label, *, host=host, revision=revision, docker=None, source="real", mirrors=None, lane=lane):
        double = docker or Docker(0, answer)
        chosen = {"real": None, "blobs-empty": Blobs({}), "blobs": Blobs(dict(files))}[source]
        case = env.rec(lambda: A.first_activation_facts(lane, host, revision, run=double, source=chosen),
                       mirrors=mirrors)
        case["docker_calls"] = env.n(double.calls)
        out[label] = case

    run("facts_from_the_committed_resources", mirrors=None)
    out["facts_from_the_committed_resources"]["revision"] = revision
    run("facts_with_a_source_double", source="blobs")
    run("unconfigured_image_no_settings", host={}, docker=Docker(0, ""),
        mirrors="test_the_port_re_derives_the_image_from_settings_and_the_local_image")
    run("image_not_an_immutable_id", host={"ZEUS_WORKER_IMAGE": "zeus-worker:latest"})
    run("image_tag_with_a_digest_is_not_an_id", host={"ZEUS_WORKER_IMAGE": T.IMAGE})
    run("image_none_token", host={"HARNESS_WORKER_IMAGE": "none"})
    run("image_harness_alias", host={"HARNESS_WORKER_IMAGE": IMAGE_ID})
    run("image_id_padded_with_spaces", host={"ZEUS_WORKER_IMAGE": "  " + IMAGE_ID + "  "})
    run("image_id_uppercase_hex", host={"ZEUS_WORKER_IMAGE": "sha256:" + "D" * 64})
    run("other_image_reported", docker=Docker(0, IMAGE_ID_OTHER + " " + SOURCE_REVISION),
        source="blobs-empty", mirrors="test_the_port_re_derives_the_image_from_settings_and_the_local_image")
    run("docker_nonzero_exit", docker=Docker(1, ""), source="blobs-empty",
        mirrors="test_the_port_re_derives_the_image_from_settings_and_the_local_image")
    run("docker_reports_no_revision_label", docker=Docker(0, IMAGE_ID), source="blobs-empty",
        mirrors="test_the_port_re_derives_the_image_from_settings_and_the_local_image")
    run("docker_reports_three_fields", docker=Docker(0, IMAGE_ID + " " + SOURCE_REVISION + " extra"))
    run("docker_reports_a_short_revision", docker=Docker(0, IMAGE_ID + " abc123"))
    run("docker_reports_an_uppercase_revision", docker=Docker(0, IMAGE_ID + " " + SOURCE_REVISION.upper()))
    run("docker_reports_no_value_label", docker=Docker(0, IMAGE_ID + " <no value>"))
    run("docker_stdout_empty", docker=Docker(0, ""))
    run("docker_raises", docker=Docker(0, "", raises=OSError("injected: docker unavailable")))
    run("docker_raises_a_timeout", docker=Docker(0, "", raises=TimeoutError("injected")))
    run("revision_not_a_hash", revision="main", source="blobs")
    run("revision_short", revision="a" * 39, source="blobs")
    run("revision_not_a_string", revision=None, source="blobs")
    run("revision_unknown_to_the_repository", revision="a" * 40)
    run("empty_source_is_unresolved", source="blobs-empty", mirrors="test_the_port_re_derives_the_image_from_settings_and_the_local_image")
    run("lane_without_repository_and_a_source_double", lane={}, source="blobs")
    out["docker_is_asked_before_the_revision_is_checked"] = {
        "note": "an invalid revision still runs the docker inspect first (the refusal order)",
        "calls": out["revision_not_a_hash"]["docker_calls"], "result": out["revision_not_a_hash"]["result"]}
    # `host=None` reads the host settings: a LABELLED settings file and environment.
    for label, dotenv, environment in (("settings_file", "ZEUS_WORKER_IMAGE=" + IMAGE_ID + "\n", {}),
                                       ("environment", None, {"HARNESS_WORKER_IMAGE": IMAGE_ID}),
                                       ("nothing", None, {})):
        double = Docker(0, answer)
        with env.settings(dotenv, **environment):
            out["host_none_labelled_" + label] = {
                "result": env.attempt(lambda: A.first_activation_facts(lane, None, revision, run=double,
                                                                          source=Blobs(dict(files)))),
                "docker_calls": env.n(double.calls)}
    return out


# ===== plan ==========================================================================================================
def plan_document(A, **overrides) -> dict:
    return {"schema": A.PLAN_SCHEMA, "plan_id": "delivery-plan-1", "release_id": "release-1",
            "revision": REVISION, "tree": TREE, "policy_hash": POLICY_HASH,
            "repository": "github:zeus-owner/zeus-harness", "required_checks": [CHECK],
            "target_id": "canary-service", "expected_descriptor": None,
            "target_descriptor": {"revision": REVISION, "worker_image": T.IMAGE, "profile_digest": T.PROFILE},
            "canary_check_id": A.CANARY_STARTUP, "ci_timeout_seconds": 300,
            "consumption_timeout_seconds": 120, **overrides}


def group_plan(env: Env) -> dict:
    A, out = env.api, {}
    body = json.dumps(plan_document(A), sort_keys=True).encode("utf-8")

    def at(name, data, **kwargs):
        root, revision = env.repository("plan-" + name, {PLAN_PATH: data}, **kwargs)
        return root, revision

    root, revision = at("pinned", body)
    loaded = env.attempt(lambda: A.load_plan(A.GitSource(str(root)), revision, PLAN_PATH))
    (root / PLAN_PATH).write_bytes(json.dumps(plan_document(A, plan_id="edited")).encode("utf-8"))
    edited = env.attempt(lambda: A.load_plan(A.GitSource(str(root)), revision, PLAN_PATH))
    out["pinned_to_the_exact_committed_bytes"] = {
        "mirrors": "tests/test_host_delivery_cli.py::test_the_plan_is_read_from_the_commit_and_pinned_to_its_exact_bytes",
        "revision": revision, "sha256_of_the_bytes": hashlib.sha256(body).hexdigest(), "bytes": len(body),
        "loaded": loaded, "after_a_working_tree_edit": edited,
        "pin_equals": loaded["returned"]["pin"] == {"revision": revision, "path": PLAN_PATH,
                                                     "sha256": hashlib.sha256(body).hexdigest()}}
    mirrored_refusals = {
        "not_json": (b"{not json", "tests/test_host_delivery_cli.py::test_a_malformed_or_oversized_plan_is_refused_"
                                   "by_code_without_its_bytes[not-json]"),
        "missing_fields": (json.dumps({"schema": A.PLAN_SCHEMA}).encode(),
                           "tests/test_host_delivery_cli.py::test_a_malformed_or_oversized_plan_is_refused_by_code_"
                           "without_its_bytes[missing-fields]"),
        "invalid_canary": (json.dumps(plan_document(A, canary_check_id="curl evil")).encode(),
                           "tests/test_host_delivery_cli.py::test_a_malformed_or_oversized_plan_is_refused_by_code_"
                           "without_its_bytes[invalid-canary]"),
        "oversized": (b"x" * (A.MAX_PLAN_BYTES + 1),
                      "tests/test_host_delivery_cli.py::test_a_malformed_or_oversized_plan_is_refused_by_code_"
                      "without_its_bytes[oversized]")}
    for label, (data, mirror) in mirrored_refusals.items():
        root, revision = at(label, data)
        case = env.rec(lambda r=root, v=revision: A.load_plan(A.GitSource(str(r)), v, PLAN_PATH), mirrors=mirror)
        case["message_carries_no_bytes"] = all(
            word not in json.dumps(case["result"]) for word in ("curl", "CANARY-must-never-be-emitted"))
        out["refused_" + label] = case
    root, revision = env.repository("plan-missing", {"README.md": "fixture\n"})
    out["refused_missing_path"] = env.rec(
        lambda: A.load_plan(A.GitSource(str(root)), revision, PLAN_PATH),
        mirrors="tests/test_host_delivery_cli.py::test_a_missing_path_or_revision_is_a_code_not_a_traceback")
    out["refused_unknown_revision"] = env.rec(
        lambda: A.load_plan(A.GitSource(str(root)), "b" * 40, PLAN_PATH),
        mirrors="tests/test_host_delivery_cli.py::test_a_missing_path_or_revision_is_a_code_not_a_traceback")
    root, revision = at("read", body)
    for label, (revision_arg, path) in {
            "branch_name_as_the_revision": ("main", PLAN_PATH), "abbreviated_revision": (revision[:12], PLAN_PATH),
            "path_traversal": (revision, "../outside.json"), "absolute_path": (revision, "/etc/hostname"),
            "empty_path": (revision, ""), "directory_path": (revision, "docs/zeus"),
            "backslash_path": (revision, "docs\\zeus\\operations\\delivery.json"),
            "empty_revision": ("", PLAN_PATH), "option_like_revision": ("--all", PLAN_PATH)}.items():
        out["read_" + label] = env.rec(lambda r=revision_arg, p=path: A.load_plan(A.GitSource(str(root)), r, p),
                                       revision=revision)
    root, revision = at("symlink", b"x", commit=False)
    (root / PLAN_PATH).unlink()
    os.symlink("../../../README.md", root / PLAN_PATH)
    (root / "README.md").write_text("target\n", encoding="utf-8")
    env.git(root, "add", "--all")
    env.git(root, "commit", "-q", "--no-verify", "-m", "symlink plan")
    out["refused_a_committed_symlink"] = env.rec(
        lambda: A.load_plan(A.GitSource(str(root)), env.git(root, "rev-parse", "HEAD"), PLAN_PATH))
    root, revision = env.repository("plan-submodule-like", {PLAN_PATH + "/inner.json": b"{}"})
    out["refused_a_directory_at_the_plan_path"] = env.rec(
        lambda: A.load_plan(A.GitSource(str(root)), revision, PLAN_PATH))
    padded = body + b" " * (A.MAX_PLAN_BYTES - len(body))
    root, revision = at("exact-bound", padded)
    out["exactly_at_the_size_bound_is_accepted"] = env.rec(
        lambda: A.load_plan(A.GitSource(str(root)), revision, PLAN_PATH), size=len(padded))
    for label, data in {
            "utf8_bom_is_accepted": b"\xef\xbb\xbf" + body, "not_utf8": b"\xff\xfe" + body, "empty_file": b"",
            "json_null": b"null", "json_list": b"[]", "json_string": b'"plan"', "trailing_garbage": body + b"x",
            "whitespace_padded": b"\n\n" + body + b"\n", "nul_bytes": body + b"\x00",
            "unknown_field": json.dumps({**plan_document(A), "command": "rm -rf"}).encode(),
            "missing_one_field": json.dumps({k: v for k, v in plan_document(A).items()
                                             if k != "tree"}).encode(),
            "other_schema": json.dumps(plan_document(A, schema="urn:other")).encode(),
            "duplicate_checks": json.dumps(plan_document(A, required_checks=[CHECK, CHECK])).encode(),
            "no_checks": json.dumps(plan_document(A, required_checks=[])).encode(),
            "bad_revision": json.dumps(plan_document(A, revision="xyz")).encode(),
            "bad_repository": json.dumps(plan_document(A, repository="gitlab:a/b")).encode(),
            "bad_timeout": json.dumps(plan_document(A, ci_timeout_seconds=5)).encode(),
            "bad_expected_descriptor": json.dumps(plan_document(A, expected_descriptor="abc")).encode(),
            "each_canary_fleet": json.dumps(plan_document(A, canary_check_id=A.CANARY_FLEET)).encode(),
            "each_canary_collect": json.dumps(plan_document(A, canary_check_id=A.CANARY_COLLECT)).encode(),
            "unicode_plan_id": json.dumps(plan_document(A, plan_id="plän")).encode()}.items():
        root, revision = at("shape-" + label, data)
        out["shape_" + label] = env.rec(lambda r=root, v=revision: A.load_plan(A.GitSource(str(r)), v, PLAN_PATH),
                                        size=len(data))
    return out


# ===== checks ==========================================================================================================
def group_checks(env: Env) -> dict:
    A, out = env.api, {}
    out["rollups_of_test_host_delivery_cli"] = {
        "mirrors": "tests/test_host_delivery_cli.py::test_check_rollup_states_are_normalized_without_inventing_a_pass",
        "none": env.attempt(lambda: A.normalize_checks(None)),
        "nameless": env.attempt(lambda: A.normalize_checks([{"no": "name"}])),
        "queued": env.attempt(lambda: A.normalize_checks([{"name": CHECK, "status": "QUEUED", "conclusion": None}])),
        "completed_skipped": env.attempt(lambda: A.normalize_checks(
            [{"name": CHECK, "status": "COMPLETED", "conclusion": "SKIPPED"}])),
        "context_error": env.attempt(lambda: A.normalize_checks([{"context": CHECK, "state": "ERROR"}]))}
    out["skipped_and_cancelled_are_never_a_pass"] = {
        "mirrors": "tests/test_host_delivery.py::test_skipped_and_cancelled_conclusions_are_never_a_pass",
        "failures": env.attempt(lambda: A.normalize_checks([
            {"name": CHECK, "status": "COMPLETED", "conclusion": c} for c in ("SKIPPED", "CANCELLED", "NEUTRAL",
                                                                              "FAILURE")])),
        "in_progress": env.attempt(lambda: A.normalize_checks(
            [{"name": CHECK, "status": "IN_PROGRESS", "conclusion": None}])),
        "context_success": env.attempt(lambda: A.normalize_checks([{"context": CHECK, "state": "SUCCESS"}]))}
    sources = {"generator": (lambda: (row for row in [{"name": "a", "state": "SUCCESS"}])),
               "tuple": lambda: ({"name": "a", "state": "SUCCESS"},), "empty_list": lambda: [], "empty_tuple": lambda: (),
               "falsy_zero": lambda: 0, "dict_iterates_its_keys": lambda: {"name": "a", "state": "SUCCESS"},
               "string_iterates_characters": lambda: "abc", "integer_raises": lambda: 7}
    for label, build in sources.items():
        out["rows_" + label] = env.attempt(lambda b=build: A.normalize_checks(b()))
    row = {"name": "n"}
    statuses = {"queued_no_conclusion": {"status": "QUEUED"}, "in_progress": {"status": "IN_PROGRESS"},
                "waiting": {"status": "WAITING"}, "pending_status": {"status": "PENDING"},
                "completed_no_conclusion": {"status": "COMPLETED"},
                "completed_success": {"status": "COMPLETED", "conclusion": "SUCCESS"},
                "completed_success_lowercase": {"status": "completed", "conclusion": "success"},
                "completed_failure": {"status": "COMPLETED", "conclusion": "FAILURE"},
                "completed_timed_out": {"status": "COMPLETED", "conclusion": "TIMED_OUT"},
                "completed_stale": {"status": "COMPLETED", "conclusion": "STALE"},
                "completed_action_required": {"status": "COMPLETED", "conclusion": "ACTION_REQUIRED"},
                "completed_startup_failure": {"status": "COMPLETED", "conclusion": "STARTUP_FAILURE"},
                "completed_unknown_future_conclusion": {"status": "COMPLETED", "conclusion": "SOMETHING_NEW"},
                "completed_blank_conclusion": {"status": "COMPLETED", "conclusion": ""},
                "queued_with_success_conclusion": {"status": "QUEUED", "conclusion": "SUCCESS"},
                "in_progress_with_failure_conclusion": {"status": "IN_PROGRESS", "conclusion": "FAILURE"},
                "blank_status_no_conclusion": {"status": ""}, "blank_status_blank_conclusion": {
                    "status": "", "conclusion": ""},
                "conclusion_only_success": {"conclusion": "SUCCESS"}, "conclusion_only_failure": {
                    "conclusion": "FAILURE"},
                "status_none_conclusion_none_uses_state": {"status": None, "conclusion": None, "state": "SUCCESS"},
                "status_present_beats_state": {"status": "QUEUED", "state": "SUCCESS"},
                "state_success": {"state": "SUCCESS"}, "state_success_lowercase": {"state": "success"},
                "state_pending": {"state": "PENDING"}, "state_expected": {"state": "EXPECTED"},
                "state_queued": {"state": "QUEUED"}, "state_in_progress": {"state": "IN_PROGRESS"},
                "state_error": {"state": "ERROR"}, "state_failure": {"state": "FAILURE"},
                "state_blank": {"state": ""}, "state_none": {"state": None}, "state_absent": {},
                "state_integer": {"state": 1}, "state_neutral": {"state": "NEUTRAL"}}
    out["states"] = {label: env.attempt(lambda extra=extra: A.normalize_checks([{**row, **extra}]))
                     for label, extra in statuses.items()}
    names = {"name_preferred_over_context": {"name": "n", "context": "c", "state": "SUCCESS"},
             "context_when_name_is_empty": {"name": "", "context": "c", "state": "SUCCESS"},
             "context_when_name_is_none": {"name": None, "context": "c", "state": "SUCCESS"},
             "context_only": {"context": "c", "state": "SUCCESS"},
             "name_not_a_string": {"name": 5, "state": "SUCCESS"}, "name_empty_no_context": {"name": ""},
             "name_non_empty_and_context_not_a_string": {"name": "n", "context": 5, "state": "SUCCESS"},
             "no_name_no_context": {"state": "SUCCESS"}, "whitespace_name_kept": {"name": " ", "state": "SUCCESS"},
             "extra_keys_ignored": {"name": "n", "state": "SUCCESS", "url": "http://x", "output": "log text"}}
    out["names"] = {label: env.attempt(lambda r=r: A.normalize_checks([r])) for label, r in names.items()}
    out["mixed_rows_keep_order_duplicates_and_skip_the_unusable"] = env.attempt(lambda: A.normalize_checks([
        {"name": "b", "state": "FAILURE"}, "not a row", None, {"name": "a", "status": "COMPLETED",
                                                                "conclusion": "SUCCESS"},
        {"name": "b", "state": "SUCCESS"}, [], {"context": "c", "state": "PENDING"}, 7, {"name": "d", "status": "QUEUED"}]))
    return out


# ===== ports =============================================================================================================
def port_view(env: Env, port, *attributes) -> dict:
    view = {"class": type(port).__name__, "bases": [base.__name__ for base in type(port).__mro__[1:-1]],
            "kind": getattr(port, "kind", "<none>")}
    for name in attributes:
        view[name] = getattr(port, name, "<absent>")
    return env.n(view)


def group_ports(env: Env) -> dict:
    A, out = env.api, {}
    fleet = object()
    ports = A.host_ports()
    out["default"] = {"kinds": list(ports), "kind_constants": {
        "process": A.KIND_PROCESS, "scheduled_task": A.KIND_SCHEDULED_TASK, "managed": A.KIND_MANAGED,
        "managed_systemd": A.KIND_MANAGED_SYSTEMD, "systemd": A.KIND_SYSTEMD},
        "ports": {kind: port_view(env, port, "python", "max_seconds", "lock_timeout", "timeout", "workload",
                                  "heartbeat_max_age", "stop_timeout", "control_dir", "control_reason")
                  for kind, port in ports.items()},
        "fleet": {kind: getattr(port, "fleet", "<absent>") for kind, port in ports.items()},
        "distinct_instances": len({id(port) for port in ports.values()}) == len(ports)}
    bound = A.host_ports(fleet=fleet)
    out["fleet_bound_to_the_managed_kinds_only"] = {
        kind: (getattr(port, "fleet", "<absent>") is fleet) if hasattr(port, "fleet") else "<absent>"
        for kind, port in bound.items()}
    out["kwargs_reach_the_process_target_only"] = {
        "ports": {kind: port_view(env, port, "python", "max_seconds", "lock_timeout")
                  for kind, port in A.host_ports(python=T.PY, max_seconds=7, lock_timeout=3.5).items()},
        "note": "the process kind receives python, max_seconds and lock_timeout; the managed kinds construct with none"}
    for label, control in {
            "none": None, "invalid": {"control_dir": None, "reason_code": "control_dir_invalid"},
            "valid": {"control_dir": "/fixture/aibox/runtime/control", "reason_code": None},
            "empty_mapping": {}}.items():
        out["systemd_control_" + label] = env.attempt(
            lambda c=control: port_view(env, A.host_ports(systemd_control=c)[A.KIND_SYSTEMD], "control_dir",
                                        "control_reason"))
    out["unknown_keyword_is_refused"] = env.rec(lambda: A.host_ports(bogus=1))
    out["positional_argument_is_refused"] = env.rec(lambda: A.host_ports(object()))
    # --- systemd_control_dir ---------------------------------------------------------------------------------
    aibox = env.directory("aibox")
    (aibox / "runtime" / "control").mkdir(parents=True)
    out["control_dir_valid"] = env.rec(lambda: A.systemd_control_dir({"ZEUS_AIBOX_ROOT": str(aibox)}))
    for label, settings in {
            "none": None, "empty_settings": {}, "other_key_only": {"ZEUS_HOST_DELIVERY_ENABLED": "1"},
            "harness_alias_is_not_read": {"HARNESS_AIBOX_ROOT": str(aibox)}, "none_value": {"ZEUS_AIBOX_ROOT": None},
            "integer_value": {"ZEUS_AIBOX_ROOT": 5}, "empty_string": {"ZEUS_AIBOX_ROOT": ""},
            "blank_string": {"ZEUS_AIBOX_ROOT": "   "}, "bytes_value": {"ZEUS_AIBOX_ROOT": b"/x"},
            "relative_path": {"ZEUS_AIBOX_ROOT": "aibox/relative"},
            "parent_component": {"ZEUS_AIBOX_ROOT": str(aibox) + "/../" + aibox.name},
            "missing_root": {"ZEUS_AIBOX_ROOT": str(env.base / "no-aibox")},
            "padded_value": {"ZEUS_AIBOX_ROOT": " " + str(aibox) + " "},
            "trailing_slash": {"ZEUS_AIBOX_ROOT": str(aibox) + "/"},
            "dot_component": {"ZEUS_AIBOX_ROOT": str(aibox) + "/./"}}.items():
        out["control_dir_" + label] = env.attempt(lambda s=settings: A.systemd_control_dir(s))
    no_runtime = env.directory("aibox-no-runtime")
    out["control_dir_runtime_missing"] = env.rec(lambda: A.systemd_control_dir({"ZEUS_AIBOX_ROOT": str(no_runtime)}))
    no_control = env.directory("aibox-no-control")
    (no_control / "runtime").mkdir()
    out["control_dir_control_missing"] = env.rec(lambda: A.systemd_control_dir({"ZEUS_AIBOX_ROOT": str(no_control)}))
    file_control = env.directory("aibox-file-control")
    (file_control / "runtime").mkdir()
    (file_control / "runtime" / "control").write_text("file", encoding="utf-8")
    out["control_dir_control_is_a_file"] = env.rec(lambda: A.systemd_control_dir({"ZEUS_AIBOX_ROOT": str(file_control)}))
    real = env.directory("aibox-real")
    (real / "runtime" / "control").mkdir(parents=True)
    for label, build in {
            "root_is_a_symlink": lambda: (os.symlink(real, env.base / "aibox-link-root"), env.base / "aibox-link-root")[1],
            "runtime_is_a_symlink": lambda: _link_runtime(env, real),
            "control_is_a_symlink": lambda: _link_control(env, real)}.items():
        path = build()
        out["control_dir_" + label] = env.rec(lambda p=path: A.systemd_control_dir({"ZEUS_AIBOX_ROOT": str(p)}))
    return out


def _link_runtime(env: Env, real: Path) -> Path:
    root = env.directory("aibox-link-runtime")
    os.symlink(real / "runtime", root / "runtime")
    return root


def _link_control(env: Env, real: Path) -> Path:
    root = env.directory("aibox-link-control")
    (root / "runtime").mkdir()
    os.symlink(real / "runtime" / "control", root / "runtime" / "control")
    return root


# ===== canaries ===========================================================================================================
def group_canaries(env: Env) -> dict:
    A, fx, out = env.api, env.fx, {}

    def world(name, *, kind=None):
        target = fx.target(name)
        if kind:
            target["kind"] = kind
        descriptor = fx.descriptor(target, name + "-descriptor", REVISION)
        return target, descriptor

    # --- startup_identity_canary --------------------------------------------------------------------------------
    target, descriptor = world("startup-process", kind=A.KIND_PROCESS)
    startup = {"instance_id": T.INSTANCE_A, "runtime_root": target["root"]}
    out["startup_receipt_missing"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.RECEIPT_FILE, "{not json")
    out["startup_receipt_malformed"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.RECEIPT_FILE, [fx.receipt_for(descriptor, 1)])
    out["startup_receipt_not_an_object"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    other = fx.descriptor(target, "startup-other", "two")
    planted = fx.plant(target, other, live=True)
    out["startup_receipt_of_another_descriptor"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup),
        mirrors="the task spec example 3: a receipt of another descriptor names canary_descriptor_mismatch")
    fx.write(target, A.RECEIPT_FILE, fx.receipt_for(descriptor, planted["pid"], T.INSTANCE_B))
    out["startup_receipt_of_another_instance"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.RECEIPT_FILE, fx.receipt_for(descriptor, planted["pid"], T.INSTANCE_A))
    fx.write(target, A.STATE_FILE, {"pid": planted["pid"], "started_at": T.STAMP})
    out["startup_matching_receipt_and_a_live_process_passes"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup),
        mirrors="the task spec example 3: the same canary over the matching receipt passes")
    out["startup_startup_none_against_a_receipt_with_an_instance_is_changed"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, None))
    receipt_without_instance = {k: v for k, v in fx.receipt_for(descriptor, planted["pid"]).items()
                                if k != "instance_id"}
    fx.write(target, A.RECEIPT_FILE, receipt_without_instance)
    out["startup_no_instance_on_either_side_passes"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, {}))
    out["startup_no_instance_on_the_receipt_only_changes"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.RECEIPT_FILE, fx.receipt_for(descriptor, planted["pid"], T.INSTANCE_A))
    dead = fx.dead_pid()
    fx.write(target, A.STATE_FILE, {"pid": dead})
    out["startup_process_kind_reads_the_pid_from_the_launch_record"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup), launch_pid="dead", receipt_pid="live")
    fx.write(target, A.RECEIPT_FILE, fx.receipt_for(descriptor, dead, T.INSTANCE_A))
    fx.write(target, A.STATE_FILE, {"pid": planted["pid"]})
    out["startup_process_kind_ignores_the_receipt_pid"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup), launch_pid="live", receipt_pid="dead")
    fx.state(target, A.STATE_FILE).unlink()
    out["startup_process_kind_without_a_launch_record"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup), receipt_pid="dead")
    fx.write(target, A.STATE_FILE, "{broken")
    out["startup_process_kind_with_a_malformed_launch_record"] = env.rec(
        lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.STATE_FILE, {"pid": True})
    out["startup_launch_pid_is_a_boolean"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.STATE_FILE, {"pid": str(planted["pid"])})
    out["startup_launch_pid_is_a_string"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.STATE_FILE, ["not", "a", "record"])
    out["startup_launch_record_is_a_list"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    fx.write(target, A.STATE_FILE, {"pid": 0})
    out["startup_launch_pid_zero"] = env.rec(lambda: A.startup_identity_canary(target, descriptor, startup))
    for kind in (A.KIND_SCHEDULED_TASK, A.KIND_MANAGED, A.KIND_MANAGED_SYSTEMD, A.KIND_SYSTEMD, None):
        other_target, other_descriptor = world("startup-" + str(kind), kind=kind)
        live = fx.plant(other_target, other_descriptor, live=True)
        fx.write(other_target, A.STATE_FILE, {"pid": dead})
        out["startup_kind_" + str(kind) + "_reads_the_receipt_pid"] = env.rec(
            lambda t=other_target, d=other_descriptor: A.startup_identity_canary(t, d, startup), launch_pid="dead",
            receipt_pid="live")
        dead_receipt = fx.plant(other_target, other_descriptor, live=False)
        fx.write(other_target, A.STATE_FILE, {"pid": live["pid"]})
        out["startup_kind_" + str(kind) + "_with_a_dead_receipt_pid"] = env.rec(
            lambda t=other_target, d=other_descriptor: A.startup_identity_canary(t, d, startup), launch_pid="live",
            receipt_pid="dead")
        del dead_receipt
    receipt_no_pid = fx.receipt_for(descriptor, 1)
    del receipt_no_pid["pid"]
    scheduled, scheduled_descriptor = world("startup-no-pid", kind=A.KIND_SCHEDULED_TASK)
    fx.write(scheduled, A.RECEIPT_FILE, {k: v for k, v in fx.receipt_for(scheduled_descriptor, 1).items() if k != "pid"})
    out["startup_receipt_without_a_pid"] = env.rec(lambda: A.startup_identity_canary(scheduled, scheduled_descriptor,
                                                                                     startup))
    big = env.fx.state(scheduled, A.RECEIPT_FILE)
    big.write_text(json.dumps(fx.receipt_for(scheduled_descriptor, 1)) + " " * A.MAX_STATE_BYTES, encoding="utf-8")
    out["startup_receipt_over_the_size_bound"] = env.rec(
        lambda: A.startup_identity_canary(scheduled, scheduled_descriptor, startup))
    # --- collect_monitor_canary -----------------------------------------------------------------------------------
    store = SerialStore(A)
    mtarget = {"target_id": "canary-service", "state_dir": str(env.base / "unused-state"), "root": str(env.base)}
    mdescriptor = {"schema": A.DESCRIPTOR_SCHEMA, "target_id": "canary-service", "root": mtarget["root"],
                   "revision": REVISION, "worker_image": T.IMAGE, "profile_digest": T.PROFILE, "predecessor": None}
    fx.digests[A.descriptor_digest(mdescriptor)] = "monitor-descriptor"
    mstartup = {"instance_id": INSTANCE_ONE, "revision": REVISION, "runtime_root": mtarget["root"]}

    def observed(**fields):
        with store.transaction() as tx:
            tx.put(A.BUCKET_DESCRIPTORS, "canary-service", {"id": "canary-service", "target_id": "canary-service",
                                                              **fields})
        return A.collect_monitor_canary(mtarget, mdescriptor, mstartup, store=store)

    mirror = "tests/test_host_delivery.py::test_the_collect_canary_refuses_a_missing_or_stale_monitor_source"
    out["collect_store_unavailable"] = env.rec(
        lambda: A.collect_monitor_canary(mtarget, mdescriptor, mstartup, store=None), mirrors=mirror)
    out["collect_store_omitted"] = env.rec(lambda: A.collect_monitor_canary(mtarget, mdescriptor, mstartup))
    out["collect_target_unobserved"] = env.rec(
        lambda: A.collect_monitor_canary(mtarget, mdescriptor, mstartup, store=store), mirrors=mirror)
    digest = A.descriptor_digest(mdescriptor)
    out["collect_descriptor_not_observed_stale_snapshot"] = env.rec(
        lambda: observed(descriptor_sha256="0" * 64, startup_observed=True, observed_instance_id=INSTANCE_ONE,
                         observed_revision=REVISION), mirrors=mirror)
    out["collect_descriptor_not_observed_no_startup"] = env.rec(
        lambda: observed(descriptor_sha256=digest, startup_observed=False, observed_instance_id=None,
                         observed_revision=None), mirrors=mirror)
    out["collect_another_instance"] = env.rec(
        lambda: observed(descriptor_sha256=digest, startup_observed=True, observed_instance_id=INSTANCE_TWO,
                         observed_revision=REVISION), mirrors=mirror)
    out["collect_another_revision"] = env.rec(
        lambda: observed(descriptor_sha256=digest, startup_observed=True, observed_instance_id=INSTANCE_ONE,
                         observed_revision="6" * 40), mirrors=mirror)
    out["collect_passes"] = env.rec(
        lambda: observed(descriptor_sha256=digest, startup_observed=True, observed_instance_id=INSTANCE_ONE,
                         observed_revision=REVISION), mirrors=mirror)
    with store.transaction() as tx:
        tx.put(A.BUCKET_DESCRIPTORS, "canary-service", {"id": "canary-service", "target_id": "canary-service",
                                                          "descriptor_sha256": digest, "startup_observed": True,
                                                          "observed_instance_id": INSTANCE_ONE,
                                                          "observed_revision": REVISION})
    out["collect_startup_none"] = env.rec(lambda: A.collect_monitor_canary(mtarget, mdescriptor, None, store=store))
    out["collect_startup_without_an_instance"] = env.rec(
        lambda: A.collect_monitor_canary(mtarget, mdescriptor, {"instance_id": ""}, store=store))
    out["collect_another_target_is_unobserved"] = env.rec(
        lambda: A.collect_monitor_canary({**mtarget, "target_id": "other-service"}, {**mdescriptor,
                                                                                    "target_id": "other-service"},
                                         mstartup, store=store))
    revisionless = {k: v for k, v in mdescriptor.items() if k != "revision"}
    fx.digests[A.descriptor_digest(revisionless)] = "monitor-descriptor-without-revision"
    with store.transaction() as tx:
        tx.put(A.BUCKET_DESCRIPTORS, "canary-service", {
            "id": "canary-service", "target_id": "canary-service", "descriptor_sha256": A.descriptor_digest(revisionless),
            "startup_observed": True, "observed_instance_id": INSTANCE_ONE, "observed_revision": REVISION})
    out["collect_descriptor_without_a_revision_raises_after_every_other_check"] = env.rec(
        lambda: A.collect_monitor_canary(mtarget, revisionless, mstartup, store=store))
    broken = BrokenStore(SerialStore(A))
    broken.failing = True
    out["collect_source_unavailable"] = env.rec(
        lambda: A.collect_monitor_canary(mtarget, mdescriptor, mstartup, store=broken))
    out["collect_the_projection_shows_the_observed_fields"] = {
        "target_row": env.n({k: v for k, v in next(
            row for row in A.host_delivery_facts(store)["targets"] if row["target_id"] == "canary-service").items()
                              if k in {"target_id", "descriptor_sha256", "startup_observed", "observed_instance_id",
                                       "observed_revision"}})}
    # --- owner_qualified_canary ---------------------------------------------------------------------------------------
    otarget, odescriptor = world("owner", kind=A.KIND_PROCESS)
    ostartup = {"instance_id": INSTANCE_ONE, "runtime_root": otarget["root"]}
    plan = {"plan_id": H1, "target_id": otarget["target_id"]}
    out["owner_no_plan"] = env.rec(lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup))
    out["owner_plan_not_a_dict"] = env.rec(lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=[H1]))
    out["owner_plan_without_an_id_raises"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan={}))
    out["owner_plan_id_is_not_a_token_raises"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan={"plan_id": "../x"}))
    out["owner_no_receipt_no_request"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan),
        mirrors="tests/test_host_delivery.py::test_an_owner_qualified_canary_needs_the_owners_own_receipt (missing)")

    def request_for(plan_arg, descriptor_arg, **changes):
        document = {"schema": A.CANARY_REQUEST_SCHEMA, "action_id": "a" * 64, "plan_id": plan_arg["plan_id"],
                    "plan_sha256": A.plan_digest(plan_arg), "target_id": otarget["target_id"],
                    "revision": descriptor_arg["revision"], "expected_descriptor": descriptor_arg.get("predecessor"),
                    "requested_at": "t"}
        return {**document, **changes}

    request_path = A.canary_request_file(H1)
    fx.write(otarget, request_path, request_for(plan, odescriptor))
    out["owner_matching_request_is_pending"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan),
        mirrors="tests/test_owner_canary_plan.py::test_the_actual_first_delivery_shape_with_no_predecessor_keeps_"
                "each_plans_own_wait (H1 pending)")
    plan_two = {"plan_id": H2, "target_id": otarget["target_id"]}
    out["owner_another_plans_request_never_answers"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan_two),
        mirrors="tests/test_owner_canary_plan.py::test_the_actual_first_delivery_shape_with_no_predecessor_keeps_"
                "each_plans_own_wait (H2 missing)")
    out["owner_request_for_another_revision_is_missing"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, {**odescriptor, "revision": "8" * 40}, ostartup, plan=plan),
        mirrors="tests/test_owner_canary_plan.py::test_the_actual_first_delivery_shape_with_no_predecessor_keeps_"
                "each_plans_own_wait (another revision)")
    for label, changes in {"another_schema": {"schema": "urn:other"}, "another_plan_digest": {"plan_sha256": "0" * 64},
                           "another_target": {"target_id": "other"}, "another_predecessor": {"expected_descriptor": "f" * 64},
                           "extra_field": {"extra": 1}, "another_plan_id": {"plan_id": H2}}.items():
        fx.write(otarget, request_path, request_for(plan, odescriptor, **changes))
        out["owner_request_" + label + "_is_missing"] = env.rec(
            lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan))
    fx.write(otarget, request_path, {k: v for k, v in request_for(plan, odescriptor).items() if k != "requested_at"})
    out["owner_request_missing_a_field_is_missing"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan))
    fx.write(otarget, request_path, "{broken")
    out["owner_request_malformed_is_missing"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan))
    fx.write(otarget, request_path, request_for(plan, odescriptor))
    # Receipts: the owner's own file for exactly this plan.
    receipt_path = A.canary_receipt_file(H1)
    digest = A.descriptor_digest(odescriptor)
    stale_mirror = "tests/test_host_delivery.py::test_an_owner_qualified_canary_needs_the_owners_own_receipt"
    fx.write(otarget, receipt_path, {"descriptor_sha256": "0" * 64, "passed": True})
    out["owner_receipt_for_another_descriptor_is_stale"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan), mirrors=stale_mirror)
    fx.write(otarget, receipt_path, {"descriptor_sha256": digest, "passed": True, "instance_id": INSTANCE_TWO,
                                     "evidence": "sha256:" + "a" * 64})
    out["owner_receipt_for_another_instance_is_stale"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan), mirrors=stale_mirror)
    fx.write(otarget, receipt_path, {"descriptor_sha256": digest, "passed": True, "instance_id": INSTANCE_ONE,
                                     "evidence": "sha256:" + "a" * 64})
    out["owner_receipt_passes"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan), mirrors=stale_mirror)
    out["owner_receipt_pass_needs_no_request"] = env.rec(
        lambda: (fx.state(otarget, request_path).unlink(), A.owner_qualified_canary(otarget, odescriptor, ostartup,
                                                                                    plan=plan))[1])
    for label, receipt in {
            "failed": {"descriptor_sha256": digest, "passed": False, "instance_id": INSTANCE_ONE, "evidence": "e"},
            "weak_null_instance_and_string_passed": {"descriptor_sha256": digest, "passed": "yes", "instance_id": None},
            "null_instance_passes": {"descriptor_sha256": digest, "passed": True, "instance_id": None, "evidence": "e"},
            "absent_instance_passes": {"descriptor_sha256": digest, "passed": True, "evidence": "e"},
            "passed_absent_fails": {"descriptor_sha256": digest, "instance_id": INSTANCE_ONE},
            "passed_zero_fails": {"descriptor_sha256": digest, "passed": 0, "instance_id": INSTANCE_ONE},
            "passed_one_passes": {"descriptor_sha256": digest, "passed": 1, "instance_id": INSTANCE_ONE},
            "passed_empty_string_fails": {"descriptor_sha256": digest, "passed": "", "instance_id": INSTANCE_ONE},
            "evidence_passes_through_unvalidated": {"descriptor_sha256": digest, "passed": True,
                                                    "instance_id": INSTANCE_ONE, "evidence": {"any": ["thing"]}},
            "descriptor_digest_absent": {"passed": True, "instance_id": INSTANCE_ONE},
            "failed_and_stale": {"descriptor_sha256": "0" * 64, "passed": False}}.items():
        fx.write(otarget, receipt_path, receipt)
        out["owner_receipt_" + label] = env.rec(
            lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan),
            mirrors=("tests/test_host_migration_evidence.py::test_incumbent_owner_canary_is_weaker_and_unchanged"
                     if label == "weak_null_instance_and_string_passed" else None))
    fx.write(otarget, receipt_path, {"descriptor_sha256": digest, "passed": True, "instance_id": INSTANCE_ONE})
    out["owner_startup_none_with_an_instance_on_the_receipt_is_stale"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, None, plan=plan))
    out["owner_another_plan_is_not_answered_by_this_plans_receipt"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan_two))
    fx.write(otarget, receipt_path, "{broken")
    fx.write(otarget, request_path, request_for(plan, odescriptor))
    out["owner_malformed_receipt_falls_back_to_the_request"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan))
    fx.state(otarget, receipt_path).unlink()
    fx.write(otarget, "owner-canary-receipt.json", {"descriptor_sha256": digest, "passed": True,
                                                    "instance_id": INSTANCE_ONE})
    fx.write(otarget, "owner-canary-request.json", request_for(plan, odescriptor))
    fx.state(otarget, request_path).unlink()
    out["owner_a_target_global_receipt_and_request_are_never_read"] = env.rec(
        lambda: A.owner_qualified_canary(otarget, odescriptor, ostartup, plan=plan),
        mirrors="tests/test_owner_canary_plan.py (plan-scoped files: a target-global file grants nothing)",
        state_files=sorted(p.name for p in Path(otarget["state_dir"]).iterdir()))
    # --- canary_checks -------------------------------------------------------------------------------------------------
    checks = A.canary_checks()
    out["canary_checks_map"] = {
        "ids": list(checks), "constants": {"startup": A.CANARY_STARTUP, "collect": A.CANARY_COLLECT,
                                           "fleet": A.CANARY_FLEET},
        "startup_is_the_function": checks[A.CANARY_STARTUP] is A.startup_identity_canary,
        "fleet_is_the_function": checks[A.CANARY_FLEET] is A.owner_qualified_canary,
        "collect_is_a_binding_lambda": checks[A.CANARY_COLLECT].__name__,
        "collect_is_not_the_function": checks[A.CANARY_COLLECT] is not A.collect_monitor_canary,
        "fresh_map_each_call": A.canary_checks() is not checks,
        "mirrors": "tests/test_owner_canary_plan.py (canary_checks() wired as the delivery's canaries); "
                   "tests/test_host_delivery_lane_routing.py (wired.canaries[CANARY_FLEET] is owner_qualified_canary)"}
    out["canary_checks_collect_without_a_store"] = env.rec(
        lambda: A.canary_checks()[A.CANARY_COLLECT](mtarget, mdescriptor, mstartup))
    out["canary_checks_collect_binds_the_store"] = env.rec(
        lambda: A.canary_checks(store)[A.CANARY_COLLECT](mtarget, mdescriptor, mstartup))
    out["canary_checks_collect_rejects_a_plan_keyword"] = env.rec(
        lambda: A.canary_checks(store)[A.CANARY_COLLECT](mtarget, mdescriptor, mstartup, plan=plan))
    fx.write(otarget, A.canary_receipt_file(H1), {"descriptor_sha256": digest, "passed": True,
                                                    "instance_id": INSTANCE_ONE, "evidence": "e"})
    out["canary_checks_fleet_takes_the_plan_keyword"] = env.rec(
        lambda: A.canary_checks()[A.CANARY_FLEET](otarget, odescriptor, ostartup, plan=plan))
    startup_target, startup_descriptor = target, descriptor
    fx.write(startup_target, A.STATE_FILE, {"pid": planted["pid"]})
    fx.write(startup_target, A.RECEIPT_FILE, fx.receipt_for(startup_descriptor, planted["pid"], T.INSTANCE_A))
    out["canary_checks_startup_through_the_map"] = env.rec(
        lambda: A.canary_checks()[A.CANARY_STARTUP](startup_target, startup_descriptor, startup))
    out["canary_checks_startup_rejects_a_plan_keyword"] = env.rec(
        lambda: A.canary_checks()[A.CANARY_STARTUP](startup_target, startup_descriptor, startup, plan=plan))
    return out


GROUPS = [("files", group_files), ("state_json", group_state_json), ("revisions", group_revisions),
          ("profile", group_profile), ("first_activation", group_first_activation), ("plan", group_plan),
          ("checks", group_checks), ("ports", group_ports), ("canaries", group_canaries)]


def run(api) -> dict:
    result, counts, live = {}, {}, 0
    with tempfile.TemporaryDirectory(prefix="s7-host-delivery-helpers-") as raw:
        env = Env(api, Path(raw).resolve())
        for name, group in GROUPS:
            result[name] = group(env)
            live += env.fx.sweep(name)
            counts[name] = len(result[name])
        result["live_children"] = live
        result["cases_per_group"] = counts
    return result
