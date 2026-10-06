"""Entry of the schema migration operator process (`precheck|apply`).

Layer: entry
Owns: nothing; delegates to the one composition function
Does not own: the migrator (`storage.adapters.migrator`, reached through `composition.process_entries`)
Entry points: main
Contracts: none

M7 `adapters/migrations.py` `__main__` (SOURCE e38aa722): `sys.exit(main())`. Owner, int44 (DESIGN-s10 §16b): the M7
module path is a kept shim, which delegates here.
"""
from codex_harness.composition.process_entries import migrations_main


def main(argv=None):
    return migrations_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
