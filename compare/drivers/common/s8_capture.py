"""Shared S8 scenario steps (`research.capture`): `GitCapture.capture` of M7 `adapters/research_program.py`, the detached
capture commit and its create-only reference, characterized BEFORE step 3 moves it (DESIGN-s8 §1 V5, §2; TRACE-s8 §2
"Capture", §5 T-ENV-1; RESEARCH-S8 R1).

- **c01_success**: M7 `test_capture_commit_writes_only_the_snapshot_and_ref_and_leaves_the_checkout_alone` (the commit,
  its tree against base, the exact UTF-8 bytes, the `CAPTURE_AUTHOR` identity, the checkout and the temporary index);
  the size limit at its boundary; empty, CRLF, multibyte and unterminated bodies; a base named by a ref; a chain.
- **c02_refusals**: EVERY `GitCapture` refusal reached with labelled inputs, in the code's order: `capture_path_invalid`,
  `capture_ref_invalid` (each segment rule), `capture_too_large`, `base_revision_missing`, `capture_path_exists`,
  `capture_ref_exists`, `capture_read_tree_failed`, `capture_blob_failed`, `capture_blob_mismatch`,
  `capture_index_failed`, `capture_tree_failed`, `capture_commit_failed`, `capture_readback_mismatch` and
  `capture_ref_failed` (labelled faults at the `_git` seam, the blob hash and the readback; plus real git refusals of
  a reference name git itself rejects and a directory/file conflict), and the precedence of the checks.
- **c03_create_only**: the create-only CAS: two captures to one reference (the second is refused, the reference still
  names the first commit); a reference planted BETWEEN the probe and `update-ref` (a labelled wrapper of `_git`):
  `capture_ref_failed`, the planted reference unchanged; two references for the same content.
- **c04_checkout**: the checkout (HEAD, the branch, the staged content, `status`, the raw index file) is equal before
  and after a capture, with a dirty tree, staged changes, `core.autocrlf` and a `.gitattributes` eol rule.
- **c05_exact_bytes**: M7 `test_r3_capture_stores_exact_utf8_bytes_and_verifies_them_before_the_ref` (a simulated
  Windows text-mode pipe, a wrong blob id caught before any commit or reference).
- **c06_environment** (T-ENV-1, TRACE-s8 §5): a capture with `GIT_DIR` planted in the driver process environment, pointing
  at a SECOND labelled fixture repository, restored afterwards. The behavior is recorded as observed: where the
  reference landed, and the refusal or success. No mask, no judgement here.

Layer: harness (never shipped)

Every fixture repository is REAL, built under the pinned `GIT_*` identity, dates and empty configuration files; every
injected fault is labelled at its injection point. `api` is the `s8_research_program` API plus `run_process` (the
adapter module's own name, for the simulated pipe), `CAPTURE_AUTHOR`, `CAPTURE_ROOT` and `MAX_SNAPSHOT_BYTES`.
"""

from __future__ import annotations

import hashlib
import json
import os

import s8_research_program as R

PATH, REF = R.CAPTURE_PATH, R.CAPTURE_REF
BODY = json.dumps({"schema": "urn:zeus:research-capture:1", "note": R.CANARY}) + "\n"


class Fixture:
    """A fixture repository, its capture and the case directory."""

    def __init__(self, api, ws, name, **options):
        self.api, self.ws = api, ws
        self.base = ws.case(name)
        self.root, self.head = R.repository(self.base, **options)
        self.capture = api.GitCapture(self.root)

    def commit_file(self, relative, data: bytes, message):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.chmod(path, 0o644)
        R.git(self.root, "add", "--", relative)
        R.git(self.root, "commit", "-q", "-m", message)
        self.head = R.out(self.root, "rev-parse", "HEAD")
        return self.head


def attempt(fx, base, path, body, ref, capture=None):
    """One capture: its result or refusal, the effect on the refs and the loose objects, whether the checkout moved and
    whether the owned temporary directory is gone."""
    before, objects = R.checkout(fx.root), R.git_snapshot(fx.root)["loose_objects"]
    result = R.call(fx.ws, (capture or fx.capture).capture, base, path, body, ref)
    after = R.git_snapshot(fx.root)
    return {"result": result, "refs": after["refs"], "loose_objects_added": after["loose_objects"] - objects,
            "checkout_unchanged": R.unchanged(before, R.checkout(fx.root)),
            "temporary_directories_left": fx.ws.leftovers()}


