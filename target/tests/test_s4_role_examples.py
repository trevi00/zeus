"""S4 CE-4: canonical role examples are packaged, validated and reference-only until S10 (D10)."""

import copy
import json
import re
from importlib.resources import files

import pytest
from _layout import TARGET

from codex_harness.context.adapters.role_examples import load_role_examples
from codex_harness.context.domain.role_examples import FORBIDDEN, MAX_FIELD, select, validate
from codex_harness.kernel.errors import ContractError

AGENTS = [a["id"] for a in json.loads(
    files("codex_harness.resources").joinpath("organization.json").read_text())["agents"]]
RAW = json.loads(files("codex_harness.context").joinpath("role-examples-v1.json").read_text())

SRC = TARGET / "src"


def test_packaged_file_validates_against_organization():
    document = load_role_examples(AGENTS)
    assert set(document["roles"]) == set(AGENTS) and len(AGENTS) == 12
    assert document["delivery"] == "reference_only_until_S10"


def test_every_role_has_normal_and_variation_within_bounds():
    for role, entry in RAW["roles"].items():
        kinds = [e["kind"] for e in entry["examples"]]
        assert 3 <= len(kinds) <= 5 and kinds.count("normal") >= 2 and "variation" in kinds, role
        assert entry["basis"]
        for e in entry["examples"]:
            assert all(0 < len(e[f]) <= MAX_FIELD for f in ("input", "action", "result")), role


def test_no_forbidden_shape_or_provider_word_appears():
    text = json.dumps(RAW)
    assert FORBIDDEN.search(text) is None
    assert not re.search(r"https?://(?!example\.invalid)|claude|codex|gpt|openai|anthropic|password|token|secret",
                         text, re.I)
    assert len(text.encode()) < 40 * 1024


def test_select_keeps_file_order_and_refuses_unknown_role():
    examples = select(RAW, "worker:implementation")
    assert examples == RAW["roles"]["worker:implementation"]["examples"]
    with pytest.raises(ContractError):
        select(RAW, "lead:nobody")


def _mut(fn):
    document = copy.deepcopy(RAW)
    fn(document)
    return document


DEFECTS = {
    "schema": lambda d: d.update(schema="urn:zeus:role-examples:2"),
    "version": lambda d: d.update(version=2),
    "delivery": lambda d: d.update(delivery="delivered"),
    "missing role": lambda d: d["roles"].pop("conductor"),
    "extra role": lambda d: d["roles"].update(extra=d["roles"]["conductor"]),
    "too few": lambda d: d["roles"]["conductor"]["examples"].__delitem__(slice(2, None)),
    "too many": lambda d: d["roles"]["lead:dba"]["examples"].extend(
        copy.deepcopy(d["roles"]["lead:dba"]["examples"][:3])),
    "no variation": lambda d: [e.update(kind="normal") for e in d["roles"]["lead:dba"]["examples"]],
    "bad kind": lambda d: d["roles"]["lead:dba"]["examples"][0].update(kind="edge"),
    "long field": lambda d: d["roles"]["lead:dba"]["examples"][0].update(result="x" * (MAX_FIELD + 1)),
    "key": lambda d: d["roles"]["lead:dba"]["examples"][0].update(input="uses sk-abc"),
    "path": lambda d: d["roles"]["lead:dba"]["examples"][0].update(input="reads /home/user/x"),
    "email": lambda d: d["roles"]["lead:dba"]["examples"][0].update(input="mail a@b.c"),
    "extra field": lambda d: d["roles"]["lead:dba"]["examples"][0].update(note="x"),
}


@pytest.mark.parametrize("name", sorted(DEFECTS))
def test_validate_refuses_defect(name):
    with pytest.raises(ContractError):
        validate(_mut(DEFECTS[name]), AGENTS)


def test_no_other_module_imports_role_examples():
    own = {SRC / "codex_harness/context/domain/role_examples.py",
           SRC / "codex_harness/context/adapters/role_examples.py"}
    users = [p for p in SRC.rglob("*.py") if p not in own and "role_examples" in p.read_text()]
    assert users == []
