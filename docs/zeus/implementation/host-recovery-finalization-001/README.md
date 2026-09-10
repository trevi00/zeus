# Current-PC recovery handoff

The tested source is 0c66a678acc6653f553a62bf2a6b1f7de205bad7. It fixes the
Compose compatibility failure from c651ac4 without weakening the interruption
checks. Application source and scripts/host_cycle.py remain unchanged.

The final CI run is https://github.com/trevi00/zeus/actions/runs/34434703972.
Read ci.json for its completed status. Its real integration log records Compose
2.38.2, 1208 passed / 8 skipped in the main integration suite, and 15 passed /
1 skipped in the separate Docker suite. The native suspension case skipped in
the latter step already runs in the main integration environment.

Corrected local measurements are in ../host-recovery-ci-fix-001/: Windows full
911 passed / 305 skipped, Windows targeted 66 passed, Ubuntu interruption
6 passed. The initial failure and all real Claude review sessions are retained.

armed.json is preparation evidence only. It starts Windows and Ubuntu heartbeat
workers on an isolated schema of the current real ledger and does not initiate
or prove any host restart. Save work and use Windows Restart within three hours
of preparation, then run `uv run python scripts/host_cycle.py verify` from the
Zeus repository. Let verification finish; retries use the existing bounded attempt
budget. If the preparation expired, inspect it before cancelling and preparing again.

The current ticket is revision 2 and remains OPEN. Actual Windows boot recovery,
PC sleep/resume, WSL interruption recovery and isolated real OS clock-step
observations remain required. A signed approval cannot replace missing measurements.
Full reference absorption is also incomplete. Samsung device work remains deferred.
