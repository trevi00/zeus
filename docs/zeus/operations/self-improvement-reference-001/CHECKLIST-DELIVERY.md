# Evidence-checklist delivery and the evidence-refusal owner handoff (2026-09-21 KST)

What was built for the SPEC.md section *Evidence-checklist delivery and retained-candidate review*,
what it deliberately does not do, and what is still unverified here. The rule text is
INV-PROJECT-EVIDENCE-001, INV-ISOLATED-WORKER-001 and INV-OPERATION-001 in `docs/contracts.md`;
this file is the delivery note, not an additional authority.

## The failure family this answers

The worker could still choose which commands counted as evidence, because the container path had no
host-authored checklist: the existing project-evidence profile deliberately refused Docker
isolation, so an isolated run fell back to the legacy `{summary, tests}` free-text contract and
every extra command the model mentioned became a claim. Prompt-only guidance did not fix that
twice. The correction connects the EXISTING contract to isolated execution rather than whitelisting
command spellings or relaxing `all_checked`.

## What was added

| Owner | Change |
|---|---|
| `domain/project_evidence.py` | `urn:zeus:project-evidence:2`: the version-1 grammar plus a closed `execution = {kind: "container", image: "sha256:<64hex>"}`; a version-2 context interpreter must be `/opt/zeus/bin/python`. Checks, worker schema, observations and classifier are shared, unmodified. |
| `adapters/project_evidence.py` | `container_binding`, `resolve_container_profile`, `container_worker_delivery`, `container_execution_instructions`: the candidate tree is verified on the host, the executing values are container paths, the image interpreter and a fixed allowlisted environment. `_execute_check` is the one seam for WHERE a check runs. |
| `adapters/isolated_evidence.py` | `IsolatedProjectEvidenceInspector`: the inherited claim parsing, denominator, classification, aggregate deadline and archive, replayed by the SAME verifier-container function (`DockerEvidenceInspector._replay`, now with the check's container `workdir`). |
| `adapters/isolated_worker.py`, `..._entry.py` | The delivery travels in the request under `zeus-isolated-worker-v1-project-evidence`; protocol and delivery must agree in both directions, and the delivery must name this image and the mounted workspace. |
| `adapters/executor.py`, `bootstrap.py`, `operation_cli.py`, `autonomous_cli.py` | One pairing rule before any provider entry: version 2 requires isolation and its exact image, version 1 beside isolation stays refused, no profile is the untouched legacy path. Both entry points load profile and isolation in the same order and bind both into the operation identity. |
| `application/operation.py`, `application/fleet.py`, `adapters/fleet_runtime.py` | `owner_handoff` (`urn:zeus:operation-evidence-handoff:1`) on the operation row, written in the same transaction as the terminal `failed` / `evidence_gate_refused` status, and its counts-only projection on a lane job. |

## Correction after independent review: foreign evidence earns no progress (2026-09-21)

The independent review of candidate `e4dded2` reproduced one false progress attribution: a handoff
whose inspection row belonged to ANOTHER execution was summarized with `known=true`, the foreign
`all_checked` verdict and its passed/remaining checklist, and `Fleet` relayed `passed=1,
remaining=1` for it. The operation itself stayed `failed`; the evidence gate stayed closed, so this
was misleading owner-facing reporting, not a false release acceptance.

- `application/operation.py` establishes the COMPLETE current execution binding (task id,
  generation, attempt, candidate source revision) before reading any finding. Missing, unreadable,
  incomplete and foreign binding each yield `bound=false`, `known=false` and a fixed reason code
  (`inspection_missing`, `inspection_unknown`, `execution_binding_incomplete`,
  `inspection_bound_elsewhere`) with the inspection id kept for diagnosis and no verdict,
  denominator, claim counts or checklist items - unknown is absent, not a completed zero.
- `application/fleet.py` decides credit itself: `owner_handoff_view` relays `passed`/`remaining`
  only when the record states both `bound` and `known` as exactly true, so a handoff written and
  retained before this rule cannot leak credit through the projection an owner polls. It also
  carries the inspection's reason code, so null progress is interpretable.
- Bound evidence is unchanged: the same passed/remaining checklist, limits, identity, owner, next
  action, reason code, gate, retry authority, operation state and stored history as before.

## What it deliberately does not do

- No retry, acceptance, model call, merge, deployment or scheduling. `pending_owner` is a visible
  request for `lead:improvement`; nothing consumes it automatically, and no daemon was added.
- No historical rewrite: the existing failed operation, its cancelled pending review, the candidate
  task and every older receipt stay byte-for-byte as they are.
- No new evidence store, replay policy, broker, mount, network, credential path or global profile
  activation, and no image build or deployment from this change.
- No normalization of model command strings and no stripping of a `timeout` wrapper from an existing
  receipt: a claim that was recorded is judged as it was recorded.
- Version 1 host profiles and unprofiled runs are untouched, including the Python-only argv
  boundary, the absolute aggregate replay deadline and the existing review context.

## Limits of the verification done here

- Every Docker client and attached capture in `tests/test_isolated_project_evidence.py` is an
  INJECTED fake; a real daemon, image, container, model or network was never used. Those tests prove
  the composed argv, the request bytes, the entry's parsing, the claim/classification path and the
  cache identity - they are not an observation of a real container.
- The owner's real-Docker canary (no model first, then one actual isolated model/check/review flow)
  and the full CI matrix on Windows and Linux remain owner work; they are not claimed here.
- A pinned image interpreter and byte digests still do not attest the immutability of the
  dependencies installed in that image; the host prepares them.
- Whether the installed Claude CLI honours the delivered permission rules is decided by that canary,
  not by this configuration, which only records the delivery digests.
- The foreign-evidence correction is verified by the focused
  `tests/test_operation.py`/`tests/test_fleet.py` regressions and the linter only: a pure projection
  change over `MemoryStore` fixtures, with no live database, model or container run behind it.
