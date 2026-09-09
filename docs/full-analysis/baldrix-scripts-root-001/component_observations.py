"""Original CLI observations in isolated scratch inputs; no product acceptance."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SOURCE = Path("/source/scripts")


def emit(name, **data):
    print(json.dumps({"case": name, **data}, sort_keys=True, ensure_ascii=True))


def run(name, argv, cwd, stdin=None):
    proc = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, timeout=15)
    emit(name, argv=argv, returncode=proc.returncode,
         stdout=proc.stdout.decode("utf-8", errors="replace"),
         stderr=proc.stderr.decode("utf-8", errors="replace"))
    return proc


def cli(name, script, root, args=(), stdin=None):
    return run(name, [sys.executable, "-B", str(SOURCE / script), *args], root, stdin)


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        cli("jacoco_missing", "jacoco-gap.py", root)
        report = root / "report.xml"
        for name, body in (
            ("empty_report", "<report/>"),
            ("root_gap_without_methods", '<report><counter type="LINE" missed="2" covered="3"/></report>'),
            ("class_gap_without_methods", '<report><package name="p"><class name="p/C"><counter type="LINE" missed="2" covered="3"/></class></package></report>'),
        ):
            report.write_text(body, encoding="utf-8")
            cli("jacoco_" + name, "jacoco-gap.py", root, ["--xml", str(report)])
            cli("jacoco_" + name + "_summary", "jacoco-gap.py", root,
                ["--xml", str(report), "--summary-only"])
        body = ('<report><counter type="LINE" missed="1" covered="0"/><package name="p">'
                '<class name="p/Dto"><counter type="LINE" missed="1" covered="0"/>'
                '<method name="m" line="1"><counter type="LINE" missed="1" covered="0"/></method>'
                '</class></package></report>')
        report.write_text(body, encoding="utf-8")
        cli("jacoco_excluded_detail", "jacoco-gap.py", root, ["--xml", str(report), "--exclude", "Dto"])
        cli("jacoco_excluded_summary", "jacoco-gap.py", root,
            ["--xml", str(report), "--exclude", "Dto", "--summary-only"])
        document = root / "diagram.md"
        for name, body in (
            ("no_blocks", "No diagram here.\n"),
            ("unclosed_fence", "```mermaid\nflowchart TD\nA --> B\n"),
            ("empty_block", "```mermaid\n\n```\n"),
            ("unknown_type", "```mermaid\nunknownType\nA --> B\n```\n"),
            ("unparsed_body", "```mermaid\nflowchart TD\nnot_a_parsed_grammar [][][]\n```\n"),
            ("two_blocks", "```mermaid\nflowchart TD\nA --> B\n```\n```mermaid\ngraph LR\nC --> D\n```\n"),
        ):
            document.write_text(body, encoding="utf-8")
            before = hashlib.sha256(document.read_bytes()).hexdigest()
            cli("mermaid_" + name, "mermaid-validate.py", root, [str(document)])
            assert before == hashlib.sha256(document.read_bytes()).hexdigest()
        empty = root / "empty"
        empty.mkdir()
        cli("mermaid_empty_directory", "mermaid-validate.py", root, [str(empty)])
        for name, payload in (
            ("two_dependency_paths", {"file_paths": ["a/package.json", "b/pom.xml"]}),
            ("substring_match", {"file_paths": ["a/.envoy/config", "b/CLAUDE.md.backup"]}),
            ("windows_basename", {"file_paths": [r"C:\repo\package.json"]}),
            ("malformed_entry_discards_prior", {"file_paths": ["package.json", 1]}),
            ("nonobject", ["package.json"]),
        ):
            cli("file_changed_" + name, "file-changed-handler.py", root,
                stdin=json.dumps(payload).encode())
        cli("file_changed_invalid_json", "file-changed-handler.py", root, stdin=b"{")
        bash, git, jq = shutil.which("bash"), shutil.which("git"), shutil.which("jq")
        emit("available_tools", bash=bash, git=git, jq=jq)
        if bash and git:
            repo = root / "repo"
            repo.mkdir()
            run("git_init_scratch", [git, "init", "-q", str(repo)], root)
            readme = repo / "README"
            readme.write_text("isolated install observation\n", encoding="utf-8")
            run("git_stage_scratch", [git, "add", "README"], repo)
            run("git_commit_scratch", [git, "-c", "user.name=Review", "-c", "user.email=review@example.invalid",
                                       "commit", "-qm", "isolated input"], repo)
            original_hook = repo / ".git/hooks/pre-commit"
            original_hook.write_text("#!/bin/sh\n# existing local hook\n", encoding="utf-8")
            run("installer_existing_hook", [bash, str(SOURCE / "install_pre_commit.sh")], repo)
            emit("installer_hook_after", existing_marker_retained="existing local hook" in original_hook.read_text(),
                 pre_push_exists=(repo / ".git/hooks/pre-push").exists())
            custom = repo / "custom-hooks"
            custom.mkdir()
            run("git_custom_hooks_path", [git, "config", "core.hooksPath", str(custom)], repo)
            run("installer_custom_hooks_path", [bash, str(SOURCE / "install_pre_commit.sh")], repo)
            emit("custom_hooks_after", configured_pre_commit_exists=(custom / "pre-commit").exists(),
                 default_pre_commit_exists=original_hook.exists())
            run("git_unset_custom_hooks", [git, "config", "--unset", "core.hooksPath"], repo)
            linked = root / "linked"
            run("git_linked_worktree", [git, "worktree", "add", "--detach", str(linked), "HEAD"], repo)
            if linked.is_dir():
                run("installer_linked_worktree", [bash, str(SOURCE / "install_pre_commit.sh")], linked)
        else:
            emit("installer_unavailable", reason="Actual bash/git dependencies unavailable; no substitution")
        if bash:
            run("context_bar_no_transcript", [bash, str(SOURCE / "context-bar.sh")], root,
                json.dumps({"cwd": str(empty), "model": {"display_name": "Synthetic"},
                            "context_window": {"context_window_size": 200000}}).encode())
        emit("complete", limits="Synthetic inputs, actual original CLI processes and optional isolated Git installation. No actual push, full hook suite, host registration, current transcript, renderer/build/device/human/model acceptance.",
             claude_home_is_scratch=os.environ.get("CLAUDE_HOME", "").startswith("/tmp/"))


if __name__ == "__main__":
    main()
