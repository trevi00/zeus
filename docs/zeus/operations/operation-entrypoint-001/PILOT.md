# Operating quickstart

Three steps for one bounded operation (manifest schema in RUNBOOK.md).

1. **Choose the pinned manifest.** Write `OPERATION.json` with `id`, `base_revision`, the
   goal path plus its Git sha256, the plan (objective, acceptance criteria, allowed paths)
   and the `budget` ceilings.
2. **Run it.** `zeus --repository ROOT operate run --file OPERATION.json`. Exit 0 only for an
   `accepted` receipt; anything else exits 1 with `status` and `reason_code`.
3. **Inspect it.** `zeus --repository ROOT operate status ID` reads the saved receipt only.
   Rerunning `operate run` with an already terminal id returns that receipt with
   `cached: true` and makes no new calls.

Execution ledgers, artifacts and audit records are not validated knowledge. This path has no
knowledge writer and no automatic merge; promotion and merging are separate human-owned steps.

Written by the pilot's worker; whether the pilot is accepted is decided by its later review,
not here.
