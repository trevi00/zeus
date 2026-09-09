Read all four. Findings below are bounded to these files.

## Verdict

The direction is right and the diagnosis checks out, but the proposal as stated will break the discovery path and make an already-unrecoverable failure mode more frequent. Six must-fix items before merge.

## Confirming the root finding

`sync` reads `title,state` at `github_tickets.py:32` and then uses only `issue["body"]`. Title is written unconditionally (`:94`) and state is never examined, so a remote CLOSED issue is recorded `status: "synced"` (`:109`). The sharpest real-world case is the **no-op path**: when `digest(issue["body"]) == digest(body)` the write is skipped entirely (`:87`), so a remote issue with the correct body and an externally edited title returns `synced` and is never even corrected. FA-029's own record (issue #30) has `body_hash` and no title field, so it will hit exactly this.

The write trigger must become `issue is None or body differs or title differs`.

## Must-fix

**1. Discovery path has no title/state — production KeyError.** `issue list` requests only `number,url,body` (`:68`), so `matches[0]` has no `title`/`state`. Any title/state comparison against a discovered issue crashes or silently skips. Fix by calling `_read(repository, matches[0]["number"])` after discovery so both branches produce one uniform full artifact. Do not just widen the `--json` list — the readback helper should be the single source of remote shape.

The test fixture hides this: `call` at `tests/test_github_tickets.py:26` returns the whole `state["issue"]` for `issue list`, including `title`/`state`/`comments`, which real `gh` does not. **Project the fixture return by the requested `--json` fields** — this is the highest-value test change in the patch and is what would have caught the bug class.

**2. The "changed externally" conflict is a permanent dead end, and you are about to add two more ways in.** `pull` (`:123`) records an observation but never updates `link["body_hash"]` and never clears anything, so once `:77` fires, sync can never succeed for that issue again — there is no adopt/reconcile path anywhere in these files. Adding title and state conflicts multiplies entries into that state. Land a reconcile step (e.g. sync accepting an explicit `ticket_remote_observations` ref as authorization to re-baseline) **in the same patch**, or the fix converts a wrong-status bug into a stuck-sync bug.

**3. Legacy links without `title_hash` must not become permanent conflicts.** Mirroring `:78`'s `link["body_hash"]` fallback with `link["title_hash"]` will KeyError, and treating missing-as-conflict strands every existing link — including #30 — with no way out given (2). Recommended policy, stated explicitly in code and in a test: a link lacking `title_hash` is *untracked*, not tampered — persist the observed title artifact, backfill the hash, do not block. Absence of a field is not evidence of external edit.

**4. Conflict evidence is destroyed before it is preserved.** `:77` raises before anything is written, so the external body is lost; the same would happen for title. The observation must be committed *before* the `require`. Reuse `pull`'s exact path (`artifacts.put(canonical(remote), ...)` + `ticket_remote_observations`) via one shared `_observe(...)` helper with a `purpose` field (`pull` / `pre_write` / `post_write`), and link the receipt refs into `record`. `Tickets.get` already surfaces that table as `external_observations` (`tickets.py:105`), so no new store table and no reader changes.

**5. Readback lengthens the critical section past the lease.** The lease is 300s (`:42`), each `_call` has a 60s timeout (`:25`), and readback adds a fourth call. `_owned` is only checked at `:81` and `:105` — never before the write at `:89`. If the lease expires mid-flight, the write lands and the finalization raises, leaving no record, while another owner may have claimed and written concurrently. Fix: renew the lease immediately before the final transaction (or set it strictly above the sum of call timeouts), and re-verify `_owned` after readback, treating loss-of-lease as `needs_attention` with the readback artifact retained rather than overwriting the other owner's record.

Related, and cheap: after the create receipt parses (`:97-99`), persist the issue number into `ticket_syncs` **before** the readback. Today a create that succeeds and a readback that fails leaves recovery dependent on GitHub search indexing, which `test_lost_ack_does_not_create_duplicate_even_before_search_indexing` shows is not reliable.

**6. One normalization domain, applied everywhere.** GitHub can return CRLF and strip trailing newline. If readback becomes a hard `require`, an unnormalized comparison makes every sync fail. Define one `_normalize` (CRLF→LF, single trailing `\n`) and apply it at `:77`, at readback, and when computing the stored `body_hash`. No migration is needed — `render_ticket` (`tickets.py:185`) already emits normalized text written with `newline="\n"` (`:92`), so `normalize(body) == body` and existing hashes stay valid. Say that in the commit message so nobody re-derives it.

## Other concrete points

- **State comparison has no local counterpart yet.** There is no closed status in `Tickets` — that is what FA-029 is for. The only sound rule now: if remote state is not `OPEN`, do not write, do not mark `synced`, record the conflict and the observation. Do not auto-reopen, do not derive any local status. The adapter must keep never writing to the `tickets` table; assert that in a test.
- Fetch `stateReason` alongside `state` now and store it in the record/observation. Close-vs-not_planned matters for the receipt-bound lifecycle and this avoids a second schema pass.
- **Prune the accepted-hash set on success.** `observed_body_hash` (`:85`) is the *pre-write* remote body and is never cleared on success (only `pending_body_hash` is, `:113`). It stays in the accepted set at `:77` forever, so an old body silently reads as non-external. With title hashes added the same set grows monotonically and the check weakens over time. On success, set observed to the readback hashes and clear the rest.
- Adding a `status` value like `state_conflict` requires checking consumers of `ticket_github["status"]` (CLI/render) — outside the files I was asked to read, so verify before introducing it; otherwise reuse `needs_attention` on the sync row and keep `ticket_github.status` a closed set.
- Store the literal remote `title` next to `title_hash`. It is short, and reconcile is unusable if the operator can only see a hash.
- Preview (`test:89`) is genuinely pure and the assertion is adequate. Since the API title becomes a compared field, have preview print the exact title it will send — it is currently only visible as the `# {title}` line inside the body.

## Tests that would actually distinguish behavior

Beyond the fixture projection in (1), none of these exist today:

1. External title change, body untouched → `ContractError`, `edits == 0`, observation preserving the external title exists.
2. Body matches, title differs → an edit **is** issued (guards the no-op path).
3. Remote `state == "CLOSED"` → no write, not `synced`, no row written to `tickets`.
4. Readback divergence (fixture mutates body after write) → not `synced`, pending hashes retained, next sync recovers without a duplicate.
5. Legacy `ticket_github` row constructed without `title_hash` → asserts the chosen policy from (3) explicitly.
6. Lease forced into the past between the pending transaction and finalization → no record written, sync row `needs_attention`. `test_parallel_sync_claim_cannot_publish_twice` only covers claim contention, not mid-flight expiry.

## Scope

Agreed that this fix does not close FA-029. It addresses acceptance criterion 5 (observe external state/title changes, flag conflict, never fabricate local acceptance) and part of 4. Criteria 1, 2, 3, and 6 — receipt-bound close/reopen, resumable PG/GitHub split, real verification — remain open. The commit should say so; do not touch FA-029's status.