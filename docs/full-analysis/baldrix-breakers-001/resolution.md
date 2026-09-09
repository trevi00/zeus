# Composite breaker joint review resolution

Root independently read all three primary bodies (28,465 bytes) at Baldrix
`cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`, then compared actual Claude review
and discussion in session `26cd1ac0-a918-4f4b-abc0-c5e002d4a87e`.
Scope SHA-256: `486f22b87fc9e170e280e10691430fa2dc270c00702cb7a0fe8a6037fde74551`.
The initial independent notes, raw responses, corrections and process receipts are retained.
This is a bounded review, not full caller closure or adoption approval.

## Agreed source findings and original execution

`composite.py` separates CLOSED/OPEN/HALF_OPEN and never automatically selects a replacement
model. Keep explicit transitions and distinguish operator advice from execution admission.
Its thread-unsafe warning asks callers for locks; atomic JSON replacement does not make
read/modify/write admission atomic. The `atomically` acquire claim needs that qualification.
No owner, generation, attempt or policy revision is bound to a returned bool.

Three isolated executions completed with return code zero: the original composite wrapper
(18 tests), original config wrapper (16 tests), and `component_observations.py`. See their
individual `.receipt.json`, stdout and stderr files. All 1,648 pinned source files remained
byte-identical. Docker used the recorded immutable image, network none, read-only source/root,
uid 65534, dropped capabilities, bounded resources and a 60-second internal deadline.

The component program called original methods with real temporary JSON/YAML and a filesystem
permission failure. It did not patch clocks, SUT methods, providers or SDKs. Observed:

- With an existing state directory made non-writable, two acquire calls returned true while
  persisted state stayed OPEN. `_save` ignores the atomic writer's failure result.
- Seeded HALF_OPEN with `probe_in_flight=false` admitted twice without reserving. This is an
  input-state case; reachability through a clean normal transition is not established.
- After a second object reclaimed a seeded old reservation, the old object's success closed
  the current slot. This was sequential, in one process, not a killed or live child experiment.
- A malformed JSON file remained malformed while snapshot became CLOSED and admission true.
  `history=null` raised TypeError; infinite trip count raised OverflowError. NaN cooldown
  admitted; NaN reservation age rejected the observed attempt.
- Slash replacement and `__` delimiter composition produced identical paths for distinct keys.
  An absolute project path escaped the breaker subdirectory in path construction, still within
  isolated scratch. That path case did not write or establish an exploitable live caller.
- Duplicating sibling keys changed the secondary decision; changing sibling order changed
  CLOSED to OPEN with the same per-mode histories. Concatenation is not event chronology.
- A Python bool override returned true and wrote `True`, but the effective reloaded threshold
  was the default 3. Raw version 99, negative threshold and zero window were accepted; zero
  window retained all 13 recorded history entries.

The original unit wrappers call the real SUT and real temporary files. They also inject clocks,
emitter callbacks or the config module path. Their 34 passes are not proof of actual process
concurrency, real provider invocations, human acceptance or native Windows/WSL behavior.

## Caller, policy and observation boundaries

Root's seven supporting records identify exact reads: four full bodies and three partial
ranges. `external_jury` acquires before retry, but model resolution and admission emission
can throw outside its result-recording try/finally. Permanent exception classification does
not prove provider reachability: local failures and ValueError-family decoding errors can
be recorded as breaker success. Dispatch history must be distinguished from physical attempts,
usage and model qualification. The jury deliberately disables the cross-mode rule; that alone
is not a defect. The sampled outcome hook records failures and leaves its success branch empty;
this does not establish absence of every other writer or every dynamic/document caller.

Policy objects are not runtime schema validation. Unknown versions, invalid numeric values,
cross-field relations, bool/int ambiguity and plain-file read/modify/write need explicit
handling. Literal safe/strong tokens are direction labels, not identity-bound authorization.
An equal-value no-op before token checking performs no mutation. Loss of an override can
either tighten or relax policy depending on its previous value. Per-result policy reloads
also fail to preserve the policy used at admission.

The 120-second probe TTL and source timeout bounds of 180/300 seconds show possible overlap,
not measured overlap frequency, actual request latency or holder death. A finite backward
clock change can delay recovery; it alone does not prove a permanent wedge. mkdir failures
and emitter exceptions differ from the observed existing-directory write failure.

## Corrections after discussion

Claude explicitly withdrew its initial static-as-measured labels, global no-caller/no-visibility
claims, permanent-OPEN language, unconditional finally-safety/provider-reached claims, timing
frequency and cost assertions, and an invented split of the supplied scope hash. Preserve
`claude-initial.md`; `claude-discussion.md` records the corrections rather than rewriting history.
Claude's additional operator-ledger/dashboard citations are its bounded supporting observations,
not new root primary coverage. Root's listed support remains the authority for root read extent.

Two discussion sentences still require precision. In C-1 the bool case *does* persist changed
file bytes; what fails is effective policy application, not every possible meaning of persistence.
In D-5 the remaining loader gaps are not limited to OverflowError/NaN: history null's TypeError
is also observed outside the relevant local coercion catch. Neither sentence narrows the
recorded observations. Supplementary claims about untested window overrides, actual process
kill/races, invalid-encoding policy reads and native platform behavior remain open.

## Zeus adaptation decision and remaining work

Adapt the explicit state machine concept after full analysis. Use PostgreSQL conditional
admission, owner/generation fencing and durable results tied to runner, attempt and Git policy
revision. Preserve missing/unknown/corrupt/repaired distinctions and write/notification receipts.
Reject stale-owner results; use canonical identities and unique ordered events for cross-mode
aggregation. Validate policy on read and write, including cross-field and finite bounds. A
healthy breaker cannot authorize SDD acceptance, model graduation or deployment.

FA-020 records this implementation topic and actual process/platform acceptance requirements;
FA-019 covers provider invocation and FA-018 covers completion authority. Root will implement
agreed behavior after the requested full source analysis. Source licensing, full transitive
closure, Windows/Linux/WSL process behavior, real model/canary execution and human acceptance
remain incomplete. No live harness was changed, and no adoption or pilot readiness is claimed.
