Read `ticket_review.py`, the `review`/`_evidence` changes, the CLI branch and the parser. The read-only property holds: `review` calls `authority.policy()` (pure), `_evidence` (pure reads), then one transaction that only *reads* `tickets`, runs `verify_chain`, and compares the anchor without ever calling `_anchor` (`ticket_lifecycle.py:103-110`). No signatures, no subprocess beyond the git reads inside `policy()`, no network, no writes.

I verified the displayed hash is meaningful: `digest(x) == sha256(canonical(x))` (`domain/model.py:26-31`), so `"sha256:" + digest(packet)` is exactly the artifact ref `close` will compute from the same bytes the CLI already pinned via `raw == canonical(packet).encode()`. A reviewer comparing that hash is comparing the right thing.

Escaping is complete. Every interpolated string goes through `esc`; the only unescaped interpolations are `packet['revision']`, `packet['sequence']`, `row["index"] + 1` and `len(...)`, all of which `validate_packet` has already constrained to `int` before rendering. `people`, `signers`, `scope` and `criteria` are escaped at their construction sites, and `canonical(packet)` is escaped at line 81. The `next(...)` role lookup can't raise, since `policy()` guarantees `required_signers ⊆ enrolled`.

## Three defects

**1. Environment evidence can be starved of preview budget.** `criteria` is built at line 37, before the f-string body evaluates `document(packet['environment_ref'])` at line 75. Both draw from the same `remaining = 256 * 1024`. With enough criterion evidence, the environment section renders with `budget = 0`: empty `<pre>`, only the clip notice. The environment document is arguably the one a reviewer most needs. Render it first, or reserve a dedicated 64 KiB for it before the criteria loop.

**2. `solution_commit` is presented as verified but isn't.** `close` requires `merge-base <commit> HEAD == <commit>` (`ticket_authority.py:116`), and `review` never runs it — reasonable, since it lives in `verify` alongside signature checks. But the HTML shows 해결 커밋 in a plain `<dl>` next to genuinely validated fields, so a reviewer will read it as established provenance. Either run the `merge-base` check in `review` (bounded local git call, no mutation, consistent with the `policy()` reads already happening) or label it as not-yet-verified in the markup.

**3. `write_export` will reject regeneration across the expiry boundary.** There's no generation timestamp in the body, which is right — but `time_status` is computed from `now` (`ticket_lifecycle.py:111-113`), so the same packet rendered before and after `expires_at` produces different bytes. Re-running `review-close` to the same path then fails with "Export exists with different content; choose a new path", which doesn't hint that expiry is the cause. The content genuinely changed, so failing is defensible; a clearer message or a documented note would save someone a confusing minute.

## Minor

`current.get(k, 0)` at `:105` uses `0` as the default for `content_hash` and `status`, where two missing values would compare equal. Not reachable — `Tickets.get` already populated both — but `object()` or an explicit sentinel would be more obviously correct.

## Assessment

Approve after defects 1 and 2; 3 is a message-quality call. Nothing here weakens the honesty boundary — the "제출 결과: 통과 · 사람의 승인 여부는 확인되지 않았습니다" per-criterion framing and the prominent empty-`required_human_signers` warning do exactly what I'd hoped, and `approval_granted: False` travels in the CLI return. Browser rendering, XSS unit tests and the state-unchanged test remain yours to run; FA-029 and #30 stay open.