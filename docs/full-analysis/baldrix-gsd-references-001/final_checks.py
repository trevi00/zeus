"""Validate owned review anchors and whitespace; no reviewed source execution."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-gsd-references-001'
files = json.loads((OUT / 'files.json').read_text(encoding='utf-8'))
text = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
blocks = re.split(r'(?=<a id="file-\d+">)', text)[1:]
assert len(blocks) == 32
for index, (row, block) in enumerate(zip(files, blocks, strict=True), 1):
    assert block.startswith(f'<a id="file-{index:02}"></a>\n## {row["path"]}\n')
commands = []
for path in sorted(OUT.iterdir()):
    if not path.is_file() or path.name == 'artifact-hashes.json':
        continue
    argv = ['git', '-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab',
            'diff', '--no-index', '--check', '--', '/dev/null', str(path)]
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, encoding='utf-8')
    # --no-index reports1 for an added file even when --check emits no errors.
    assert result.returncode in {0, 1} and not result.stdout and not result.stderr, (
        path.name, result.returncode, result.stdout, result.stderr
    )
    commands.append(dict(argv=argv, exit_code=result.returncode,
                         stdout=result.stdout, stderr=result.stderr))
ruff_argv = ['.venv/Scripts/ruff.exe', 'check', str(OUT)]
ruff = subprocess.run(ruff_argv, cwd=ROOT, capture_output=True, encoding='utf-8')
assert ruff.returncode == 0, ruff.stdout + ruff.stderr
receipt = dict(
    workdir=str(ROOT), primary_anchors_in_order=32, exact_path_binding=True,
    metadata_run_chunk='44afca', korean_full_readback_chunk='087034',
    initial_checker_failure='7a4bfb expected git --no-index0 but got1 with empty output for added file; corrected exit semantics, raw helper preserved.',
    korean_readback='All32 per-file notes, review and20 support notes read back; prose intact.',
    standard_git_whitespace_checks=commands,
    ruff=dict(argv=ruff_argv, exit_code=ruff.returncode, stdout=ruff.stdout, stderr=ruff.stderr),
    source_execution=0, upstream_tests_executed=0,
    scope='Owned metadata/format checks only; no semantic coverage added by this script.',
)
(OUT / 'verification-receipt.json').write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n'
)
print(json.dumps(dict(anchors=32, path_binding=True, git_whitespace_files=len(commands),
                      ruff_exit=ruff.returncode, source_execution=0)))
