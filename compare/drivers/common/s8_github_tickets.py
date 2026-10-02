"""Shared S8 scenario steps (`intake.github_tickets`): M7 `adapters/github_tickets.py` (`GitHubTickets`: `_repo`, `_call`, `_read`, `_observe`, `sync`, `pull`
and the lease), characterized BEFORE the module moves into INTAKE (S8 batch B2, DESIGN-s8 §25 V30). The golden is placement-neutral: it observes SOURCE
behaviour only.

Each case is labelled with the M7 test it mirrors (`m7_test`), or `none`. M7's `tests/test_github_tickets.py` (24 tests, parametrized memory/postgres)
drives `GitHubTickets` through a monkeypatched `_call`, the ticket CLI and PostgreSQL; the golden is MODULE-level instead, and goes one level LOWER than the
tests: it scripts the `gh` PROCESS through a LABELLED fake `run_process` (the one spawn point), so the `_call` failure mapping, the argv and the 60 second
timeout are observed too. The fake models one remote issue (`create`, `edit`, `view`, `list`, `close`, `reopen`, the lost acknowledgement, the missing search
index, scripted failures and hooks); the body file is read at call time and recorded as its text. No real `gh`, no network, no spawn, no database.

The ticket rows are planted the way `Tickets.create` leaves them (`s8_ticket_lifecycle.World`); the lifecycle is the REAL `TicketLifecycle` over that
module's LABELLED authority and artifact store, so a closed or reopened ticket carries real events. Left out, by name, in `m7_tests`: the ticket CLI's
`sync`/`preview` options, the thread overlap and PostgreSQL; their module-level halves are cases.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. For every case the digest of the whole store before and after, the artifacts
added, the `gh` calls made and the counts of the module's own buckets are recorded. The clock and ids are the harness's.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import s8_ticket_lifecycle as lc

M7_TESTS = {
    "covered": ["test_sync_updates_same_issue_and_keeps_comments", "test_lost_ack_does_not_create_duplicate_even_before_search_indexing",
                "test_external_body_change_blocks_overwrite_and_pull_is_only_evidence",
                "test_lost_ack_followed_by_new_revision_recovers_exact_pending_projection (the create and edit halves)",
                "test_repeated_lost_ack_and_unreached_edit_retains_last_observed_body",
                "test_remote_manual_close_is_a_conflict_not_local_acceptance",
                "test_observations_read_back_in_the_order_they_were_made_even_within_one_clock_tick",
                "test_external_title_change_is_preserved_and_invalidates_synced_status",
                "test_successful_edit_response_requires_matching_remote_readback",
                "test_reconciliation_is_bound_to_observed_issue_and_current_revision", "test_legacy_link_uses_its_original_revision_title",
                "test_created_number_survives_readback_failure_without_search_index", "test_local_status_change_during_readback_cannot_be_synced",
                "test_expired_lease_after_remote_write_cannot_record_success", "test_identical_sync_observations_are_bounded_and_plain_revision_is_checked",
                "test_legacy_link_does_not_trust_an_arbitrary_observed_title", "test_create_ack_after_lease_expiry_is_retained_for_recovery",
                "test_dispatch_bounds_external_observations_without_deleting_evidence (the observations; Tickets.dispatch is the intake.tickets family)",
                "test_failed_reconcile_does_not_authorize_plain_retry_after_revision_change",
                "test_closed_issue_reconciliation_does_not_trust_unwritten_foreign_content",
                "test_closed_issue_readback_does_not_promote_new_external_content_to_trusted"],
    "unreachable": {"test_preview_is_pure_and_does_not_call_github": "the ticket CLI (S10)",
                    "test_parallel_sync_claim_cannot_publish_twice": "a thread overlap (the claim refusal is a case, sequentially)",
                    "every [postgres] parametrization": "PostgreSQL"}}

REPO = "fixture/zeus"
URL = "https://github.com/fixture/zeus/issues/7"


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


def shape(value):
    if isinstance(value, dict):
        return {str(k): shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [shape(v) for v in value]
    return value


class FakeGh:
    """LABELLED double of `run_process(["gh", ...], timeout=60)`: one remote issue and the verbs M7 uses. `fail` (verbs -> stderr) answers a non-zero exit
    status; `lose_ack` applies the write and then raises `TimeoutError`; `indexed` False makes `issue list` answer nothing; `hooks` run once at a verb
    BEFORE it is answered (an external edit, a clock jump); `garbage` replaces the stdout of a verb."""

    def __init__(self):
        self.issue, self.calls, self.fail, self.hooks, self.garbage = None, [], {}, {}, {}
        self.lose_ack, self.indexed, self.number = False, True, 7

    def run(self, argv, cwd=None, timeout=120, input_text=None, env=None):
        assert argv[0] == "gh"
        args = list(argv[1:])
        verb = " ".join(args[:2])
        body = None
        record_args = list(args)
        if "--body-file" in args:
            index = args.index("--body-file") + 1
            path = Path(args[index])
            body = path.read_text("utf-8")
            record_args[index] = "<body-file:" + path.name + ":" + str(path.parent.name.startswith("zeus-issue-")) + ">"
        self.calls.append({"verb": verb, "args": record_args, "timeout": timeout, "cwd": cwd, "input": input_text, "env": env, "body": body})
        hook = self.hooks.pop(verb, None)
        if hook is not None:
            hook()
        if verb in self.fail:
            return SimpleNamespace(returncode=1, stdout="", stderr=self.fail[verb], args=argv)
        out = self._answer(verb, args, body)
        if verb in self.garbage:
            out = self.garbage[verb]
        return SimpleNamespace(returncode=0, stdout=out, stderr="", args=argv)

    def _answer(self, verb, args, body):
        if verb == "issue list":
            fields = args[args.index("--json") + 1].split(",")
            rows = [{k: self.issue[k] for k in fields}] if self.issue and self.indexed else []
            return json.dumps(rows) + "\n"
        if verb == "issue view":
            return json.dumps(self.issue) + "\n"
        if verb in ("issue close", "issue reopen"):
            self.issue["state"] = "CLOSED" if args[1] == "close" else "OPEN"
            if self.lose_ack:
                raise TimeoutError("fixture response lost after state change")
            return self.issue["url"] + "\n"
        title = args[args.index("--title") + 1]
        if verb == "issue create":
            self.issue = {"number": self.number, "url": URL, "body": body, "title": title, "state": "OPEN", "comments": []}
        else:
            self.issue.update(body=body, title=title)
        if self.lose_ack:
            raise TimeoutError("fixture response lost after " + verb)
        return self.issue["url"] + "\n"

    def verbs(self):
        return [c["verb"] for c in self.calls]


OWN = ("ticket_github", "ticket_remote_creations", "ticket_remote_observations", "ticket_syncs")


class Bound:
    """The `GitHubTickets` of one world: every method call first binds that world's fake `gh` where the side needs it (the reference binds M7's
    module-level `run_process`; the target takes it by injection and ignores the bind), so worlds may interleave."""

    def __init__(self, api, runner, github):
        self._api, self._runner, self._github = api, runner, github

    def __getattr__(self, name):
        value = getattr(self._github, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            self._api.bind_runner(self._runner)
            return value(*args, **kwargs)
        return call


class GhWorld(lc.World):
    """The lifecycle's world (tickets, artifacts, authority, the REAL lifecycle) plus the fake `gh` and the `GitHubTickets` over it."""

    def __init__(self, api, **kwargs):
        super().__init__(api, links=False, **kwargs)
        self.gh = FakeGh()
        self.github = Bound(api, self.gh.run, api.new_github(self.tickets, self.artifacts, self.life, self.gh.run))

    def sync(self, **kwargs):
        return self.github.sync(lc.TICKET, REPO, **kwargs)

    def gh_snap(self):
        with self.store.transaction() as tx:
            records = tx.records()
        return {"store": sha(records), "artifacts": len(self.artifacts.bodies), "calls": len(self.gh.calls),
                "counts": {b: sum(r["bucket"] == b for r in records) for b in OWN}}

    def observe(self, call):
        self.api.bind_runner(self.gh.run)
        before = self.gh_snap()
        try:
            out = {"outcome": "returned", "value": shape(call())}
        except BaseException as exc:  # noqa: BLE001 - what propagates is part of the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc), "is_contract_error": isinstance(exc, self.api.ContractError),
                   "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__}
        after = self.gh_snap()
        out.update(store_before=before["store"], store_after=after["store"], store_unchanged=before["store"] == after["store"],
                   artifacts_added=after["artifacts"] - before["artifacts"], gh_verbs=self.gh.verbs()[before["calls"]:], counts_after=after["counts"])
        return out

    def rows(self):
        return {b: sorted(self.scan(b), key=lambda r: json.dumps(r, sort_keys=True)) for b in OWN}

    def closed(self):
        prepared, signatures = self.ready()
        self.life.close(prepared["packet_ref"], signatures)
        return prepared

    def external(self, **changes):
        return lambda: self.gh.issue.update(changes)


