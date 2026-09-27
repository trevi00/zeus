"""Named worker credentials (INV-WORKER-CREDENTIALS-001): the required selection matrix over MemoryStore (and the
isolated PostgreSQL store for concurrency), the host adapters over private fixture files, the real Fleet runner and
lane launcher with a recorded spawn. Every provider reading here is a labeled FIXTURE observation; no Claude
process, no provider usage read and no model call is made."""
import json
import os
import stat
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_harness.adapters import fleet_runtime
from codex_harness.adapters import worker_credentials as adapter
from codex_harness.adapters import worker_credentials_cli as cli
from codex_harness.adapters.store import MemoryStore
from codex_harness.application.fleet import Fleet, FleetRunner
from codex_harness.application.worker_credentials import BUCKET, WorkerCredentials
from codex_harness.domain import worker_credentials as domain
from codex_harness.domain.operation import validate_manifest

PRIMARY_SECRET = "fixture-primary-token-" + "A" * 24
SECONDARY_SECRET = "fixture-secondary-token-" + "B" * 24
T0 = datetime(2026, 9, 27, 8, 0, tzinfo=timezone.utc)
VERSION = "2.1.280"
USAGE = "claude-provider-usage-limit-exceeded"
AUTH = "claude-provider-authentication-failed"


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self) -> str:
        return self.now.isoformat()

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def reading(alias, generation, at, *, weekly=50, five=10, status="known", code="usage_windows_missing",
            version=VERSION, isolated=True):
    """A FIXTURE provider observation in the adapter's exact output shape."""
    known = status == "known"
    return {"schema": domain.OBSERVATION_SCHEMA, "alias": alias, "generation": generation,
            "source": {"kind": "claude_cli_usage", "cli_version": version, "isolated_config": isolated,
                       "cache_free": True},
            "observed_at": at, "status": status, "reason_code": None if known else code,
            "weekly": {"used_percent": weekly, "resets_at": "Oct 3, 9am"} if known else None,
            "five_hour": {"used_percent": five, "resets_at": "1pm"} if known else None}


class Telemetry:
    """Fixture telemetry port: what the provider 'reports' per alias, and every call made."""

    def __init__(self, clock, **readings):
        self.clock, self.readings, self.calls = clock, dict(readings), []

    def __call__(self, row):
        self.calls.append(row["alias"])
        fields = dict(self.readings[row["alias"]])
        generation = fields.pop("generation", row["generation"])
        return reading(row["alias"], generation, self.clock(), **fields)


@pytest.fixture
def root(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    os.chmod(secrets, 0o700)
    monkeypatch.setattr(domain, "SECRET_ROOT", str(secrets))
    monkeypatch.setattr(adapter, "SECRET_ROOT", str(secrets))
    return secrets


def telemetry_row(root, generation, name):
    return {"kind": "claude_cli_usage", "login_credentials_path": str(root / name), "cli_version": VERSION,
            "binding": {"generation": generation, "attested_by": "owner-fixture", "attested_at": "2026-09-27T07:00:00Z"}}


def config(root, *, secondary=True, primary_telemetry=False, primary_generation="p1", secondary_generation="s1",
           primary_in_flight=2, secondary_in_flight=1, **policy):
    rows = [{"alias": "primary", "generation": primary_generation,
             "secret": {"kind": "env_file_key", "path": str(root / "zeus-aibox.env"), "key": "CLAUDE_CODE_OAUTH_TOKEN"},
             "telemetry": telemetry_row(root, primary_generation, "primary-login.json") if primary_telemetry else None,
             "max_in_flight": primary_in_flight}]
    if secondary:
        rows.append({"alias": "secondary", "generation": secondary_generation,
                     "secret": {"kind": "token_file", "path": str(root / "claude-secondary.token")},
                     "telemetry": telemetry_row(root, secondary_generation, "secondary-login.json"),
                     "max_in_flight": secondary_in_flight})
    return {"schema": domain.CONFIG_SCHEMA, "credentials": rows,
            "policy": {"secondary_weekly_below_percent": 80, "telemetry_max_age_seconds": 300,
                       "unknown_reset_seconds": 3600, "reservation_seconds": 7200, **policy}}


def fake_secrets(reference):
    return PRIMARY_SECRET if reference["path"].endswith("zeus-aibox.env") else SECONDARY_SECRET


def credentials(root, clock, telemetry=None, store=None, secrets=fake_secrets, **options):
    return WorkerCredentials(store if store is not None else MemoryStore(), config(root, **options), clock=clock,
                             telemetry=telemetry, secrets=secrets)


def limited(service, alias="primary", cause=USAGE, **release):
    """One dispatch served by the eligible credential, then refused by the provider with `cause`."""
    grant = service.admit("limited-" + alias + "-" + str(len(service.status()["credentials"][0]["audit"])))
    assert grant["granted"] and grant["alias"] == alias
    return service.release(grant["owner"], cause=cause, **release)


def no_secret(value) -> None:
    text = json.dumps(value, default=str)
    assert PRIMARY_SECRET not in text and SECONDARY_SECRET not in text


# ---- configuration --------------------------------------------------------------------------------------------

def test_the_configuration_names_references_only_and_never_loosens_the_bound(root):
    assert domain.validate_config(config(root))["policy"]["secondary_weekly_below_percent"] == 80
    assert domain.validate_config(config(root, secondary_weekly_below_percent=70))
    good = config(root)
    bad = [
        {**good, "policy": {**good["policy"], "secondary_weekly_below_percent": 81}},
        {**good, "policy": {**good["policy"], "telemetry_max_age_seconds": 3601}},
        {**good, "credentials": [good["credentials"][1]]},                                   # no primary
        {**good, "credentials": [good["credentials"][0], {**good["credentials"][1], "alias": "primary"}]},
        {**good, "credentials": [{**good["credentials"][0], "secret": {"kind": "env_file_key",
                                                                        "path": "/etc/zeus.env",
                                                                        "key": "CLAUDE_CODE_OAUTH_TOKEN"}}]},
        {**good, "credentials": [{**good["credentials"][0], "secret": {"kind": "token_file",
                                                                        "path": str(root / "a/../b")}}]},
        {**good, "credentials": [good["credentials"][0], {**good["credentials"][1], "telemetry": {
            **good["credentials"][1]["telemetry"], "binding": {"generation": "s0", "attested_by": "x",
                                                               "attested_at": "2026-09-27T07:00:00Z"}}}]},
        {**good, "credentials": [good["credentials"][0], {**good["credentials"][1], "token": SECONDARY_SECRET}]},
    ]
    for document in bad:
        with pytest.raises(domain.CredentialRefused) as refused:
            domain.validate_config(document)
        assert refused.value.reason_code == "credentials_config_invalid"
        assert SECONDARY_SECRET not in str(refused.value)


# ---- the required selection matrix ----------------------------------------------------------------------------

def test_a_healthy_primary_is_preferred_and_the_secondary_quota_is_never_read(root):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 10})
    service = credentials(root, clock, telemetry)
    grant = service.admit_fresh("dispatch-1")
    assert grant["granted"] and grant["alias"] == "primary" and grant["reason_code"] == "primary_eligible"
    assert telemetry.calls == [], "no secondary usage read while the primary serves"
    assert service.status()["serving"] == "primary"


