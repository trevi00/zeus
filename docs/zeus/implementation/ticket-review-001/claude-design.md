Read `sdd.py`'s export/render helpers and the current `ticket` parser. The design is sound and read-only by construction. Six things to settle before implementing.

## Blockers

**1. Don't compose the review from `verify_closed` — it mutates.** `verify_closed` calls `_anchor`, which *writes* `ticket_trust_anchors` on first use (`ticket_lifecycle.py:101-103`). A review that happens to run first on a fresh deployment would pin the anchor. Build `review` from `authority.policy()` + `validate_packet` + `_evidence` directly, and add a test asserting the store is byte-identical before and after generation (the pattern `test_preview_is_pure_and_does_not_call_github` already uses).

**2. Expiry will make the tool unusable exactly when it's needed.** `validate_packet` requires `issued <= now < expires` (`domain/ticket_lifecycle.py:41`) and `prepare` sets a 1-hour window (`:71`). A human who opens the packet 90 minutes later cannot generate a review at all, and a historical packet can never be re-rendered. Pass `now = timestamp(packet["issued_at"])` for structural validation and surface expiry as a prominent banner instead of a hard failure. Separately, consider whether a human-review workflow wants a longer `expires_at` — `validate_packet` already caps it at 24h, so `prepare` could accept an explicit duration.

**3. Reconsider the base64 `data:` download.** Chrome blocks top-level `data:` navigation, so the link may silently fail; more importantly, `prepare-close --output` already wrote the exact canonical file, and the reviewer should sign *that*. Two sources of the same signing bytes is a divergence risk. Better: display the packet's `sha256` and byte count prominently, show the canonical bytes in an escaped `<pre>`, and reference the on-disk path — so the human verifies rather than re-extracts. If you keep the link, add `download` and verify it in the real-browser check.

**4. Cap inlined evidence.** `_evidence` permits 8 MiB total; inlining that into one HTML file is unusable. Render at most ~64 KiB per document with the full ref, digest and byte count shown, and state that the complete document lives at the ref.

## Decisions to make explicitly

**5. `write_export` semantics vs "exclusive creation."** `sdd.write_export` (`sdd.py:50-62`) already enforces `.html` and `open("xb")`, but permits a rewrite when bytes are identical. If the HTML embeds a generation timestamp, regeneration always differs and raises "choose a new path" — friction on every retry. I'd drop the generation timestamp (the packet's `issued_at`/`expires_at` and `policy_commit` are the meaningful dates and are already deterministic), making output byte-identical, idempotent, and itself content-hashable. Then reuse `write_export` unchanged. Also `require` the output path is outside the artifacts root so a review can't be mistaken for a content-addressed artifact.

**6. Don't reuse the SDD render path.** `render_review` (`sdd.py:65-70`) injects JSON into a JS-consuming template, and its `<`→`\u003c` escaping is JS-string-context, not HTML-text-context — not reusable. Use `html.escape(value, quote=True)` for both text and attribute contexts. For CSP in a `file://` meta tag: `default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'` (inline `<style>` needs `'unsafe-inline'` or a hash; `frame-ancestors` is ignored in meta). Treat CSP as defense in depth — escaping is the control.

## Two details worth getting right

Emit `<meta charset="utf-8">` and avoid `ensure_ascii=True` for displayed JSON — FA-029's content is Korean and `\uXXXX` escapes would defeat the purpose. And make the honesty boundary structural rather than a footnote: render each criterion as "패킷이 통과를 주장함" next to the evidence document's own `observed_at`/`details`, and print `required_human_signers` in the header, saying so explicitly when it is empty. That mirrors what the proof already records and is the single most valuable thing the viewer can show.

Nothing here changes the design's shape. FA-029 and #30 stay open.