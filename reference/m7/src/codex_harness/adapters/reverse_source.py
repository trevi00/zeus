"""Observe a Git source without executing its hooks or project code."""
from pathlib import Path

from codex_harness.adapters.commands import run_process


def observe_source(path):
    root = str(Path(path).resolve())
    def git(*args):
        result = run_process(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                              '-c', 'core.untrackedCache=false', '-C', root, *args], timeout=15)
        if result.returncode:
            raise ValueError('Git source observation failed')
        return result.stdout.strip()
    try:
        repository = git('rev-parse', '--show-toplevel')
        if Path(repository).resolve() != Path(root):
            return {'status': 'unknown', 'repository': repository,
                    'reason': 'Source must identify the Git worktree root'}
        before = git('rev-parse', 'HEAD')
        tree = git('rev-parse', before + '^{tree}')
        dirty = bool(git('status', '--porcelain=v1', '--untracked-files=all',
                         '--ignore-submodules=none'))
        after = git('rev-parse', 'HEAD')
        if before != after:
            return {'status': 'unknown', 'repository': repository, 'reason': 'HEAD changed during observation'}
        return {'status': 'dirty' if dirty else 'clean',
                'repository': str(Path(repository).resolve()), 'commit': before, 'tree': tree}
    except Exception as exc:
        return {'status': 'unknown', 'repository': root, 'reason': type(exc).__name__}