def test_a_primary_usage_limit_switches_to_a_secondary_strictly_below_the_bound(root):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 79})
    service = credentials(root, clock, telemetry)
    effect = limited(service)
    assert effect["effect"] == "cooldown" and effect["reset_reported"] is False
    assert effect["until"] == (T0 + timedelta(seconds=3600)).isoformat()
    grant = service.admit_fresh("dispatch-2")
    assert grant["granted"] and grant["alias"] == "secondary" and grant["refreshed"] == ["secondary"]
    assert grant["reason_code"] == "primary_unavailable_secondary_eligible"
    assert grant["primary"] == "primary_cooling_down" and grant["secondary"]["weekly_used_percent"] == 79
    status = service.status()
    assert [(s["from"], s["to"]) for s in status["switches"]] == [(None, "primary"), ("primary", "secondary")]
    assert status["switches"][-1]["primary"] == "primary_cooling_down"


@pytest.mark.parametrize("weekly,granted", [(0, True), (79, True), (80, False), (81, False), (100, False)])
def test_the_secondary_is_held_at_or_above_eighty_percent_weekly_used(root, weekly, granted):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": weekly}))
    limited(service)
    grant = service.admit_fresh("dispatch-2")
    assert grant["granted"] is granted
    if not granted:
        assert grant["reason_code"] == "held_no_eligible_credential"
        assert grant["reasons"] == {"primary": "primary_cooling_down",
                                    "secondary": "secondary_weekly_at_or_above_bound"}
        assert grant["secondary"]["weekly_used_percent"] == weekly


def test_a_stricter_configured_bound_holds_earlier(root):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 70}), secondary_weekly_below_percent=70)
    limited(service)
    assert service.admit_fresh("dispatch-2")["reasons"]["secondary"] == "secondary_weekly_at_or_above_bound"


def test_the_five_hour_window_still_applies(root):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 10, "five": 100}))
    limited(service)
    assert service.admit_fresh("dispatch-2")["reasons"]["secondary"] == "secondary_five_hour_exhausted"


@pytest.mark.parametrize("fields,reason", [
    ({"status": "unknown", "code": "usage_windows_missing"}, "secondary_telemetry_unknown"),
    ({"status": "unknown", "code": "cli_version_mismatch"}, "secondary_telemetry_unknown"),
    ({"status": "unknown", "code": "model_call_detected"}, "secondary_telemetry_unknown"),
    ({"version": "2.1.281"}, "secondary_telemetry_version_unpinned"),
])
def test_unknown_or_unpinned_telemetry_holds_and_is_never_an_assumed_zero(root, fields, reason):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary=fields))
    limited(service)
    grant = service.admit_fresh("dispatch-2")
    assert not grant["granted"] and grant["reasons"]["secondary"] == reason


def test_missing_stale_future_and_foreign_telemetry_hold(root):
    clock = Clock()
    service = credentials(root, clock, telemetry=None)
    limited(service)
    assert service.admit_fresh("d-missing")["reasons"]["secondary"] == "secondary_telemetry_missing"
    telemetry = Telemetry(clock, secondary={"weekly": 10})
    service.telemetry = telemetry
    service.observe("secondary")
    clock.advance(301)
    assert service.admit("d-stale")["reasons"]["secondary"] == "secondary_telemetry_stale"
    row = domain.credential(service.config, "secondary")
    future = {"generation": "s1", "observation": reading("secondary", "s1", (clock.now + timedelta(seconds=60)).isoformat())}
    assert domain.eligibility(service.config, "secondary", future, clock.now)["reason_code"] == "secondary_telemetry_future"
    foreign = {"generation": "s1", "observation": reading("secondary", "s0", clock())}
    assert domain.eligibility(service.config, "secondary", foreign, clock.now)["reason_code"] == \
        "secondary_telemetry_foreign"
    assert row["telemetry"]["binding"]["generation"] == "s1"
    telemetry.readings["secondary"] = {"weekly": 10, "generation": "s0"}
    with pytest.raises(domain.CredentialRefused) as refused:
        service.observe("secondary")
    assert refused.value.reason_code == "observation_foreign"
    telemetry.readings["secondary"] = {"weekly": 10, "isolated": False}
    with pytest.raises(domain.CredentialRefused) as refused:
        service.observe("secondary")
    assert refused.value.reason_code == "observation_invalid", "a known reading needs an isolated cache-free source"


