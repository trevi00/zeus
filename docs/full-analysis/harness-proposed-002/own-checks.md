# Own artifact checks

- `python docs/full-analysis/harness-proposed-002/build_index.py`: passed after correcting the local recorder's ledger key from status to disposition.
- `.venv/Scripts/ruff.exe check --no-cache docs/full-analysis/harness-proposed-002/build_index.py docs/full-analysis/harness-proposed-002/validate_index.py`: all checks passed.
- `python docs/full-analysis/harness-proposed-002/validate_index.py`: passed, including raw SHA-256/Git blob/byte length, prior row identity, ranges, report anchors, JSON parsing, UTF-8, one trailing LF and whitespace checks.
- Human-readable report readback retained the distinction between historical claims, static code observations and zero current upstream executions. The mount-test unconditional denominator was corrected from four to three before final hashing.

These checks validate only this folder's records. No reference test, import, probe, collection, network request or operational action was performed. Four supporting files were read in full and twenty in partial ranges. Three supporting files are test assets; their existence and test syntax are not execution receipts.
