"""Permanent entry shim (§3.5): `python -m codex_harness.adapters.artifact_reader --root R --ref sha256:… …`.

Kept by the corrected S0 pinned-argv scan (`static.source.json` `shims.conditional`, keep_shim true; OWNER-DECISIONS-S11
#11): the multi-line reader argv of M7 `executor.py:252-253`, which `context.domain.composition.artifact_reader_handle`
hands to agents. It only delegates.
"""
from codex_harness.entry.processes.artifact_reader import main

if __name__ == "__main__":
    raise SystemExit(main())