def test_a_persistent_telemetry_defect_costs_one_usage_read_per_freshness_bound(root):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"status": "unknown", "code": "usage_timeout"})
    service = credentials(root, clock, telemetry)
    limited(service)
    for tick in range(5):
        assert not service.admit_fresh("dispatch-" + str(tick))["granted"]
        clock.advance(30)
    assert telemetry.calls == ["secondary"]
    clock.advance(300)
    assert not service.admit_fresh("dispatch-late")["granted"]
    assert telemetry.calls == ["secondary", "secondary"]
    held = [e["reasons"]["secondary"] for e in service.status()["credentials"][1]["audit"] if e["event"] == "held"]
    assert held == ["secondary_telemetry_missing", "secondary_telemetry_unknown"], \
        "a hold is audited when its reasons change, not once per tick"


def test_both_blocked_holds_new_work_with_named_reasons(root):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 50})
    service = credentials(root, clock, telemetry)
    limited(service)
    served = service.admit_fresh("on-secondary")
    assert served["alias"] == "secondary"
    assert service.release(served["owner"], cause=USAGE)["effect"] == "cooldown"
    grant = service.admit_fresh("dispatch-3")
    assert not grant["granted"] and grant["reason_code"] == "held_no_eligible_credential"
    assert grant["reasons"] == {"primary": "primary_cooling_down", "secondary": "secondary_cooling_down"}
    assert service.status()["selection"] == "held_no_eligible_credential"


def test_a_reported_primary_reset_switches_back_to_the_primary(root):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 20}))
    limited(service, resets_at=(T0 + timedelta(seconds=600)).isoformat())
    assert service.admit_fresh("on-secondary")["alias"] == "secondary"
    service.release("on-secondary")
    clock.advance(601)
    grant = service.admit_fresh("after-reset")
    assert grant["alias"] == "primary" and grant["reason_code"] == "primary_eligible"
    status = service.status()
    assert [(s["from"], s["to"]) for s in status["switches"]][-1] == ("secondary", "primary")
    assert status["credentials"][0]["cooldown"] is None
    cleared = [e for e in status["credentials"][0]["audit"] if e["event"] == "cooldown_cleared"]
    assert cleared[-1]["reset_confirmed"] is True, "a provider-reported reset that passed confirms the switch back"


def test_an_unreported_reset_is_confirmed_by_fresh_primary_telemetry_after_the_refusal(root):
    clock = Clock()
    telemetry = Telemetry(clock, primary={"weekly": 100, "five": 30})
    service = credentials(root, clock, telemetry, secondary=False, primary_telemetry=True)
    limited(service)
    clock.advance(3601)
    held = service.admit("before-reading")
    assert not held["granted"] and held["reasons"]["primary"] == "primary_reset_unconfirmed"
    exhausted = service.admit_fresh("still-exhausted")
    assert not exhausted["granted"] and telemetry.calls == ["primary"]
    clock.advance(301)
    telemetry.readings["primary"] = {"weekly": 40, "five": 5}
    grant = service.admit_fresh("confirmed")
    assert grant["granted"] and grant["alias"] == "primary" and telemetry.calls == ["primary", "primary"]
    cleared = [e for e in service.status()["credentials"][0]["audit"] if e["event"] == "cooldown_cleared"]
    assert cleared[-1]["reset_confirmed"] is True


def test_without_primary_telemetry_the_bounded_default_is_the_only_reset_evidence(root):
    clock = Clock()
    service = credentials(root, clock, secondary=False)
    limited(service)
    clock.advance(3599)
    assert service.admit("early")["reasons"]["primary"] == "primary_cooling_down"
    clock.advance(2)
    grant = service.admit("late")
    assert grant["granted"] and grant["alias"] == "primary"
    cleared = [e for e in service.status()["credentials"][0]["audit"] if e["event"] == "cooldown_cleared"]
    assert cleared[-1]["reset_confirmed"] is False


def test_a_revoked_primary_needs_a_new_generation_and_the_secondary_serves_meanwhile(root):
    clock = Clock()
    store = MemoryStore()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 30}), store=store)
    assert limited(service, cause=AUTH)["effect"] == "revoked"
    clock.advance(10 * 86400)
    grant = service.admit_fresh("after-revocation")
    assert grant["alias"] == "secondary" and grant["primary"] == "primary_revoked"
    service.release(grant["owner"])
    reprovisioned = credentials(root, clock, Telemetry(clock, secondary={"weekly": 30}), store=store,
                                primary_generation="p2")
    grant = reprovisioned.admit_fresh("new-generation")
    assert grant["alias"] == "primary" and grant["generation"] == "p2"
    assert reprovisioned.status()["credentials"][0]["revoked"] is None


