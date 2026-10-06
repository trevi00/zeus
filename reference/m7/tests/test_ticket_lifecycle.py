import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
import test_github_tickets
from test_tickets import content

from codex_harness.adapters.commands import run_process
from codex_harness.adapters.git import GitWorkspace
from codex_harness.adapters.ticket_authority import TicketAuthority
from codex_harness.application.ticket_lifecycle import TicketLifecycle
from codex_harness.application.tickets import TicketClosed, TicketSuperseded, ticket_binding
from codex_harness.domain.model import ContractError, canonical, digest, utcnow

github_setup = test_github_tickets.setup


@pytest.fixture
def lifecycle(github_setup, tmp_path):
    tickets, ticket, github, state = github_setup
    root = tmp_path / "trust-repository"
    root.mkdir()
    key = tmp_path / "test-only-key"
    assert run_process(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)]).returncode == 0
    principal = "test-only-not-a-human@zeus.invalid"
    policy = {"version": 1, "scope": "test-only-ticket-authority", "signers": [{"principal": principal,
        "role": "automation", "public_key": " ".join(key.with_suffix(".pub").read_text().split()[:2]),
        "valid_after": "2020-01-01T00:00:00+00:00", "valid_before": "2099-01-01T00:00:00+00:00"}],
        "required_signers": [principal], "required_human_signers": [], "revoked": [], "max_evidence_age_seconds": 86400}
    (root / ".zeus").mkdir()
    (root / ".zeus/ticket-trust.json").write_text(canonical(policy), encoding="utf-8")
    assert run_process(["git", "init", "-q", "-b", "main", str(root)]).returncode == 0
    git = GitWorkspace(str(root), str(tmp_path / "workspaces"))
    git._git("config", "core.hooksPath", str(tmp_path / "no-hooks"))
    git._git("add", ".")
    git._git("-c", "user.name=Zeus test", "-c", "user.email=test@zeus.invalid", "-c", "commit.gpgsign=false",
             "commit", "-qm", "Test-only trust anchor")
    commit = git._git("rev-parse", "HEAD")
    authority = TicketAuthority(git, github.artifacts, commit)
    life = TicketLifecycle(tickets, github.artifacts, authority)
    github.lifecycle = life
    def prepare():
        current = tickets.get(ticket["id"])
        bound = {k: current[k] for k in ("revision", "content_hash")}
        base = {**bound, "ticket_id": ticket["id"], "solution_commit": commit,
                "observed_at": utcnow(), "details": {"test_only": True, "human_acceptance": False}}
        environment = github.artifacts.put(canonical({**base, "kind": "ticket-environment-v1"}), "test-environment")["ref"]
        evidence = github.artifacts.put(canonical({**base, "kind": "ticket-criterion-evidence-v1",
            "criterion_index": 0, "outcome": "passed"}), "test-evidence")["ref"]
        return life.prepare(ticket["id"], {"solution_commit": commit, "environment_ref": environment,
            "reason": "Test-only acceptance", "criteria": [{"index": 0,
                "criterion_hash": digest(current["content"]["acceptance_criteria"][0]),
                "outcome": "passed", "evidence_refs": [evidence]}]})
    def sign(packet_ref, *, namespace="zeus-ticket-close-v1", signing_key=key):
        payload = tmp_path / (packet_ref[7:] + ".json")
        payload.write_text(github.artifacts.text(packet_ref, 1024 * 1024), encoding="utf-8", newline="\n")
        signature = payload.with_suffix(".json.sig")
        if signature.exists():
            signature.unlink()
        result = run_process(["ssh-keygen", "-Y", "sign", "-f", str(signing_key), "-n", namespace, str(payload)])
        assert result.returncode == 0, result.stderr
        ref = github.artifacts.put(signature.read_text("utf-8"), "test-only-signature")["ref"]
        return [{"principal": principal, "signature_ref": ref}]
    return life, ticket, github, state, prepare, sign, policy, key


