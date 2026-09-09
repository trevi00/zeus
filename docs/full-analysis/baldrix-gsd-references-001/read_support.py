"""Print selected inert support bytes as UTF8, no source imports."""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path('C:/Users/rudtn/zeus')
OUT = ROOT / 'docs/full-analysis/baldrix-gsd-references-001'
specs = json.loads((OUT / 'support-specs.json').read_text(encoding='utf-8'))
for index in range(int(sys.argv[1]), int(sys.argv[2]) + 1):
    path, ranges, _ = specs[index - 1]
    lines = (ROOT / '.runtime/absorption/sources/baldrix/pinned' / path).read_text(encoding='utf-8').splitlines()
    print(f'SUPPORT {index} {path}')
    for start, end in ranges:
        assert 1 <= start <= end <= len(lines)
        print('\n'.join(f'{number}: {lines[number - 1]}' for number in range(start, end + 1)))
