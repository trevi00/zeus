"""Shared S8 scenario steps for three small research adapters, characterized BEFORE pilot 91 moves them (DESIGN-s8 §13 V18):

- `research.decision_feedback_registry`: M7 `adapters/decision_feedback.py` (`load_registry`) over a LABELLED fake `GitSource`
  (R-df1: the `GitBlobSource` Protocol replaces the `adapters.operation_cli.GitSource` annotation; the body is unchanged);
- `research.reverse_source`: M7 `adapters/reverse_source.py` (`observe_source`) over a LABELLED fake `run_process`
  (R-rs1: `run_process` is an injected keyword-only port);
- `research.source_verification`: M7 `adapters/source_verification.py` (`GitSourceVerifier`) over a LABELLED fake `subprocess.run` and a
  LABELLED fake `no_console_kwargs` (R-sv1: `console_kwargs` is an injected keyword-only port).

The reference side replaces the M7 module's `run_process`/`no_console_kwargs` (and the stdlib `subprocess.run` it calls); the target side
injects them. The recorded results must be identical. No real git process runs: every double is scripted from the scenario.

Cases mirror M7 `tests/test_decision_feedback_cli.py` (the registry cases), `tests/test_reverse_progress.py` (the two source cases) and
`tests/test_research_audits.py` (the verifier cases: inventory of a blob, a symlink, a raw tab/newline path and a submodule; the cross-
repository, commit, tree, manifest and inventory refusals) plus LABELLED additions for every `require` and branch of the three modules;
`M7_TESTS` names which group reaches which M7 test and which M7 case needs a real git process (unreachable).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`: `load_registry`, `observe`, `verifier`, `FileArtifacts`,
`SourceIdentity`, `InventoryEntry`, `canonical`, `ContractError` and the error classes. The scenario's file system use is the temp
directory of the artifacts (content-addressed, so no result holds a path); `ws.scrub` projects the root as `<root>`."""

from __future__ import annotations

import hashlib
import json
from subprocess import CompletedProcess

import s8_research_program as R

SHA = "a" * 40
TREE = "b" * 40
REPOSITORY = "https://github.com/fixture/repo"
REGISTRY_PATH = "docs/zeus/procedures.json"
CONSOLE_MARK = {"fake_console_kwarg": "console"}


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    return value


def outcome(fn) -> dict:
    """The returned value, or the refusal's type, fixed code and message."""
    try:
        return {"returned": plain(fn())}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "reason_code": getattr(exc, "reason_code", None), "message": str(exc)[:300]}


# =====================================================================================================================
# research.decision_feedback_registry
# =====================================================================================================================
class FakeGitSource:
    """LABELLED double of `operation_cli.GitSource` (the consumer shape `commit_exists`/`blob`): the commits and blobs are scripted."""

    def __init__(self, commits, blobs):
        self.commits, self.blobs, self.calls = set(commits), dict(blobs), []

    def commit_exists(self, revision):
        self.calls.append(["commit_exists", revision])
        return revision in self.commits

    def blob(self, revision, path):
        self.calls.append(["blob", revision, path])
        return self.blobs.get((revision, path), (None, b""))


def registry_entry(**overrides):
    row = {"id": "runbook-note", "source_kind": "council", "repository": "repo-identity", "allowed_paths": ["docs/a.md", "docs/b.md"],
           "acceptance_criteria_sha256": "c" * 64, "remediation": "existing_owner_review"}
    row.update(overrides)
    return row


def registry_doc(*entries):
    return {"schema": "urn:zeus:procedure-registry:1", "version": 1, "entries": list(entries) or [registry_entry()]}


def registry_bytes(document):
    return json.dumps(document, indent=2).encode("utf-8")


def load(api, source, revision, path):
    result = outcome(lambda: api.load_registry(source, revision, path))
    result["calls"] = source.calls
    return result