def a_surface(api):
    cases = {}
    cases["signatures"] = {n: str(inspect.signature(getattr(api.GitHubTickets, n))) for n in ("_repo", "_call", "_read", "_observe", "_claim", "_owned",
                                                                                                "_renew", "sync", "pull")}
    cases["__init__positional"] = [n for n, p in inspect.signature(api.GitHubTickets.__init__).parameters.items()
                                   if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    cases["static"] = {n: isinstance(inspect.getattr_static(api.GitHubTickets, n), staticmethod) for n in ("_repo", "_owned", "_call")}
    cases["methods"] = sorted(n for n, v in vars(api.GitHubTickets).items() if callable(v) or isinstance(v, staticmethod))
    w = GhWorld(api)
    cases["constructor"] = {"tickets": w.github.tickets is w.tickets, "store_is_the_tickets_store": w.github.store is w.tickets.store,
                            "artifacts": w.github.artifacts is w.artifacts, "lifecycle": w.github.lifecycle is w.life}
    bare = api.new_github(w.tickets, w.artifacts, None, w.gh.run)
    cases["lifecycle_defaults_to_none"] = bare.lifecycle is None
    return {"surface": cases}


def b_repo_call_read(api):
    cases, w = {}, GhWorld(api)
    for name, repository in {"owner_name": "a/b", "dots_dashes": "my-org.x/repo_1.2", "no_slash": "ab", "two_slashes": "a/b/c", "empty": "", "space": "a/b c",
                             "none": None, "number": 1, "trailing_newline": "a/b\n", "unicode": "ö/b"}.items():
        cases["repo_" + name] = w.observe(lambda repository=repository: w.github._repo(repository))
        cases["sync_repo_" + name] = w.observe(lambda repository=repository: w.github.sync(lc.TICKET, repository))
    # _call: the argv, the timeout, the stripped stdout and the failure mapping
    w.gh.issue = {"number": 7, "url": URL, "body": "b", "title": "t", "state": "OPEN", "comments": []}
    cases["call_ok"] = w.observe(lambda: w.github._call(["issue", "view", "7", "--repo", REPO]))
    cases["call_stdout_is_stripped"] = w.observe(lambda: w.github._call(["issue", "close", "7", "--repo", REPO]))
    w.gh.fail["issue view"] = "gh: HTTP 502 secret-looking-detail"
    cases["call_failure_is_a_runtime_error_without_the_detail"] = w.observe(lambda: w.github._call(["issue", "view", "7", "--repo", REPO]))
    w.gh.fail.clear()
    w.gh.lose_ack = True
    cases["call_runner_exception_propagates"] = w.observe(lambda: w.github._call(["issue", "close", "7", "--repo", REPO]))
    w.gh.lose_ack = False
    cases["gh_calls"] = w.gh.calls
    # _read
    r = GhWorld(api)
    base = {"number": 7, "url": URL, "body": "b", "title": "t", "state": "OPEN", "comments": []}
    r.gh.issue = deepcopy(base)
    cases["read_ok"] = r.observe(lambda: r.github._read(REPO, 7))
    for name, number in {"zero": 0, "negative": -1, "string": "7", "bool": True, "float": 7.0, "none": None}.items():
        cases["read_number_" + name] = r.observe(lambda number=number: r.github._read(REPO, number))
    edits = {"other_number": {"number": 8}, "state_merged": {"state": "MERGED"}, "state_lowercase": {"state": "open"}, "state_closed_ok": {"state": "CLOSED"},
             "other_url": {"url": "https://github.com/fixture/other/issues/7"}, "title_not_text": {"title": 1}, "body_not_text": {"body": None},
             "no_title": {"title": None}}
    for name, edit in edits.items():
        r.gh.issue = {**deepcopy(base), **edit}
        cases["read_remote_" + name] = r.observe(lambda: r.github._read(REPO, 7))
    r.gh.issue = deepcopy(base)
    r.gh.garbage["issue view"] = "not json"
    cases["read_not_json"] = r.observe(lambda: r.github._read(REPO, 7))
    r.gh.garbage["issue view"] = "[]"
    cases["read_not_an_object"] = r.observe(lambda: r.github._read(REPO, 7))
    r.gh.garbage.clear()
    r.gh.fail["issue view"] = "gh: not found"
    cases["read_gh_failure"] = r.observe(lambda: r.github._read(REPO, 7))
    cases["read_argv"] = r.gh.calls[0]
    return {"repo_call_read": cases}


def c_sync_create(api):
    """test_sync_updates_same_issue_and_keeps_comments, test_identical_sync_observations_are_bounded_and_plain_revision_is_checked."""
    cases, w = {}, GhWorld(api)
    w.tick()
    first = w.observe(lambda: w.sync())
    cases["sync_creates"] = first
    cases["sync_gh_calls"] = w.gh.calls
    cases["sync_rows"] = w.rows()
    cases["sync_remote_issue"] = w.gh.issue
    cases["sync_body_is_the_projection"] = w.gh.issue["body"].splitlines()[0] == "<!-- zeus-ticket:" + lc.TICKET + " -->"
    w.tick()
    cases["sync_repeat_is_a_noop_write"] = w.observe(lambda: w.sync())
    cases["sync_repeat_rows"] = w.rows()
    cases["sync_repeat_verbs"] = w.gh.verbs()
    cases["sync_repeat_view_only_observation_sequence"] = [r["sequence"] for r in sorted(w.scan("ticket_remote_observations"), key=lambda r: r["sequence"])]
    w.gh.issue["comments"].append({"body": "External reviewer question"})
    w.tick()
    w.revise()
    cases["sync_after_a_revision_edits"] = w.observe(lambda: w.sync(expected_revision=2))
    cases["sync_after_a_revision_rows"] = w.rows()
    cases["sync_comments_are_kept"] = w.gh.issue["comments"]
    cases["sync_edit_call"] = [c for c in w.gh.calls if c["verb"] == "issue edit"]
    cases["pull_observes_only"] = w.observe(lambda: w.github.pull(lc.TICKET, REPO))
    cases["pull_repeat_keeps_first_seen_and_sequence"] = w.observe(lambda: w.github.pull(lc.TICKET, REPO))
    cases["pull_unknown_link"] = w.observe(lambda: w.github.pull(lc.OTHER, REPO))
    cases["pull_bad_repo"] = w.observe(lambda: w.github.pull(lc.TICKET, "x"))
    cases["pull_other_repo_has_no_link"] = w.observe(lambda: w.github.pull(lc.TICKET, "fixture/other"))
    w.gh.issue["body"] = "an external body"
    cases["pull_remote_without_marker"] = w.observe(lambda: w.github.pull(lc.TICKET, REPO))
    cases["observations_order"] = [[r["sequence"], r["purpose"]] for r in sorted(w.scan("ticket_remote_observations"), key=lambda r: (r["sequence"], r["at"], r["id"]))]
    # the existing issue is found by its marker (no link, no creation receipt)
    f = GhWorld(api)
    f.gh.issue = {"number": 7, "url": URL, "title": f.tickets.get(lc.TICKET)["content"]["title"], "state": "OPEN", "comments": [],
                  "body": api_render(api, f)}
    cases["sync_discovers_the_marked_issue"] = f.observe(lambda: f.sync())
    cases["sync_discovered_verbs"] = f.gh.verbs()
    cases["sync_discovered_rows"] = f.rows()
    cases["sync_expected_revision_current_ok"] = f.observe(lambda: f.sync(expected_revision=1))
    return {"sync_create": cases}


def api_render(api, world):
    return api.render_ticket(world.tickets.get(lc.TICKET))


def d_refusals(api):
    cases = {}
    w = GhWorld(api)
    cases["unknown_ticket"] = w.observe(lambda: w.github.sync("ZEUS-unknown", REPO))
    cases["stale_expected_revision"] = w.observe(lambda: w.sync(expected_revision=2))
    cases["reconcile_needs_the_revision"] = w.observe(lambda: w.sync(reconcile_observation="x"))
    cases["reconcile_an_undiscovered_issue"] = w.observe(lambda: w.sync(reconcile_observation="x", expected_revision=1))
    cases["refusals_called_no_gh"] = w.gh.verbs()
    big = GhWorld(api)
    huge = {**lc.CONTENT, "evidence_refs": ["x" * 4000] * 16}
    with big.store.transaction() as tx:
        row = tx.get("tickets", lc.TICKET)
        tx.put("ticket_revisions", lc.TICKET + ":1", {**tx.get("ticket_revisions", lc.TICKET + ":1"), "content": huge, "content_hash": api.digest(huge)})
        tx.put("tickets", lc.TICKET, {**row, "content_hash": api.digest(huge)})
    cases["body_too_large"] = big.observe(lambda: big.sync())
    cases["body_too_large_called_no_gh"] = big.gh.verbs()
    run = GhWorld(api)
    run.put("ticket_syncs", "x", {"id": "x"})
    key = api.digest({"ticket_id": lc.TICKET, "repository": REPO})
    run.put("ticket_syncs", key, {"id": key, "owner": "someone", "status": "running", "lease_until": run.now(120)})
    cases["sync_already_running"] = run.observe(lambda: run.sync())
    run.put("ticket_syncs", key, {"id": key, "owner": "someone", "status": "running", "lease_until": run.now(-1)})
    cases["sync_over_an_expired_lease_takes_over"] = run.observe(lambda: run.sync())
    cases["takeover_rows"] = run.rows()
    cl = GhWorld(api)
    cl.closed()
    cl_no_life = api.new_github(cl.tickets, cl.artifacts, None, cl.gh.run)
    cases["closed_without_lifecycle"] = cl.observe(lambda: cl_no_life.sync(lc.TICKET, REPO))
    cases["closed_without_lifecycle_rows"] = cl.rows()
    two = GhWorld(api)
    two.put("ticket_remote_creations", "c1", {"id": "c1", "ticket_id": lc.TICKET, "repository": REPO, "number": 7})
    two.put("ticket_remote_creations", "c2", {"id": "c2", "ticket_id": lc.TICKET, "repository": REPO, "number": 8})
    cases["multiple_creation_receipts"] = two.observe(lambda: two.sync())
    cases["multiple_creation_receipts_rows"] = two.rows()
    many = GhWorld(api)
    marker = "<!-- zeus-ticket:" + lc.TICKET + " -->\n"
    many.gh.issue = {"number": 7, "url": URL, "title": "t", "state": "OPEN", "comments": [], "body": marker + "x"}
    many.gh.garbage["issue list"] = json.dumps([{"number": 7, "url": URL, "body": marker}, {"number": 8, "url": URL, "body": marker + "y"}])
    cases["multiple_remote_tickets"] = many.observe(lambda: many.sync())
    unrelated = GhWorld(api)
    unrelated.gh.garbage["issue list"] = json.dumps([{"number": 3, "url": URL, "body": "no marker"}, {"number": 4, "url": URL, "body": ""},
                                                     {"number": 5, "url": URL}])
    cases["unrelated_search_hits_are_ignored_and_the_issue_created"] = unrelated.observe(lambda: unrelated.sync())
    receipt = GhWorld(api)
    receipt.gh.garbage["issue create"] = "created!\n"
    cases["unrecognized_created_receipt"] = receipt.observe(lambda: receipt.sync())
    cases["unrecognized_created_receipt_rows"] = receipt.rows()
    other = GhWorld(api)
    other.gh.garbage["issue create"] = "https://github.com/other/zeus/issues/7\n"
    cases["created_receipt_for_another_repository"] = other.observe(lambda: other.sync())
    zero = GhWorld(api)
    zero.gh.garbage["issue create"] = "https://github.com/fixture/zeus/issues/0\n"
    cases["created_receipt_number_zero"] = zero.observe(lambda: zero.sync())
    # gh failure at each verb: the M7 refusal, no link row, the sync marked needs_attention
    for verb in ("issue list", "issue create", "issue view"):
        f = GhWorld(api)
        f.gh.fail[verb] = "gh: boom"
        cases["gh_failure_" + verb.replace(" ", "_")] = f.observe(lambda: f.sync())
        cases["gh_failure_" + verb.replace(" ", "_") + "_rows"] = {**f.rows(), "verbs": f.gh.verbs()}
    f = GhWorld(api)
    f.sync()
    f.revise()
    f.gh.fail["issue edit"] = "gh: boom"
    cases["gh_failure_issue_edit"] = f.observe(lambda: f.sync())
    cases["gh_failure_issue_edit_rows"] = f.rows()
    f.gh.fail.clear()
    cases["gh_failure_then_a_plain_retry"] = f.observe(lambda: f.sync())
    return {"refusals": cases}


def e_lost_ack(api):
    """test_lost_ack_does_not_create_duplicate_even_before_search_indexing, test_created_number_survives_readback_failure_without_search_index,
    test_create_ack_after_lease_expiry_is_retained_for_recovery, test_repeated_lost_ack_and_unreached_edit_retains_last_observed_body."""
    cases, w = {}, GhWorld(api)
    w.gh.lose_ack = True
    cases["create_ack_lost"] = w.observe(lambda: w.sync())
    cases["create_ack_lost_rows"] = w.rows()
    w.gh.indexed = False
    w.gh.lose_ack = False
    cases["retry_before_indexing_is_refused_as_uncertain"] = w.observe(lambda: w.sync())
    cases["retry_rows"] = w.rows()
    w.gh.indexed = True
    cases["retry_after_indexing_recovers_without_a_duplicate"] = w.observe(lambda: w.sync())
    cases["creates"] = w.gh.verbs().count("issue create")
    # the created number survives a readback failure without a search index
    r = GhWorld(api)
    r.gh.indexed = False
    r.gh.fail["issue view"] = "gh: boom"
    cases["readback_failure_after_create"] = r.observe(lambda: r.sync())
    cases["readback_failure_rows"] = r.rows()
    r.gh.fail.clear()
    cases["retry_uses_the_created_number"] = r.observe(lambda: r.sync())
    cases["retry_uses_the_created_number_verbs"] = r.gh.verbs()
    # a lost acknowledgement of an edit, repeated, then an unreached edit
    e = GhWorld(api)
    e.sync()
    e.revise()
    e.gh.lose_ack = True
    cases["edit_ack_lost"] = e.observe(lambda: e.sync())
    cases["edit_ack_lost_again"] = e.observe(lambda: e.sync())
    cases["edit_ack_lost_rows"] = e.rows()
    e.gh.lose_ack = False
    e.revise({**lc.CONTENT, "title": "A third revision"})
    cases["recovery_after_a_new_revision"] = e.observe(lambda: e.sync())
    cases["recovery_rows"] = e.rows()
    # the lease expires after the remote write: the create acknowledgement is retained for recovery
    x = GhWorld(api)
    x.gh.hooks["issue view"] = lambda: x.clock.advance(400)
    cases["lease_expired_after_the_write"] = x.observe(lambda: x.sync())
    cases["lease_expired_rows"] = x.rows()
    cases["lease_expired_remote"] = x.gh.issue is not None
    cases["lease_expired_then_retry"] = x.observe(lambda: x.sync())
    cases["lease_expired_then_retry_rows"] = x.rows()
    return {"lost_ack": cases}


def f_external(api):
    """test_external_body_change_blocks_overwrite_and_pull_is_only_evidence, test_external_title_change_is_preserved_and_invalidates_synced_status,
    test_reconciliation_is_bound_to_observed_issue_and_current_revision, test_failed_reconcile_does_not_authorize_plain_retry_after_revision_change,
    test_legacy_link_*, test_closed_issue_*, test_remote_manual_close_is_a_conflict_not_local_acceptance."""
    cases, w = {}, GhWorld(api)
    w.sync()
    w.gh.issue["body"] = "An external edit\n"
    cases["external_body_change_blocks_the_overwrite"] = w.observe(lambda: w.sync())
    cases["external_body_change_rows"] = w.rows()
    cases["external_body_unchanged_remote"] = w.gh.issue["body"]
    pulled = w.observe(lambda: w.github.pull(lc.TICKET, REPO))
    cases["pull_records_the_foreign_body"] = pulled
    observation = pulled["value"]["id"]
    w.revise()
    cases["reconcile_needs_the_current_revision"] = w.observe(lambda: w.sync(reconcile_observation=observation))
    cases["reconcile_with_a_stale_revision"] = w.observe(lambda: w.sync(reconcile_observation=observation, expected_revision=1))
    cases["reconcile_with_an_unknown_observation"] = w.observe(lambda: w.sync(reconcile_observation="nope", expected_revision=2))
    other = w.observe(lambda: w.github.pull(lc.TICKET, REPO))["value"]["id"]
    w.gh.issue["body"] = "A second external edit\n"
    cases["reconcile_after_the_remote_changed_again"] = w.observe(lambda: w.sync(reconcile_observation=other, expected_revision=2))
    fresh = w.github.pull(lc.TICKET, REPO)["id"]
    cases["reconcile_overwrites_the_observed_issue"] = w.observe(lambda: w.sync(reconcile_observation=fresh, expected_revision=2))
    cases["reconcile_rows"] = w.rows()
    cases["reconcile_remote_after"] = w.gh.issue["body"].splitlines()[0]
    cases["reconcile_failure_records_no_standing_grant"] = {"syncs": [{k: v for k, v in r.items() if k not in ("lease_until",)} for r in w.scan("ticket_syncs")]}
    # an observation of another issue
    foreign = GhWorld(api)
    foreign.sync()
    foreign.put("ticket_remote_observations", "foreign", {"id": "foreign", "ticket_id": lc.TICKET, "repository": REPO, "number": 99,
                                                          "evidence_ref": "sha256:" + "0" * 64, "sequence": 9, "at": foreign.now()})
    foreign.revise()
    cases["reconcile_observation_of_another_issue"] = foreign.observe(lambda: foreign.sync(reconcile_observation="foreign", expected_revision=2))
    # the title changed externally
    t = GhWorld(api)
    t.sync()
    t.gh.issue["title"] = "An external title"
    cases["external_title_change_blocks_the_overwrite"] = t.observe(lambda: t.sync())
    cases["external_title_rows"] = t.rows()
    # the remote was closed by hand: a conflict, not local acceptance
    m = GhWorld(api)
    m.sync()
    m.gh.issue["state"] = "CLOSED"
    cases["remote_manual_close_is_a_state_conflict"] = m.observe(lambda: m.sync())
    cases["remote_manual_close_rows"] = m.rows()
    cases["remote_manual_close_leaves_the_ticket_open"] = m.get("tickets", lc.TICKET)["status"]
    # a legacy link (no title_hash): the title of its original revision is trusted, an arbitrary observed one is not
    legacy = GhWorld(api)
    legacy.sync()
    link_key = api.digest({"ticket_id": lc.TICKET, "repository": REPO})
    link = legacy.get("ticket_github", link_key)
    legacy.put("ticket_github", link_key, {k: v for k, v in link.items() if k != "title_hash"})
    legacy.revise()
    cases["legacy_link_uses_the_original_revision_title"] = legacy.observe(lambda: legacy.sync())
    arbitrary = GhWorld(api)
    arbitrary.sync()
    link = arbitrary.get("ticket_github", link_key)
    arbitrary.put("ticket_github", link_key, {k: v for k, v in link.items() if k != "title_hash"})
    arbitrary.gh.issue["title"] = "An arbitrary title"
    state = arbitrary.get("ticket_syncs", link_key)
    arbitrary.put("ticket_syncs", link_key, {**state, "observed_title_hash": api.digest("An arbitrary title")})
    cases["legacy_link_does_not_trust_an_arbitrary_observed_title"] = arbitrary.observe(lambda: arbitrary.sync())
    # the readback does not match the projection after a successful edit
    rb = GhWorld(api)
    rb.sync()
    rb.revise()

    def mangle():
        rb.gh.issue["body"] = rb.gh.issue["body"] + "\nappended by a webhook"
    original = rb.gh._answer

    def answer(verb, args, body):
        out = original(verb, args, body)
        if verb == "issue edit":
            mangle()
        return out
    rb.gh._answer = answer
    cases["edit_readback_must_match_the_projection"] = rb.observe(lambda: rb.sync())
    cases["edit_readback_rows"] = rb.rows()
    # the local ticket changes during the readback
    c = GhWorld(api)
    c.gh.hooks["issue view"] = c.revise
    cases["local_change_before_the_write"] = c.observe(lambda: c.sync())
    s = GhWorld(api)
    s.sync()
    s.gh.hooks["issue view"] = s.revise
    cases["local_revision_during_the_readback_is_outdated"] = s.observe(lambda: s.sync())
    cases["local_revision_rows"] = s.rows()
    return {"external": cases}


def g_state(api):
    """The closed and reopened projections through the REAL lifecycle (the authority is the lifecycle driver's labelled one)."""
    cases, w = {}, GhWorld(api)
    w.sync()
    w.tick()
    w.closed()
    cases["closed_ticket_closes_the_issue"] = w.observe(lambda: w.sync())
    cases["close_call"] = [c for c in w.gh.calls if c["verb"] == "issue close"]
    cases["close_rows"] = w.rows()
    cases["close_remote_state"] = w.gh.issue["state"]
    cases["close_again_is_a_noop"] = w.observe(lambda: w.sync())
    cases["close_again_verbs"] = w.gh.verbs()[-3:]
    w.tick()
    w.life.reopen(lc.TICKET, 1, 1, "Recurrence")
    cases["reopened_ticket_reopens_the_issue"] = w.observe(lambda: w.sync())
    cases["reopen_call"] = [c for c in w.gh.calls if c["verb"] == "issue reopen"]
    cases["reopen_rows"] = w.rows()
    cases["reopen_remote_state"] = w.gh.issue["state"]
    cases["reopen_again_is_a_noop"] = w.observe(lambda: w.sync())
    # a lifecycle event that does not belong to this ticket or sequence is refused
    v = GhWorld(api)
    v.sync()
    v.closed()
    v.life.reopen(lc.TICKET, 1, 1, "Recurrence")
    row = v.get("tickets", lc.TICKET)
    v.put("tickets", lc.TICKET, {**row, "lifecycle_sequence": row["lifecycle_sequence"] + 1})
    cases["reopen_authority_with_a_wrong_sequence"] = v.observe(lambda: v.sync())
    cases["reopen_wrong_sequence_rows"] = v.rows()
    # a closed ticket whose remote was already closed by hand
    h = GhWorld(api)
    h.sync()
    h.gh.issue["state"] = "CLOSED"
    h.closed()
    cases["closed_ticket_with_a_remote_already_closed"] = h.observe(lambda: h.sync())
    cases["already_closed_verbs"] = h.gh.verbs()
    # the lease is renewed through the heartbeat while the authority verifies
    k = GhWorld(api)
    k.sync()
    k.closed()
    k.clock.advance(250)
    cases["heartbeat_keeps_the_lease_alive"] = k.observe(lambda: k.sync())
    return {"state": cases}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_repo_call_read, c_sync_create, d_refusals, e_lost_ack, f_external, g_state):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
