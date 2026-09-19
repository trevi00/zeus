# Local operations desk 001 — frontend note (parts A + C)

Worker: Claude, isolated Zeus worker (Linux), 2026-09-19. Task-recorded base `9b194278…`, SPEC base `e67842a…`; git is unreadable here
(dubious ownership, git commands denied by tool policy) so no revision was confirmed locally. Replaces the earlier notes; behaviour is
unchanged except where stated. No backend file edited.

Accounting (`lib/accounting.ts`, both decoders). `interpretAccounting(accounting_mode, budget.mode)`, `undefined` = absent. Both absent →
`finite` (legacy shape). Exactly one present → that explicit mode (`top_level`/`budget_mode`): one statement is the only statement, so
`subscription` without `budget.mode` reads subscription. Both present and equal → that mode; both present and different, or any off-contract
value (`null`, wrong type, unknown string) → `unknown`; never silently finite, never "no ceiling". Subscription numbers are captioned
이관 메타데이터 · 호출 수 상한 미적용, finite keeps true ceilings, and the reading, its basis and the raw wire values stay in the report JSON.

Owner delivery (live 팀 작업 + pinned report). `readDelivery` in `lib/snapshot.ts` narrows the optional per-job `urn:zeus:owner-delivery:1`
document; `views/fleet.tsx` and `lib/report.ts` both use it. Merge and deploy stay separate, the label says `owner_recorded` (the owner's own
report, not GitHub verification), a null deployed revision is 확인 불가, no record is unknown — never 미배포 — and an off-contract record is
shown as unreadable. The sample counters now narrow `delivery` by truthiness alone (`null` and `false` are both falsy), removing the
`!== false` comparisons the owner's `npm run build` rejected as TS2367 in `views/fleet.tsx`.

Desk (`lib/desk.ts`, `views/desk.tsx`). Exactly the four implemented routes; POSTs carry `Content-Type: application/json` and
`X-Zeus-Desk: 1`. Status, `urn:zeus:desk:1` schema and row shape are all checked. Only an explicit 4xx (validation/conflict) decides a
submission; a rejected or aborted fetch, the 8s deadline, an unreadable or off-contract body AND any 5xx with a fixed code (503
`desk_unavailable`) are uncertainty — never "sent", never "not stored". The deadline and the caller's cancellation now stay connected through
the body read, an already-aborted caller never opens a connection, and timer and listener are released in one outer `finally`. Both a message
(id + body) and a session creation (id + title) are written to `localStorage` and read back BEFORE the POST: if the write cannot be verified
the screen refuses to send and says so, instead of holding the identity in memory only. A frozen identity is released only by the server (an
authoritative answer, a 4xx refusal, or the record appearing in the session list or history), so there is no erase-unresolved button and the
create title stays frozen while uncertain; a retry reuses the same id and body, so the desk replays instead of calling the provider twice.
History reads (poll, manual refresh, post-send) run one at a time on a single promise chain and each carries a number, so an older answer
cannot replace newer history; unmount aborts and blocks state writes; the shown session is derived per session id instead of being cleared in
an effect, and refs are written only in effects and handlers — the patterns the owner's `npm run lint` flagged at desk.tsx 153/156 and
194/199. Receipt ids, reason codes and the server's authority wording sit inside `자세히` details; visible copy states action and outcome.

Checks. Run here: `python -m ruff check .` (backend unchanged; says nothing about TypeScript). `node_modules` and npm are absent from this
worker, so **this TypeScript has never been compiled**: `npm run lint|typecheck|build`, the deterministic 503 and body-timeout probes and the
browser replay/reload/selection turns are the owner's, and the packaged bundle under `resources/observatory/assets/` stays stale.
