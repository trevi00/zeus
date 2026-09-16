"""Read-only inventory. Hashes describe bytes, not semantic analysis or adoption approval."""
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

SOURCE = Path('D:/old-projects/codex-harness')
OUT = Path(__file__).resolve().parent


def git(*args):
    return subprocess.run(['git', '-c', f'safe.directory={SOURCE.as_posix()}',
                           '-C', str(SOURCE), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def main():
    commit = git('rev-parse', 'HEAD').decode().strip()
    tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    entries = {}
    for raw in git('ls-tree', '-rz', '-l', 'HEAD').split(b'\0'):
        if not raw:
            continue
        meta, path = raw.split(b'\t', 1)
        mode, kind, oid, size = meta.decode().split()
        entries[path.decode('utf-8')] = {
            'head_mode': mode, 'head_kind': kind, 'head_oid': oid,
            'head_size': int(size) if size != '-' else None,
        }
    indexed = set(filter(None, git('ls-files', '-z').decode('utf-8').split('\0')))
    untracked = set(filter(None, git('ls-files', '--others', '--exclude-standard', '-z')
                           .decode('utf-8').split('\0')))
    rows = []
    for relative in sorted(set(entries) | indexed | untracked):
        p = SOURCE / relative
        row = {'path': relative, **entries.get(relative, {}),
               'in_index': relative in indexed, 'untracked': relative in untracked,
               'semantic_disposition': 'unreviewed'}
        try:
            if p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()):
                row['working_kind'] = 'link-not-followed'
            elif p.is_file():
                before = p.stat()
                with p.open('rb') as stream:
                    value = hashlib.file_digest(stream, 'sha256').hexdigest()
                after = p.stat()
                row.update(working_kind='file', working_size=after.st_size, working_sha256=value,
                           stable_during_read=(before.st_size, before.st_mtime_ns) ==
                           (after.st_size, after.st_mtime_ns))
            else:
                row['working_kind'] = 'missing-or-nonfile'
        except OSError as exc:
            row.update(working_kind='unavailable', error=type(exc).__name__)
        rows.append(row)
    summary = {
        'source': str(SOURCE), 'remote': git('remote', 'get-url', 'origin').decode().strip(),
        'commit': commit, 'tree': tree, 'head_unchanged': git('rev-parse', 'HEAD').decode().strip() == commit,
        'head_paths': len(entries), 'index_paths': len(indexed), 'untracked_nonignored_paths': len(untracked),
        'inventoried_paths': len(rows), 'top_level_counts': dict(Counter(r['path'].split('/')[0] for r in rows)),
        'working_kinds': dict(Counter(r['working_kind'] for r in rows)),
        'semantic_review_complete': False, 'adoption_approved': False,
        'limits': 'Ignored files excluded. Working hashes bind each observed file, not an atomic checkout snapshot. '
                  'No source program or installer executed. No raw asset contents copied.'}
    (OUT / 'inventory.json').write_text(json.dumps({'summary': summary, 'paths': rows}, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
