"""Reviewer observations against original code; input fixtures, not acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from lib.frontmatter import parse_frontmatter
from validators import skill_quality_axes as quality


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def invoke(module, args, assets):
    env = {**os.environ, "CLAUDE_ASSETS_HOME": str(assets)}
    proc = subprocess.run(
        [sys.executable, "-B", "-m", module, *args],
        env=env, capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def main():
    records = {}
    source = Path(os.environ["CLAUDE_ASSETS_HOME"])
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        stub_text = (source / "skills/_common/skill-distillation-pipeline.md").read_text(encoding="utf-8")
        flag = next(line for line in stub_text.splitlines() if line.startswith("quality_axes_enforced:") and "#" in line)
        stub = write(root / "stub/skills/_common/example.md", f"---\nname: example\n{flag}\n---\n# bare\n")
        meta, _ = parse_frontmatter(stub)
        records["copied_inline_flag"] = {
            "line": flag, "parsed_flag": meta["quality_axes_enforced"],
            "enforced": quality._is_enforced(Path("_common/example.md"), meta),
            "cli": invoke("validators.skill_quality_axes", [], root / "stub"),
        }
        for label, rival, queries in [
            ("empty_negative", None, {"should_trigger": ["uniquetarget"], "should_not_trigger": []}),
            ("specificity_not_precision", None, {"should_trigger": ["uniquetarget"], "should_not_trigger": ["uniquetarget", "nothing", "unrelated", "elsewhere"]}),
            ("ineligible_rival", "keywords: uniquetarget extra\nmin_score: 99", {"should_trigger": ["uniquetarget extra"], "should_not_trigger": ["unrelated"]}),
            ("tie", "keywords: uniquetarget\nmin_score: 1", {"should_trigger": ["uniquetarget"], "should_not_trigger": ["unrelated"]}),
        ]:
            assets = root / label
            target = write(assets / "skills/_common/target.md", "---\nname: target\nkeywords: uniquetarget\nmin_score: 1\n---\nbody\n")
            if rival:
                write(assets / "skills/_common/rival.md", f"---\nname: rival\n{rival}\n---\nbody\n")
            query_path = write(assets / "queries.json", json.dumps(queries))
            result = invoke("cli.skill_trigger_eval", [str(target), "--queries", str(query_path), "--json"], assets)
            result["data"] = json.loads(result["stdout"])
            records[label] = result

        # Text-mode reading uses universal newlines: verify the proposed CRLF
        # discrepancy instead of turning a static suspicion into a finding.
        text = "---\nname: boundary\nrequires: dependency\ntech-stack: any\n---\n" + "x\n" * 245
        lf = write(root / "lf.md", text)
        crlf = root / "crlf.md"
        crlf.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        lf_gaps = quality._check_quality_axes(lf, skill_index={"dependency"})
        crlf_gaps = quality._check_quality_axes(crlf, skill_index={"dependency"})
        records["newline_boundary"] = {
            "logical_lines": len(text.splitlines()),
            "lf_raw_bytes": lf.stat().st_size, "crlf_raw_bytes": crlf.stat().st_size,
            "lf_gaps": lf_gaps, "crlf_gaps": crlf_gaps,
            "same_gaps": lf_gaps == crlf_gaps,
        }
        lint = source / "skills/_common/skill-lint-workflow.md"
        records["lint_direct_gate_check"] = quality._check_quality_axes(lint, skill_index=set())
        list_file = write(root / "list.md", "---\nname: lists\nrequires: [a, b]\ntech-stack: [any]\n---\n")
        records["yaml_lists"] = quality._check_quality_axes(list_file, skill_index={"a", "b"})
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
