# Original calibration observations after the independent root review

The initial review preceded execution and remains unchanged. Root then read operator_ledger.py
lines 71–137 for the project identity helper. One original threshold-tuning unit wrapper and
one separate component program completed with return code zero. Receipts retain the exact argv,
immutable image, source tree digest and stream hashes. All 1,648 source files stayed unchanged.

The original unit wrapper passed 16 tests, using actual SUT methods/files together with mocked
registry/path objects and synthetic telemetry. The separate program used original methods,
real isolated JSON/YAML/ready files, synthetic outcomes and the source's literal policy token.
It did not patch clocks, methods, providers or SDKs. Neither execution is authenticated human
approval, real model quality, actual incident distribution, process concurrency or native
Windows/WSL acceptance.

Observed in `components.stdout.txt`:

- A generated flag suggested 4 from current 3. Applying 999 returned true and reloaded as 999.
  The next proposal still reported current 3 and suggested 4.
- A same-name flag containing malformed JSON still permitted applying 1000. An empty flag
  permitted NaN, and the effective override reloaded as NaN.
- A threshold above every score produced an admit-precision metric of 1.0. The generic
  threshold gate accepted 3→999 on this synthetic corpus. This is a direct gate call, not
  evidence that the single-step proposer itself proposes 999.
- A partly unsized event returned non-truncation rate 1.0. The observation does not measure
  the unknown body's actual size or prove real context overflow.
- Ten records with success false and empty failure modes produced sample 10, success 0,
  failure 0 and success_rate 1.0. A repeated fabrication mode counted 3 for one failure.
- A JSON array record raised AttributeError. The output field `scalar_record_exception` is
  imprecisely named: the actual injected value was `[]`, a non-object array, not a scalar.
- A seeded breaker with ten failures out of ten and trip count 5 suggested raising 3→4.
  Corrupt breaker JSON yielded zero-history CLOSED statistics rather than None.

These measurements support the state/approval and metric-boundary concerns in the initial
review. They do not establish current live exploitation or a complete caller audit. Actual
Claude discussion, additional caller/test closure, licensing and platform acceptance remain
pending at this observation checkpoint. No source or live harness policy was edited.

After reading Claude's initial response, root additionally read skill_token_budget.py in full
and skill_match.py lines 40–67 and 391–474. The consumer selects on base scores while recorded
top-five telemetry uses boosted scores, so the metric replay is not the same decision function.
Current apply_token_budget calls fit_top_skill to bound the top body. Its old docstring and a
skill_match comment still describe the former top-body budget bypass; that historical behavior
must not be reported as current. These fresh support reads are recorded separately from the
earlier independent initial review and do not add primary coverage.
