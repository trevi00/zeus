**Verdict: no remaining shipping blockers for the current scope (task + threshold-review recovery).** The previously flagged defects are genuinely closed in the source I read:

- `execution_recovery.py:16-34` — `_row` pins exact storage identity (`row['id'] == task_id`), task `message.when.deadline` / `what.details` shape, decision `input` shape, and integer counters, so a corrupt row can never be snapshotted as valid.
- `:56-62` — the `_related` wrapper re-raises `ContractError` and converts `OSError/ValueError/KeyError/TypeError` into `ContractError`; it never returns a value on evidence or shape failure, so the replay branches (`:158`, `:173`) cannot report `replayed: True` when coupled threshold evidence is missing or changed.
- `:126-134` — `_packet_size` enforces finite JSON plus the 1 MiB canonical bound, and is called on both `prepare` (`:123`) and `apply` (`:138`).
- Unsupported phases fail explicitly at `:67` (`No recovery coupling handler for this decision phase`), matching that full issue and deployment recovery remain out of scope.
- `cli.py:390-402` maps both packet-write and packet-read `OSError` to `ContractError`, and pre-checks file size before parse.

Tests match the claims: `test_corruption_claim_block_repair_and_claim_again` corrupts the stored deadline/budget, asserts a real `claim` returns `None`, then repairs and re-claims; `test_unhandled_decision_phase_is_explicitly_rejected` and `test_prepare_rejects_invalid_or_unexportable_snapshot` cover phase, identity, shape, NaN and oversized cases.

Residual non-blockers (worth a follow-up, not a hold): `ticket_binding` is enforced only in `apply` (`:187`), not in `prepare`, so broken ticket coupling surfaces late; and the `threshold_proposal_runs` row at `:79` is hashed but not identity-checked.

I have not run the suite — treat the in-flight target/full runs as the source of pass/fail truth.