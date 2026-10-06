"""Permanent entry shim (§3.5): `python -m codex_harness.cli ...` and the `zeus`/`harness` console scripts.

The M7 dotted path (`codex_harness.cli:main`, `parser`, `emit`); it only delegates to `codex_harness.entry.cli`.
"""
from codex_harness.entry.cli import emit, main, parser

__all__ = ["emit", "main", "parser"]

if __name__ == "__main__":
    main()