def test_signed_close_reopen_and_new_cycle_invalidate_old_work(lifecycle):
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    tickets = life.tickets
    dispatched = tickets.dispatch(ticket["id"], 1, "repository")
    with tickets.store.transaction() as tx:
        bound = tx.get("outbox", dispatched["message_id"])["message"]["what"]["details"]["zeus_ticket"]
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    closed = life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    replay = life.close(packet["packet_ref"], [])
    assert replay["decision"] == closed["decision"] and replay["replayed"] is True
    assert replay["verification"] == "not_repeated" and closed["replayed"] is False
    assert tickets.get(ticket["id"])["github"][0]["status"] == "pending"
    assert state["issue"]["state"] == "OPEN"
    with tickets.store.transaction() as tx, pytest.raises(TicketClosed):
        ticket_binding(tx, {"zeus_ticket": bound})
    with pytest.raises(ContractError, match="Reopen"):
        tickets.update(ticket["id"], 1, content("New topic"), "Revise")
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert state["issue"]["state"] == "CLOSED"
    reopened = life.reopen(ticket["id"], 1, 1, "Recurrence")
    replay = life.reopen(ticket["id"], 1, 1, "Recurrence")
    assert replay["decision"] == reopened["decision"] and replay["replayed"] is True
    with pytest.raises(ContractError, match="Stale closure retry"):
        life.close(packet["packet_ref"], [])
    with tickets.store.transaction() as tx, pytest.raises(TicketSuperseded):
        ticket_binding(tx, {"zeus_ticket": bound})
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    new_dispatch = tickets.dispatch(ticket["id"], 1, "repository")
    assert new_dispatch["id"] != dispatched["id"]
    assert new_dispatch == tickets.dispatch(ticket["id"], 1, "repository")
    fresh = prepare()
    life.close(fresh["packet_ref"], sign(fresh["packet_ref"]))
    with pytest.raises(ContractError, match="Stale reopen retry"):
        life.reopen(ticket["id"], 1, 1, "Recurrence")
    history = tickets.get(ticket["id"])["lifecycle_history"]
    assert [r["kind"] for r in history] == ["closed", "reopened", "closed"]
    proof = life.artifacts.document(history[0]["proof_ref"])
    assert proof["attestation_scope"] == "configured_key_authority_only"
    assert proof["physical_human_presence_verified"] is False


@pytest.mark.parametrize("corruption", ["missing", "failed", "skipped", "unknown", "wrong-index", "expired", "old-evidence", "modified-signature"])
def test_closure_rejects_missing_failed_stale_or_unsigned_evidence(lifecycle, corruption):
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    prepared = prepare()
    packet = deepcopy(prepared["packet"])
    signatures = sign(prepared["packet_ref"])
    if corruption == "missing":
        packet["criteria"] = []
    elif corruption in {"failed", "skipped", "unknown"}:
        packet["criteria"][0]["outcome"] = corruption
    elif corruption == "wrong-index":
        packet["criteria"][0]["index"] = 1
    elif corruption == "expired":
        packet["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    elif corruption == "old-evidence":
        evidence = life.artifacts.document(packet["criteria"][0]["evidence_refs"][0])
        evidence["revision"] = 0
        packet["criteria"][0]["evidence_refs"] = [life.artifacts.put(canonical(evidence), "stale-test-evidence")["ref"]]
    else:
        packet["reason"] = "Changed after signing"
    ref = life.artifacts.put(canonical(packet), "test-modified-packet")["ref"]
    with pytest.raises(ContractError):
        life.close(ref, signatures)
    with life.store.transaction() as tx:
        assert tx.get("tickets", ticket["id"])["status"] == "open"
        assert not tx.scan("ticket_lifecycle_events") and not tx.scan("ticket_trust_anchors")


@pytest.mark.parametrize("case", ["missing", "wrong-principal", "duplicate", "wrong-namespace", "untrusted-key"])
def test_signature_authority_is_not_an_actor_string(lifecycle, tmp_path, case):
    life, _, _, _, prepare, sign, _, _ = lifecycle
    packet = prepare()
    signatures = sign(packet["packet_ref"])
    if case == "missing":
        signatures = []
    elif case == "wrong-principal":
        signatures[0]["principal"] = "human"
    elif case == "duplicate":
        signatures *= 2
    elif case == "wrong-namespace":
        signatures = sign(packet["packet_ref"], namespace="zeus-ticket-reopen-v1")
    else:
        key = tmp_path / "untrusted-key"
        assert run_process(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)]).returncode == 0
        signatures = sign(packet["packet_ref"], signing_key=key)
    with pytest.raises(ContractError):
        life.close(packet["packet_ref"], signatures)


