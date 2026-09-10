# Current PC recovery: measured progress, not closure

Source commit: `c651ac464aa8ce0db55148d5f8c437c7ef619495`. Application runtime source is unchanged in this slice.

Ticket ZEUS-3875a025c20d / GitHub #18 is OPEN at revision 2. Revision 1 acceptance inputs do not satisfy revision 2. This work does not complete full reference absorption.

## Corrected current-host configuration

The running PostgreSQL ledger had an empty host-port binding and restart policy `no`. Its replacement pins the existing `127.0.0.1:63556` address and uses `unless-stopped`, preserving the exact image, environment, PGDATA, volume, commands and health check. A custom database dump was restored into a separate volume and all canonical table hashes and sequences were compared before cutover. Two container starts and a subsequent Docker Desktop stop/start retained the address and data. Zero database sequences exist; workflow records live in JSON document buckets.

The original container remains stopped as configuration rollback. The private dump is the data backup. Never start both containers against the same volume. Secrets, the dump, globals and full inspect are retained only under `.runtime/host-ledger-repair/` and are not published.

Docker Desktop AutoStart was false; it is now enabled. Ubuntu integration is enabled and its real Docker CLI connects to the daemon. `desktop-restart-verified.json` records the actual post-restart data comparison. This does not yet prove Windows login autostart.

## Independent review and tests

Root and the real local Claude CLI reviewed and discussed findings; root made the changes. Raw prompts, outputs and receipts preserve the sequence. Claude identified private-schema fallback and interrupted-verification lease reuse defects; both were corrected. Its final followup found no concrete blocker before arming. Review is not execution evidence.

Six actual interruption tests cover native worker suspension past deadline, two PostgreSQL pause lengths, rollback of an uncommitted transaction across restart, outage past a durable deadline, and refusal to fall back into public tasks when a private probe table is missing. Owned disposable containers and schemas are cleaned up. No worker pause is labelled host sleep and no stored-time mutation is labelled a real clock step.

Final Windows targeted execution: 66 passed (see `target-tests.json` and log); `native-verified/` contains measurements. `pre-final-*`, `native/` and `native-final/` are earlier runs, not the final source validation. Native Ubuntu ran the same six interruption cases: 6 passed (`wsl-target.json`, `wsl-native/`). Windows full suite: **911 passed, 305 skipped** (`full-tests.json` and log). Required external-environment cases skipped by the ordinary suite are measured separately; skips are not passes. CI for the source commit is tracked separately. Smart App Control blocked the pytest launcher, so tests use the allowed `uv run python -m pytest` interpreter entrypoint without disabling security policy.

## Real Windows restart procedure

`scripts/host_cycle.py prepare --wsl-python <persistent interpreter>` creates a private schema and starts real Windows and Ubuntu heartbeat workers. The durable interpreter path is recorded in `persistent-wsl-runtime.json`. The trial actually prepared both workers, rejected an unchanged Windows boot marker and cancelled/removed its schema; `trial-receipt.json` is explicitly not boot proof.

After a final prepare, save work and use Windows **Restart within three hours**. Return to Zeus and run `uv run python scripts/host_cycle.py verify` to completion. Do not edit the probe or application during the cycle. If Docker has not returned, verification waits. A changed Windows boot marker, changed WSL boot marker, retained container/volume/address, expired original leases, new execution generations, rejected stale writes and completed continuation are required. Per-generation checkpoints allow interruption recovery within the existing attempt budget (two post-prepare claims), without resetting that budget. If the budget is exhausted or workers stopped before the boot, the result is inconclusive.

The result distinguishes a verified Windows boot transition from restart-versus-power-on classification, which is not independently measured. The operator action is Windows Restart. Preparing or reviewing does not reboot the PC and does not count as a pass.

## Still required

Actual Windows restart observation; actual PC sleep/resume observation; WSL interruption recovery observation; and a real OS clock step in an isolated VM. Docker Desktop recovery is measured, but does not replace these. Human review/acceptance remains downstream of measured evidence. Samsung devices are deferred and multiple hosts are outside this single-PC readiness scope. Issue #18 must remain open until its current acceptance criteria are satisfied.
