"""Versioned SDD work and evidence preparation, without impersonating human acceptance."""
from dataclasses import asdict, replace

from codex_harness.application.tickets import ticket_binding
from codex_harness.domain.gate_verdicts import bind_runner_receipt, fold_verdicts, parse_verdict
from codex_harness.domain.model import canonical, digest, require, utcnow
from codex_harness.domain.sdd import (
    STAGES,
    gate_report,
    propose_scenarios,
    validate_environment,
    validate_events,
    validate_spec,
)


class SDD:
    def __init__(self, store, artifacts, human_provider=None):
        self.store, self.artifacts = store, artifacts
        # INV-ORACLE-001: without an authenticated decision provider, no verdict can carry that authority.
        self.human_provider = human_provider

    @staticmethod
    def statement_definitions(row, stage):
        """INV-GATE-001: each stage check is a fixed statement bound to the spec revision it judges."""
        checks = next(checks for key, _, _, checks in STAGES if key == stage)
        return {name: digest({'stage': stage, 'statement': name, 'spec_hash': row['spec_hash']}) for name in checks}

    @staticmethod
    def _gate_verdicts(tx, row):
        return [event['details']['verdict'] for event in tx.scan('sdd_events')
                if event['iteration_id'] == row['id'] and event['kind'] == 'gate_verdict_recorded']

    def _gates(self, tx, row):
        verdicts = self._gate_verdicts(tx, row)
        return {stage: fold_verdicts(verdicts, self.statement_definitions(row, stage), row['id'], row['revision'])
                for stage, _, _, _ in STAGES}

    def record_gate_verdict(self, iteration_id, document):
        require(isinstance(document, dict), 'Gate verdict document required')
        require(document.get('authority') != 'authenticated_provider' or self.human_provider is not None,
                'Authenticated human authority requires a configured decision provider')
        with self.store.transaction() as tx:
            row = tx.get('sdd_iterations', iteration_id)
            require(row, 'SDD iteration not found')
            self._current(tx, row)
            stage = document.get('stage')
            require(any(key == stage for key, _, _, _ in STAGES), 'Unknown SDD stage')
            definitions = self.statement_definitions(row, stage)
            require(document.get('statement_id') in definitions, 'Statement is not part of this stage')
            verdict = parse_verdict({**document, 'run_id': row['id'], 'cycle': row['revision'],
                                     'sequence': row['sequence'] + 1,
                                     'definition_hash': definitions[document['statement_id']]})
            details = {}
            if verdict.receipt_ref:
                self.artifacts.inspect(verdict.receipt_ref)
            if verdict.retracts is None and verdict.origin == 'runner_receipt':
                # The receipt is evidence only if it names this run, cycle, statement, definition and
                # exit status itself; free text or a receipt for another statement is not (PR #46).
                details['receipt_binding'] = bind_runner_receipt(
                    verdict, self.artifacts.document(verdict.receipt_ref))
            elif verdict.retracts is None and verdict.authority == 'authenticated_provider':
                verdict, details['provider_decision'] = self._provider_decision(verdict)
            if verdict.retracts is not None:
                fold_verdicts(self._gate_verdicts(tx, row) + [asdict(verdict)], definitions, row['id'], row['revision'])
            event = self._append(tx, row, 'gate_verdict_recorded',
                                 [verdict.receipt_ref] if verdict.receipt_ref else [], verdict=asdict(verdict),
                                 **details)
            return {'sequence': event['sequence'], 'verdict': asdict(verdict),
                    'gate': self._gates(tx, row)[stage], 'release_authorized': False}

    def _provider_decision(self, verdict):
        """Authority comes from the provider's own verification of this exact statement, never from
        the caller's claim. An unverified claim is kept as a pending unauthenticated claim."""
        verify = getattr(self.human_provider, 'verify', None)
        require(callable(verify), 'Decision provider must verify reviewer decisions')
        decision = verify({key: getattr(verdict, key) for key in
                           ('statement_id', 'stage', 'run_id', 'cycle', 'definition_hash', 'actor', 'verdict')})
        require(isinstance(decision, dict) and type(decision.get('authenticated')) is bool
                and all(decision.get(key) == getattr(verdict, key) for key in
                        ('statement_id', 'run_id', 'cycle', 'definition_hash', 'actor', 'verdict')),
                'Decision provider result does not bind this reviewer decision')
        if not decision['authenticated']:
            verdict = replace(verdict, authority='unauthenticated_claim')
        return verdict, {'authenticated': decision['authenticated'], 'provider': type(self.human_provider).__name__}

    def _spec(self, row):
        spec = self.artifacts.document(row["spec_ref"])
        require(digest(spec) == row["spec_hash"], "SDD snapshot changed")
        return validate_spec(spec)

    @staticmethod
    def _current(tx, row):
        ticket_binding(tx, row)
        head = tx.get("sdd_spec_heads", row["spec_id"])
        require(head and head["iteration_id"] == row["id"], "Superseded SDD specification")

    @staticmethod
    def _append(tx, row, kind, evidence_refs=(), **details):
        event = {"iteration_id": row["id"], "sequence": row["sequence"] + 1,
                 "previous_hash": row["event_hash"], "at": utcnow(), "kind": kind,
                 "spec_hash": row["spec_hash"], "evidence_refs": list(evidence_refs), "details": details}
        event["hash"] = digest(event)
        tx.put("sdd_events", row["id"] + ":" + str(event["sequence"]).zfill(8), event)
        row.update(sequence=event["sequence"], event_hash=event["hash"])
        tx.put("sdd_iterations", row["id"], row)
        return event

    @staticmethod
    def _notify(tx, row, code, message):
        key = digest({"iteration_id": row["id"], "code": code})
        old = tx.get("sdd_notifications", key) or {}
        tx.put("sdd_notifications", key, {"id": key, "iteration_id": row["id"], "code": code,
            "severity": "warning", "message": message, "count": old.get("count", 0) + 1,
            "first_seen": old.get("first_seen", utcnow()), "last_seen": utcnow(),
            "delivery": "local_only", "status": "open"})

    def register(self, spec, ticket_id, ticket_revision, source):
        spec = validate_spec(spec)
        require(isinstance(source, dict) and set(source) == {"mode", "repository", "revision", "path"}
                and source["mode"] in {"git", "working_tree_draft"}, "Invalid spec provenance")
        require(all(isinstance(source[k], str) and source[k].strip() for k in ("repository", "path")), "Spec origin required")
        require((source["mode"] == "working_tree_draft" and source["revision"] is None)
                or (source["mode"] == "git" and isinstance(source["revision"], str) and len(source["revision"]) in {40, 64}
                    and all(c in "0123456789abcdef" for c in source["revision"])), "Invalid spec revision")
        snapshot = self.artifacts.put(canonical(spec), "sdd-spec-snapshot")
        with self.store.transaction() as tx:
            ticket = tx.get("tickets", ticket_id)
            require(ticket and ticket["revision"] == ticket_revision, "Stale SDD ticket")
            bound = {k: ticket[k] for k in ("id", "revision", "content_hash")}
            ticket_binding(tx, {"zeus_ticket": bound})
            identity = digest({"spec_hash": digest(spec), "ticket": bound, "source": source})
            old = tx.get("sdd_iterations", identity)
            if old:
                self._spec(old)
                return old
            head = tx.get("sdd_spec_heads", spec["id"])
            if head:
                previous = self._spec(tx.get("sdd_iterations", head["iteration_id"]))
                validate_spec(spec, previous)
            row = {"id": identity, "spec_id": spec["id"], "spec_hash": digest(spec),
                "spec_ref": snapshot["ref"], "source": source, "zeus_ticket": bound,
                "revision": 1 + (head or {}).get("revision", 0), "stage": STAGES[0][0],
                "status": "awaiting_human_scope", "sequence": 0, "event_hash": None, "created_at": utcnow(),
                "authority": "preparation_only"}
            tx.put("sdd_spec_heads", spec["id"], {"iteration_id": identity, "revision": row["revision"]})
            self._append(tx, row, "spec_registered", [snapshot["ref"]])
            self._notify(tx, row, "human_authority_missing", "Review scenario intent; authenticated human approval is not configured")
            return row

    def status(self, iteration_id):
        with self.store.transaction() as tx:
            row = tx.get("sdd_iterations", iteration_id)
            require(row, "SDD iteration not found")
            spec = self._spec(row)
            runs = [r for r in tx.scan("sdd_observations") if r["iteration_id"] == iteration_id]
            notices = [r for r in tx.scan("sdd_notifications") if r["iteration_id"] == iteration_id]
            events = sorted((r for r in tx.scan("sdd_events") if r["iteration_id"] == iteration_id), key=lambda r: r["sequence"])
            previous_hash = None
            for sequence, event in enumerate(events, 1):
                require(event["sequence"] == sequence and event["previous_hash"] == previous_hash
                        and digest({k: v for k, v in event.items() if k != "hash"}) == event["hash"], "SDD event journal gap or corruption")
                previous_hash = event["hash"]
            require(len(events) == row["sequence"] and previous_hash == row["event_hash"], "SDD event head changed")
            ticket = tx.get("tickets", row["zeus_ticket"]["id"])
            superseded = not ticket or ticket["revision"] != row["zeus_ticket"]["revision"]
            head = tx.get("sdd_spec_heads", row["spec_id"])
            spec_superseded = not head or head["iteration_id"] != iteration_id
            gates = self._gates(tx, row)
        return {**row, "status": "superseded_ticket" if superseded else "superseded_spec" if spec_superseded else row["status"],
                "spec": spec, "report": gate_report(spec, runs), "observations": runs,
                "notifications": notices, "events": events, "gates": gates}

    def observe(self, iteration_id, environment, events, source_name):
        validate_environment(environment)
        validate_events(events)
        require(isinstance(source_name, str) and 0 < len(source_name) <= 200, "Observation source required")
        document = {"environment": environment, "events": events, "source_name": source_name,
                    "authority": "imported_observation_not_verified_execution"}
        artifact = self.artifacts.put(canonical(document), "sdd-observation-import")
        with self.store.transaction() as tx:
            row = tx.get("sdd_iterations", iteration_id)
            require(row, "SDD iteration not found")
            self._current(tx, row)
            spec = self._spec(row)
            proposal = propose_scenarios(spec, environment, events)
            identity = digest({"iteration_id": iteration_id, "artifact_ref": artifact["ref"]})
            existing = tx.get("sdd_observations", identity)
            if existing:
                return existing
            receipt = {"id": identity, "iteration_id": iteration_id, "spec_hash": row["spec_hash"],
                "environment_hash": digest(environment), "artifact_ref": artifact["ref"],
                "authority": document["authority"], "at": utcnow(), "sequence_complete": proposal["sequence_complete"]}
            tx.put("sdd_observations", identity, receipt)
            self._append(tx, row, "observations_imported", [artifact["ref"]], observation_id=identity)
            if not proposal["sequence_complete"]:
                self._notify(tx, row, "observation_gap", "Observation sequence is incomplete; replay and acceptance are blocked")
            self._notify(tx, row, "unverified_observation", "Imported logs cannot certify physical-device execution or human QA")
            return receipt

    def propose(self, iteration_id, observation_id):
        with self.store.transaction() as tx:
            row = tx.get("sdd_iterations", iteration_id)
            observation = tx.get("sdd_observations", observation_id)
            require(row and observation and observation["iteration_id"] == iteration_id, "Observation is not bound to this iteration")
            self._current(tx, row)
            document = self.artifacts.document(observation["artifact_ref"])
            proposal = propose_scenarios(self._spec(row), document["environment"], document["events"])
            require(proposal["environment_hash"] == observation["environment_hash"], "Observation identity changed")
            proposal["observation_ref"] = observation["artifact_ref"]
            proposal["iteration_id"] = iteration_id
        # Artifact maintenance locks files before PostgreSQL. Never invert that lock order.
        artifact = self.artifacts.put(canonical(proposal), "sdd-scenario-proposal")
        with self.store.transaction() as tx:
            row = tx.get("sdd_iterations", iteration_id)
            require(row, "SDD iteration not found")
            self._current(tx, row)
            current = tx.get("sdd_observations", observation_id)
            require(current == observation and row["spec_hash"] == proposal["spec_hash"], "Stale scenario proposal")
            existing = tx.get("sdd_proposals", artifact["ref"])
            if existing:
                return existing
            result = {"id": artifact["ref"], "iteration_id": iteration_id, "artifact_ref": artifact["ref"],
                      "status": "requires_human_oracle_review", "acceptance_passed": False}
            tx.put("sdd_proposals", result["id"], result)
            self._append(tx, row, "scenario_proposal_created", [artifact["ref"]])
            return result

    def request_advance(self, iteration_id, expected_sequence):
        with self.store.transaction() as tx:
            row = tx.get("sdd_iterations", iteration_id)
            require(row and row["sequence"] == expected_sequence, "Stale SDD transition")
            self._current(tx, row)
            report = gate_report(self._spec(row))
            gate = self._gates(tx, row)[row["stage"]]
            # INV-GATE-001: the transition consumes the shared fold, statement by statement.
            unsettled = sorted(name for name, state in gate["statements"].items() if state["state"] != "passed")
            reason = (report["next_action"] if not unsettled else
                      "Stage statements not passed: " + ", ".join(f"{name}={gate['statements'][name]['state']}"
                                                                    for name in unsettled))
            self._append(tx, row, "transition_blocked", stage=row["stage"], reason=reason, gate=gate)
            self._notify(tx, row, "transition_blocked", reason)
            return {"status": "blocked", "stage": row["stage"], "sequence": row["sequence"],
                    "reason": reason, "gate": gate, "release_authorized": False}

    def record_transfer(self, iteration_id, record):
        keys = {"task_family", "contract_hash", "guardrail_hash", "toolchain_hash", "source_model", "target_model", "evidence_refs"}
        require(isinstance(record, dict) and set(record) == keys, "Invalid model transfer record")
        require(record["source_model"] in {"gpt-6-astra", "gpt-5.6-sol"}
                and record["target_model"] == {"gpt-6-astra": "gpt-5.6-sol", "gpt-5.6-sol": "gpt-5.6-terra"}[record["source_model"]],
                "Transfer must follow Astra to Sol to Terra")
        require(isinstance(record["task_family"], str) and 0 < len(record["task_family"]) <= 100
                and not any(c in record["task_family"] for c in "*?[]"), "Concrete task family required")
        from codex_harness.domain.sdd import HASH
        require(all(isinstance(record[k], str) and HASH.fullmatch(record[k]) for k in ("contract_hash", "guardrail_hash", "toolchain_hash")),
                "Versioned transfer identity required")
        require(isinstance(record["evidence_refs"], list) and 0 < len(record["evidence_refs"]) <= 50, "Transfer evidence required")
        for ref in record["evidence_refs"]:
            require(isinstance(ref, str), "Invalid transfer evidence reference")
            self.artifacts.text(ref, 1024 * 1024)
        with self.store.transaction() as tx:
            row = tx.get("sdd_iterations", iteration_id)
            require(row, "SDD iteration not found")
            self._current(tx, row)
            identity = digest({"iteration_id": iteration_id, "record": record})
            old = tx.get("sdd_transfer_candidates", identity)
            if old:
                return old
            result = {**record, "id": identity, "iteration_id": iteration_id,
                      "status": "recorded_unqualified", "routing_authority": False}
            tx.put("sdd_transfer_candidates", identity, result)
            self._append(tx, row, "transfer_evidence_recorded", record["evidence_refs"], transfer_id=identity)
            return result