def d1_registry_cases(api, ws) -> dict:
    head, moved = SHA, "d" * 40
    good = registry_bytes(registry_doc())
    cases = {}

    def source(blob=("100644", good)):
        return FakeGitSource({head, moved}, {(head, REGISTRY_PATH): blob})

    cases["valid_registry"] = load(api, source(), head, REGISTRY_PATH)
    cases["valid_registry_sha_and_bytes"] = {"sha256": hashlib.sha256(good).hexdigest(), "bytes": len(good)}
    cases["valid_with_bom"] = load(api, source(("100644", b"\xef\xbb\xbf" + good)), head, REGISTRY_PATH)
    cases["valid_entries_sorted_and_two_entries"] = load(
        api, source(("100644", registry_bytes(registry_doc(registry_entry(id="z-last"), registry_entry(id="a-first"))))),
        head, REGISTRY_PATH)
    cases["history_stays_readable_other_commit"] = load(
        api, FakeGitSource({head, moved}, {(head, REGISTRY_PATH): ("100644", good),
                                            (moved, REGISTRY_PATH): ("100644", registry_bytes(registry_doc(registry_entry(id="edited"))))}),
        moved, REGISTRY_PATH)
    cases["commit_missing"] = load(api, FakeGitSource(set(), {}), "0" * 40, REGISTRY_PATH)
    cases["blob_missing_at_revision"] = load(api, source(), head, "docs/zeus/missing.json")
    cases["revision_invalid_head"] = load(api, source(), "HEAD", REGISTRY_PATH)
    cases["revision_invalid_short"] = load(api, source(), head[:39], REGISTRY_PATH)
    cases["revision_not_a_string"] = load(api, source(), None, REGISTRY_PATH)
    cases["path_invalid_parent"] = load(api, source(), head, "../escape.json")
    cases["path_invalid_nested_parent"] = load(api, source(), head, "docs/../../etc/passwd")
    cases["not_regular_executable"] = load(api, source(("100755", good)), head, REGISTRY_PATH)
    cases["not_regular_symlink"] = load(api, source(("120000", b"target")), head, REGISTRY_PATH)
    cases["not_regular_submodule"] = load(api, source(("160000", b"")), head, REGISTRY_PATH)
    cases["not_regular_directory"] = load(api, source(("040000", b"")), head, REGISTRY_PATH)
    cases["too_large_over_limit"] = load(api, source(("100644", b"[" + b"0," * api.MAX_REGISTRY_BYTES + b"0]")),
                                         head, REGISTRY_PATH)
    cases["exactly_at_limit_is_parsed"] = load(api, source(("100644", b" " * api.MAX_REGISTRY_BYTES)), head, REGISTRY_PATH)
    cases["invalid_json_canary_not_echoed"] = load(
        api, source(("100644", b"{not json CANARY-must-never-be-emitted")), head, REGISTRY_PATH)
    cases["invalid_utf8"] = load(api, source(("100644", b"\xff\xfe{}")), head, REGISTRY_PATH)
    cases["duplicate_keys"] = load(
        api, source(("100644", b'{"schema": "a", "schema": "b", "version": 1, "entries": []}')), head, REGISTRY_PATH)
    cases["duplicate_nested_keys"] = load(
        api, source(("100644", b'{"schema": "urn:zeus:procedure-registry:1", "version": 1, "entries": [{"id": "a", "id": "b"}]}')),
        head, REGISTRY_PATH)
    cases["not_an_object"] = load(api, source(("100644", b"[]")), head, REGISTRY_PATH)
    cases["empty_file"] = load(api, source(("100644", b"")), head, REGISTRY_PATH)
    cases["unknown_source_kind"] = load(
        api, source(("100644", registry_bytes(registry_doc(registry_entry(source_kind="operation"))))), head, REGISTRY_PATH)
    cases["unknown_schema"] = load(
        api, source(("100644", registry_bytes({**registry_doc(), "schema": "other"}))), head, REGISTRY_PATH)
    cases["unknown_version"] = load(
        api, source(("100644", registry_bytes({**registry_doc(), "version": 2}))), head, REGISTRY_PATH)
    cases["empty_entries"] = load(
        api, source(("100644", registry_bytes({**registry_doc(), "entries": []}))), head, REGISTRY_PATH)
    cases["missing_field"] = load(
        api, source(("100644", registry_bytes(registry_doc({k: v for k, v in registry_entry().items() if k != "remediation"})))),
        head, REGISTRY_PATH)
    cases["duplicate_entry_ids"] = load(
        api, source(("100644", registry_bytes(registry_doc(registry_entry(), registry_entry())))), head, REGISTRY_PATH)
    cases["commit_checked_before_blob"] = load(api, FakeGitSource(set(), {(head, REGISTRY_PATH): ("100644", good)}), head, REGISTRY_PATH)
    cases["invalid_pin_reads_nothing"] = load(api, source(), "HEAD", "../x")
    return {k: ws.scrub(v) for k, v in cases.items()}


