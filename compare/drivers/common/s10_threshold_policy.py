"""Shared S10 scenario steps for `research.threshold_policy`: M7 `adapters/threshold_policy.py:current_policy` (DESIGN-s8 §18 V20 item 3).

`current_policy(git, revision)` binds the loaded threshold constants to the text of one Git revision. The git object is a LABELLED fake whose
`_git` serves the policy sources' own texts at one fixed fake commit id; the reference serves M7's `POLICY_PATHS` files, the target the
target `POLICY_PATHS` files under `GIT_PREFIX`. The golden compares `values`, `kind`, `encoding` and every refusal; `sources` (keyed by the
side's own paths) and `revision` are recorded by the reference only and declared `absent` for the target (V20 §18.3).

Cases: a valid HEAD; revision `-x`; one source missing from the fake `ls-tree`; one `show` whose text differs from the loaded file (loaded/committed
mismatch); and a definition mismatch (the loaded text equals the committed text, but the effective policy is patched to differ from it).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`."""

from __future__ import annotations

COMMIT = "c" * 40
VICTIM = 3  # the index of the source the missing / altered cases touch (the threshold replay domain module on both sides)


class FakeGit:
    """`_git(*args, strip=True)` as `current_policy` calls it: rev-parse, ls-tree -rz and show."""

    def __init__(self, tree, omit=None, altered=None):
        self.tree, self.omit, self.altered = tree, omit, altered

    def _git(self, *args, strip=True):
        if args[0] == "rev-parse":
            return COMMIT
        if args[0] == "ls-tree":
            return "".join(f"100644 blob {'0' * 40}\t{path}\0" for path in self.tree if path != self.omit)
        if args[0] == "show":
            path = args[1].split(":", 1)[1]
            return self.tree[path] + ("\n# altered\n" if path == self.altered else "")
        raise AssertionError(args)


def refusal(fn):
    try:
        return {"returned": fn()}
    except Exception as exc:  # the refusal is the characterized result
        return {"refused": type(exc).__name__, "message": str(exc), "cause": type(exc.__cause__).__name__ if exc.__cause__ else None}


def policy_cases(api) -> dict:
    tree = api.tree()
    paths = list(tree)

    def run(git, revision="HEAD"):
        return api.current_policy(git, revision)

    valid = refusal(lambda: run(FakeGit(tree)))
    if "returned" in valid:
        document = valid["returned"]
        valid["returned"] = {"values": document["values"], "kind": document["kind"], "encoding": document["encoding"]}
        if api.record_source_fields:
            valid["returned"]["revision"] = document["revision"]
            valid["returned"]["sources"] = {path: entry["hash"] for path, entry in document["sources"].items()}
    cases = {"valid_head": valid,
             "revision_dash": refusal(lambda: run(FakeGit(tree), "-x")),
             "missing_source": refusal(lambda: run(FakeGit(tree, omit=paths[VICTIM]))),
             "loaded_committed_mismatch": refusal(lambda: run(FakeGit(tree, altered=paths[VICTIM])))}
    with api.patched_effective_policy({"values": {"skill_match.FULL_BODY_MIN_SCORE": 99}}):
        cases["definition_mismatch"] = refusal(lambda: run(FakeGit(tree)))
    return {"cases": cases, **({"sources_count": len(paths)} if api.record_source_fields else {})}
