# research-program-001 — packet producer alignment (Claude implementation, 2026-09-19 batch)

Producer alignment only. This batch changes the researcher's model-facing output schema and
guidance so that they state the packet contract the live cycle 1 output violated. It does not
complete the live path, retry the council, touch program state, budget, the diagnostic-log residual
or deployment, edit the owner SPEC, or claim that a live model will follow the guidance.

## What was wrong (from RESULT.md, unchanged artifact)

The real researcher output of cycle 1 passed the execution output schema and was refused by
`packet_from_research`: answered question `q3` cited claim `c11` of kind `unknown`. The consumer
(`domain/dge.py::_questions`) has three question rules; the producer schema (`adapters/autonomous_roles.py`
`QUESTION`) stated none of them and `OBJECTIVES[researcher]` never named the reference rule:

| Consumer rule (`_questions`) | Can a local item schema state it? | Before | After |
|---|---|---|---|
| answered ⇒ nonempty `claim_ids` | yes (`minItems`) | not stated | answered variant, `minItems: 1` |
| unknown ⇒ `blocking` false | yes (typed `enum: [false]`) | not stated | unknown variant, `blocking` enum `[false]` |
| answered ⇒ every cited claim is fact/inference | no (needs the claims array) | not stated anywhere | stays the consumer's check; guidance + self-check in the objective |

## Files touched

- `src/codex_harness/adapters/autonomous_roles.py`: `QUESTION` is now `{"anyOf": [answered, unknown]}`
  built by `_question` from the shared `QUESTION_STATUSES` constant (`ANSWERED_STATUSES`,
  `UNRESOLVED_STATUS`, mirroring `SOURCED_KINDS`/`UNSOURCED_KIND`), same five fields in both variants;
  the researcher objective gains the reference rule, the self-check, the "unknown stays unknown"
  instruction, the two honest forms of a "what remains unknown?" question and the instruction to
  report a truly blocking design choice honestly. Module docstring extended. No other role, schema,
  consumer, `role_schema` or `execute_role` behaviour changed.
- `tests/test_autonomous_roles.py`: matrix tests below; the enum-location test now joins the two
  question variants; two existing expectations updated (a bad status and a blocking unknown are now
  refused at the item's `anyOf`, instance path `["questions", 0]`).
- `tests/test_council_roles.py`: one added assertion that no council role schema carries `anyOf` or
  a `questions` field and no council objective carries the researcher self-check.
- `docs/contracts.md`: one paragraph appended to INV-AUTONOMOUS-001.
- This file.

## Acceptance matrix, actual tests (synthetic fixtures, no model called)

| SPEC item | Test | Observed |
|---|---|---|
| normal: fact/inference answered references pass schema and unchanged validator | `test_valid_full_role_output_passes_the_schema_and_the_consumer[researcher]`; `test_every_local_question_shape_is_admitted_exactly_when_the_consumer_accepts_it[cited-*-answered]` | pass |
| failure: answered+unknown still fails the domain validator; no coercion or retry | `test_live_answered_question_citing_an_unknown_claim_fixture_is_still_refused_and_the_honest_forms_pass` (`PacketError: ... cites only non-unknown claims`) | pass |
| local schema: answered empty refs refused, blocking unknown refused, nonblocking unknown accepted | `test_every_local_question_shape_is_admitted_exactly_when_the_consumer_accepts_it` (8 cases: status × blocking × empty/cited); refusals are `schema_mismatch`, owner `agent_output`, path `["questions", 2]`, no text echoed, and the consumer refuses the same cases | pass |
| relational limits: unknown-kind, mixed known+unknown, missing id, duplicate id pass the schema and stay consumer-refused | `test_relational_reference_limits_pass_the_schema_and_stay_consumer_refused` (4 cases) | pass |
| concrete recurrence: q3/c11 fixture rejected; honest nonblocking-unknown and sourced-limitation controls pass; relabelling is not a control | same recurrence test; fixture is labelled SYNTHETIC (`LIVE_UNKNOWN_CITED_CLAIM`, `LIVE_ANSWERED_WITH_UNKNOWN`), the saved live artifact is not read or changed | pass |
| provider: preflight accepts all roles; other role contracts unchanged | `test_every_role_schema_enum_is_the_consumer_constant_and_passes_preflight` (v1 roles: `anyOf` only in researcher, no `if/then/else/allOf`), `test_council_output_passes_the_schema_preflight_and_the_consumer` (council roles: no `anyOf`, no `questions`), `test_question_variants_state_the_two_local_consumer_rules_with_typed_anyof_and_never_the_cross_array_rule` | pass |
| guidance: explicit reference rule, self-check, meta-question, honest blocking | `test_prompts_name_the_finite_values_and_separate_design_unknowns_from_future_tests` | pass |
| restart/concurrency/cleanup | no new ownership, resources, primitives or runtime state; nothing to test here | n/a |

Commands run (Linux, `python` 3.13.15, base a7ab776bf25b175b91034f2bac8fdb9c0a748a17 plus this change):

```
python -m pytest tests/test_autonomous_roles.py tests/test_council_roles.py tests/test_autonomous.py tests/test_council.py -q -p no:cacheprovider
python -m ruff check .
```

Observed: 80 passed (baseline before the change: 66 passed); ruff "All checks passed!".

## Limitations and honest gaps

- Fixture behaviour is not model adherence. A schema the provider honours still lets an answered
  question cite an unknown claim; only the unchanged `PacketError` stops that, after a paid start.
  Nothing here estimates how often a live researcher will follow the self-check.
- A blocking unknown question is now refused at the model boundary (`schema_mismatch`) instead of
  at the packet. Both are the same stop with no retry, and the guidance tells the researcher to
  report it anyway. Owner decision to keep or revisit: the refusal reason moves from
  `packet_invalid:PacketError` to the executor's output failure.
- The disposable-copy check that the new tests fail against the old `QUESTION` shape did not run:
  the session refused the compound shell command needed to copy and patch a `/tmp` clone. By
  inspection, `test_every_local_question_shape_...` asserts `answer is None` for answered-empty and
  blocking-unknown, and `test_question_variants_...` reads `["items"]["anyOf"]`, both of which the
  old single-object schema cannot satisfy. The reviewer can confirm by reverting the `QUESTION`
  definition in a scratch copy.
- Read-only `git` was unavailable in this session (dubious-ownership refusal; the global config
  exception is a host setting and was not applied). The base revision above is from the task packet.
- Full suite, CI, Windows/PostgreSQL checks and any live council run were not executed and are the
  owner's. Remaining ceiling headroom is unchanged by this batch; no provider was called.
- The live execution artifact and capture (`RESULT.md` digests) were not read; the fixture reproduces
  the documented q3/c11 relationship only, with placeholder text.
