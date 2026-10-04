"""Entry of the exact-ref artifact reader process (INV-ARTIFACT-001).

Layer: entry
Owns: nothing; the M7 `__main__` stdout encoding step, then the one composition function
Does not own: the reader (`storage.adapters.artifact_reader`, reached through `composition.process_entries`)
Entry points: main
Contracts: INV-ARTIFACT-001

M7 `adapters/artifact_reader.py` `__main__` (SOURCE e38aa722): reconfigure stdout to UTF-8, then `main()`. Owner, int44
(DESIGN-s10 §16b): the M7 module path is a kept shim, which delegates here.
"""
import sys

from codex_harness.composition.process_entries import artifact_reader_main


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    return artifact_reader_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
