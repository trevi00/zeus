"""Source preparation reaches the existing lease heartbeat before the provider is entered
(INV-ISOLATED-WORKER-001, self-improvement-reference-001 delivery obstacle).

The repository, the files, the export and the staged bytes are REAL; the Docker client and the
inner process are the existing injected fakes from `test_isolated_worker`, and the lease is a
LABELLED stand-in for the `Workflow` API the REAL `LeaseProgress` calls. No model, provider,
container or host service runs here, and nothing here observes a real preparation delay: these
tests bound the behaviour of the fix, not the cause of the delay that motivated it.

Ported SOURCE M7 suite `tests/test_isolated_worker_preparation.py` run against the target (REBUILD-DESIGN-v2
§5.3 S3). Import paths rewritten through `m7_containers`; `PREPARATION_TICK_SECONDS` is patched on the
target staging module that owns it. The labelled lease stand-ins (`OwnedLease`, `FakeMonotonic`, `lease`)
are dropped with the tests that used them.

Not ported here (owning slice; carried forward, listed in the S3 coverage evidence):
- test_the_export_beats_the_existing_heartbeat_as_it_makes_progress: S4 execution (the REAL LeaseProgress moves with RunTask)
- test_a_lease_that_ends_while_preparing_starts_no_container_and_retains_the_record: S4 execution (LeaseProgress)
- test_a_live_lease_is_renewed_during_preparation_and_the_run_still_completes: S4 execution (LeaseProgress)
"""

import pytest
from m7_containers import ContractError, iw, staging
from test_isolated_worker import (  # noqa: F401  `candidate` is an imported fixture
    candidate,
    git,
)

FILES = 12


def big_candidate(repo):
    """The real fixture repository with more real files to export."""
    for index in range(FILES):
        (repo / ("module_%02d.py" % index)).write_text("VALUE = %d\n" % index, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "more files")
    return git(repo, "rev-parse", "HEAD")


# ----- the export itself --------------------------------------------------------------------------
def test_preparation_without_a_callback_is_byte_identical(candidate, tmp_path, monkeypatch):  # noqa: F811
    head = big_candidate(candidate)
    monkeypatch.setattr(staging, "PREPARATION_TICK_SECONDS", 0)
    plain = iw.stage_source(candidate, head, tmp_path / "plain")
    ticks = []
    beaten = iw.stage_source(candidate, head, tmp_path / "beaten", on_progress=lambda: ticks.append(1))
    assert plain == beaten and len(ticks) >= FILES
    for name in plain["manifest"]:
        left = (tmp_path / "plain").joinpath(*name.split("/"))
        right = (tmp_path / "beaten").joinpath(*name.split("/"))
        assert left.read_bytes() == right.read_bytes()
        assert (left.stat().st_mode & 0o777) == (right.stat().st_mode & 0o777)
    assert plain["manifest_sha256"] == beaten["manifest_sha256"]


def test_a_refusing_heartbeat_stops_the_export_before_the_next_file(candidate, tmp_path, monkeypatch):  # noqa: F811
    """The caller's own refusal travels unchanged and the export stops where it was."""
    head = big_candidate(candidate)
    monkeypatch.setattr(staging, "PREPARATION_TICK_SECONDS", 0)
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) > 3:
            raise ContractError("Execution lease expired or was superseded")

    with pytest.raises(ContractError, match="lease expired"):
        iw.stage_source(candidate, head, tmp_path / "stage", on_progress=cancel)
    staged = [path for path in (tmp_path / "stage").rglob("*") if path.is_file()]
    assert len(calls) == 4 and 0 < len(staged) < FILES + 3, "it stopped mid export, not at the end"


# ----- the run: before the container exists ---------------------------------------------------------