# =====================================================================================================================
# research.reverse_source
# =====================================================================================================================
class FakeProcess:
    """LABELLED double of `commands.run_process(argv, timeout=...)`: `script(args)` answers by the git arguments after `-C <root>`;
    it returns stdout text, an int return code, or raises."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, argv, timeout=None):
        args = list(argv[argv.index("-C") + 2:])
        self.calls.append({"prefix": list(argv[:argv.index("-C")]), "args": args, "timeout": timeout, "root": argv[argv.index("-C") + 1]})
        answer = self.script(args, len(self.calls))
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, int):
            return CompletedProcess(argv, answer, "", "boom")
        return CompletedProcess(argv, 0, answer + "\n", "")


def observe(api, ws, name, script, path=None, repository_as_root=True):
    """`observe_source` over the fake: the result and the calls (the path of the case directory is `<root>/...`)."""
    case = ws.case(name)
    target = path(case) if path else case
    process = FakeProcess(lambda args, n: script(args, n, str(case)))
    result = outcome(lambda: api.observe(target, process))
    result["calls"] = process.calls
    return ws.scrub(result)


def standard(top=None, head=SHA, tree=TREE, status="", head_after=None, fail_on=None):
    """The scripted answers of a healthy observation; each knob changes one answer."""
    def script(args, n, case):
        key = args[-1]
        if fail_on is not None and fail_on(args, n):
            return 1
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            return case if top is None else top(case)
        if args[:2] == ["rev-parse", "HEAD"]:
            return head if n < 5 or head_after is None else head_after
        if key.endswith("^{tree}"):
            return tree
        if args[0] == "status":
            return status
        return ""
    return script


def r1_observations(api, ws) -> dict:
    cases = {}
    cases["clean"] = observe(api, ws, "clean", standard())
    cases["dirty"] = observe(api, ws, "dirty", standard(status="?? new.txt"))
    cases["dirty_tracked_change"] = observe(api, ws, "dirty-tracked", standard(status=" M file.py\n?? other"))
    cases["not_the_worktree_root"] = observe(api, ws, "not-root", standard(top=lambda case: case + "/.."))
    cases["not_the_worktree_root_elsewhere"] = observe(api, ws, "elsewhere", standard(top=lambda case: "/some/other/place"))
    cases["head_changed_during_observation"] = observe(api, ws, "moved", standard(head_after="e" * 40))
    cases["tree_is_resolved_from_captured_commit"] = observe(api, ws, "tree", standard(head="a" * 40, tree="b" * 40))
    cases["git_failure_is_unknown_toplevel"] = observe(api, ws, "fail-top", standard(fail_on=lambda args, n: n == 1))
    cases["git_failure_is_unknown_head"] = observe(api, ws, "fail-head", standard(fail_on=lambda args, n: args[:2] == ["rev-parse", "HEAD"] and n == 2))
    cases["git_failure_is_unknown_tree"] = observe(api, ws, "fail-tree", standard(fail_on=lambda args, n: args[-1].endswith("^{tree}")))
    cases["git_failure_is_unknown_status"] = observe(api, ws, "fail-status", standard(fail_on=lambda args, n: args[0] == "status"))
    cases["git_failure_is_unknown_second_head"] = observe(api, ws, "fail-after", standard(fail_on=lambda args, n: n == 5))
    cases["runner_raises_oserror"] = observe(api, ws, "oserror", lambda args, n, case: OSError("no git"))
    cases["runner_raises_timeout"] = observe(api, ws, "timeout", lambda args, n, case: TimeoutError("slow"))
    cases["missing_path_with_failing_git"] = observe(api, ws, "missing", lambda args, n, case: 128,
                                                      path=lambda case: case / "missing")
    cases["nested_directory_is_not_the_root"] = observe(api, ws, "nested", standard(top=lambda case: case), path=lambda case: case / "nested")
    cases["output_is_stripped"] = observe(api, ws, "strip", lambda args, n, case: (case + " ") if args[1] == "--show-toplevel" else (
        SHA if args[1] == "HEAD" else (TREE if args[-1].endswith("^{tree}") else "")))
    return cases


# =====================================================================================================================
# research.source_verification
# =====================================================================================================================
class FakeRepository:
    """LABELLED double of one source repository, answered by `FakeRun` (the stdlib `subprocess.run`): the origin, the commit and its tree, the
    tracked entries (mode, kind, oid, raw path bytes, blob bytes); `fail` names an argv prefix that returns a non-zero code."""

    def __init__(self, origin=REPOSITORY + ".git", commit=SHA, tree=TREE, entries=None, commit_type=b"commit\n", tree_of=None, fail=None):
        self.origin, self.commit, self.tree, self.commit_type, self.fail = origin, commit, tree, commit_type, fail
        self.tree_of = tree if tree_of is None else tree_of
        self.entries = entries if entries is not None else default_entries()


def default_entries():
    """A blob, a symlink, a raw tab/newline path (INV-GRAPH-001: Git paths need not be representable) and a submodule."""
    return [("100644", "blob", "1" * 40, b"normal", b"source"),
            ("120000", "blob", "2" * 40, b"link", b"normal"),
            ("100644", "blob", "3" * 40, b"space\tand\nnewline", b"\xff\x00\xfe"),
            ("160000", "commit", "4" * 40, b"vendor/sub", b"")]


class FakeRun:
    """LABELLED double of `subprocess.run` as `GitSourceVerifier.git` calls it: records argv and every keyword, answers one repository."""

    def __init__(self, repository):
        self.repository, self.calls = repository, []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "kwargs": {k: (str(v) if k != "timeout" else v) for k, v in kwargs.items()}})
        repo = self.repository
        args = list(argv[argv.index("-C") + 2:])
        if repo.fail is not None and args[:len(repo.fail)] == list(repo.fail):
            return CompletedProcess(argv, 128, b"", b"fatal: scripted failure \xff")
        if args == ["config", "--get", "remote.origin.url"]:
            return CompletedProcess(argv, 0, repo.origin.encode() + b"\n", b"")
        if args[:2] == ["cat-file", "-t"]:
            return CompletedProcess(argv, 0, repo.commit_type, b"")
        if args[0] == "rev-parse":
            return CompletedProcess(argv, 0, repo.tree_of.encode() + b"\n", b"")
        if args[:2] == ["ls-tree", "-r"]:
            body = b"".join(("%s %s %s\t" % (m, k, o)).encode() + p + b"\0" for m, k, o, p, _ in repo.entries) + b"\0"
            return CompletedProcess(argv, 0, body, b"")
        if args[:2] == ["cat-file", "blob"]:
            for m, k, o, p, data in repo.entries:
                if o == args[2]:
                    return CompletedProcess(argv, 0, data, b"")
        return CompletedProcess(argv, 1, b"", b"unscripted")


def identity(api, ws, artifacts, repository, manifest_entries=None, **overrides):
    """A `SourceIdentity` whose manifest artifact holds the (canonical) manifest of `manifest_entries` (None: the repository's own inventory)."""
    probe = FakeRun(repository)
    entries = manifest_entries if manifest_entries is not None else api.verifier(ws.root / "repo", artifacts, probe).inventory(
        api.SourceIdentity(REPOSITORY, SHA, TREE, "sha256:" + "0" * 64))
    manifest = {"version": 1, "repository": REPOSITORY, "commit": SHA, "tree": TREE, "entries": entries}
    manifest.update(overrides)
    ref = artifacts.put(api.canonical(manifest), "fixture")["ref"]
    return api.SourceIdentity(REPOSITORY, SHA, TREE, ref), entries


def verifier_case(api, ws, name, repository, action):
    """`action(verifier, artifacts)` over a fresh artifact store and a verifier bound to the fake; the argv and keyword calls recorded."""
    artifacts = api.FileArtifacts(str(ws.case(name) / "artifacts"))
    run = FakeRun(repository)
    verifier = api.verifier(ws.root / "repo", artifacts, run)
    result = outcome(lambda: action(verifier, artifacts))
    result["calls"] = len(run.calls)
    result["first_call"] = run.calls[0] if run.calls else None
    result["subcommands"] = [c["argv"][c["argv"].index("-C") + 2:][:2] for c in run.calls]
    return ws.scrub(result)


def s1_inventory(api, ws) -> dict:
    cases = {}
    source = api.SourceIdentity(REPOSITORY, SHA, TREE, "sha256:" + "0" * 64)
    cases["inventory_blob_symlink_raw_path_submodule"] = verifier_case(api, ws, "inv", FakeRepository(), lambda v, a: v.inventory(source))
    cases["inventory_empty_tree"] = verifier_case(api, ws, "empty", FakeRepository(entries=[]), lambda v, a: v.inventory(source))
    cases["inventory_origin_without_git_suffix"] = verifier_case(api, ws, "origin", FakeRepository(origin=REPOSITORY), lambda v, a: v.inventory(source))
    cases["cross_repository_refused"] = verifier_case(api, ws, "cross", FakeRepository(origin="https://github.com/other/repo.git"),
                                                      lambda v, a: v.inventory(source))
    cases["source_is_not_a_commit"] = verifier_case(api, ws, "nocommit", FakeRepository(commit_type=b"tree\n"), lambda v, a: v.inventory(source))
    cases["changed_tree_binding"] = verifier_case(api, ws, "tree", FakeRepository(tree_of="9" * 40), lambda v, a: v.inventory(source))
    cases["unsupported_tracked_object"] = verifier_case(api, ws, "tracked", FakeRepository(entries=[("100644", "tree", "5" * 40, b"dir", b"")]),
                                                        lambda v, a: v.inventory(source))
    cases["invalid_submodule_object"] = verifier_case(api, ws, "submodule", FakeRepository(entries=[("160000", "blob", "6" * 40, b"sub", b"")]),
                                                      lambda v, a: v.inventory(source))
    cases["unsupported_mode_is_refused_by_the_entry"] = verifier_case(
        api, ws, "mode", FakeRepository(entries=[("100666", "blob", "7" * 40, b"odd", b"x")]), lambda v, a: v.inventory(source))
    cases["invalid_path_is_refused_by_the_entry"] = verifier_case(
        api, ws, "path", FakeRepository(entries=[("100644", "blob", "8" * 40, b"/absolute", b"x")]), lambda v, a: v.inventory(source))
    cases["git_failure_reports_stderr"] = verifier_case(api, ws, "fail", FakeRepository(fail=("config",)), lambda v, a: v.inventory(source))
    cases["git_failure_on_blob"] = verifier_case(api, ws, "failblob", FakeRepository(fail=("cat-file", "blob")), lambda v, a: v.inventory(source))
    cases["invalid_source_identity_is_refused_first"] = verifier_case(
        api, ws, "badsource", FakeRepository(), lambda v, a: v.inventory(api.SourceIdentity("https://example.com/x", SHA, TREE, "sha256:" + "0" * 64)))
    cases["git_call_shape"] = verifier_case(api, ws, "shape", FakeRepository(), lambda v, a: v.git("rev-parse", "HEAD"))
    return cases


def s2_verify(api, ws) -> dict:
    cases = {}

    def run(name, repository, action):
        artifacts = api.FileArtifacts(str(ws.case(name) / "artifacts"))
        process = FakeRun(repository)
        v = api.verifier(ws.root / "repo", artifacts, process)
        result = outcome(lambda: action(v, artifacts, process))
        result["calls"] = len(process.calls)
        result["subcommands"] = [c["argv"][c["argv"].index("-C") + 2:][:2] for c in process.calls]
        return ws.scrub(result)

    def build(artifacts, api=api, **kwargs):
        return identity(api, ws, artifacts, FakeRepository(), **kwargs)

    def ok(v, artifacts, process):
        source, inventory = build(artifacts)
        return v.verify(source, [api.InventoryEntry(**e) for e in inventory])

    cases["verify_complete_inventory"] = run("ok", FakeRepository(), ok)

    def changed_blob(v, artifacts, process):
        source, inventory = build(artifacts)
        process.repository = FakeRepository(entries=[("100644", "blob", "1" * 40, b"normal", b"CHANGED"), *default_entries()[1:]])
        return v.verify(source, [api.InventoryEntry(**e) for e in inventory])
    cases["verify_changed_blob_bytes_same_oid"] = run("changed", FakeRepository(), changed_blob)

    def manifest_mismatch(v, artifacts, process):
        source, inventory = build(artifacts, commit="f" * 40)
        return v.verify(source, [api.InventoryEntry(**e) for e in inventory])
    cases["verify_manifest_source_mismatch"] = run("mismatch", FakeRepository(), manifest_mismatch)

    def incomplete(v, artifacts, process):
        source, inventory = build(artifacts)
        process.repository = FakeRepository(entries=default_entries()[:2])
        return v.verify(source, [api.InventoryEntry(**e) for e in inventory])
    cases["verify_incomplete_or_changed_inventory"] = run("incomplete", FakeRepository(), incomplete)

    def duplicate(v, artifacts, process):
        source, inventory = build(artifacts)
        rows = [api.InventoryEntry(**e) for e in inventory]
        return v.verify(source, rows + rows[:1])
    cases["verify_duplicate_inventory_path"] = run("duplicate", FakeRepository(), duplicate)

    def invalid_entry(v, artifacts, process):
        source, inventory = build(artifacts)
        rows = [api.InventoryEntry(**e) for e in inventory]
        rows[0] = api.InventoryEntry(rows[0].path, "100666", rows[0].object_id, rows[0].size, rows[0].artifact_ref)
        return v.verify(source, rows)
    cases["verify_invalid_entry_is_refused_before_any_git"] = run("entry", FakeRepository(), invalid_entry)

    def invalid_source(v, artifacts, process):
        return v.verify(api.SourceIdentity("https://example.com/x", SHA, TREE, "sha256:" + "0" * 64), [])
    cases["verify_invalid_source_is_refused_before_any_git"] = run("source", FakeRepository(), invalid_source)

    def missing_manifest(v, artifacts, process):
        return v.verify(api.SourceIdentity(REPOSITORY, SHA, TREE, "sha256:" + "e" * 64), [])
    cases["verify_missing_manifest_artifact"] = run("manifest", FakeRepository(), missing_manifest)

    def missing_envelope(v, artifacts, process):
        source, inventory = build(artifacts)
        rows = [api.InventoryEntry(**e) for e in inventory]
        blob = next(e for e in rows if e.artifact_ref)
        path = artifacts.root / (blob.artifact_ref.partition(":")[2] + ".txt")
        path.write_text("tampered", encoding="utf-8")
        return v.verify(source, rows)
    cases["verify_modified_original_envelope"] = run("envelope", FakeRepository(), missing_envelope)

    def git_failure(v, artifacts, process):
        source, inventory = build(artifacts)
        process.repository = FakeRepository(fail=("ls-tree",))
        return v.verify(source, [api.InventoryEntry(**e) for e in inventory])
    cases["verify_git_failure_during_inventory"] = run("gitfail", FakeRepository(), git_failure)

    def empty(v, artifacts, process):
        process.repository = FakeRepository(entries=[])
        source, inventory = identity(api, ws, artifacts, FakeRepository(entries=[]))
        return v.verify(source, [api.InventoryEntry(**e) for e in inventory])
    cases["verify_empty_inventory"] = run("emptyverify", FakeRepository(entries=[]), empty)
    return cases


def s3_console_kwargs(api, ws) -> dict:
    """The console kwargs seam: the verifier passes exactly the kwargs the (fake) helper answers, with the stdout/stderr pipes and the timeout."""
    artifacts = api.FileArtifacts(str(ws.case("console") / "artifacts"))
    run = FakeRun(FakeRepository())
    verifier = api.verifier(ws.root / "repo", artifacts, run)
    result = outcome(lambda: verifier.git("rev-parse", "HEAD"))
    result["call"] = run.calls
    result["console_marker"] = CONSOLE_MARK
    result["repository"] = verifier.repository
    result["artifacts_is_given"] = verifier.artifacts is artifacts
    return ws.scrub(result)


# ---- the three families ---------------------------------------------------------------------------------------------
M7_TESTS = {
    "decision_feedback": {
        "test_the_registry_is_read_at_the_pinned_commit_and_never_from_the_working_tree": {
            "d1_registry_cases": "valid_registry, history_stays_readable_other_commit, blob_missing_at_revision, commit_missing, revision_invalid_*, "
                                 "path_invalid_*; the working-tree edit needs a real repository (unreachable: the fake has no work tree)"},
        "test_a_non_regular_oversized_malformed_or_invalid_registry_is_refused": {
            "d1_registry_cases": "not_regular_*, invalid_json_canary_not_echoed, duplicate_keys, unknown_source_kind, too_large_over_limit"}},
    "reverse_source": {
        "test_tree_is_resolved_from_captured_commit": {"r1_observations": "tree_is_resolved_from_captured_commit"},
        "test_git_observation_detects_dirty_and_unknown_sources": {
            "r1_observations": "clean, dirty, missing_path_with_failing_git, nested_directory_is_not_the_root",
            "unreachable": "the real git process, the invalid fsmonitor helper that must not run (the argv prefix is pinned by every call)"}},
    "source_verification": {
        "test_git_inventory_preserves_raw_paths_binary_and_symlink": {"s1_inventory": "inventory_blob_symlink_raw_path_submodule"},
        "verifier cases of test_research_audits.py (cross repository, commit, tree, manifest, incomplete inventory)": {
            "s1_inventory, s2_verify": "cross_repository_refused, source_is_not_a_commit, changed_tree_binding, verify_*"},
        "test_piped_git_docker_and_probe_children_are_silent[source_verification] (tests/test_background_processes.py)": {
            "s3_console_kwargs": "the helper's kwargs reach subprocess.run unchanged; the real silent spawn is unreachable"}},
}


def decision_feedback(api) -> dict:
    ws = R.Workspace()
    try:
        cases = d1_registry_cases(api, ws)
        return {"d1_registry_cases": cases, "constants": {"MAX_REGISTRY_BYTES": api.MAX_REGISTRY_BYTES, "REGULAR_BLOB": api.REGULAR_BLOB},
                "m7_tests": M7_TESTS["decision_feedback"], "cases_per_group": {"d1_registry_cases": len(cases)}}
    finally:
        ws.close()


def reverse_source(api) -> dict:
    ws = R.Workspace()
    try:
        cases = r1_observations(api, ws)
        return {"r1_observations": cases, "m7_tests": M7_TESTS["reverse_source"], "cases_per_group": {"r1_observations": len(cases)}}
    finally:
        ws.close()


def source_verification(api) -> dict:
    ws = R.Workspace()
    try:
        groups = {"s1_inventory": s1_inventory(api, ws), "s2_verify": s2_verify(api, ws), "s3_console_kwargs": s3_console_kwargs(api, ws)}
        return {**groups, "m7_tests": M7_TESTS["source_verification"],
                "cases_per_group": {k: len(v) for k, v in groups.items()}}
    finally:
        ws.close()
