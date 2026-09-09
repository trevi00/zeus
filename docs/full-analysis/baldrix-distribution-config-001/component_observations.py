"""Bounded original CLI observations inside an isolated, read-only source container."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def emit(row):
    print(json.dumps(row, ensure_ascii=False), flush=True)


def observe(label, home, expected, inputs=None):
    argv = [sys.executable, '-B', '-m', 'cli.brain_snapshot', 'status']
    env = {**os.environ, 'CLAUDE_HOME': str(home)}
    result = subprocess.run(argv, cwd='/source/scripts', env=env, capture_output=True, timeout=10)
    emit({'observation': label, 'argv': argv, 'claude_home': str(home),
          'inputs': inputs or [], 'returncode': result.returncode,
          'stdout': result.stdout.decode('utf-8'), 'stderr': result.stderr.decode('utf-8'),
          'stdout_sha256': digest(result.stdout), 'stderr_sha256': digest(result.stderr)})
    assert result.returncode == expected, (label, result.returncode)
    return json.loads(result.stdout)['result'] if expected == 0 else None


def main():
    observe('committed_snapshot_status', Path('/source'), 0)
    cases = [
        ('absent_snapshot', {}, 0),
        ('malformed_middle_line', {'brain/l1/insight-index.jsonl':
            '{"id":"first","schema_version":"1"}\nBROKEN-MIDDLE\n'
            '{"id":"last","schema_version":"1"}\n'}, 0),
        ('non_object_lines', {'brain/l1/insight-index.jsonl': '[]\nnull\n42\n'}, 0),
        ('missing_schema_and_id', {'brain/l1/insight-index.jsonl': '{"unrelated":true}\n'}, 0),
        ('malformed_graduation', {'brain/graduation/graduation-state.json': 'BROKEN\n'}, 0),
        ('mismatched_schema_control', {'brain/l1/insight-index.jsonl':
            '{"id":"control","schema_version":"999"}\n'}, 1),
    ]
    with tempfile.TemporaryDirectory(prefix='distribution-observation-') as temporary:
        root = Path(temporary)
        for label, contents, expected in cases:
            home = root / label
            home.mkdir()
            inputs = []
            for relative, body in contents.items():
                path = home / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                raw = body.encode('utf-8')
                path.write_bytes(raw)
                inputs.append({'path': relative, 'utf8': body, 'bytes': len(raw), 'sha256': digest(raw)})
            status = observe(label, home, expected, inputs)
            if status and label in ('malformed_middle_line', 'non_object_lines', 'missing_schema_and_id'):
                expected_count = {'malformed_middle_line': 2, 'non_object_lines': 0,
                                  'missing_schema_and_id': 1}[label]
                assert status['l1']['insight-index.jsonl']['brain'] == expected_count
        from lib.tech_stack import load_tech_stack
        selected = load_tech_stack('/source')
        nested = load_tech_stack('/source/scripts')
        existing = [p for p in selected if (Path('/source/skills') / p).is_dir()]
        assert selected == ['_common', 'python/lang', 'python'] and existing == ['_common']
        assert nested is None
        emit({'observation': 'original_tech_stack_loader', 'root_candidates': selected,
              'existing_candidate_directories': existing, 'nested_cwd_candidates': nested,
              'full_skill_match_hook_executed': False})


if __name__ == '__main__':
    main()
