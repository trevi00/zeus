**Approved. No blockers.**

You were right that renewing only after the authority block doesn't help — verification itself can exceed the lease, and my suggestion only moved the boundary. Renew-before-each-bounded-call is the correct shape.

## Verified

**`_renew` cannot revive an expired lease** (`github_tickets.py:75-79`): it calls `_owned` first, which requires the row to be owned *and* `lease_until > now`. Once expired, every heartbeat fails and `sync` goes to the `except` path. That preserves the existing expired-lease guarantees intact — the new heartbeat is strictly a renewal of a live lease, never a resurrection.

**Every unbounded-latency segment is now covered.** `policy()` heartbeats before each of its three `git` reads via the `read` wrapper (`ticket_authority.py:25-28`); `verify` heartbeats at the top of each signature iteration (`:83-84`), so each 30s `ssh-keygen` is preceded by a fresh 300s lease; and again before `merge-base` (`:114-115`). `verify_closed` threads it into both `policy` (`:179`) and `verify` (`:184`). Since every call between heartbeats is individually bounded well under 300s, total wall-clock no longer matters — which is what the 120s-per-heartbeat clock test demonstrates. The post-authority renewal at `github_tickets.py:106` covers the gap to the first remote call.

**Reopen projection now full-chain** (`:98-101`) — the last asymmetry I flagged is closed.

**Reopen return shape is consistent** across both paths: `:159-160` (replayed) and `:166` (fresh), both `{decision, replayed, verification}` with `not_required_authority_removed`. That reads correctly — it states the authority position rather than implying a verification occurred.

**`_evidence` single bounded read** (`:82-86`): `text(ref, 1MiB)`, then `json.loads` on that same string, then `body == canonical(document)`. No second unbounded `document()` call, and requiring canonical bytes closes the door on non-canonical evidence that would hash differently than it validates. Existing evidence written via `put(canonical(...))` — including the CLI import path — satisfies it.

**`valid_before` rechecked post-verification** (`ticket_authority.py:118-120`) against `finished`, covering every seen principal. Combined with the existing pre-check and the commit-time check in `close`, a signer expiring mid-verification can no longer slip through.

## Accepted decisions

Conservative reassert-OPEN as a real new cycle, documented as superseding in-flight work with a test proving the old binding and dispatch are invalid — that's a legitimate resolution of the item I raised; the safe direction is the right default and it's now pinned rather than incidental. Same for requiring local reopen plus fresh signatures to re-close after an external reopen.

## Minor, non-blocking

`_evidence` itself has no heartbeat while reading up to 8 MiB of artifacts inside `verify_closed`. These are local, bounded file reads, so the exposure is negligible — but it is the one remaining segment between heartbeats whose duration isn't subprocess-capped.

Code approval only, as scoped. Final test suite, real PG/GitHub test-issue acceptance, and WSL/CI remain outstanding; FA-029 and #30 stay open.