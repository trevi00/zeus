# Cutover preparation (non-shipped)

This directory is the one `NON_SHIPPED_PREFIXES` entry of the fleet maintenance permit (INV-FLEET-001, the
`forward_candidate` paragraph of `docs/contracts.md`). A `forward_candidate` permit may admit exactly one owner-registered
job whose `allowed_paths` all lie under `docs/cutover/`, while the Fleet stays owner-paused.

Nothing here is product code, configuration or a runtime input: no module imports it and no release reads it. Files
added under this prefix are cutover preparation records, reviewed through the ordinary path.