def test_an_unreadable_granted_secret_revokes_that_generation_before_any_launch(root):
    clock = Clock()

    def secrets(reference):
        if reference["path"].endswith("zeus-aibox.env"):
            raise domain.CredentialRefused("secret_unavailable", "path")
        return SECONDARY_SECRET
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 30}), secrets=secrets)
    grant = service.admit_fresh("dispatch-1")
    assert grant["granted"] and grant["alias"] == "secondary"
    primary = service.status()["credentials"][0]
    assert primary["revoked"]["reason_code"] == "secret_unavailable" and primary["reservations"] == []


def test_in_flight_work_finishes_while_new_dispatch_is_held(root):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 60})
    service = credentials(root, clock, telemetry)
    limited(service)
    running = service.admit_fresh("in-flight")
    assert running["alias"] == "secondary"
    # The secondary's own in-flight bound: one dispatch at a time spends it.
    assert service.admit_fresh("second")["reasons"]["secondary"] == "secondary_in_flight_bound"
    telemetry.readings["secondary"] = {"weekly": 85}
    clock.advance(301)
    service.observe("secondary")
    assert service.token(running) == SECONDARY_SECRET, "the in-flight worker keeps its credential"
    released = service.release("in-flight")
    assert released["effect"] == "none"
    held = service.admit_fresh("after")
    assert not held["granted"] and held["reasons"]["secondary"] == "secondary_weekly_at_or_above_bound"


def test_a_busy_primary_is_not_unavailable_and_never_spends_the_secondary(root):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 5})
    service = credentials(root, clock, telemetry)
    assert [service.admit_fresh(o)["alias"] for o in ("one", "two")] == ["primary", "primary"]
    busy = service.admit_fresh("three")
    assert not busy["granted"] and busy["reason_code"] == "held_primary_in_flight_bound"
    assert telemetry.calls == []


def test_a_replayed_admission_returns_its_reservation_and_a_restart_keeps_state(root):
    clock = Clock()
    store = MemoryStore()
    first = credentials(root, clock, store=store, secondary=False, primary_in_flight=1)
    grant = first.admit("owner-1")
    restarted = credentials(root, clock, store=store, secondary=False, primary_in_flight=1)
    again = restarted.admit("owner-1")
    assert again["cached"] is True and again["alias"] == grant["alias"]
    assert restarted.admit("owner-2")["reason_code"] == "held_primary_in_flight_bound"
    # A crashed owner's lease ends; its late release still applies the provider outcome.
    clock.advance(7201)
    assert restarted.admit("owner-2")["granted"]
    late = restarted.release("owner-1", cause=USAGE)
    assert late["late"] is True and late["effect"] == "cooldown"
    events = [e["event"] for e in restarted.status()["credentials"][0]["audit"]]
    assert "reservations_expired" in events and events[-1] == "released"


def test_release_of_an_unknown_owner_changes_nothing(root):
    clock = Clock()
    service = credentials(root, clock, secondary=False)
    before = service.status()
    assert service.release("never-granted", cause=USAGE)["reason_code"] == "reservation_unknown"
    assert service.status()["credentials"] == before["credentials"]


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def concurrent_store(request):
    if request.param == "memory":
        return MemoryStore()
    return request.getfixturevalue("isolated_pgstore")


def test_concurrent_admissions_never_exceed_the_in_flight_bound(root, concurrent_store):
    clock = Clock()
    grants, barrier = [], threading.Barrier(8)

    def admit(index):
        service = credentials(root, clock, store=concurrent_store, secondary=False, primary_in_flight=2)
        barrier.wait()
        grants.append(service.admit("owner-" + str(index)))
    threads = [threading.Thread(target=admit, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for g in grants if g["granted"]) == 2
    assert {g["reason_code"] for g in grants if not g["granted"]} == {"held_primary_in_flight_bound"}


# ---- redaction ------------------------------------------------------------------------------------------------

def test_no_secret_reaches_status_audit_records_or_cli_output(root, capsys):
    clock = Clock()
    store = MemoryStore()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 40}), store=store)
    limited(service)
    grant = service.admit_fresh("dispatch")
    no_secret(grant)
    no_secret(service.status())
    with store.transaction() as tx:
        no_secret([tx.get(BUCKET, key) for key in ("primary", "secondary", "selection")])
    for command, extra in (("status", {}), ("admit", {"owner": "cli-owner"}), ("release", {"owner": "cli-owner",
                                                                                            "cause": "none",
                                                                                            "resets_at": None})):
        args = SimpleNamespace(worker_credentials_command=command, **extra)
        no_secret(cli.execute(None, args, credentials=service))
    with pytest.raises(domain.CredentialRefused) as refused:
        cli.execute(SimpleNamespace(store=store), SimpleNamespace(worker_credentials_command="status"), host={})
    assert refused.value.reason_code == "credentials_unconfigured"
    assert cli.refusal(refused.value)["reason_code"] == "credentials_unconfigured"


def test_select_env_writes_one_private_variable_and_prints_no_value(root):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 40}))
    target = root / "zeus-aibox-selected.env"
    result = cli.execute(None, SimpleNamespace(worker_credentials_command="select-env", owner="managed-generation",
                                               path=str(target)), credentials=service)
    assert result["status"] == "granted" and result["alias"] == "primary" and result["written"] is True
    no_secret(result)
    assert target.read_text() == "CLAUDE_CODE_OAUTH_TOKEN=" + PRIMARY_SECRET + "\n"
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    limited(service)   # the primary is refused while the selected generation runs
    held_service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 90}), store=service.store)
    held = cli.execute(None, SimpleNamespace(worker_credentials_command="select-env", owner="next-generation",
                                             path=str(target)), credentials=held_service)
    assert held["status"] == "held" and held["exit_code"] == 1
    assert target.read_text().endswith(PRIMARY_SECRET + "\n"), "a hold never rewrites the selected file"
    with pytest.raises(domain.CredentialRefused):
        adapter.write_selected_env("/etc/zeus-selected.env", PRIMARY_SECRET)


