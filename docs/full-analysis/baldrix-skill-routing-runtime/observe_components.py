"""Actual original component calls on temporary inputs; no live hook or acceptance."""
import json
from pathlib import Path
import tempfile

from lib import pipeline_stage_picker as picker
from lib import skill_match_render as render
from lib import skill_token_budget as budget
from lib import tech_stack
from lib.pipeline_yaml import parse_stages


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def pipeline(root, text):
    write(root / ".claude/stages.yaml", text)
    return picker.detect_pipeline_skills(str(root))


def main():
    results = {}
    for cap in (0, 1, 20, 4000):
        fitted, cut = budget.fit_top_skill("x" * 5000, cap)
        results[f"budget_{cap}"] = {"max_chars": cap, "actual_chars": len(fitted), "cut": cut, "within_cap": len(fitted) <= cap}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stages = """stages:
  - id: a
    name: spec
    output: a.md
    skills: [spec]
  - id: b
    name: implementation
    output: b.md
    skills: [code]
  - id: c
    name: verify
    output: c.md
    skills: [qa]
"""
        sparse = root / "sparse"
        write(sparse / "b.md", "")
        results["sparse_later_output"] = {"missing_a": not (sparse / "a.md").exists(), "b_bytes": (sparse / "b.md").stat().st_size, "recommendation": pipeline(sparse, stages)}
        for name in ("a.md", "c.md"):
            write(sparse / name, "")
        results["all_outputs_exist"] = picker.detect_pipeline_skills(str(sparse))
        optional = root / "optional"
        write(optional / "a.md", "")
        results["optional_next"] = pipeline(optional, stages.replace("    name: implementation", "    name: implementation\n    optional: true"))
        directory = root / "directory"
        (directory / "a.md").mkdir(parents=True)
        results["directory_counts"] = picker._stage_done(str(directory), {"output": "[a.md, missing.md]"})
        block = root / "block"
        block_file = write(block / ".claude/stages.yaml", "stages:\n  - id: one\n    output: missing.md\n    skills:\n      - qa\n")
        results["block_skills_parsed"] = parse_stages(block_file)
        try:
            results["block_skills_result"] = picker.detect_pipeline_skills(str(block))
        except Exception as exc:
            results["block_skills_error"] = {"type": type(exc).__name__, "message": str(exc)}
        project = root / "project"
        write(project / ".claude/tech-stack.yaml", "stack:\n  language: python\n")
        (project / "src").mkdir()
        results["stack_root_vs_subdir"] = {"root": tech_stack.load_tech_stack(project), "subdir": tech_stack.load_tech_stack(project / "src")}
    results["requires_name_vs_filename"] = {
        "name_key": render.build_cross_references([(5, "a.md", [], "")], {"a.md": {"requires": "b"}, "b": {"keywords": "dependency"}}),
        "filename_key": render.build_cross_references([(5, "a.md", [], "")], {"a.md": {"requires": "b"}, "b.md": {"keywords": "dependency"}}),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
