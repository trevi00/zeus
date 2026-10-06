"""The one place the coverage tools learn where the target tree lives (stdlib only).

The promotion sets both constants (to "" and ""); DESIGN-s11 §20.5. Every use of the target tree as a PATH in
`relabel.py`, `generate.py` and `test_node_map.py` derives from them. Not paths, so not derived: the `target:` evidence
side label, the compare result key `"target"`, `role="target"`, field names and text inside data."""
TARGET_DIR = "target"  # the target tree, relative to the repository root
TARGET_PREFIX = "target/"  # the repo-relative git prefix of the target tree
