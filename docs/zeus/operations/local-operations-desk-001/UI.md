# Local operations desk 001 — frontend note (parts A + C)

Worker: Claude, isolated Zeus worker (Linux), 2026-09-19. Task base `35749fda…`; SPEC base `e67842a…`; git is
unreadable here (dubious ownership; follow-up command denied by tool policy) so no revision was confirmed. This
replaces the longer part-A note; part-A behaviour is unchanged except where corrected below. No backend file edited.

Accounting (`lib/accounting.ts`, both decoders). `interpretAccounting(accounting_mode, budget.mode)`, `undefined` =
absent. Both absent → `finite` (legacy shape). Exactly one present → that explicit mode (`top_level`/`budget_mode`):
one statement is the only statement, so `subscription` without `budget.mode` now reads subscription, correcting the
part-A note's `conflict` row (SPEC part C). Both present and equal → that mode; both present and different, or any
off-contract value (`null`, wrong type, unknown string) → `unknown`; never silently finite, never "no ceiling".
Subscription numbers are captioned 이관 메타데이터 · 호출 수 상한 미적용, finite keeps true ceilings, and the
reading, its basis and the raw wire values stay in the report JSON.

Owner delivery (live 팀 작업 + pinned report). `readDelivery` in `lib/snapshot.ts` narrows the optional per-job
`urn:zeus:owner-delivery:1` document; `views/fleet.tsx` and `lib/report.ts` (`StoryJob.delivery`, drawn by
`report-story.tsx`) both use it. Merge and deploy stay separate, the label says `owner_recorded` (the owner's own
report, not GitHub verification), a null deployed revision is 확인 불가, no record is unknown — never 미배포 — and an
off-contract record is shown as unreadable, not as facts. `검토 수락` still never implies delivery.

Desk (`lib/desk.ts`, `views/desk.tsx`, `App.tsx` nav 대화 창구). Exactly the four implemented routes; POSTs carry
`Content-Type: application/json` and `X-Zeus-Desk: 1` (the browser supplies the same-origin `Origin`). Status,
`urn:zeus:desk:1` schema and row shape are all checked; a fixed `{error}` code is authoritative, anything else
(rejected or aborted fetch, 8s deadline, unreadable or off-contract body) is uncertain — never "sent". Client UUIDs
are stable: an uncertain submission keeps id+body in `localStorage` across reload and is retried identically, so the
server replays instead of making a second provider call. Selected session persists; polling is selected-session-only,
stops while hidden, aborts on selection change, and a stale response is discarded. Send is disabled while busy, while
a submission is unresolved and while a turn is open; 409/503 surface as their own reason. `request` is shown as an
accepted proposal (`needs_spec`), answers carry the server's unverified-context authority line, the flow picture
marks only recorded stages, there is no model/base/command/budget control, and user text never reaches the console.

Checks. Run: `python -m ruff check .` (backend unchanged; says nothing about TypeScript). Not run here, left to the
owner as the SPEC directs: `npm run lint|typecheck|build`, real browser desk turns, mobile and print passes, and the
finite/subscription/conflict fixtures. `node_modules` is absent and npm is outside this worker's profile, so **this
TypeScript has never been compiled**; the packaged bundle under `resources/observatory/assets/` stays stale too.
