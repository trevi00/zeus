"""Observe original validator behavior using actual isolated files; no patched methods."""
import dataclasses
import json
from pathlib import Path
import tempfile

from lib.validators import boilerplate, cross_ref, semantic, structural


def main():
    output = {}
    output["structural_no_checks"] = dataclasses.asdict(structural.validate(None, {}))
    output["additional_false_without_properties"] = dataclasses.asdict(structural.validate(
        {"unexpected": 1}, {"output_schema": {"type": "object", "additionalProperties": False}}))
    output["bool_in_integer_enum"] = structural.validate(True, {"output_schema": {"enum": [1]}}).ok
    output["nan_with_numeric_bounds"] = structural.validate(
        float("nan"), {"output_schema": {"type": "number", "minimum": 0, "maximum": 1}}).ok
    output["nested_evidence_unchecked"] = structural.validate(
        {"envelope": {"evidence": [{"file_path": "/tmp/not-created-validator-evidence"}]}}, {}).ok
    output["missing_tool_manifest"] = structural.validate({}, {"tool_allowlist": ["Read"]}).ok
    for name, envelope, spec in (
        ("nul_path_exception", {"evidence": [{"file_path": "bad\0path"}]}, {}),
        ("unhashable_schema_type_exception", {}, {"output_schema": {"type": [{}]}}),
    ):
        try:
            output[name] = dataclasses.asdict(structural.validate(envelope, spec))
        except Exception as exc:
            output[name] = type(exc).__name__
    with tempfile.TemporaryDirectory(prefix="validator-review-") as temp:
        directory = Path(temp)
        rich = directory / "rich.txt"
        other = directory / "other.txt"
        third = directory / "third.txt"
        rich.write_text("alpha beta gamma delta epsilon", encoding="utf-8")
        other.write_text("unrelated vocabulary elsewhere", encoding="utf-8")
        third.write_text("different words altogether", encoding="utf-8")
        summary = rich.read_text(encoding="utf-8")

        def envelope(*paths):
            return {"summary": summary, "evidence": [{"file_path": str(p)} for p in paths]}

        output["semantic_clean_with_missing"] = dataclasses.asdict(semantic.check(envelope(rich, directory / "missing.txt")))
        output["consensus_duplicate_single_file"] = dataclasses.asdict(cross_ref.check_cross_file_consensus(envelope(rich, rich)))
        output["consensus_one_readable_one_missing"] = dataclasses.asdict(cross_ref.check_cross_file_consensus(envelope(rich, directory / "missing.txt")))
        output["consensus_two_unrelated"] = dataclasses.asdict(cross_ref.check_cross_file_consensus(envelope(other, third)))
        output["semantic_ascii_lower_minimum"] = sorted(semantic._tokenize("ab cd ef", min_chars=1))
        output["semantic_cjk_ignores_large_minimum"] = sorted(semantic._tokenize("주문 처리 완료", min_chars=99))
        long_file = directory / "long.txt"
        long_file.write_text("unrelated " * 600 + summary, encoding="utf-8")
        output["semantic_default_head"] = dataclasses.asdict(semantic.check(envelope(long_file)))
        output["semantic_negative_cap"] = dataclasses.asdict(semantic.check(envelope(long_file), max_file_bytes=-1))
        output["boilerplate_small_cap"] = dataclasses.asdict(boilerplate.check(envelope(long_file), max_file_bytes=20))
        license_file = directory / "LICENSE"
        license_file.write_text("MIT License\n" + "License terms under review. " * 10, encoding="utf-8")
        output["boilerplate_legitimate_license_target"] = dataclasses.asdict(boilerplate.check(envelope(license_file)))
        output["boilerplate_windows_basename_on_linux"] = boilerplate._filename_is_boilerplate(r"C:\project\LICENSE")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
