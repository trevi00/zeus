"""The effects unit table (DESIGN-s11 §5.3 G1, §5.4; unit L3): which atomic-unit rows each `effects.*` golden unit exercises.

Layer: harness (never shipped); standard library only; no product import.

    python coverage/effects_unit_table.py            # write coverage/effects-unit-table.json
    python coverage/effects_unit_table.py --check    # byte equality with the committed table, and the G1 entries of
                                                     # coverage/evidence-resolutions.json equal their regeneration
    python coverage/effects_unit_table.py --write-g1 # rewrite ONLY the G1 entries of coverage/evidence-resolutions.json

Three committed sources are joined, deterministically and without reading prose:
  1. the 13 `compare/scenarios/effects.*.json`: the reference driver, and the REFERENCE golden (keyed by unit and case);
  2. the reference driver and the `compare/drivers/common/` modules it imports, read as ASTs (never imported or run);
  3. `compare/goldens/reference/static.source.json` `transaction_blocks` (M7's transaction blocks: the atomic-unit rows).

An entry `{family, golden_unit, atomic_unit, driver_call, block, cases}` exists iff ALL hold (the L3 spec, REBUILD-DESIGN-v2 §2.9
rules 1, 5, 6):
  1. a driver call (an attribute call found in the AST closure of the unit's driver function, `driver_call` = path:line) names
     the unit's M7 method, and that name binds to exactly ONE `Class.method` among the M7 modules the driver files import;
  2. the block `#n` is the one the call reaches: the method's only block, or, with several blocks, the ONE block whose recorded
     `literal_writes` cover the golden's durable buckets of the success case (else the first replay case); `<dynamic>` or no
     literal writes never cover;
  3. the golden holds at least one rule-6 case (a/b/c/d) for that unit.
R-L3d (DESIGN-s11 §17, S11 R-L3d-1) adds, for a family WITH a reference blocks artifact (`compare/goldens/reference/<family>.blocks.json`,
the blocks each golden case executed, recorded on the reference side by `compare/harness/block_exercise.py`), an entry
`{family, golden_unit, atomic_unit, block, basis: "block_exercise", cases, case, writes_observed}` for a block of a golden unit iff
ALL hold:
  (i)   rules 1-3 joined no entry for that atomic-unit row (in the family: one resolution per row);
  (ii)  the block key is recorded in at least one rule-6 case (a/b/c/d) of that golden unit;
  (iii) if the block lists non-`<dynamic>` literal writes, at least one of them is among that case's durable buckets
        (`writes_observed`); a block without literal writes is credited on execution alone (`writes_observed: null`).
A family without a blocks artifact gets no such entry (never inferred).
A call that is not bound or not blocked is listed (`ambiguous`), never an entry; a unit the table cannot join is listed
(`unmatched`) with the reason. The unit-under-test call is the one whose name is the golden unit's name, except the units named
in `DECLARED_CALLS`, whose method is declared here and still has to be found by the AST.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TABLE = HERE / "effects-unit-table.json"
RESOLUTIONS = HERE / "evidence-resolutions.json"
LEDGER = HERE / "ledger-coverage.json"
CATALOGUE = "compare/goldens/reference/static.source.json"
SCHEMA = "zeus:s11-effects-unit-table:1"
PENDING = "pending: recorder confirmation in the owning slice"
G1_CITATION = "coverage/effects-unit-table.json#"
DURABLE_KEYS = ("durable_writes", "durable_authority_writes")
OBSERVED_KEYS = (*DURABLE_KEYS, "durable_rows_changed")  # R-L3d (iii): the rows read back from the store count too
BASIS = "block_exercise"
BLOCKS_SCHEMA = "zeus:s11-block-exercise:1"

# golden unit -> the M7 method it exercises when the unit is not named for it. The AST still has to find a call of it.
DECLARED_CALLS = {
    ("decision_unit", "decision_unit"): "decide_one",  # F2: Executor.decide_one -> _commit_decision, cases a_/b_/c_/control_
    ("s8_units", "fail_cycle_dispatch"): "fail_cycle",  # the same call with a dispatch in flight
    # S11 AU-L3b. A `Class.method` value names the class too, where the driver imports two classes with the method's name and
    # the receiver is the only thing that tells them apart; the AST still has to find a call of the method name.
    ("admission_unit", "admit"): "admit_one",  # s5_units.py:172: `attempt(f.admit_one)`, f = the Fleet of :119
    ("admission_unit", "claim"): "Operation.claim",  # s5_units.py:159: `attempt(operation.claim, ...)`, `operation = api.operation(...)` (:146)
    ("admission_unit", "depths"): "step",  # s5_units.py:242: `attempt(cycle.step, "cycle-d")`, the LocalCycle of :236 whose depths the unit records
    # S11 AU-REC-1 (owner): `status` binds to Fleet/LocalCycle/Operation.status; the receiver is the Fleet of s5_units.py:334
    ("admission_unit", "status"): "Fleet.status",  # s5_units.py:340: `attempt(f.status)`, f = fleet(...) or bare_fleet(...) (:334)
}


# ------------------------------------------------------------------------------------------------------ the AST closure
class Driver:
    """The reference driver and the `drivers/common` modules it reaches, as parsed trees."""

    def __init__(self, sources: dict[str, str], entry: str):
        self.entry = entry
        self.trees = {path: ast.parse(text) for path, text in sources.items()}
        self.by_stem = {Path(p).stem: p for p in sources if p != entry}
        self.funcs = {p: {n.name: n for n in t.body if isinstance(n, ast.FunctionDef)} for p, t in self.trees.items()}
        self.mods: dict[str, set[str] | None] = {}  # M7 module -> imported names (None: the module itself)
        self.alias: dict[str, dict[str, str]] = {}  # path -> local name -> common module path
        self.imported_funcs: dict[str, dict[str, tuple[str, str]]] = {}
        for path, tree in self.trees.items():
            self.alias[path], self.imported_funcs[path] = {}, {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.name in self.by_stem:
                            self.alias[path][a.asname or a.name] = self.by_stem[a.name]
                        elif a.name.startswith("codex_harness"):
                            self.mods.setdefault(a.name, None)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module in self.by_stem:
                        for a in node.names:
                            self.imported_funcs[path][a.asname or a.name] = (self.by_stem[node.module], a.name)
                    elif node.module.startswith("codex_harness"):
                        for a in node.names:
                            self.mods.setdefault(f"{node.module}.{a.name}", None)  # `from pkg import module`
                            names = self.mods.setdefault(node.module, set())
                            if names is not None:
                                names.add(a.name)

    def closure(self, path: str, funcs: list[str]) -> list[tuple[str, str, int]]:
        """Every attribute call (or attribute handed as an argument) reachable from the named functions: (attr, path, line)."""
        hits: set[tuple[str, str, int]] = set()
        seen: set[tuple[str, str]] = set()
        todo = [(path, f) for f in funcs]
        while todo:
            p, name = todo.pop()
            if (p, name) in seen or name not in self.funcs.get(p, {}):
                continue
            seen.add((p, name))
            for node in ast.walk(self.funcs[p][name]):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if isinstance(f, ast.Name):
                    if f.id in self.funcs[p]:
                        todo.append((p, f.id))
                    elif f.id in self.imported_funcs[p]:
                        todo.append(self.imported_funcs[p][f.id])
                elif isinstance(f, ast.Attribute):
                    hits.add((f.attr, p, f.lineno))
                    if isinstance(f.value, ast.Name) and f.value.id in self.alias[p]:
                        todo.append((self.alias[p][f.value.id], f.attr))
                for arg in node.args:  # a callable handed on (`attempt(PR.collect, ...)`) is followed like a call
                    if isinstance(arg, ast.Attribute):
                        hits.add((arg.attr, p, arg.lineno))
                        if isinstance(arg.value, ast.Name) and arg.value.id in self.alias[p]:
                            todo.append((self.alias[p][arg.value.id], arg.attr))
                    elif isinstance(arg, ast.Name) and arg.id in self.funcs[p]:
                        todo.append((p, arg.id))
        return sorted(hits)

    def run_map(self, path: str) -> dict[str, list[tuple[str, str]]]:
        """`run()`'s string-keyed dict literals: key -> the (path, function) targets called in its value."""
        out: dict[str, list[tuple[str, str]]] = {}
        run = self.funcs[path].get("run")
        for node in ast.walk(run) if run else ():
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                for call in (c for c in ast.walk(value) if isinstance(c, ast.Call)):
                    f = call.func
                    if isinstance(f, ast.Name) and f.id in self.funcs[path]:
                        out.setdefault(key.value, []).append((path, f.id))
                    elif isinstance(f, ast.Name) and f.id in self.imported_funcs[path]:
                        out.setdefault(key.value, []).append(self.imported_funcs[path][f.id])
        return out