# ---- host adapters --------------------------------------------------------------------------------------------

def private(path: Path, text: str, mode=0o600) -> Path:
    path.write_text(text)
    os.chmod(path, mode)
    return path


def test_read_secret_accepts_only_a_private_single_well_shaped_token(root):
    env = private(root / "zeus-aibox.env", "# comment\nOTHER=x\nCLAUDE_CODE_OAUTH_TOKEN=" + PRIMARY_SECRET + "\n")
    assert adapter.read_secret({"kind": "env_file_key", "path": str(env), "key": "CLAUDE_CODE_OAUTH_TOKEN"}) \
        == PRIMARY_SECRET
    token = private(root / "claude-secondary.token", SECONDARY_SECRET + "\n")
    assert adapter.read_secret({"kind": "token_file", "path": str(token)}) == SECONDARY_SECRET
    cases = [
        (private(root / "open.token", SECONDARY_SECRET, 0o644), "secret_not_private"),
        (private(root / "empty.token", ""), "secret_empty"),
        (private(root / "two.token", SECONDARY_SECRET + "\n" + SECONDARY_SECRET), "secret_not_single_token"),
        (private(root / "short.token", "abc"), "secret_shape_invalid"),
        (root / "missing.token", "secret_unavailable"),
    ]
    for path, code in cases:
        with pytest.raises(domain.CredentialRefused) as refused:
            adapter.read_secret({"kind": "token_file", "path": str(path)})
        assert refused.value.reason_code == code
        no_secret(str(refused.value))
    os.symlink(token, root / "link.token")
    with pytest.raises(domain.CredentialRefused) as refused:
        adapter.read_secret({"kind": "token_file", "path": str(root / "link.token")})
    assert refused.value.reason_code == "secret_not_regular"
    with pytest.raises(domain.CredentialRefused) as refused:
        adapter.read_secret({"kind": "token_file", "path": "/etc/passwd"})
    assert refused.value.reason_code == "secret_path_invalid"


USAGE_TEXT = ("Current session: 12% used · resets 1pm (Asia/Seoul)\n"
              "Current week (all models): 43% used · resets Oct 3, 9am (Asia/Seoul)\n"
              "Current week (Sonnet only): 7% used · resets Oct 3, 9am (Asia/Seoul)\n")


def test_parse_usage_reads_the_pinned_lines_and_refuses_ambiguity():
    assert adapter.parse_usage(USAGE_TEXT) == {
        "five_hour": {"used_percent": 12, "resets_at": "1pm (Asia/Seoul)"},
        "weekly": {"used_percent": 43, "resets_at": "Oct 3, 9am (Asia/Seoul)"}}
    assert adapter.parse_usage("Current session: 12% used\n") is None, "no weekly window is no reading"
    assert adapter.parse_usage(USAGE_TEXT + "Current week (all models): 44% used\n") is None
    assert adapter.parse_usage(USAGE_TEXT.replace("43%", "143%")) is None
    assert adapter.parse_usage("Current week (Sonnet only): 7% used\n") is None
    assert adapter.parse_usage(None) is None


class Runner:
    """Fixture `subprocess.run`: records argv/env/cwd, never starts Claude."""

    def __init__(self, *, version=VERSION + " (Claude Code)", body=None, returncode=0, raises=None):
        self.version, self.returncode, self.raises, self.calls = version, returncode, raises, []
        self.body = body if body is not None else {"type": "result", "subtype": "success", "is_error": False,
                                                   "result": USAGE_TEXT, "usage": {"input_tokens": 0,
                                                                                   "output_tokens": 0}}
        self.seen_directory = None

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": list(argv), "env": dict(kwargs["env"]), "cwd": kwargs.get("cwd")})
        if argv[1:] == ["--version"]:
            return subprocess.CompletedProcess(argv, 0, stdout=self.version, stderr="")
        if self.raises is not None:
            raise self.raises
        directory = Path(kwargs["cwd"])
        self.seen_directory = directory
        copy = directory / ".credentials.json"
        assert copy.read_text() == '{"fixture": "login"}' and stat.S_IMODE(os.stat(copy).st_mode) == 0o600
        assert sorted(p.name for p in directory.iterdir()) == [".credentials.json"], "no cache or settings"
        return subprocess.CompletedProcess(argv, self.returncode, stdout=json.dumps(self.body), stderr="")


def secondary_row(root):
    return domain.credential(domain.validate_config(config(root)), "secondary")


def test_the_usage_telemetry_is_one_isolated_cache_free_read_with_no_token_variable(root, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", PRIMARY_SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-api-key")
    private(root / "secondary-login.json", '{"fixture": "login"}')
    runner = Runner()
    clock = Clock()
    observation = adapter.ClaudeUsageTelemetry("claude-fixture", runner=runner, clock=clock,
                                               scratch=str(tmp_path))(secondary_row(root))
    assert observation["status"] == "known" and observation["weekly"]["used_percent"] == 43
    assert observation["five_hour"]["used_percent"] == 12 and observation["source"]["cli_version"] == VERSION
    assert domain.validate_observation(observation) == observation
    usage = runner.calls[1]
    assert usage["argv"] == ["claude-fixture", *adapter.USAGE_ARGV]
    assert not {"CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"} & set(usage["env"])
    assert usage["env"]["CLAUDE_CONFIG_DIR"] == usage["env"]["HOME"] == usage["cwd"]
    assert not runner.seen_directory.exists(), "the private copy is removed"
    no_secret(runner.calls)


