# Owner research / decision packet for the DGE control implementation

Date 2026-09-16. Zeus base cc0c4057ad362149cfe472d42b908a2da0a003a5.
Task specification 2baaa4ecdf78bfe9482a540b7e3fb5c17ac732b3.

## Questions that change this design

1. Does Baldrix research before debate? The inspected protocol has research inside the planner
   step. The user requires a prior frozen meeting packet; therefore adapt, do not copy routing.
2. Does original convergence prove verified knowledge? No. The command explicitly treats
   orchestrator-authored verdict events as a trust assumption. evaluate_convergence compares
   verdict/snapshot and detects conflicts; it does not verify source truth or implementation.
3. Is a new worker engine needed? No. Zeus Operation already implements real Claude generation,
   evidence inspection and Codex review. Add the design check inside its durable claim transaction.
4. Can the first delivery claim automated debate? No. Its role submissions are trusted operator
   attestations. Provider-backed research/debate provenance and formal graph promotion remain open.

## Source identity and read scope

Baldrix pinned cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2; bytes from
C:/Users/rudtn/zeus/.runtime/absorption/sources/baldrix/pinned. Read inertly, no source execution.

| Path | Git blob | SHA256 | Scope used |
|---|---|---|---|
| commands/harness-debate.md | 7e79260c6100f55556aa6fef8486d48280fba251 | 89e7c0d185d291f33008d459c5f233be619037c09f98281ef10f6dafc751149f | protocol/roles/convergence/cap in first 115 lines; tool output partially truncated, not full-file review |
| agents/harness-critic.md | 00248210e37bb9dc96cafa4dec84cd79b6a90781 | d47955fa281a1e94dfae72678470aa4033195d2862706e8ef8bb3fb75d58d970 | role, DGE distinction, output and critique rules; full 75 lines |
| scripts/lib/debate_convergence.py | 1a263a451eb1fda4263c66de7ed1842ba72afa04 | 71ad5209899dd540e7a26a96bc7397145c2979af686865cf87affc05bf6c0704 | conflict/snapshot/evaluate logic; bounded reads including 126-225; not whole subsystem execution |

Existing semantic review references: baldrix-agents-001/file-reviews.md and
harness-pipeline-contracts/review.md. The command's full-analysis ledger is still unreviewed;
this task does not overwrite its disposition or claim source subsystem closure. New code is an
independent implementation of user requirements, not an upstream code transplant/license clearance.

## Adopt / adapt / defer

Adopt design-vs-implementation distinction, explicit proposal/attack/arbitration and finite rounds.
Adapt research to a prior immutable Git-bound packet, verdicts to honest operator attestations,
material-vs-minor triage, exact plan binding and PG transactional state/idempotency.
Do not adopt critic bypass, convergence-by-repeated-snapshot as a verification proof, automatic
formal ontology write or any upstream assertion that a role label proves independent execution.
Defer automatic independent role dispatch/provenance and post-verification graph promotion.

No external API/version question is required to choose this design: the load-bearing primary
sources are local pinned source contracts and current Zeus call sites. Internet trend collection
would not resolve a remaining acceptance question and was not performed.
