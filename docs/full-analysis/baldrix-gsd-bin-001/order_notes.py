"""Order this review's existing prose; never reads upstream code."""

import re
from pathlib import Path

path = Path('C:/Users/rudtn/zeus/docs/full-analysis/baldrix-gsd-bin-001/file-reviews.md')
text = path.read_text(encoding='utf-8')
prefix = text.split('<a id=')[0]
numbers = re.findall(r'<a id="file-(\d+)"></a>', text)
assert len(numbers) == len(set(numbers)) == 7
blocks = re.split(r'(?=<a id="file-\d+"></a>)', text)[1:]
blocks = [re.sub(r'(?m)^# .+\n', '', block) for block in blocks]
blocks.sort(key=lambda block: int(re.search(r'file-(\d+)', block).group(1)))
path.write_text((prefix + ''.join(blocks)).rstrip() + '\n', encoding='utf-8', newline='\n')
print('Ordered7 unique primary review anchors; existing prose preserved.')