# ---------------------------------------------------------------------------------------------------------- the golden
def is_case(value) -> bool:
    return isinstance(value, dict) and any(k in value for k in (*DURABLE_KEYS, "unreachable", "not_applicable"))


def rule6_letter(case: str) -> str | None:
    """The §2.9 rule-6 discriminator of a case name: the first `a_`/`b_`/`c_`/`d_` token (`success` has none)."""
    found = re.search(r"(?:^|_)([abcd])_", case)
    return found.group(1) if found else None


def golden_units(golden: dict, run_map: dict[str, list[tuple[str, str]]], family_base: str):
    """-> {unit: ({case: case dict}, entry (path, function) targets or None)} (nested, flat-by-function, or one flat unit)."""
    units: dict[str, tuple[dict, list | None]] = {}
    nested = {k: v for k, v in golden.items() if isinstance(v, dict) and v and all(is_case(c) for c in v.values())}
    for unit, cases in nested.items():
        units[unit] = (cases, run_map.get(unit))
    flat = {k: v for k, v in golden.items() if is_case(v)}
    by_function: dict[str, tuple[dict, list]] = {}
    for key, case in flat.items():
        targets = run_map.get(key)
        if targets:
            by_function.setdefault(targets[0][1], ({}, targets[:1]))[0][key] = case
    if by_function:
        units.update(by_function)
    elif flat:
        units[family_base] = (flat, None)  # one flat unit, driven by every driver function (decision_unit)
    return units


