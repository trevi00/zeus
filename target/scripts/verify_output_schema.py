"""Live provider compatibility experiment; no review, activation or deployment authority."""
import hashlib
import json
import subprocess
from pathlib import Path

from jsonschema import validate

from codex_harness.execution.adapters.output_schema import preflight
from codex_harness.execution.adapters.providers.codex_exec import CodexRuntime
from codex_harness.host_os.adapters.process_groups import run_process
from codex_harness.kernel.ids import canonical
from codex_harness.research.adapters.audit_execution import AuditExecution


def main():
    root = Path(__file__).resolve().parents[1]

    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

    # INV-RELEASE-001: bind evidence to clean exact content; this does not approve a release.
    if git('status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Commit candidate content before running the canary')
    revision, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    destination = root / '.runtime' / 'schema-rework' / revision
    destination.mkdir(parents=True, exist_ok=False)
    # S11 R-S6: ported because U6(d) does not retire the Codex exec transport (reachable through zeus canary; DESIGN-s11 §20.1);
    # the target transport takes its process runner explicitly.
    runtime = CodexRuntime(runner=run_process)
    probe = runtime.probe()
    results = []
    for kind in ('AdaptationProposal', 'IndependentReview', 'partition'):
        schema = (AuditExecution.partition_schema() if kind == 'partition'
                  else AuditExecution.typed_schema(kind))
        preflight(schema)
        schema_text = canonical(schema)
        schema_path = destination / f'{kind}.schema.json'
        schema_path.write_text(schema_text, encoding='utf-8')
        output = destination / f'{kind}.output.json'
        prompt = ('Provider schema compatibility canary only. Do not use tools or modify files. '
                  'Return a synthetic record matching the output schema. Use version 1, empty arrays, '
                  'placeholder strings and accepted=false where applicable. This is not an actual '
                  'review, source analysis, approval or evidence of tests executed.')
        argv = [runtime.executable, 'exec', '--json', '--ephemeral', '--skip-git-repo-check',
                '--color', 'never', '--output-schema', str(schema_path),
                '--output-last-message', str(output), '-C', str(root), '-']
        record = dict(kind=kind, revision=revision, tree=tree, argv=argv, prompt=prompt,
                      cli_version=probe, schema_sha256=hashlib.sha256(schema_text.encode()).hexdigest(),
                      validated=False, scope='actual CLI synthetic schema canary; not independent review')
        try:
            result = run_process(argv, input_text=prompt, timeout=120)
            record.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
            if result.returncode == 0 and output.exists():
                answer = json.loads(output.read_text(encoding='utf-8'))
                validate(answer, schema)
                record.update(validated=True, answer=answer)
        except Exception as exc:
            record.update(error=f'{type(exc).__name__}: {exc}')
        record['unchanged'] = (git('rev-parse', 'HEAD') == revision
                               and git('rev-parse', 'HEAD^{tree}') == tree
                               and not git('status', '--porcelain', '--untracked-files=no'))
        path = destination / f'{kind}.receipt.json'
        path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        results.append(record)
        print(json.dumps({'kind': kind, 'validated': record['validated'], 'receipt': str(path)}), flush=True)
    return 0 if all(r['validated'] and r['unchanged'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
