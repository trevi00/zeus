**Approved. No remaining blockers.**

Both conditions are correctly fixed:

**Environment budget** — `environment_preview = document(packet["environment_ref"])` is now evaluated at `ticket_review.py:32`, before `criteria` is built, so it draws its 64 KiB from a full `remaining` and the string is merely interpolated at line 76. `test_environment_preview_survives_exhausted_criterion_budget` drives five copies of a 100 KB criterion document past the 256 KiB total and still asserts the environment marker is present alongside the truncation notice — that fails against the old ordering and passes now, which is exactly the right shape.

**Merged ancestry** — `require_merged` (`ticket_authority.py:126-129`) is shared: `verify` calls it at `:116` (preserving the heartbeat placement) and `review` at `ticket_lifecycle.py:103`. Note it now also revalidates the commit format, so `review` rejects a malformed commit on the same path. The test builds a genuine orphan via `commit-tree` and rewrites the evidence documents' `solution_commit` so the packet is internally consistent — meaning the failure can only come from the ancestry check, not from an evidence mismatch. That is the correct way to isolate it.

The read-only ordering is right: evidence validation, then ancestry, then a single transaction that reads `tickets`, walks the chain, and compares the anchor without writing. `test_review_cli_is_read_only_and_preserves_canonical_signing_file` pins it three ways — `tx.records()` unchanged, artifact files unchanged, and `authority.verify` monkeypatched to fail if called. The idempotent second `execute` returning an identical result also confirms `write_export` reuse behaves as intended.

The XSS test parses the output with `HTMLParser` and inspects emitted tags and attributes rather than string-matching, so it would catch an injected `onerror` attribute, not just a literal `<script>`. That's stronger than the usual substring assertion.

Re-export across the expiry boundary requiring a new path is a reasonable documented choice — the bytes genuinely differ.

FA-029 and #30 remain open; browser rendering and the full suite are yours to run.