def durable_buckets(cases: dict) -> list[str]:
    """The buckets the golden's success case (else the first case with durable writes) records: the join's coverage target."""
    ordered = [c for k, c in cases.items() if re.search(r"(?:^|_)success", k)] + \
              [c for k, c in cases.items() if rule6_letter(k) == "c"]
    for case in ordered:
        for key in DURABLE_KEYS:
            if case.get(key):
                return sorted({w[0] if isinstance(w, list) else w for w in case[key]})
    return []


# --------------------------------------------------------------------------------------------------------------- the join
def short(key: str) -> str:
    return key.split(":", 1)[1]


def observed_buckets(case: dict) -> set[str]:
    return {w[0] if isinstance(w, list) else w for key in OBSERVED_KEYS for w in case.get(key) or []}


def block_exercise_entries(family: str, gunits: dict, blocks: dict | None, units: list[dict], joined: set[str]) -> list[dict]:
    """R-L3d: the entries of the rows rules 1-3 left unjoined, selected by the blocks the golden cases executed."""
    if blocks is None:
        return []
    by_key = {u["key"]: u for u in units}
    found: dict[tuple[str, str], dict] = {}
    for unit, (cases, _) in sorted(gunits.items()):
        for case in sorted(cases):
            letter = rule6_letter(case)
            for key in blocks["cases"].get(case, []) if letter else []:
                block = by_key.get(key)
                if block is None or key in joined:
                    continue
                literal = sorted(w for w in block["literal_writes"] if w != "<dynamic>")
                seen = sorted(set(literal) & observed_buckets(cases[case])) if literal else None
                if literal and not seen:
                    continue  # executed, but its literal writes were not observed in the case
                entry = found.setdefault((unit, key), {"letters": set(), "case": case, "writes": seen})
                entry["letters"].add(letter)
    return [{"family": family, "golden_unit": unit, "atomic_unit": key, "block": "#" + key.rsplit("#", 1)[1], "basis": BASIS,
             "cases": sorted(e["letters"]), "case": e["case"], "writes_observed": e["writes"]}
            for (unit, key), e in sorted(found.items())]


