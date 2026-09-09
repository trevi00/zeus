"""Observe original reference Bash functions only inside the isolated container."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    source = Path('/source/get-shit-done/references/verification-patterns.md')
    raw = source.read_bytes()
    snippet = b''.join(raw.splitlines(keepends=True)[524:552])
    with tempfile.TemporaryDirectory(prefix='guidance-observe-', dir='/tmp') as directory:
        scratch = Path(directory)
        functions = scratch / 'functions.sh'
        functions.write_bytes(snippet)
        plain = scratch / 'plain.txt'
        plain.write_text('ordinary content\n', encoding='utf-8')
        comment = scratch / 'comment.txt'
        comment.write_text('# /api/payments example only\n# padding\n', encoding='utf-8')
        stub = scratch / 'stub.txt'
        stub.write_text('TODO\n', encoding='utf-8')
        missing = scratch / 'absent.txt'
        cases = [
            ('missing_exists', 'check_exists', [str(missing)]),
            ('comment_wiring', 'check_wiring', [str(comment), '/api/payments']),
            ('missing_wiring', 'check_wiring', [str(missing), '/api/payments']),
            ('no_stub_matches', 'check_stubs', [str(plain)]),
            ('stub_control', 'check_stubs', [str(stub)]),
            ('no_substance_pattern', 'check_substantive', [str(plain), '1', 'NEEDLE']),
            ('comment_substance', 'check_substantive', [str(comment), '2', '/api/payments']),
        ]
        observations = []
        for name, function, arguments in cases:
            argv = ['bash', '-c', 'source "$1"; shift; "$@"', 'reference-observation',
                    str(functions), function, *arguments]
            result = subprocess.run(argv, capture_output=True, text=True, timeout=5,
                                    cwd=scratch, check=False)
            observations.append({'name': name, 'argv': argv, 'returncode': result.returncode,
                                 'stdout': result.stdout, 'stderr': result.stderr})
        payload = {
            'source_path': str(source), 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'original_range': [525, 552], 'snippet_sha256': hashlib.sha256(snippet).hexdigest(),
            'fixture_files': {p.name: {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                                     'content': p.read_text(encoding='utf-8')}
                              for p in [plain, comment, stub]},
            'observations': observations, 'original_reference_bash_calls': len(observations),
            'full_verifier_or_source_suite_executed': False,
        }
        print(json.dumps(payload))


if __name__ == '__main__':
    main()