def test_state_ack_loss_recovers_without_duplicate_decision(lifecycle):
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    decision = life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    state["lose_ack"] = True
    with pytest.raises(TimeoutError):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["issue"]["state"] == "CLOSED"
    state["lose_ack"] = False
    assert github.sync(ticket["id"], "fixture/zeus")["lifecycle_event"] == decision["decision"]["id"]
    assert state["state_writes"] == ["close"]
    with life.store.transaction() as tx:
        assert len(tx.scan("ticket_lifecycle_events")) == 1


def test_repo_commit_cannot_replace_anchored_signers(lifecycle, monkeypatch):
    life, _, _, _, prepare, sign, policy, _ = lifecycle
    packet = prepare()
    policy["required_human_signers"] = policy["required_signers"]
    root = life.authority.git.repository
    (root / ".zeus/ticket-trust.json").write_text(json.dumps(policy), encoding="utf-8")
    life.authority.git._git("add", ".")
    life.authority.git._git("-c", "user.name=Zeus test", "-c", "user.email=test@zeus.invalid",
                           "-c", "commit.gpgsign=false", "commit", "-qm", "Untrusted policy change")
    assert life.authority.policy()["policy_hash"] == packet["packet"]["policy_hash"]
    life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    monkeypatch.setattr(life.authority, "trust_commit", None)
    with pytest.raises(ContractError, match="Out-of-band"):
        life.authority.policy()


def test_concurrent_same_packet_commits_one_decision(lifecycle, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    life, _, _, _, prepare, sign, _, _ = lifecycle
    packet = prepare()
    signatures = sign(packet["packet_ref"])
    verify, barrier = life.authority.verify, Barrier(2)
    def both_verified(*args, **kwargs):
        result = verify(*args, **kwargs)
        barrier.wait(timeout=30)
        return result
    monkeypatch.setattr(life.authority, "verify", both_verified)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: life.close(packet["packet_ref"], signatures), range(2)))
    assert results[0]["decision"] == results[1]["decision"]
    assert sum(r["replayed"] for r in results) == 1
    with life.store.transaction() as tx:
        assert len(tx.scan("ticket_lifecycle_events")) == len(tx.scan("ticket_closure_sequences")) == 1


def test_two_valid_packets_cannot_consume_same_sequence(lifecycle):
    life, _, _, _, prepare, sign, _, _ = lifecycle
    first, second = prepare(), prepare()
    signature1, signature2 = sign(first["packet_ref"]), sign(second["packet_ref"])
    life.close(first["packet_ref"], signature1)
    with pytest.raises(ContractError, match="Stale closure"):
        life.close(second["packet_ref"], signature2)
    with life.store.transaction() as tx:
        assert len(tx.scan("ticket_lifecycle_events")) == 1