def join_family(family: str, driver: Driver, golden: dict, units: list[dict], exercised: dict | None = None) -> dict:
    """-> {entries, ambiguous, unmatched} of one family. `units` is the catalogue's `transaction_blocks.units`; `blocks` the
    family's reference blocks artifact (R-L3d), or None."""
    base = family.removesuffix(".pg").removeprefix("effects.")
    entry_path = next((p for p in driver.funcs if "run" in driver.funcs[p]), driver.entry)
    by_method: dict[str, list[dict]] = {}
    for u in units:
        by_method.setdefault(u["scope"].rsplit(".", 1)[-1], []).append(u)
    out = {"entries": [], "ambiguous": [], "unmatched": []}

    def reject(bucket, unit, reason, **more):
        out[bucket].append({"family": family, "golden_unit": unit, "reason": reason, **more})

    gunits = golden_units(golden, driver.run_map(entry_path), base)
    for unit, (cases, targets) in sorted(gunits.items()):
        letters = sorted({rule6_letter(c) for c in cases} - {None})
        if not letters:
            reject("unmatched", unit, "the golden holds no rule-6 case (a/b/c/d) for the unit")
            continue
        if targets is None:
            roots = [(p, f) for p in driver.funcs for f in driver.funcs[p] if f != "main"]
        else:
            roots = targets
        hits: list[tuple[str, str, int]] = []
        for path, func in roots:
            hits += driver.closure(path, [func])
        declared = DECLARED_CALLS.get((base, unit), unit)
        owner, _, method = declared.rpartition(".")  # `Class.method` names the class as well; a bare name binds by rule 1
        calls = sorted({h for h in hits if h[0].lstrip("_") == method.lstrip("_") and h[0] in by_method})
        if not calls:
            reject("unmatched", unit, f"no driver call of an M7 method named {method}")
            continue
        attr, path, line = calls[0]
        # rule 1: the name binds to one Class.method among the M7 modules the driver files import
        candidates = sorted({u["scope"] for u in by_method[attr] if imported(driver, u) and (not owner or u["scope"] == declared)})
        if len(candidates) != 1:
            reject("ambiguous", unit, f"{attr} binds to {len(candidates)} imported M7 methods" if candidates
                   else f"{attr} is in no M7 module the driver imports", driver_call=f"{path}:{line}", candidates=candidates)
            continue
        modules = {u["module"] for u in by_method[attr] if u["scope"] == candidates[0] and imported(driver, u)}
        blocks = sorted((u for u in by_method[attr] if u["scope"] == candidates[0] and u["module"] in modules),
                        key=lambda u: u["line"])
        if len(modules) != 1:
            reject("ambiguous", unit, f"{candidates[0]} is in {len(modules)} imported M7 modules", driver_call=f"{path}:{line}",
                   candidates=sorted(modules))
            continue
        # rule 2: the block the call reaches
        if len(blocks) == 1:
            chosen = blocks
        else:
            wanted = set(durable_buckets(cases))
            chosen = [b for b in blocks if wanted and wanted <= set(b["literal_writes"]) and "<dynamic>" not in b["literal_writes"]]
            if len(chosen) != 1:
                reject("ambiguous", unit, f"{len(chosen)} of {len(blocks)} blocks of {candidates[0]} cover the golden buckets "
                       f"{sorted(wanted)}", driver_call=f"{path}:{line}", candidates=[b["key"] for b in blocks])
                continue
        out["entries"].append({"family": family, "golden_unit": unit, "atomic_unit": chosen[0]["key"],
                               "driver_call": f"{path}:{line}", "block": "#" + chosen[0]["key"].rsplit("#", 1)[1],
                               "cases": letters})
    out["entries"] += block_exercise_entries(family, gunits, exercised, units, {e["atomic_unit"] for e in out["entries"]})
    return out


def imported(driver: Driver, unit: dict) -> bool:
    """The catalogue block's module is one the driver files import, and (for `from M import Names`) its class is named."""
    module = unit["module"]
    if module not in driver.mods:
        return False
    names = driver.mods[module]
    return names is None or unit["scope"].split(".")[0] in names


