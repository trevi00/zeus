"""S4 turn loop on the S2 ContextComposer (DESIGN-run-task D7): explicit recovery and a fixed basis revision.

Turn 1 passes neither field and composes exactly as S2 (compare:context.composition stays equal). From turn 2,
M7's `_run` recovers from that run's own state plus its last completed events, and keeps the basis revision it
read before the loop. The composer uses both exactly as given: no re-read of HEAD, no derivation from stored
rows.
"""

from __future__ import annotations

from codex_harness.context.application.compose import CompositionRequest, ContextComposer


class Artifacts:
    def __init__(self):
        self.puts = []

    def put(self, body, source, **kw):
        self.puts.append(source)
        return {"ref": "sha256:" + format(len(self.puts), "064x")}


class Repository:
    def __init__(self):
        self.reads = 0

    def revision(self, cwd):
        self.reads += 1
        return "rev-" + str(self.reads)


class Skills:
    def select(self, cwd, revision, objective):
        return [], {"selected": 0}


def request(**extra):
    base = dict(agent="lead:improvement", key="t1", objective="o", evidence={"plan": {"objective": "x"}},
                cwd="/w", snapshot="snap", runtime_policy_digest="p", reader_python="/py", provider="codex",
                default_provider="codex", read_only=True, review_context={"interpreter": "/py"})
    base.update(extra)
    return CompositionRequest(**base)


def test_turn_one_reads_head_and_derives_recovery_from_rows():
    repo = Repository()
    composed = ContextComposer(Artifacts(), "/a", repo, Skills()).compose(request())
    assert repo.reads == 1 and composed.basis_revision == "rev-1" and composed.recovery_refs == {}


def test_later_turns_use_the_explicit_recovery_and_the_fixed_basis():
    repo, artifacts = Repository(), Artifacts()
    state = {"task_id": "t1", "next_action": "continue interrupted assignment"}
    completed = [{"method": "item/completed", "params": {"item": {"id": "c1"}}}]
    composed = ContextComposer(artifacts, "/a", repo, Skills()).compose(
        request(recovery={"checkpoint": state, "completed": completed}, basis_revision="rev-fixed",
                checkpoint={"checkpoint": {"task_id": "t1"}}, progress={"id": "t1"}))
    assert repo.reads == 0 and composed.basis_revision == "rev-fixed"
    assert list(composed.recovery_refs) == ["checkpoint", "completed"]
    assert [s for s in artifacts.puts if s.startswith("recovery:")] == ["recovery:t1:checkpoint",
                                                                         "recovery:t1:completed"]
    assert composed.packet.required["recovery"]["sources"].keys() == {"checkpoint", "completed"}
