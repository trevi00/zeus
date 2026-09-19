# Short runtime layout — verified 2026-09-19

**The Windows snapshot/replay preparation blocker is resolved for the retained candidate using
the short runtime root `D:/workspaces/zeus/artifacts/rp003`.**

The owner ran the production DockerEvidenceInspector with the existing immutable image and
unchanged evidence policy. Each original command ran twice in a fresh container; no provider
token, service credentials or network were supplied. No model calls or acceptance records changed.

| Actual check | Result |
|---|---|
| Candidate | d491e1de50a412fc1d2da1dac55fc99ab0d97f5e |
| Maximum projected snapshot path | 235 characters |
| pytest replay1 / replay2 | each21passed,1skipped; exit0 |
| lint replay1 / replay2 | each passed; exit0 |
| Inspected command claims | 2 checked,0 failed |
| Owned containers | 4 created, confirmed stopped and removed |
| Unresolved runs | 0 |
| Candidate files, HEAD and clean status | unchanged |
| Machine calls | 180 before /180 after; ceiling181 |

Commands:

```
python -m pytest tests/test_research_program.py tests/test_research_program_cli.py -q -p no:cacheprovider
python -m ruff check .
```

The skipped test requires PostgreSQL integration; these credential-free containers did not run
that test. This does not replace the separate earlier Windows/PG owner checks or claim a full suite.

Raw receipt and archived stdout/stderr: `D:/workspaces/zeus/artifacts/rp003/receipt.json` and its
`artifacts/` store. The receipt binds the source candidate, original failed inspection, short runtime,
all four container identities, image, controls, exits and cleanup. Hashes are recorded below.
The previous failed inspection remains unchanged in PG. This new owner verification does not
retroactively accept the failed autonomous operation or replace its missing model review.

The runbook now prescribes the short runtime layout and a per-revision path calculation. This
is an applied owner configuration correction, not a general Windows long-path implementation.
Future longer source paths require rechecking. No active workspace was moved, no registry changed,
and no merge/deployment/full council retry occurred. The prior diagnostic-log residual remains.

| Evidence file | SHA256 |
|---|---|
| D:\workspaces\zeus\artifacts\rp003\receipt.json | d36c3ef10a89dc62ad109d8afcc580a63a4213c008eebc96891e249402fe6702 |
| D:\workspaces\zeus\artifacts\research-program-001\run002\verify-short-root.py | 79883b45c27ab598b0ed46c98dcf49ff5461de5785d8b78ab3950b9a26968539 |
