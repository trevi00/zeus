"""The `zeus` CLI output helper (M7 cli.py).

Layer: entry
Owns: emit (print one JSON document to stdout)
Does not own: the roots and the dispatch (the other modules of this package)
Entry points: emit
Contracts: none

Moved from M7 cli.py:39-40 (SOURCE e38aa722); `emit` is M7's verbatim. A leaf module, so the roots can import it
without a cycle through `entry.cli` (R-c3); `entry.cli` re-exports it.
"""

import json


def emit(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)
