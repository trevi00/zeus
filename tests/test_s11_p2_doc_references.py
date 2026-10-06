"""AR2: the paths and dotted names cited by docs/context/DELIVERY.md and docs/contracts.md resolve in the
promoted tree (REBUILD-DESIGN-v2 §8; PREP-S11 §5.2; DESIGN-s11 §20.5).

STRUCTURAL check (reference resolution): it reads the two documents as text and asks whether each cited
repository path exists and each cited ``codex_harness.`` name resolves under ``src/``. It is not behavioural
acceptance of any cited code.
"""

import re
from pathlib import Path

from _layout import REPO

DELIVERY = REPO / "docs" / "context" / "DELIVERY.md"
CONTRACTS = REPO / "docs" / "contracts.md"
PATH_ROOTS = ("src/", "tests/", "reference/", "docs/", "scripts/", "deploy/")
# An example of an accepted project path in the path-grammar contract, not a citation of a repository file.
EXAMPLES = {"docs/.github/GOAL.md"}
BACKTICKED = re.compile(r"`([^`\s]+)`")


def cited_paths(text: str) -> list[str]:
    tokens = (t.rstrip(".,;:") for t in BACKTICKED.findall(text))
    return sorted({t for t in tokens if t.startswith(PATH_ROOTS) and t not in EXAMPLES})


def missing_paths(text: str, root: Path = REPO) -> list[str]:
    return [p for p in cited_paths(text) if not (root / p).exists()]


def cited_dotted(text: str) -> list[str]:
    tokens = (t.rstrip(".,;:") for t in BACKTICKED.findall(text))
    return sorted({t for t in tokens if t.startswith("codex_harness.") and re.fullmatch(r"[\w.]+", t)})


def resolves(name: str, src: Path) -> bool:
    """A module under ``src``, or an attribute (a top-level definition) of the longest module prefix."""
    parts = name.split(".")
    for cut in range(len(parts), 0, -1):
        base = src.joinpath(*parts[:cut])
        module = base.with_suffix(".py") if base.with_suffix(".py").is_file() else base / "__init__.py"
        if not module.is_file():
            continue
        rest = parts[cut:]
        if not rest:
            return True
        if len(rest) == 1:
            return re.search(rf"^(?:def|class|async def)\s+{re.escape(rest[0])}\b|^{re.escape(rest[0])}\s*[:=]",
                             module.read_text(encoding="utf-8"), re.M) is not None
        return False
    return False


def unresolved(text: str, src: Path = REPO / "src") -> list[str]:
    return [n for n in cited_dotted(text) if not resolves(n, src)]


def test_delivery_and_contracts_cite_existing_paths():
    for doc in (DELIVERY, CONTRACTS):
        text = doc.read_text(encoding="utf-8")
        assert cited_paths(text), doc
        assert missing_paths(text) == [], doc


def test_delivery_dotted_names_resolve_under_src():
    text = DELIVERY.read_text(encoding="utf-8")
    assert cited_dotted(text)
    assert unresolved(text) == []


def test_negative_control_absent_path_is_reported():
    text = "see `tests/test_no_such_file_xyz.py` and `docs/context/DELIVERY.md`"
    assert missing_paths(text) == ["tests/test_no_such_file_xyz.py"]


def test_negative_control_unresolvable_dotted_name_is_reported():
    text = "`codex_harness.context.adapters.worker_profile` `codex_harness.runtime.worker_profile` `codex_harness.context.adapters.worker_profile.no_such_attr`"
    assert unresolved(text) == ["codex_harness.context.adapters.worker_profile.no_such_attr", "codex_harness.runtime.worker_profile"]
