"""Check owned review identity, exact read coverage, Ruff and whitespace only."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-gsd-workflows-003'
files = json.loads((OUT / 'files.json').read_text(encoding='utf-8'))
reads = json.loads((OUT / 'read-receipts.json').read_text(encoding='utf-8'))
text = (OUT / 'file-reviews.md').read_text(encoding='utf-8')
blocks = re.split(r'(?=<a id="file-\d+">)', text)[1:]
assert len(blocks) == len(reads['primary_reads']) == 17
for index, (row, block, read) in enumerate(zip(files, blocks, reads['primary_reads'], strict=True), 1):
    assert block.startswith(f'<a id="file-{index:02}"></a>\n## {row["path"]}\n')
    assert read['index'] == index
    numbers = [number for start, end in read['ranges'] for number in range(start, end + 1)]
    assert numbers == list(range(1, row['line_count'] + 1))
commands = []
for path in sorted(OUT.iterdir()):
    if not path.is_file() or path.name == 'artifact-hashes.json':
        continue
    argv = ['git', '-c', 'core.whitespace=blank-at-eol,blank-at-eof,space-before-tab',
            'diff', '--no-index', '--check', '--', '/dev/null', str(path)]
    result = subprocess.run(argv, cwd=ROOT, capture_output=True, encoding='utf-8')
    assert result.returncode in {0, 1} and not result.stdout and not result.stderr, (
        path.name, result.returncode, result.stdout, result.stderr
    )
    commands.append(dict(argv=argv, exit_code=result.returncode,
                         stdout=result.stdout, stderr=result.stderr))
ruff_argv = ['.venv/Scripts/ruff.exe', 'check', str(OUT)]
ruff = subprocess.run(ruff_argv, cwd=ROOT, capture_output=True, encoding='utf-8')
assert ruff.returncode == 0, ruff.stdout + ruff.stderr
receipt = dict(
    workdir=str(ROOT), primary_anchors_in_order=17, exact_path_binding=True,
    full_read_ranges_cover_exact_primary_lines=True,
    korean_primary_readback_chunk='5562f8',
    korean_support_overview_readback_chunk='3f94f0',
    korean_readback='All 17 per-file notes and 24 support/overview prose read back; text intact.',
    standard_git_whitespace_checks=commands,
    ruff=dict(argv=ruff_argv, exit_code=ruff.returncode, stdout=ruff.stdout, stderr=ruff.stderr),
    source_execution=0, upstream_tests_executed=0,
    scope='Owned metadata/format checks only; no semantic coverage added by this script.',
)
(OUT / 'verification-receipt.json').write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n'
)
print(json.dumps(dict(anchors=17, path_binding=True, full_read_ranges=True,
                      git_whitespace_files=len(commands), ruff_exit=ruff.returncode,
                      source_execution=0)))