def test_closure_database_failure_rolls_back_ticket_event_anchor_and_pending_links(lifecycle, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    life, ticket, github, _, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    signatures = sign(packet["packet_ref"])
    transaction = life.store.transaction
    @contextmanager
    def failing_transaction():
        with transaction() as tx:
            def put(bucket, key, row):
                if bucket == "ticket_closures":
                    raise RuntimeError("Injected PG boundary failure before commit")
                return tx.put(bucket, key, row)
            yield SimpleNamespace(get=tx.get, scan=tx.scan, put=put)
    monkeypatch.setattr(life.store, "transaction", failing_transaction)
    with pytest.raises(RuntimeError, match="before commit"):
        life.close(packet["packet_ref"], signatures)
    monkeypatch.setattr(life.store, "transaction", transaction)
    with life.store.transaction() as tx:
        assert tx.get("tickets", ticket["id"])["status"] == "open"
        assert not tx.scan("ticket_lifecycle_events") and not tx.scan("ticket_trust_anchors")
        assert tx.scan("ticket_github")[0]["status"] == "synced"
    assert life.close(packet["packet_ref"], signatures)["decision"]["kind"] == "closed"


def test_ticket_edit_during_signature_verification_prevents_closure(lifecycle, monkeypatch):
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    packet = prepare()
    verify = life.authority.verify
    def edit_after_verifying(*args, **kwargs):
        result = verify(*args, **kwargs)
        life.tickets.update(ticket["id"], 1, content("Revised criteria"), "Changed during verification")
        return result
    monkeypatch.setattr(life.authority, "verify", edit_after_verifying)
    with pytest.raises(ContractError, match="Stale closure"):
        life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    with life.store.transaction() as tx:
        assert tx.get("tickets", ticket["id"])["revision"] == 2
        assert not tx.scan("ticket_lifecycle_events")


@pytest.mark.parametrize("race", ["reopen", "expired-lease"])
def test_late_remote_close_cannot_complete_newer_local_cycle(lifecycle, monkeypatch, race):
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    link = github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    call = github._call
    def late_close(args):
        result = call(args)
        if args[:2] == ["issue", "close"]:
            if race == "reopen":
                life.reopen(ticket["id"], 1, 1, "Recurrence while remote close was in flight")
            else:
                with life.store.transaction() as tx:
                    claim = tx.get("ticket_syncs", link["id"])
                    tx.put("ticket_syncs", link["id"], {**claim, "lease_until": "2000-01-01T00:00:00+00:00"})
        return result
    monkeypatch.setattr(github, "_call", late_close)
    if race == "reopen":
        assert github.sync(ticket["id"], "fixture/zeus")["status"] == "outdated"
    else:
        with pytest.raises(ContractError, match="Stale ticket sync"):
            github.sync(ticket["id"], "fixture/zeus")
    assert state["issue"]["state"] == "CLOSED"
    monkeypatch.setattr(github, "_call", call)
    result = github.sync(ticket["id"], "fixture/zeus")
    assert result["status"] == "synced"
    assert state["issue"]["state"] == ("OPEN" if race == "reopen" else "CLOSED")


@pytest.mark.parametrize("defect", ["automation-human", "duplicate-key", "empty-required", "revoked", "expired", "future", "duplicate-json"])
def test_invalid_or_untrusted_policy_cannot_authorize_close(lifecycle, defect):
    life, _, _, _, prepare, sign, policy, _ = lifecycle
    if defect == "automation-human":
        policy["required_human_signers"] = policy["required_signers"]
    elif defect == "duplicate-key":
        policy["signers"].append({**policy["signers"][0], "principal": "second-test@zeus.invalid"})
    elif defect == "empty-required":
        policy["required_signers"] = []
    elif defect == "revoked":
        policy["revoked"] = policy["required_signers"]
    elif defect == "expired":
        policy["signers"][0]["valid_before"] = "2021-01-01T00:00:00+00:00"
    elif defect == "future":
        policy["signers"][0]["valid_after"] = "2090-01-01T00:00:00+00:00"
    raw = canonical(policy)
    if defect == "duplicate-json":
        raw = raw[:-1] + ',"version":1}'
    git = life.authority.git
    (git.repository / ".zeus/ticket-trust.json").write_text(raw, encoding="utf-8")
    git._git("add", ".")
    git._git("-c", "user.name=Zeus test", "-c", "user.email=test@zeus.invalid", "-c", "commit.gpgsign=false",
             "commit", "-qm", "Test malformed policy")
    life.authority.trust_commit = git._git("rev-parse", "HEAD")
    with pytest.raises(ContractError):
        packet = prepare()
        life.close(packet["packet_ref"], sign(packet["packet_ref"]))


def test_new_deployment_anchor_cannot_bypass_existing_pg_pin(lifecycle):
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    first = prepare()
    life.close(first["packet_ref"], sign(first["packet_ref"]))
    life.reopen(ticket["id"], 1, 1, "Next cycle")
    git = life.authority.git
    git._git("-c", "user.name=Zeus test", "-c", "user.email=test@zeus.invalid", "-c", "commit.gpgsign=false",
             "commit", "--allow-empty", "-qm", "Different commit with same policy")
    life.authority.trust_commit = git._git("rev-parse", "HEAD")
    second = prepare()
    with pytest.raises(ContractError, match="pinned authority"):
        life.close(second["packet_ref"], sign(second["packet_ref"]))
    assert life.tickets.get(ticket["id"])["status"] == "open"


def test_missing_authority_invalidates_previous_synced_link(lifecycle, monkeypatch):
    life, ticket, github, _, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    monkeypatch.setattr(life.authority, "trust_commit", None)
    with pytest.raises(ContractError, match="Out-of-band"):
        github.sync(ticket["id"], "fixture/zeus")
    assert life.tickets.get(ticket["id"])["github"][0]["status"] == "needs_attention"


def test_consumed_reopen_does_not_override_later_manual_close(lifecycle):
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    github.sync(ticket["id"], "fixture/zeus")
    life.reopen(ticket["id"], 1, 1, "First recurrence")
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"]["state"] = "CLOSED"
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "state_conflict"
    assert state["state_writes"] == ["close", "reopen"]
    life.reopen(ticket["id"], 1, 2, "Explicitly reconcile the new remote close", expected_status="open")
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert state["state_writes"] == ["close", "reopen", "reopen"]


def test_consumed_close_does_not_override_external_reopen(lifecycle):
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    github.sync(ticket["id"], "fixture/zeus")
    state["issue"]["state"] = "OPEN"
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "state_conflict"
    assert state["state_writes"] == ["close"]


def test_crlf_signature_armor_and_explicit_required_signers_receipt(lifecycle):
    life, _, _, _, prepare, sign, policy, _ = lifecycle
    packet = prepare()
    signatures = sign(packet["packet_ref"])
    signature = life.artifacts.text(signatures[0]["signature_ref"], 16384).replace("\n", "\r\n")
    signatures[0]["signature_ref"] = life.artifacts.put(signature, "test-CRLF-signature")["ref"]
    result = life.close(packet["packet_ref"], signatures)
    proof = life.artifacts.document(result["decision"]["proof_ref"])
    assert proof["required_signers"] == policy["required_signers"]
    assert proof["required_human_signers"] == [] and proof["physical_human_presence_verified"] is False


def test_old_environment_observation_rejected_even_in_same_revision(lifecycle):
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    packet = prepare()["packet"]
    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with life.store.transaction() as tx:
        current = tx.get("tickets", ticket["id"])
        revision = tx.get("ticket_revisions", ticket["id"] + ":1")
        tx.put("tickets", ticket["id"], {**current, "created_at": old})
        tx.put("ticket_revisions", ticket["id"] + ":1", {**revision, "created_at": old})
    env = life.artifacts.document(packet["environment_ref"])
    env["observed_at"] = old
    packet["environment_ref"] = life.artifacts.put(canonical(env), "test-old-environment")["ref"]
    ref = life.artifacts.put(canonical(packet), "test-old-packet")["ref"]
    with pytest.raises(ContractError, match="too old"):
        life.close(ref, sign(ref))


def test_cli_close_and_reopen_use_same_verified_application(lifecycle, tmp_path, monkeypatch):
    from codex_harness import cli
    from codex_harness.adapters import ticket_cli
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    packet = prepare()
    signatures = sign(packet["packet_ref"])
    packet_path, signature_path = tmp_path / "cli-packet.json", tmp_path / "cli-packet.sig"
    packet_path.write_text(packet["signing_payload"], encoding="utf-8", newline="\n")
    signature_path.write_text(life.artifacts.text(signatures[0]["signature_ref"], 16384), encoding="utf-8", newline="\n")
    monkeypatch.setattr(ticket_cli, "build_lifecycle", lambda _: life)
    args = cli.parser().parse_args(["ticket", "close", ticket["id"], "--packet", str(packet_path),
                                   "--signature", signatures[0]["principal"] + "=" + str(signature_path)])
    assert ticket_cli.execute(life.tickets, args)["verification"] == "performed"
    args = cli.parser().parse_args(["ticket", "reopen", ticket["id"], "--revision", "1", "--sequence", "1", "--reason", "CLI recurrence"])
    assert ticket_cli.execute(life.tickets, args)["decision"]["kind"] == "reopened"


def test_corrupted_old_event_blocks_new_closure(lifecycle):
    life, ticket, _, _, prepare, sign, _, _ = lifecycle
    first = prepare()
    closed = life.close(first["packet_ref"], sign(first["packet_ref"]))["decision"]
    life.reopen(ticket["id"], 1, 1, "Second cycle")
    second = prepare()
    with life.store.transaction() as tx:
        tx.put("ticket_lifecycle_events", closed["id"], {**closed, "reason": "Tampered history"})
    with pytest.raises(ContractError, match="corrupted"):
        life.close(second["packet_ref"], sign(second["packet_ref"]))


def test_explicit_open_reassertion_intentionally_invalidates_old_execution(lifecycle):
    life, ticket, github, state, _, _, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    dispatch = life.tickets.dispatch(ticket["id"], 1, "revision")
    with life.store.transaction() as tx:
        bound = tx.get("outbox", dispatch["message_id"])["message"]["what"]["details"]["zeus_ticket"]
    state["issue"]["state"] = "CLOSED"
    life.reopen(ticket["id"], 1, 0, "Reconcile divergence and reassess work", expected_status="dispatched")
    with life.store.transaction() as tx:
        assert tx.get("ticket_dispatches", dispatch["id"])["status"] == "superseded"
        with pytest.raises(TicketSuperseded):
            ticket_binding(tx, {"zeus_ticket": bound})
    assert github.sync(ticket["id"], "fixture/zeus")["observed_state"] == "OPEN"


def test_reopen_projection_checks_the_whole_history(lifecycle):
    life, ticket, github, state, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    first = life.close(packet["packet_ref"], sign(packet["packet_ref"]))["decision"]
    github.sync(ticket["id"], "fixture/zeus")
    life.reopen(ticket["id"], 1, 1, "Recurrence")
    with life.store.transaction() as tx:
        tx.put("ticket_lifecycle_events", first["id"], {**first, "reason": "Tampered older event"})
    with pytest.raises(ContractError, match="corrupted"):
        github.sync(ticket["id"], "fixture/zeus")
    assert state["state_writes"] == ["close"]


def test_slow_verification_renews_owned_lease_between_bounded_operations(lifecycle, monkeypatch):
    from codex_harness.adapters import github_tickets
    life, ticket, github, _, prepare, sign, _, _ = lifecycle
    github.sync(ticket["id"], "fixture/zeus")
    packet = prepare()
    life.close(packet["packet_ref"], sign(packet["packet_ref"]))
    initial = datetime.now(timezone.utc)
    clock = [initial]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0] if tz else clock[0].replace(tzinfo=None)
    monkeypatch.setattr(github_tickets, "datetime", Clock)
    renew = github._renew
    def slow_operation(claim):
        clock[0] += timedelta(seconds=120)
        renew(claim)
    monkeypatch.setattr(github, "_renew", slow_operation)
    assert github.sync(ticket["id"], "fixture/zeus")["status"] == "synced"
    assert clock[0] - initial > timedelta(seconds=300)