@pytest.mark.parametrize("runner,code", [
    (Runner(version="2.1.281 (Claude Code)"), "cli_version_mismatch"),
    (Runner(returncode=1), "usage_exit_nonzero"),
    (Runner(body={"type": "result", "subtype": "success", "is_error": True, "result": USAGE_TEXT}),
     "usage_error_result"),
    (Runner(body={"type": "result", "subtype": "success", "is_error": False, "result": USAGE_TEXT,
                  "usage": {"input_tokens": 9, "output_tokens": 1}}), "model_call_detected"),
    (Runner(body={"type": "result", "subtype": "success", "is_error": False,
                  "result": "Current session: 3% used\n"}), "usage_windows_missing"),
    (Runner(raises=subprocess.TimeoutExpired("claude", 60)), "usage_timeout"),
])
def test_every_telemetry_defect_is_a_named_unknown(root, tmp_path, runner, code):
    private(root / "secondary-login.json", '{"fixture": "login"}')
    observation = adapter.ClaudeUsageTelemetry("claude-fixture", runner=runner, clock=Clock(),
                                               scratch=str(tmp_path))(secondary_row(root))
    assert observation["status"] == "unknown" and observation["reason_code"] == code
    assert observation["weekly"] is None and observation["five_hour"] is None
    domain.validate_observation(observation)


def test_a_missing_or_open_login_is_unknown_without_running_usage(root, tmp_path):
    runner = Runner()
    observation = adapter.ClaudeUsageTelemetry("claude-fixture", runner=runner, clock=Clock(),
                                               scratch=str(tmp_path))(secondary_row(root))
    assert observation["reason_code"] == "login_secret_unavailable" and len(runner.calls) == 1
    private(root / "secondary-login.json", '{"fixture": "login"}', 0o640)
    observation = adapter.ClaudeUsageTelemetry("claude-fixture", runner=runner, clock=Clock(),
                                               scratch=str(tmp_path))(secondary_row(root))
    assert observation["reason_code"] == "login_secret_not_private"


def test_configured_credentials_is_opt_in_and_refuses_a_present_invalid_configuration(root, tmp_path):
    store = MemoryStore()
    assert adapter.configured_credentials(store, {}) is None
    path = tmp_path / "worker-credentials.json"
    path.write_text(json.dumps(config(root)))
    service = adapter.configured_credentials(store, {adapter.CONFIG_SETTING: str(path)})
    assert isinstance(service, WorkerCredentials) and service.secrets is adapter.read_secret
    path.write_text(json.dumps({**config(root), "policy": {**config(root)["policy"],
                                                            "secondary_weekly_below_percent": 90}}))
    with pytest.raises(domain.CredentialRefused) as refused:
        adapter.configured_credentials(store, {adapter.CONFIG_SETTING: str(path)})
    assert refused.value.reason_code == "credentials_config_invalid"
    with pytest.raises(domain.CredentialRefused) as refused:
        adapter.configured_credentials(store, {adapter.CONFIG_SETTING: str(tmp_path / "absent.json")})
    assert refused.value.reason_code == "credentials_config_unreadable"


# ---- dispatch: the real Fleet runner and lane launcher ----------------------------------------------------------

BASE = "a" * 40
GOAL = {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "c", "base_revision": BASE, "bytes": 3}


def manifest(op_id, path):
    from codex_harness.adapters.providers import packaged_policy
    return validate_manifest({
        "schema": "urn:zeus:operation:1", "id": op_id, "base_revision": BASE,
        "goal": {"path": "docs/GOAL.md", "sha256": "b" * 64, "criterion": "crit " + op_id, "rationale": "r"},
        "plan": {"objective": "o", "acceptance_criteria": ["ok"], "allowed_paths": [path]},
        "budget": {"per_host": 4, "total": 8},
        "claude": {"model": "claude-fixture-model", "timeout_seconds": 120, "max_budget_usd": 1.0}},
        packaged_policy())


class Spawned:
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def dispatch_world(root, tmp_path, monkeypatch, clock, telemetry, causes):
    lanes = [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
              "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")}]
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register({"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1,
                    "budget": {"per_host": 4, "total": 8}, "lanes": lanes})
    service = credentials(root, clock, telemetry, store=MemoryStore())
    spawned = []

    def popen(argv, **kwargs):
        spawned.append({"argv": list(argv), "token": kwargs["env"].get("CLAUDE_CODE_OAUTH_TOKEN")})
        return Spawned(1)
    monkeypatch.setattr(fleet_runtime, "lane_environment",
                        lambda lane, host, environ: {"ZEUS_DATABASE_URL": "dsn", "CLAUDE_CODE_OAUTH_TOKEN": "inherited-host-token"})
    monkeypatch.setattr(fleet_runtime, "verify_lane_schema", lambda dsn, schema, connect: None)
    monkeypatch.setattr(fleet_runtime.subprocess, "Popen", popen)
    jobs = {}
    monkeypatch.setattr(fleet_runtime, "read_receipt", lambda dsn, schema, operation_id, connect: (
        {"id": operation_id, "manifest_sha256": jobs[operation_id]["manifest_sha256"], "status": "failed",
         "reason_code": "provider_failure", "task_id": "task-" + operation_id}, None))
    monkeypatch.setattr(fleet_runtime, "read_provider_cause",
                        lambda dsn, schema, receipt, connect: causes.get(receipt["id"]))
    launcher = fleet_runtime.LaneLauncher(fleet.registered()["config"], {}, argv=("zeus",), connect=None,
                                          budget=SimpleNamespace(counts=lambda: {"this_host": 0, "all_hosts": 0,
                                                                                 "unreadable": 0}),
                                          environ={}, credentials=service)
    return SimpleNamespace(fleet=fleet, service=service, launcher=launcher, spawned=spawned, jobs=jobs)


