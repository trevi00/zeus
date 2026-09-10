"""Statement-attributed gate verdicts and one shared fold (INV-GATE-001).

Upstream consumers read the latest stage+mode verdict while judges wrote per-statement verdicts,
treated PARTIAL as done in one place and pending in another, folded retractions in some readers
but not others, and ignored process exit codes. Here every verdict names its statement, run,
cycle and definition; every consumer uses this fold; and a retraction removes exactly one verdict.
"""
import re
from dataclasses import asdict, dataclass

from codex_harness.domain.model import require

VERDICTS = ('PASS', 'FAIL', 'ERROR', 'PARTIAL', 'REJECT')
ORIGINS = ('runner_receipt', 'reviewer_decision')
AUTHORITIES = ('authenticated_provider', 'unauthenticated_claim')
STATES = ('passed', 'failed', 'error', 'pending', 'not_run')
HASH = re.compile(r'[0-9a-f]{64}\Z')
REFERENCE = re.compile(r'sha256:[0-9a-f]{64}\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}\Z')


@dataclass(frozen=True)
class GateVerdict:
    statement_id: str
    stage: str
    run_id: str
    cycle: int
    definition_hash: str
    artifact_hash: str | None
    environment_hash: str | None
    verdict: str
    origin: str
    receipt_ref: str | None
    exit_status: int | None
    actor: str | None
    authority: str | None
    sequence: int
    retracts: int | None = None

    def validate(self):
        for name in ('statement_id', 'stage', 'run_id'):
            require(isinstance(getattr(self, name), str) and IDENTIFIER.fullmatch(getattr(self, name)),
                    'Invalid gate ' + name)
        require(type(self.cycle) is int and self.cycle >= 0, 'Invalid gate cycle')
        require(type(self.sequence) is int and self.sequence > 0, 'Invalid gate verdict sequence')
        require(isinstance(self.definition_hash, str) and HASH.fullmatch(self.definition_hash),
                'Gate verdict requires its definition hash')
        for name in ('artifact_hash', 'environment_hash'):
            value = getattr(self, name)
            require(value is None or (isinstance(value, str) and HASH.fullmatch(value)), 'Invalid gate ' + name)
        require(self.origin in ORIGINS, 'Unknown gate verdict origin')
        if self.retracts is not None:
            require(type(self.retracts) is int and 0 < self.retracts < self.sequence, 'Invalid retraction target')
            require(self.verdict == 'RETRACT' and self.receipt_ref is None and self.exit_status is None
                    and isinstance(self.actor, str) and self.actor.strip(),
                    'A retraction names its actor and carries no verdict of its own')
            return
        require(self.verdict in VERDICTS, 'Unknown gate verdict')
        if self.origin == 'runner_receipt':
            require(isinstance(self.receipt_ref, str) and REFERENCE.fullmatch(self.receipt_ref),
                    'Runner verdict requires an immutable receipt')
            require(type(self.exit_status) is int and not isinstance(self.exit_status, bool),
                    'Runner verdict requires the process exit status')
            require(self.verdict != 'PASS' or self.exit_status == 0, 'A non-zero exit cannot be PASS')
            require(self.actor is None and self.authority is None, 'Runner verdicts carry no reviewer identity')
        else:
            require(isinstance(self.actor, str) and self.actor.strip(), 'Reviewer verdict requires an actor')
            require(self.authority in AUTHORITIES, 'Reviewer verdict requires its authority level')
            require(self.receipt_ref is None or REFERENCE.fullmatch(self.receipt_ref), 'Invalid reviewer receipt')
            require(self.exit_status is None, 'Reviewer verdicts have no process exit')

    @property
    def state(self):
        if self.origin == 'reviewer_decision' and self.authority != 'authenticated_provider':
            return 'pending'  # an unauthenticated claim never settles a statement
        return {'PASS': 'passed', 'FAIL': 'failed', 'REJECT': 'failed', 'ERROR': 'error',
                'PARTIAL': 'pending'}[self.verdict]


def parse_verdict(document):
    require(isinstance(document, dict) and set(document) <= {f for f in GateVerdict.__dataclass_fields__},
            'Unknown gate verdict fields')
    fields = {name: document.get(name) for name in GateVerdict.__dataclass_fields__}
    fields.setdefault('retracts', None)
    verdict = GateVerdict(**fields)
    verdict.validate()
    return verdict


def fold_verdicts(verdicts, statements, run_id, cycle):
    """One deterministic view: the latest live verdict per required statement of this run and cycle.

    `statements` maps every planned statement to its current definition hash; that mapping is the
    denominator, so a statement nobody judged is `not_run`, never absent. Verdicts for other runs,
    cycles or definitions are counted as foreign and ignored. A retraction removes its target;
    ERROR withdraws validity instead of leaving an earlier PASS in place; PARTIAL stays pending.
    """
    require(isinstance(statements, dict) and statements and all(
        isinstance(k, str) and isinstance(v, str) and HASH.fullmatch(v) for k, v in statements.items()),
        'Statement denominator with definition hashes required')
    parsed = [v if isinstance(v, GateVerdict) else parse_verdict(v) for v in verdicts]
    for verdict in parsed:
        verdict.validate()
    sequences = [v.sequence for v in parsed]
    require(len(sequences) == len(set(sequences)), 'Duplicate gate verdict sequence')
    by_sequence = {v.sequence: v for v in parsed}
    retracted = set()
    for verdict in parsed:
        if verdict.retracts is not None:
            target = by_sequence.get(verdict.retracts)
            require(target is not None and target.statement_id == verdict.statement_id
                    and target.retracts is None, 'Retraction must name a live verdict of the same statement')
            retracted.add(verdict.retracts)
    latest, foreign, ignored = {}, 0, []
    for verdict in sorted(parsed, key=lambda v: v.sequence):
        if verdict.retracts is not None or verdict.sequence in retracted:
            continue
        expected = statements.get(verdict.statement_id)
        if (expected is None or verdict.definition_hash != expected or verdict.run_id != run_id
                or verdict.cycle != cycle):
            foreign += 1
            ignored.append(verdict.sequence)
            continue
        latest[verdict.statement_id] = verdict
    states = {}
    for statement in statements:
        verdict = latest.get(statement)
        states[statement] = {'state': verdict.state if verdict else 'not_run',
                             'verdict': verdict.verdict if verdict else None,
                             'sequence': verdict.sequence if verdict else None,
                             'origin': verdict.origin if verdict else None}
    counts = {state: sum(row['state'] == state for row in states.values()) for state in STATES}
    return {'run_id': run_id, 'cycle': cycle, 'statements': states, 'counts': counts,
            'denominator': len(statements), 'complete': counts['passed'] == len(statements),
            'foreign_verdicts': foreign, 'ignored_sequences': ignored,
            'retracted_sequences': sorted(retracted)}


def compact(verdicts):
    """Drop retraction pairs; the fold of the compacted view must equal the fold of the full view."""
    parsed = [v if isinstance(v, GateVerdict) else parse_verdict(v) for v in verdicts]
    retracted = {v.retracts for v in parsed if v.retracts is not None}
    return [asdict(v) for v in parsed if v.retracts is None and v.sequence not in retracted]
