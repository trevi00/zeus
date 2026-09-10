"""FA-002 reproduction on the actual local upstream lessons, bound to the partition inventory.

Runs the Zeus import in preview mode over a lessons directory, then cross-checks each file's
SHA-256 against the observed/pinned entries in docs/full-analysis/harness-experience/inventory.json.
No database, artifact, Codex or GitHub write happens.
Usage: uv run python docs/zeus/implementation/experience-claims-001/probe.py LESSONS_DIR [output.json]
"""
import json
import platform
import sys
from pathlib import Path

from codex_harness.adapters.experience import preview_lessons

ROOT = Path(__file__).resolve().parents[4]
INVENTORY = ROOT / 'docs/full-analysis/harness-experience/inventory.json'


def inventory_hashes():
    entries = json.loads(INVENTORY.read_text(encoding='utf-8'))
    entries = entries if isinstance(entries, list) else next(v for v in entries.values() if isinstance(v, list))
    known = {}
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get('path', '')).startswith('knowledge/lessons/'):
            known.setdefault(entry['path'], {})[entry['version']] = entry.get('actual_sha256') or entry.get('sha256')
    return known


def main():
    directory = Path(sys.argv[1])
    report = preview_lessons([directory], 'harness', {'kind': 'observed', 'revision': None}, 'knowledge/lessons/')
    known = inventory_hashes()
    for claim in report['claims']:
        versions = known.get(claim['path'], {})
        claim['inventory_match'] = next((kind for kind, sha in versions.items() if sha == claim['sha256']), None)
    report.update({
        'python': sys.version, 'os': platform.platform(),
        'inventory': str(INVENTORY.relative_to(ROOT)),
        'inventory_matched': sum(claim['inventory_match'] is not None for claim in report['claims']),
        'scope': 'Preview parse of actual local lesson bytes; no PostgreSQL, artifact, Codex or GitHub write. '
                 'Inventory match binds bytes to the reviewed partition, not to any fresh upstream execution.'})
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(text, encoding='utf-8')
    sys.stdout.buffer.write(text.encode('utf-8'))


if __name__ == '__main__':
    main()