def enqueue(world, op_id, path):
    world.jobs[op_id] = world.fleet.enqueue("a", manifest(op_id, path), GOAL, [])["job"]


def run_once(world):
    return FleetRunner(world.fleet, world.launcher, sleep=lambda _: None, interval=0).run(once=True)


def test_the_selected_credential_reaches_only_that_child_and_a_hold_keeps_work_queued(root, tmp_path, monkeypatch):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 50})
    world = dispatch_world(root, tmp_path, monkeypatch, clock, telemetry, {"op-1": USAGE})
    enqueue(world, "op-1", "docs/one.md")
    first = run_once(world)
    assert first["admitted"] == ["op-1"] and world.spawned[-1]["token"] == PRIMARY_SECRET
    assert [(x["id"], x["status"]) for x in first["finalized"]] == [("op-1", "failed")], first
    assert all(PRIMARY_SECRET not in part for part in world.spawned[-1]["argv"])
    no_secret(first)
    enqueue(world, "op-2", "docs/two.md")
    second = run_once(world)
    assert second["admitted"] == ["op-2"] and world.spawned[-1]["token"] == SECONDARY_SECRET, second
    no_secret(second)
    telemetry.readings["secondary"] = {"weekly": 80}
    clock.advance(301)
    enqueue(world, "op-3", "docs/three.md")
    held = run_once(world)
    assert held["admitted"] == [] and held["credential"] == {
        "state": "held", "reason_code": "held_no_eligible_credential",
        "reasons": {"primary": "primary_cooling_down", "secondary": "secondary_weekly_at_or_above_bound"}}
    assert held["blocked"] == {"op-3": "credential_held"}
    job = {j["id"]: j for j in world.fleet.status()["jobs"]}["op-3"]
    assert (job["status"], job["reason_code"]) == ("queued", "credential_held"), "pending ownership is visible"
    assert len(world.spawned) == 2, "no child was started for held work"
    clock.advance(3600)
    resumed = run_once(world)
    assert resumed["admitted"] == ["op-3"] and world.spawned[-1]["token"] == PRIMARY_SECRET, \
        "the primary's reset switches new work back"
    with world.service.store.transaction() as tx:
        audit = [e for alias in ("primary", "secondary") for e in tx.get(BUCKET, alias)["audit"]]
    released = {e["subject"]: (e["alias"], e["effect"]) for e in audit if e["event"] == "released" and "subject" in e}
    assert released == {"op-1": ("primary", "cooldown"), "op-2": ("secondary", "none"), "op-3": ("primary", "none")}


def test_without_a_credential_port_the_runner_and_launcher_keep_the_previous_behaviour(root, tmp_path, monkeypatch):
    clock = Clock()
    world = dispatch_world(root, tmp_path, monkeypatch, clock, None, {})
    world.launcher.credentials = None
    enqueue(world, "op-1", "docs/one.md")
    summary = run_once(world)
    assert summary["admitted"] == ["op-1"] and "credential" not in summary, summary
    assert world.spawned[-1]["token"] == "inherited-host-token"


def test_idle_or_otherwise_blocked_ticks_reserve_nothing_and_read_no_usage(root, tmp_path, monkeypatch):
    clock = Clock()
    telemetry = Telemetry(clock, secondary={"weekly": 10})
    world = dispatch_world(root, tmp_path, monkeypatch, clock, telemetry, {})
    limited(world.service)   # the primary is unavailable: a reservation attempt WOULD read the secondary's usage
    for _ in range(3):
        assert run_once(world)["admitted"] == []
    world.fleet.pause()
    enqueue(world, "op-1", "docs/one.md")
    paused = run_once(world)
    assert paused["admitted"] == [] and paused["blocked"] == {"op-1": "paused"} and "credential" not in paused
    assert telemetry.calls == [] and world.spawned == []
    status = world.service.status()
    assert [e["event"] for e in status["credentials"][1]["audit"]] == []
    assert all(c["reservations"] == [] for c in status["credentials"])


def test_a_job_admitted_after_the_preview_without_a_grant_waits_instead_of_failing(root, tmp_path, monkeypatch):
    clock = Clock()
    world = dispatch_world(root, tmp_path, monkeypatch, clock, None, {})
    enqueue(world, "op-1", "docs/one.md")
    monkeypatch.setattr(world.fleet, "admissible", lambda budget_exhausted=False: None)   # the race: preview saw none
    raced = run_once(world)
    assert raced["admitted"] == [] and raced["blocked"] == {"op-1": "credential_held"} and world.spawned == []
    monkeypatch.undo()