def git_fault(capture, on, mode="fail", plant=None):
    """LABELLED fault seam: wrap the capture's own `_git` so the first call whose subcommand is `on` fails (`fail`:
    nonzero exit), returns a short answer (`short`) or runs `plant()` just before it (`plant`)."""
    real = capture._git
    state = {"calls": 0}

    def wrapper(*args, env=None, input_text=None):
        if args and args[0] == on:
            state["calls"] += 1
            if mode == "fail":
                return 1, ""
            if mode == "short":
                return 0, "abc"
            if mode == "plant":
                plant()
        return real(*args, env=env, input_text=input_text)
    wrapper.state = state
    return R.replaced(capture, "_git", wrapper)


# ---- success -------------------------------------------------------------------------------------------------------------
def c01_success(api, ws):
    results = {}
    fx = Fixture(api, ws, "c01")
    before = R.checkout(fx.root)
    first = attempt(fx, fx.head, PATH, BODY, REF)
    commit = first["result"]["value"]["revision"]
    results["m7_test"] = {
        **first, "head_is_base": R.out(fx.root, "rev-parse", "HEAD") == fx.head,
        "ref_names_revision": R.out(fx.root, "rev-parse", REF) == commit,
        "checkout_before": R.public(before), "checkout_after": R.public(R.checkout(fx.root)),
        "snapshot_equals_body": R.git(fx.root, "show", commit + ":" + PATH).stdout == BODY,
        "goal_bytes_equal_base": R.git(fx.root, "show", commit + ":docs/GOAL.md", text=False).stdout == R.GOAL,
        "changed_paths": R.out(fx.root, "diff", "--name-only", fx.head, commit).split(),
        "changed_status": R.out(fx.root, "diff-tree", "-r", "--name-status", fx.head, commit).split("\n"),
        "path_in_checkout": (fx.root / PATH).exists(),
        "author_constants": {k: v for k, v in sorted(api.CAPTURE_AUTHOR.items())},
        "sha256_is_body": first["result"]["value"]["sha256"] == hashlib.sha256(BODY.encode()).hexdigest()}
    # The size limit at its boundary.
    limit = api.MAX_SNAPSHOT_BYTES
    for label, body in (("at_limit", "a" * limit), ("one_over", "a" * (limit + 1)),
                        ("multibyte_at_limit", "한" * (limit // 3) + "a" * (limit % 3)),
                        ("multibyte_over", "한" * (limit // 3 + 1)),
                        ("empty", ""), ("crlf", "a\r\nb\r\n"), ("no_final_newline", "{}"), ("nul_free_binaryish", "\x01\x02")):
        fx = Fixture(api, ws, "c01-" + label)
        done = attempt(fx, fx.head, PATH, body, REF)
        if "value" in done["result"]:
            done["result"]["value"]["verified_bytes"] = (
                R.git(fx.root, "cat-file", "blob", done["result"]["value"]["blob"], text=False).stdout == body.encode("utf-8"))
        results["body_" + label] = done
    # A base named by a reference (the code accepts any revision string `cat-file` resolves).
    for label in ("HEAD", "main", "short_sha"):
        fx = Fixture(api, ws, "c01-base-" + label)
        base = {"HEAD": "HEAD", "main": "main", "short_sha": fx.head[:10]}[label]
        done = attempt(fx, base, PATH, BODY, REF)
        done["parents_are_head"] = (done["result"].get("value") is not None and
                                    R.out(fx.root, "log", "-1", "--format=%P", done["result"]["value"]["revision"]) == fx.head)
        results["base_by_" + label] = done
    # A chain: the second capture's base is the first capture commit.
    fx = Fixture(api, ws, "c01-chain")
    first = attempt(fx, fx.head, PATH, BODY, REF)
    second_path, second_ref = "docs/zeus/research-captures/rp-001/002.json", "refs/zeus/research/rp-001/002"
    second = attempt(fx, first["result"]["value"]["revision"], second_path, BODY + "\n", second_ref)
    results["chain"] = {"first": first, "second": second,
                        "second_parent_is_first": R.out(fx.root, "log", "-1", "--format=%P", second["result"]["value"]["revision"])
                        == first["result"]["value"]["revision"],
                        "second_changed_paths": R.out(fx.root, "diff", "--name-only", fx.head,
                                                      second["result"]["value"]["revision"]).split()}
    # A deeper path and a path with dots.
    for label, path in (("nested_path", "docs/zeus/research-captures/a/b/c/d.json"),
                        ("dotted_name", "docs/zeus/research-captures/rp.001/v1.2.json"),
                        ("hidden_dir", "docs/zeus/research-captures/.hidden/1.json")):
        fx = Fixture(api, ws, "c01-" + label)
        results[label] = attempt(fx, fx.head, path, BODY, "refs/zeus/research/x/" + label)
    return results


# ---- refusals --------------------------------------------------------------------------------------------------------------
def c02_refusals(api, ws):
    results = {}
    fx = Fixture(api, ws, "c02")
    root = api.CAPTURE_ROOT
    paths = {
        "outside_capture_root": "docs/GOAL.md", "not_json": root + "/rp-001/001.txt", "root_itself": root,
        "root_with_slash_only": root + "/", "bare_json_name": root + "/.json", "absolute": "/" + root + "/1.json",
        "traversal": root + "/../x.json", "backslash": root + "\\x.json", "dot_git_segment": root + "/.git/x.json",
        "dot_git_upper": root + "/.GIT/x.json", "empty_segment": root + "//x.json", "empty": "", "none": None,
        "too_long": root + "/" + "a" * 1100 + ".json", "space": root + "/a b.json", "wrong_case_root": "Docs/zeus/research-captures/1.json",
        "trailing_dot_segment": root + "/x./1.json", "prefix_lookalike": "docs/zeus/research-captures-x/1.json"}
    for label, path in paths.items():
        # a case that is unexpectedly accepted creates its own ref, so no case depends on another
        results["path_invalid." + label] = attempt(fx, fx.head, path, BODY, "refs/zeus/research/path/" + label)
    refs = {
        "heads": "refs/heads/main", "prefix_without_slash": "refs/zeus/research", "prefix_only": "refs/zeus/research/",
        "prefix_lookalike": "refs/zeus/researchx/1", "empty_segment": "refs/zeus/research//x", "dot_segment": "refs/zeus/research/./x",
        "dotdot_segment": "refs/zeus/research/../x", "lock_suffix": "refs/zeus/research/x.lock",
        "lock_in_middle": "refs/zeus/research/x.lock/y", "trailing_slash": "refs/zeus/research/x/", "empty": "",
        "tags": "refs/tags/t", "head": "HEAD", "zeus_other": "refs/zeus/other/1"}
    for label, ref in refs.items():
        results["ref_invalid." + label] = attempt(fx, fx.head, PATH, BODY, ref)
    results["too_large.one_over"] = attempt(fx, fx.head, PATH, "a" * (api.MAX_SNAPSHOT_BYTES + 1), REF)
    results["too_large.multibyte"] = attempt(fx, fx.head, PATH, "한" * (api.MAX_SNAPSHOT_BYTES // 3 + 1), REF)
    results["too_large.checked_before_any_git_call"] = attempt(fx, "0" * 40, PATH, "a" * (api.MAX_SNAPSHOT_BYTES + 1), REF)
    # Precedence: path, then ref, then size, then the base (no git call before the size check).
    results["order.path_before_ref"] = attempt(fx, fx.head, "docs/GOAL.md", BODY, "refs/heads/main")
    results["order.ref_before_size"] = attempt(fx, fx.head, PATH, "a" * (api.MAX_SNAPSHOT_BYTES + 1), "refs/heads/main")
    results["order.size_before_base"] = attempt(fx, "0" * 40, PATH, "a" * (api.MAX_SNAPSHOT_BYTES + 1), REF)
    tree, blob = R.out(fx.root, "rev-parse", "HEAD^{tree}"), R.out(fx.root, "rev-parse", "HEAD:docs/GOAL.md")
    for label, base in (("zeros", "0" * 40), ("not_a_revision", "no-such-revision"), ("tree_not_commit", tree),
                        ("blob_not_commit", blob), ("option_like", "--no-such-option"), ("empty", ""),
                        ("abbreviated_ambiguous", "0000")):
        results["base_revision_missing." + label] = attempt(fx, base, PATH, BODY, "refs/zeus/research/base/" + label)
    # `capture_path_exists`: the base already holds the path (a capture commit as the base, as M7's test).
    fx2 = Fixture(api, ws, "c02-exists")
    first = attempt(fx2, fx2.head, PATH, BODY, REF)
    results["path_exists.capture_commit_as_base"] = attempt(fx2, first["result"]["value"]["revision"], PATH, BODY,
                                                            "refs/zeus/research/rp-001/002")
    fx2.commit_file(PATH, b"{}\n", "the capture path is committed")
    results["path_exists.committed_at_base"] = attempt(fx2, fx2.head, PATH, BODY, "refs/zeus/research/rp-001/003")
    results["path_exists.checked_before_ref"] = attempt(fx2, fx2.head, PATH, BODY, REF)
    # The probe of `ls-tree` failing is treated as the path existing (any nonzero exit).
    fx3 = Fixture(api, ws, "c02-lstree")
    with git_fault(fx3.capture, "ls-tree", "fail"):  # LABELLED fault: `ls-tree` exits nonzero
        results["path_exists.ls_tree_fails"] = attempt(fx3, fx3.head, PATH, BODY, REF)
    with git_fault(fx3.capture, "cat-file", "fail"):  # LABELLED fault: the base probe exits nonzero
        results["base_revision_missing.cat_file_fails"] = attempt(fx3, fx3.head, PATH, BODY, REF)
    # `capture_ref_exists`: a ref that already exists (M7's stale ref), and a protected ref the grammar admits.
    fx4 = Fixture(api, ws, "c02-ref")
    R.git(fx4.root, "update-ref", REF, fx4.head)  # LABELLED: a ref planted before the capture
    results["ref_exists.planted"] = attempt(fx4, fx4.head, PATH, BODY, REF)
    with git_fault(fx4.capture, "show-ref", "short"):  # LABELLED fault: show-ref answers code 0 for any ref
        results["ref_exists.show_ref_says_zero"] = attempt(fx4, fx4.head, PATH, BODY, "refs/zeus/research/rp-001/009")
    # The step failures, one labelled fault each.
    faults = (("capture_read_tree_failed", "read-tree", "fail"), ("capture_blob_failed.hash_object_fails", "hash-object", "fail"),
              ("capture_blob_failed.hash_object_short", "hash-object", "short"),
              ("capture_index_failed", "update-index", "fail"), ("capture_tree_failed.write_tree_fails", "write-tree", "fail"),
              ("capture_tree_failed.write_tree_short", "write-tree", "short"),
              ("capture_commit_failed.commit_tree_fails", "commit-tree", "fail"),
              ("capture_commit_failed.commit_tree_short", "commit-tree", "short"))
    for label, command, mode in faults:
        fx5 = Fixture(api, ws, "c02-" + label.replace(".", "-"))
        with git_fault(fx5.capture, command, mode):  # LABELLED fault: this git step fails or answers short
            results[label] = attempt(fx5, fx5.head, PATH, BODY, REF)
    fx6 = Fixture(api, ws, "c02-blob")
    with R.replaced(fx6.capture, "_hash_blob",  # LABELLED fault: a wrong blob id from the hash step
                    lambda file, data, env: hashlib.sha1(b"other").hexdigest()):
        results["capture_blob_mismatch"] = attempt(fx6, fx6.head, PATH, BODY, REF)
    # The readback before the ref exists (a labelled GitSource whose blob differs from what was stored).
    for label, answer in (("wrong_mode", ("100755", None)), ("wrong_bytes", ("100644", b"other bytes\n")),
                          ("missing", (None, b""))):
        fx7 = Fixture(api, ws, "c02-readback-" + label)

        class Shifted:
            def __init__(self, repository, answer=answer, fx=fx7):
                self.repository, self.answer, self.fx = repository, answer, fx

            def blob(self, revision, path):  # LABELLED fault: the read-back disagrees with the stored commit
                mode, data = self.answer
                return mode, (data if data is not None else BODY.encode("utf-8"))
        with api.patch("GitSource", Shifted):
            results["capture_readback_mismatch." + label] = attempt(fx7, fx7.head, PATH, BODY, REF)
    # `capture_ref_failed`: refusals by git itself of reference names the M7 grammar admits (real git).
    for label, suffix in (("space", "a b"), ("double_dot", "a..b"), ("leading_dot", ".hidden"), ("tilde", "x~1"),
                          ("colon", "a:b"), ("trailing_dot", "x."), ("at_brace", "a@{b"), ("backslash", "a\\b"),
                          ("control_char", "a\x01b"), ("question", "a?b"), ("star", "a*b"), ("caret", "a^b"),
                          ("bracket", "a[b")):
        fx8 = Fixture(api, ws, "c02-gitref-" + label)  # a fresh repository: the objects written before the refusal show
        results["ref_failed.git_rejects_name." + label] = attempt(fx8, fx8.head, PATH, BODY, "refs/zeus/research/" + suffix)
    fx9 = Fixture(api, ws, "c02-df")
    ok = attempt(fx9, fx9.head, PATH, BODY, "refs/zeus/research/p1")
    results["ref_failed.directory_file.file_then_directory"] = {
        "first": ok, "second": attempt(fx9, fx9.head, PATH, BODY, "refs/zeus/research/p1/2")}
    fx10 = Fixture(api, ws, "c02-fd")
    ok = attempt(fx10, fx10.head, PATH, BODY, "refs/zeus/research/p1/2")
    results["ref_failed.directory_file.directory_then_file"] = {
        "first": ok, "second": attempt(fx10, fx10.head, PATH, BODY, "refs/zeus/research/p1")}
    fx11 = Fixture(api, ws, "c02-uf")
    with git_fault(fx11.capture, "update-ref", "fail"):  # LABELLED fault: update-ref exits nonzero
        results["ref_failed.update_ref_fails"] = attempt(fx11, fx11.head, PATH, BODY, REF)
    return results


# ---- the create-only CAS ---------------------------------------------------------------------------------------------------
def c03_create_only(api, ws):
    results = {}
    fx = Fixture(api, ws, "c03")
    first = attempt(fx, fx.head, PATH, BODY, REF)
    second = attempt(fx, fx.head, PATH, BODY + "\n", REF)
    results["second_capture_to_the_same_ref"] = {
        "first": first, "second": second,
        "ref_still_first": R.out(fx.root, "rev-parse", REF) == first["result"]["value"]["revision"]}
    fx = Fixture(api, ws, "c03-race")

    def plant():
        # LABELLED fault: the ref appears just before the `update-ref` invocation (another process won the race).
        R.git(fx.root, "update-ref", REF, fx.head)
    with git_fault(fx.capture, "update-ref", "plant", plant):
        race = attempt(fx, fx.head, PATH, BODY, REF)
    results["ref_planted_between_probe_and_update_ref"] = {
        **race, "planted_ref_unchanged": R.out(fx.root, "rev-parse", REF) == fx.head}
    # The same race with the planted ref pointing at the very commit the capture is about to create.
    fx = Fixture(api, ws, "c03-race3")
    probe = attempt(fx, fx.head, PATH, BODY, "refs/zeus/research/probe")
    created = probe["result"]["value"]["revision"]

    def plant3():
        R.git(fx.root, "update-ref", REF, created)  # LABELLED fault: a concurrent writer created the SAME commit's ref
    with git_fault(fx.capture, "update-ref", "plant", plant3):
        same = attempt(fx, fx.head, PATH, BODY, REF)
    results["ref_planted_at_the_same_commit"] = {**same, "planted_ref_unchanged": R.out(fx.root, "rev-parse", REF) == created}
    # Two references for the same content under the pinned dates: one commit.
    fx = Fixture(api, ws, "c03-two")
    one = attempt(fx, fx.head, PATH, BODY, "refs/zeus/research/a/1")
    two = attempt(fx, fx.head, PATH, BODY, "refs/zeus/research/b/1")
    results["same_content_two_refs"] = {"one": one, "two": two,
                                        "same_commit": one["result"]["value"]["revision"] == two["result"]["value"]["revision"]}
    # A ref that exists pointing at an unrelated commit is refused before any object is written.
    fx = Fixture(api, ws, "c03-early")
    R.git(fx.root, "update-ref", REF, fx.head)
    results["existing_ref_refused_before_objects"] = attempt(fx, fx.head, PATH, BODY, REF)
    return results


# ---- the checkout is never moved ---------------------------------------------------------------------------------------------
def c04_checkout(api, ws):
    results = {}
    fx = Fixture(api, ws, "c04")
    results["dirty_tree"] = {"before": R.public(R.checkout(fx.root)), **attempt(fx, fx.head, PATH, BODY, REF),
                             "after": R.public(R.checkout(fx.root))}
    fx = Fixture(api, ws, "c04-staged")
    R.git(fx.root, "add", "dirty.txt")
    (fx.root / "staged-new.txt").write_text("staged\n", encoding="utf-8")
    R.git(fx.root, "add", "staged-new.txt")
    done = attempt(fx, fx.head, PATH, BODY, REF)
    results["staged_changes_are_not_captured"] = {
        "before": "dirty.txt and staged-new.txt staged", **done,
        "capture_tree_files": done["refs"][REF]["files"] if REF in done["refs"] else None,
        "status_after": R.public(R.checkout(fx.root))["status"]}
    fx = Fixture(api, ws, "c04-autocrlf")
    R.git(fx.root, "config", "core.autocrlf", "true")
    results["core_autocrlf_true"] = attempt(fx, fx.head, PATH, BODY, REF)
    fx = Fixture(api, ws, "c04-attributes")
    fx.commit_file(".gitattributes", b"*.json text eol=crlf\n", "attributes")
    crlf = "{\n\"a\": 1\n}\n"
    done = attempt(fx, fx.head, PATH, crlf, REF)
    done["raw_blob_equals_body"] = (R.git(fx.root, "cat-file", "blob", done["result"]["value"]["blob"], text=False).stdout
                                    == crlf.encode("utf-8")) if "value" in done["result"] else None
    results["gitattributes_eol_rule_does_not_change_the_bytes"] = done
    fx = Fixture(api, ws, "c04-detached")
    R.git(fx.root, "checkout", "-q", "--detach")
    results["detached_head"] = {"before": R.public(R.checkout(fx.root)), **attempt(fx, fx.head, PATH, BODY, REF)}
    fx = Fixture(api, ws, "c04-branch")
    R.git(fx.root, "checkout", "-q", "-b", "other")
    results["other_branch_checked_out"] = attempt(fx, "main", PATH, BODY, REF)
    fx = Fixture(api, ws, "c04-hook")
    hooks = fx.root / ".git" / "hooks"
    marker = fx.base / "hook-ran"
    hook = hooks / "reference-transaction"
    hook.write_text("#!/bin/sh\necho ran >> %s\n" % marker, encoding="utf-8")
    os.chmod(hook, 0o755)
    done = attempt(fx, fx.head, PATH, BODY, REF)
    done["reference_transaction_hook_ran"] = marker.exists()
    results["reference_transaction_hook_observed"] = done
    return results


# ---- exact bytes (M7 r3) ---------------------------------------------------------------------------------------------------------
def c05_exact_bytes(api, ws):
    results = {}
    fx = Fixture(api, ws, "c05")
    R.git(fx.root, "config", "core.autocrlf", "true")  # the Windows default; a path hash-object would convert without --no-filters
    body = "{\n \"note\": \"한국어 텍스트\",\n \"lines\": \"a\\nb\"\n}\n"
    data = body.encode("utf-8")
    real_run = api.run_process

    def windows_pipe(argv, **kwargs):  # LABELLED fault: simulates the Windows text-mode stdin pipe (LF -> CRLF)
        if kwargs.get("input_text") is not None:
            kwargs["input_text"] = kwargs["input_text"].replace("\n", "\r\n")
        return real_run(argv, **kwargs)
    with api.patch("run_process", windows_pipe):
        done = attempt(fx, fx.head, PATH, body, REF)
    value = done["result"]["value"]
    raw = R.git(fx.root, "cat-file", "blob", value["blob"], text=False).stdout
    done.update(
        body_has_cr=b"\r" in data, bytes=len(data), more_bytes_than_characters=len(data) > len(body),
        raw_blob_equals_utf8=raw == data,
        reader_sees_the_same_bytes=api.GitSource(fx.root).blob(value["revision"], PATH) == ("100644", data),
        blob_id_is_the_content_address=hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == value["blob"],
        ref_names_revision=R.out(fx.root, "rev-parse", REF) == value["revision"],
        head_unmoved=R.out(fx.root, "rev-parse", "HEAD") == fx.head,
        dirty_file_kept=(fx.root / "dirty.txt").exists(), path_in_checkout=(fx.root / PATH).exists())
    results["windows_pipe_simulated_and_autocrlf"] = done
    with R.replaced(fx.capture, "_hash_blob",  # LABELLED fault: a wrong blob id caught before any commit or reference
                    lambda file, data, env: hashlib.sha1(b"other").hexdigest()):
        wrong = attempt(fx, fx.head, "docs/zeus/research-captures/rp-001/002.json", body, "refs/zeus/research/rp-001/002")
    wrong["only_the_verified_ref_exists"] = sorted(R.git_snapshot(fx.root)["refs"]) == [REF]
    results["wrong_blob_id_before_any_commit_or_ref"] = wrong
    return results


# ---- T-ENV-1 ---------------------------------------------------------------------------------------------------------------------
def c06_environment(api, ws):
    """T-ENV-1 (TRACE-s8 §5): `GIT_DIR` planted in the process environment, pointing at a SECOND labelled fixture
    repository B, restored afterwards. The `-C <repository>` of `GitCapture` and of the read-back reader do not
    override it; what M7 did is recorded here as observed, with no judgement."""
    results = {}
    for label, base_from in (("base_from_repository_a", "a"), ("base_from_repository_b", "b")):
        a = Fixture(api, ws, "c06a-" + label)
        b = Fixture(api, ws, "c06b-" + label, note=R.NOTE + b"second repository\n", message="second base")
        # LABELLED: B is another real repository with its OWN history: neither head is an object of the other.
        base = a.head if base_from == "a" else b.head
        before = {"a": R.public(R.checkout(a.root)), "b": R.public(R.checkout(b.root)),
                  "a_refs": R.git_snapshot(a.root), "b_refs": R.git_snapshot(b.root)}
        saved = os.environ.get("GIT_DIR")
        os.environ["GIT_DIR"] = str(b.root / ".git")  # LABELLED: the planted redirecting variable
        try:
            result = R.call(ws, a.capture.capture, base, PATH, BODY, REF)
        finally:
            if saved is None:
                os.environ.pop("GIT_DIR", None)
            else:
                os.environ["GIT_DIR"] = saved
        after_a, after_b = R.git_snapshot(a.root), R.git_snapshot(b.root)
        landed = ("repository_a_only" if REF in after_a["refs"] and REF not in after_b["refs"] else
                  "repository_b_only" if REF in after_b["refs"] and REF not in after_a["refs"] else
                  "both" if REF in after_a["refs"] else "neither")
        results[label] = {
            "capture_called_on": "repository A (GitCapture(A)) with GIT_DIR naming repository B",
            "base_is_head_of": base_from, "a_head_in_b": R.git(b.root, "cat-file", "-e", a.head + "^{commit}", check=False).returncode == 0,
            "b_head_in_a": R.git(a.root, "cat-file", "-e", b.head + "^{commit}", check=False).returncode == 0, "result": result, "where_the_ref_landed": landed,
            "refs_in_a": after_a["refs"], "refs_in_b": after_b["refs"],
            "loose_objects_a": [before["a_refs"]["loose_objects"], after_a["loose_objects"]],
            "loose_objects_b": [before["b_refs"]["loose_objects"], after_b["loose_objects"]],
            "head_a_unchanged": R.public(R.checkout(a.root)) == before["a"],
            "head_b_unchanged": R.public(R.checkout(b.root)) == before["b"],
            "environment_restored": os.environ.get("GIT_DIR") == saved,
            "temporary_directories_left": ws.leftovers()}
    return results


GROUPS = (("c01_success", c01_success), ("c02_refusals", c02_refusals), ("c03_create_only", c03_create_only),
          ("c04_checkout", c04_checkout), ("c05_exact_bytes", c05_exact_bytes), ("c06_environment", c06_environment))


def run(api) -> dict:
    ws = R.Workspace()
    try:
        result, counts = {}, {}
        for name, group in GROUPS:
            result[name] = ws.scrub(group(api, ws))
            counts[name] = len(result[name])
        result["cases_per_group"] = counts
        result["leftover_capture_directories"] = ws.leftovers()
        return result
    finally:
        ws.close()
