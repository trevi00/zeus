"""Observe original seam code on isolated synthetic files; not fleet acceptance."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile

from lib.seams import get_seam_extractor
from lib.seams.base import EnumContract, WireValue
from lib.seams.parity import compute_parity
from validators.seam_parity_drift import audit_ledger


def emit(name, **data):
    print(json.dumps({"case": name, **data}, sort_keys=True))


def contract(values, fidelity="HIGH"):
    return EnumContract("E", "synthetic", "input", "observation", fidelity,
                        [WireValue(v, v, "input", 1, "observation") for v in values])


def parity(name, producer, consumer, transform=None, fidelity="HIGH"):
    result = compute_parity(contract(producer, fidelity), contract(consumer), transform)
    emit(name, producer=producer, consumer=consumer, transform=transform,
         result=asdict(result), blocking_eligible=result.blocking_eligible())


def extract(name, stack, files):
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
        contracts = get_seam_extractor(stack).extract_enums(root)
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
        emit(name, input_files=files, contracts=[asdict(c) for c in contracts],
             values=[c.values() for c in contracts], input_bytes_unchanged=before == after)
        assert before == after
        return contracts


def main():
    parity("partial_map_passthrough_collision", ["A", "B"], ["B"],
           {"kind": "value_map", "map": {"A": "B"}})
    parity("affix_strip_collision", ["X", "preX"], ["X"], {"kind": "affix", "strip": "pre"})
    parity("explicit_collision_guard", ["A", "B"], ["X"],
           {"kind": "value_map", "map": {"A": "X", "B": "X"}})
    parity("unknown_fidelity", ["A", "B"], ["A"], fidelity="UNKNOWN")
    parity("low_guard", ["A", "B"], ["A"], fidelity="LOW")
    parity("empty_high_direct_api", [], [])
    parity("explicit_identity_disjoint", ["A"], ["B"], {"kind": "identity"})
    parity("affix_unknown_option", ["A"], ["preA"], {"kind": "affix", "added": "pre"})
    extract("java_short_and_same_line_omission", "java", {"src/main/java/E.java":
            "enum E implements SocketAction {\n OK,\n LONG, OTHER;\n String toValueString() { return name(); }\n}"})
    extract("java_second_field_not_resolved", "java", {"src/main/java/E.java":
            'enum E implements SocketAction {\n ORDER("label", "wire");\n'
            ' final String label, code;\n E(String label, String code) { this.label = label; this.code = code; }\n'
            ' public String toValueString() { return code; }\n}'})
    extract("java_comment_line_shift", "java", {"src/main/java/E.java":
            '/* first\n second\n third */\nenum E implements SocketAction {\n LONG;\n String toValueString() { return name(); }\n}'})
    extract("dart_nonliteral_arguments", "dart", {"lib/e_action.dart":
            'enum EAction { A(Foo.bar), B(Foo.baz);\n const EAction(this.value); final Object value; }'})
    extract("dart_mixed_arguments", "dart", {"lib/e_action.dart":
            'enum EAction {\n A("A"),\n B(Foo.baz);\n const EAction(this.value); final Object value; }'})
    extract("dart_outside_enum_call", "dart", {"lib/e_action.dart":
            'enum EAction {\n A("A");\n const EAction(this.value); final String value;\n}\nvoid ui() {\n Text("foreign");\n}'})
    proto_a = extract("proto_type_a", "proto", {"e.proto": 'syntax = "proto3";\nmessage E {\n string x = 1;\n}'})
    proto_b = extract("proto_type_b", "proto", {"e.proto": 'syntax = "proto3";\nmessage E {\n int64 x = 1;\n}'})
    emit("proto_type_change_parity", result=asdict(compute_parity(proto_a[0], proto_b[0])),
         limitation="Parsed text only. No protobuf compiler, serialization or wire compatibility observation.")
    extract("proto_nested_options_and_map", "proto", {"e.proto":
            'message E {\n string own = 1;\n map<string,string> lookup = 2;\n string optioned = 3 [deprecated=true];\n'
            ' message Child {\n string nested = 4;\n }\n}'})
    extract("proto_same_short_name", "proto", {
            "a.proto": 'package a;\nmessage E {\n string first = 1;\n}',
            "b.proto": 'package b;\nmessage E {\n string second = 2;\n}'})
    with tempfile.TemporaryDirectory() as td:
        state = Path(td)
        event = state / "seam" / "events.jsonl"
        event.parent.mkdir()
        record = {"seam_id": "seam", "status": "DRIFT", "matched": ["A"], "producer_only": ["B"],
                  "consumer_only": [], "producer_fidelity": "HIGH", "consumer_fidelity": "HIGH"}
        event.write_text(json.dumps(record) + "\n", encoding="utf-8")
        emit("ledger_valid_drift", audit=audit_ledger(state))
        with event.open("a", encoding="utf-8") as stream:
            stream.write('{"incomplete":\n')
        emit("ledger_malformed_tail", audit=audit_ledger(state),
             limitation="Actual scratch-file parse behavior; no live ledger mutation.")
    emit("complete", limitation="Synthetic input observation, no mocks/patches; not actual fleet, human, device, OS matrix or promotion acceptance.")


if __name__ == "__main__":
    main()
