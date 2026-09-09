"""Original parsers on pinned and explicitly changed scratch inputs, inside Docker."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import yaml

from cli.fleet_atlas import build_fleet_atlas, render_md
from cli.ontology_query import build_graph, q_shared
from cli.seam_gate import evaluate
from cli.seam_scan import scan

SCRIPTS = Path('/source/scripts')
FIXTURE = SCRIPTS / 'synthetic-fleet'


def emit(label, data):
    print(json.dumps({'observation': label, **data}, sort_keys=True), flush=True)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def command(label, argv):
    result = subprocess.run(argv, cwd=SCRIPTS, capture_output=True, timeout=20)
    emit(label, {'argv': argv, 'cwd': str(SCRIPTS), 'returncode': result.returncode,
                'stdout': result.stdout.decode('utf-8'), 'stderr': result.stderr.decode('utf-8'),
                'stdout_sha256': digest(result.stdout)})
    return result


def load(fixture):
    fleet = yaml.safe_load((fixture / 'fleet.syn.yaml').read_text(encoding='utf-8'))
    spec = yaml.safe_load((fixture / 'seams.syn.spec.yaml').read_text(encoding='utf-8'))
    for repo in fleet['repos'].values():
        repo['path'] = str(fixture / Path(repo['path']).name)
    return fleet, spec


def main():
    manual = command('original_ontology_manual_test', [sys.executable, '-B', str(SCRIPTS / 'tests/test_ontology_query.py')])
    if manual.returncode:
        return manual.returncode
    fleet, spec = load(FIXTURE)
    report = scan(fleet, spec)
    graph = build_graph(fleet, spec)
    atlas = build_fleet_atlas(fleet, spec)
    emit('original_baseline', {'report': report, 'node_count': len(graph['nodes']),
                              'edge_count': len(graph['edges']), 'shared': q_shared(graph),
                              'undeclared_graph_node_present': any(n['id'] == 'enum:syn-tran.TranResult' for n in graph['nodes']),
                              'gate': evaluate(report, ('DRIFT', 'BLOCKED'))})
    common = ['--fleet', str(FIXTURE / 'fleet.syn.yaml'), '--spec', str(FIXTURE / 'seams.syn.spec.yaml')]
    dump = command('original_dump', [sys.executable, '-B', '-m', 'cli.ontology_query', *common, 'dump'])
    emit('committed_graph_comparison', {'same_bytes': dump.stdout == (FIXTURE / 'ontology.jsonl').read_bytes(),
                                       'generated_sha256': digest(dump.stdout),
                                       'pinned_sha256': digest((FIXTURE / 'ontology.jsonl').read_bytes())})
    rendered = render_md(atlas, title='synthetic-fleet — Fleet Atlas').encode('utf-8')
    emit('committed_map_comparison', {'same_bytes': rendered == (FIXTURE / 'FLEET-MAP.md').read_bytes(),
                                     'generated_sha256': digest(rendered),
                                     'pinned_sha256': digest((FIXTURE / 'FLEET-MAP.md').read_bytes())})
    emit('proto_file_identity', {'canonical_sha256': digest((FIXTURE / 'syn-tran/protos/tran.proto').read_bytes()),
                                 'poslink_sha256': digest((FIXTURE / 'syn-poslink/protos/tran.proto').read_bytes()),
                                 'agent_sha256': digest((FIXTURE / 'syn-agent/protos/tran.proto').read_bytes())})
    with tempfile.TemporaryDirectory() as td:
        copied = Path(td) / 'fleet'
        shutil.copytree(FIXTURE, copied)
        changed = copied / 'syn-tran/protos/tran.proto'
        before = changed.read_bytes()
        text = before.decode('utf-8')
        assert 'int64  amount' in text and 'rpc SaveTran' in text
        text = text.replace('int64  amount', 'string amount').replace('rpc SaveTran', 'rpc RecordTran')
        changed.write_text(text, encoding='utf-8')
        changed_fleet, changed_spec = load(copied)
        after_proto = scan(changed_fleet, changed_spec)
        emit('scratch_proto_type_and_rpc_change', {'input_before_sha256': digest(before),
             'input_after_sha256': digest(changed.read_bytes()), 'changes': ['amount int64 -> string', 'SaveTran -> RecordTran'],
             'report_unchanged': after_proto == report,
             'canonical_seam': next(s for s in after_proto['seams'] if s['seam_id'] == 'tran__poslink__proto'),
             'actual_protobuf_execution': False})
        envelope = copied / 'syn-agent/lib/src/Common/Data/socket_data.dart'
        before_envelope = envelope.read_bytes()
        text = before_envelope.decode('utf-8')
        assert 'final String? errorCode;' in text and "json['errorCode'] as String?" in text
        text = text.replace('final String? errorCode;', 'final int? errorCode;').replace("json['errorCode'] as String?", "json['errorCode'] as int?")
        envelope.write_text(text, encoding='utf-8')
        after_envelope = scan(changed_fleet, changed_spec)
        emit('scratch_response_type_change', {'input_before_sha256': digest(before_envelope),
             'input_after_sha256': digest(envelope.read_bytes()), 'change': 'agent response errorCode String? -> int?',
             'report_unchanged': after_envelope == after_proto, 'actual_dart_execution': False})
    emit('tool_availability', {name: shutil.which(name) for name in ('javac', 'java', 'dart', 'flutter', 'protoc', 'gradle')})
    emit('limits', {'original_manual_functions_passed': 5, 'scratch_source_inputs_changed': True,
                   'methods_monkeypatched': False, 'model_calls': 0, 'service_e2e': False,
                   'native_windows_or_wsl': False, 'human_acceptance': False})
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