def test_read_provider_cause_prefers_authentication_and_ignores_uncertainty():
    class Conn:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, query, params=None):
            row = ("lane_a",) if "current_schema" in query else ((self.body,) if self.body is not None else None)
            return SimpleNamespace(fetchone=lambda: row)
    body = {"failure": {"cause": USAGE}, "attempt_outcomes": [{"failure": {"cause": AUTH}}]}
    read = fleet_runtime.read_provider_cause
    assert read("dsn", "lane_a", {"task_id": "t"}, lambda dsn, **_: Conn(body)) == AUTH
    assert read("dsn", "lane_a", {"task_id": "t"}, lambda dsn, **_: Conn({"failure": {"cause": USAGE}})) == USAGE
    assert read("dsn", "lane_a", {"task_id": "t"}, lambda dsn, **_: Conn({"failure": {"cause": "x"}})) is None
    assert read("dsn", "lane_a", {"task_id": "t"}, lambda dsn, **_: Conn(None)) is None
    assert read("dsn", "lane_b", {"task_id": "t"}, lambda dsn, **_: Conn(body)) is None
    assert read("dsn", "lane_a", None, lambda dsn, **_: Conn(body)) is None

    def broken(dsn, **_):
        raise OSError("fixture outage")
    assert read("dsn", "lane_a", {"task_id": "t"}, broken) is None


def test_the_fleet_cli_wires_configured_credentials_and_refuses_an_invalid_configuration(root, tmp_path, monkeypatch):
    import argparse
    import signal

    from codex_harness.adapters import fleet_cli
    store = MemoryStore()
    fleet = Fleet(store)
    fleet.register({"schema": "urn:zeus:fleet:1", "id": "fleet-1", "max_parallel": 1,
                    "budget": {"per_host": 4, "total": 8},
                    "lanes": [{"id": "a", "team": "alpha", "repository": str(tmp_path / "repo-a"), "schema": "lane_a",
                               "redis_namespace": "fleet-a", "runtime": str(tmp_path / "rt-a")}]})
    path = tmp_path / "worker-credentials.json"
    path.write_text(json.dumps(config(root)))
    host = {adapter.CONFIG_SETTING: str(path)}
    built = []

    class Recorded:
        reserves_credentials = True

        def __init__(self, registered, settings, **kwargs):
            built.append(kwargs)

        def reserve(self):
            return kwargs_credentials().admit_fresh("fleet-dispatch:fixture")

        def unreserve(self, grant):
            kwargs_credentials().release(grant["owner"])

        def budget_exhausted(self, budget):
            return False

    def kwargs_credentials():
        return built[-1]["credentials"]
    monkeypatch.setattr("codex_harness.adapters.configuration.settings", lambda: host)
    monkeypatch.setattr("codex_harness.adapters.fleet_runtime.LaneLauncher", Recorded)
    monkeypatch.setattr("codex_harness.adapters.portfolio.portfolio_reconciler", lambda store: None)
    monkeypatch.setattr(signal, "signal", lambda *args: None)
    result = fleet_cli.run(SimpleNamespace(store=store), argparse.Namespace(once=True))
    assert result["exit_code"] == 0 and result["admitted"] == []
    assert isinstance(built[0]["credentials"], WorkerCredentials)
    assert built[0]["credentials"].secrets is adapter.read_secret
    path.write_text(json.dumps({**config(root), "schema": "urn:zeus:worker-credentials:0"}))
    with pytest.raises(domain.CredentialRefused) as refused:
        fleet_cli.run(SimpleNamespace(store=store), argparse.Namespace(once=True))
    assert refused.value.reason_code == "credentials_config_invalid" and len(built) == 1


def test_the_admission_hold_names_only_otherwise_admissible_jobs(root, tmp_path, monkeypatch):
    from codex_harness.domain.fleet import FleetRefused
    world = dispatch_world(root, tmp_path, monkeypatch, Clock(), None, {})
    enqueue(world, "op-1", "docs/one.md")
    world.jobs["op-2"] = world.fleet.enqueue("a", manifest("op-2", "docs/two.md"), GOAL, ["op-1"])["job"]
    assert world.fleet.admissible() == "op-1"
    decision = world.fleet.admit_one(hold="credential_held")
    assert decision["job"] is None and decision["blocked"]["op-1"] == "credential_held"
    assert decision["blocked"]["op-2"].startswith("dependency"), "a job's own reason is kept"
    with pytest.raises(FleetRefused) as refused:
        world.fleet.admit_one(hold="anything_else")
    assert refused.value.reason_code == "hold_invalid"
    assert world.fleet.admit_one()["job"]["id"] == "op-1", "without the hold the same job is claimed"


def test_an_owner_records_a_refusal_observed_outside_a_dispatch_once(root):
    clock = Clock()
    service = credentials(root, clock, Telemetry(clock, secondary={"weekly": 30}))
    evidence = "sha256:" + "4" * 64
    recorded = service.record_refusal("primary", cause=USAGE, evidence_ref=evidence)
    assert recorded["effect"] == "cooldown" and recorded["cached"] is False and recorded["reset_reported"] is False
    assert service.record_refusal("primary", cause=USAGE, evidence_ref=evidence)["cached"] is True
    grant = service.admit_fresh("after-recorded-refusal")
    assert grant["alias"] == "secondary" and grant["primary"] == "primary_cooling_down"
    for alias, cause, ref, code in (("primary", "worker-credential-secret-unavailable", evidence, "refusal_cause_invalid"),
                                    ("primary", USAGE, "sha256:short", "refusal_evidence_invalid"),
                                    ("tertiary", USAGE, evidence, "credential_unconfigured")):
        with pytest.raises(domain.CredentialRefused) as refused:
            service.record_refusal(alias, cause=cause, evidence_ref=ref)
        assert refused.value.reason_code == code
    out = cli.execute(None, SimpleNamespace(worker_credentials_command="record-refusal", alias="secondary",
                                            cause="authentication", evidence="sha256:" + "5" * 64, resets_at=None),
                      credentials=service)
    assert out["effect"] == "revoked" and out["exit_code"] == 0
    no_secret(out)
    no_secret(service.status())
