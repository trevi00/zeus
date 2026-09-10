# FA-017 closure audit

Scope is the seven unchanged criteria in `ticket-scope.json`, not all Zeus adoption.
Root independently inspected claim ordering, execution ownership, failure replay,
clock validation, existing process evidence and the local closure contract.

The actual PostgreSQL baseline accepts a repeated failure with altered `agent`,
`actor` or `recovery_sequence`. It returns an existing retry row, without a new
transition, because the receipt branch does not apply strict execution identity.
The request digest omits these fields. This is a criterion 2/4 defect, not evidence
of authenticated tenant isolation being breached: this runtime is a trusted local
executor service, not a multi-tenant authorization service.

Proposed correction: before returning a failure receipt, compare the current
execution identity using the already checked receipt's original owner (the retry
row deliberately cleared its lease owner). Preserve existing receipt digests and
same-input redelivery; reject altered identity with the existing contract error.
Test both task and decision aggregates, memory and real PostgreSQL, plus distinct
processes operating in shared/nested UTF-8 project paths with tied timestamps.

The clock contract detects observed backwards UTC and same-domain wall/monotonic
divergence. Foreign process origins cannot be subtracted. Existing UTC fallback
does not detect every offline clock change. Actual host clock mutation and VM
resume have not been measured. Pure clock samples and altered stored pins must
never be relabelled as those measurements. Final closure must resolve this exact
coverage boundary; passing unrelated CI does not resolve it.

Human enrollment is an implemented Zeus closure policy, not a GitHub/platform
requirement. Root must prepare reviewable evidence before asking for a signature.
Do not generate an agent-controlled key and label it human approval. No additional
issue is required for the defects above.
