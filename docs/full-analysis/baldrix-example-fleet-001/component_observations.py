"""Run original fixture tests and CLI inside the separately constrained container."""
import collections
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import yaml

from cli.fleet_atlas import build_fleet_atlas, render_md
from cli.ontology_query import build_graph, q_orphans, q_shared
from cli.seam_gate import evaluate
from cli.seam_scan import scan

SCRIPTS = Path('/source/scripts')
FIXTURE = SCRIPTS / 'example-fleet'


def emit(label, data):
    print(json.dumps({'observation': label, **data}, sort_keys=True), flush=True)


def command(label, argv, cwd=SCRIPTS):
    result = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=20)
    emit(label, {'argv': argv, 'cwd': str(cwd), 'returncode': result.returncode,
                'stdout': result.stdout.decode('utf-8'), 'stderr': result.stderr.decode('utf-8'),
                'stdout_sha256': hashlib.sha256(result.stdout).hexdigest()})
    return result


def inputs(absent=False):
    suffix = 'absent' if absent else 'example'
    fleet = yaml.safe_load((FIXTURE / f'fleet.{suffix}.yaml').read_text())
    spec = yaml.safe_load((FIXTURE / f'seams.{suffix}.spec.yaml').read_text())
    for repo in fleet['repos'].values():
        if repo.get('path'):
            repo['path'] = str(SCRIPTS / repo['path'])
    return fleet, spec


def main():
    manual = command('original_manual_test', [sys.executable, '-B', str(SCRIPTS / 'tests/test_example_fleet.py')])
    if manual.returncode:
        return manual.returncode
    fleet, spec = inputs()
    report = scan(fleet, spec)
    graph = build_graph(fleet, spec)
    emit('original_fixture', {'statuses': dict(collections.Counter(s['status'] for s in report['seams'])),
                             'nodes': len(graph['nodes']), 'edges': len(graph['edges']),
                             'shared': q_shared(graph), 'orphans': q_orphans(graph)})
    common = ['--fleet', str(FIXTURE / 'fleet.example.yaml'), '--spec', str(FIXTURE / 'seams.example.spec.yaml')]
    dump = command('original_graph_dump', [sys.executable, '-B', '-m', 'cli.ontology_query', *common, 'dump'])
    pinned = (FIXTURE / 'ontology.jsonl').read_bytes()
    emit('committed_graph_comparison', {'same_bytes': pinned == dump.stdout,
                                      'pinned_sha256': hashlib.sha256(pinned).hexdigest(),
                                      'generated_sha256': hashlib.sha256(dump.stdout).hexdigest()})
    atlas = build_fleet_atlas(fleet, spec)
    committed = (FIXTURE / 'FLEET-MAP.md').read_bytes()
    for label, title in [('explicit_title', 'example-fleet — Fleet Atlas (ontology ACTIVE)'), ('default_title', 'Fleet Atlas')]:
        generated = render_md(atlas, title=title).encode('utf-8')
        emit('atlas_' + label, {'same_bytes': generated == committed,
                               'generated_sha256': hashlib.sha256(generated).hexdigest(),
                               'pinned_sha256': hashlib.sha256(committed).hexdigest()})
    command('gate_default', [sys.executable, '-B', '-m', 'cli.seam_gate', *common, '--json'])
    command('scan_from_other_cwd', [sys.executable, '-B', '-m', 'cli.seam_scan', *common, '--no-write', '--json'], Path('/tmp'))
    absent_fleet, absent_spec = inputs(True)
    absent_report = scan(absent_fleet, absent_spec)
    absent_graph = build_graph(absent_fleet, absent_spec)
    emit('absent_input', {'report': absent_report, 'graph': absent_graph,
                         'atlas': build_fleet_atlas(absent_fleet, absent_spec),
                         'default_decision': evaluate(absent_report, ('DRIFT', 'BLOCKED')),
                         'drift_only_decision': evaluate(absent_report, ('DRIFT',))})
    absent_common = ['--fleet', str(FIXTURE / 'fleet.absent.yaml'), '--spec', str(FIXTURE / 'seams.absent.spec.yaml')]
    command('absent_gate_default', [sys.executable, '-B', '-m', 'cli.seam_gate', *absent_common, '--json'])
    command('absent_gate_drift_only', [sys.executable, '-B', '-m', 'cli.seam_gate', *absent_common, '--fail-on', 'DRIFT', '--json'])
    command('unrecognized_fail_on', [sys.executable, '-B', '-m', 'cli.seam_gate', *common, '--fail-on', 'TYPO', '--json'])
    emit('empty_declared_scope', {'decision': evaluate(scan(fleet, {'seams': []}), ('DRIFT', 'BLOCKED'))})
    emit('compiler_availability', {'javac': shutil.which('javac'), 'java_compilation_performed': False})
    emit('limits', {'actual_service_execution': False, 'business_acceptance': False,
                    'windows_native_or_wsl_execution': False, 'methods_monkeypatched': False})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