# ----------------------------------------------------------------------------------------------------------- the table
def build(root: Path) -> dict:
    catalogue = json.loads((root / CATALOGUE).read_text(encoding="utf-8"))["transaction_blocks"]["units"]
    table = {"schema": SCHEMA, "sources": {"catalogue": CATALOGUE, "scenarios": "compare/scenarios/effects.*.json"},
             "entries": [], "ambiguous": [], "unmatched": []}
    for scenario in sorted((root / "compare/scenarios").glob("effects.*.json")):
        meta = json.loads(scenario.read_text(encoding="utf-8"))
        entry = meta["reference_driver"]
        sources = {f"compare/{entry}": (root / "compare" / entry).read_text(encoding="utf-8")}
        for stem in sorted(set(re.findall(r"^(?:import|from) (\w+)", sources[f"compare/{entry}"], flags=re.M))):
            common = root / "compare/drivers/common" / f"{stem}.py"
            if common.is_file():
                sources[f"compare/drivers/common/{stem}.py"] = common.read_text(encoding="utf-8")
        for _ in range(4):  # the common modules' own common imports (bounded; the closure is cycle-safe)
            for text in list(sources.values()):
                for stem in re.findall(r"^(?:import|from) (\w+)", text, flags=re.M):
                    common = root / "compare/drivers/common" / f"{stem}.py"
                    if common.is_file():
                        sources.setdefault(f"compare/drivers/common/{stem}.py", common.read_text(encoding="utf-8"))
        golden = json.loads((root / "compare" / meta["golden"]).read_text(encoding="utf-8"))
        blocks_path = root / "compare/goldens/reference" / f"{meta['family']}.blocks.json"
        blocks = json.loads(blocks_path.read_text(encoding="utf-8")) if blocks_path.is_file() else None
        result = join_family(meta["family"], Driver(sources, f"compare/{entry}"), golden, catalogue, blocks)
        for k in ("entries", "ambiguous", "unmatched"):
            table[k] += result[k]
    for k in ("entries", "ambiguous", "unmatched"):
        table[k].sort(key=lambda e: (e["family"], e["golden_unit"], e.get("atomic_unit", "")))
    return table


def dump(document: dict) -> str:
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


# -------------------------------------------------------------------------------------------------------------- G1
def g1_resolutions(table: dict, ledger: dict, elsewhere: set[str] | None = None) -> list[dict]:
    """The G1 resolution entries: an atomic-unit row carrying the pending item resolves to `compare:<family>` of every table
    entry for it (the `.pg` family joins when its own entry names the same atomic unit); the citation names each entry.
    A row another rule already resolves (`elsewhere`: the keys of the non-G1 resolutions, default those committed) keeps that
    one: a pending item is resolved once (S11 R-L3d-1: a block the exercise reaches may be a row G1b already verified)."""
    if elsewhere is None:
        committed = json.loads(RESOLUTIONS.read_text(encoding="utf-8"))["resolutions"]
        elsewhere = {e["key"] for e in committed if e["rule"] != "G1"}
    pending_rows = {r["key"] for r in ledger["rows"] if r["kind"] == "atomic_unit" and PENDING in r["evidence"]} - elsewhere
    by_row: dict[str, list[dict]] = {}
    for e in table["entries"]:
        by_row.setdefault("atomic_unit:" + e["atomic_unit"], []).append(e)
    out = []
    for key in sorted(by_row):
        if key not in pending_rows:
            continue
        entries = sorted(by_row[key], key=lambda e: (e["family"], e["golden_unit"]))
        families = sorted({e["family"] for e in entries})
        out.append({"key": key, "pending": PENDING, "replaced_by": [f"compare:{f}" for f in families], "rule": "G1",
                    "citation": "; ".join(f"{G1_CITATION}{e['family']}/{e['golden_unit']}" for e in entries)})
    return out


def with_g1(resolutions: dict, g1: list[dict]) -> dict:
    kept = [e for e in resolutions["resolutions"] if e["rule"] != "G1"]
    return {**resolutions, "resolutions": g1 + kept}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write-g1", action="store_true")
    args = parser.parse_args(argv)
    table = build(ROOT)
    text = dump(table)
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    resolutions = json.loads(RESOLUTIONS.read_text(encoding="utf-8"))
    wanted = json.dumps(with_g1(resolutions, g1_resolutions(table, ledger)), indent=1) + "\n"
    if args.check:
        same_table = TABLE.read_text(encoding="utf-8") == text
        same_g1 = RESOLUTIONS.read_text(encoding="utf-8") == wanted
        print(json.dumps({"table_matches": same_table, "g1_matches": same_g1}))
        return 0 if same_table and same_g1 else 1
    if args.write_g1:
        RESOLUTIONS.write_text(wanted, encoding="utf-8")
        return 0
    TABLE.write_text(text, encoding="utf-8")
    counts = {}
    for k in ("entries", "ambiguous", "unmatched"):
        for e in table[k]:
            counts.setdefault(e["family"], {}).setdefault(k, 0)
            counts[e["family"]][k] += 1
    print(json.dumps(counts, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
