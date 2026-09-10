"""Host-owned Docker execution with no source-agent Docker socket or credentials."""
import base64
import hashlib
import os
import platform
import re
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from codex_harness.adapters.commands import run_process
from codex_harness.application.source_execution import SourceExecutions
from codex_harness.domain.check_results import classify_isolated_run
from codex_harness.domain.model import ContractError, canonical, digest, require
from codex_harness.domain.policy import POLICY
from codex_harness.domain.research import ExecutionReceipt, SourceIdentity

DRIVER_HASH = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class SourceExecutionClient:
    def execute(self, workflow, task, source, command, timeout=POLICY.source_request_seconds):
        queue = SourceExecutions(workflow)
        request = queue.request(task, source, command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = queue.result(task, request['id'])
            require(row['status'] != 'cancelled', 'Source execution cancelled')
            if row['status'] == 'succeeded':
                body = dict(row['receipt'])
                body['source'] = SourceIdentity(**body['source'])
                return ExecutionReceipt(**body)
            time.sleep(1)
        raise TimeoutError('Host source execution did not complete within its budget')


def bounded_command(argv, timeout):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    tails = [b'', b'']
    def drain(stream, index):
        while block := stream.read(4096):
            tails[index] = (tails[index] + block)[-POLICY.source_output_bytes:]
    readers = [threading.Thread(target=drain, args=(stream, i), daemon=True)
               for i, stream in enumerate((process.stdout, process.stderr))]
    for thread in readers:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except BaseException:
        process.kill()
        process.wait(timeout=10)
        raise
    finally:
        for thread in readers:
            thread.join(timeout=5)
    return subprocess.CompletedProcess(argv, process.returncode,
        tails[0].decode('utf-8', errors='replace'), tails[1].decode('utf-8', errors='replace'))


class _ClientTimeout(Exception):
    """The docker client outlived its deadline; the container may still be running until removed."""


class DockerSourceRunner:
    def __init__(self, root, artifacts):
        self.root, self.artifacts = Path(root), artifacts
        self.root.mkdir(parents=True, exist_ok=True)

    def execute(self, source, command, image, attempt=None):
        source.validate()
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', image) is not None, 'Immutable runner image required')
        require(command and all(isinstance(arg, str) and arg for arg in command), 'Invalid command')
        configuration = {'image': image, 'runner': 'host-docker-v1', 'driver_sha256': DRIVER_HASH,
                         'host_platform': platform.platform(), 'policy': POLICY.snapshot()}
        manifest = self.artifacts.document(source.manifest_ref)
        require(all(manifest[k] == getattr(source, k) for k in ('repository', 'commit', 'tree')),
                'Runner source mismatch')
        name = 'harness-source-' + uuid4().hex
        with tempfile.TemporaryDirectory(prefix='source-', dir=self.root) as directory:
            root = Path(directory).resolve()
            require(root.parent == self.root.resolve(), 'Temporary source root escaped workspace')
            stage, verdict = 'materialize', None
            try:
                seen = set()
                for entry in manifest['entries']:
                    name_bytes = os.fsdecode(base64.b64decode(entry['path'], validate=True))
                    if os.name == 'nt':
                        parts = name_bytes.split('/')
                        require(all(not re.search(r'[<>:"\\|?*\x00-\x1f]', part)
                                    and not part.endswith(('.', ' '))
                                    and part.split('.')[0].upper() not in
                                    {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(10)],
                                     *[f'LPT{i}' for i in range(10)]} for part in parts),
                                'Source path cannot be represented on this host')
                    path = root / name_bytes
                    require(root in path.resolve().parents, 'Unsafe source path')
                    identity = os.path.normcase(str(path.resolve()))
                    require(identity not in seen, 'Source path collision on this host')
                    seen.add(identity)
                    if entry['mode'] == '160000':
                        continue
                    envelope = self.artifacts.document(entry['artifact_ref'])
                    raw = base64.b64decode(envelope['data'], validate=True)
                    require(hashlib.sha256(raw).hexdigest() == envelope['bytes_sha256'], 'Invalid source bytes')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)  # Source symlinks remain inert regular files.
                    path.chmod(0o755 if entry['mode'] == '100755' else 0o644)
                argv = ['docker', 'run', '--rm', '--name', name, '--network', 'none',
                        '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                        '--memory', str(POLICY.source_memory_mb) + 'm', '--cpus', str(POLICY.source_cpus),
                        '--pids-limit', str(POLICY.source_pids),
                        '--tmpfs', '/tmp:rw,nosuid,size=' + str(POLICY.source_scratch_mb) + 'm', '-e', 'HOME=/tmp',
                        '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'PYTHONPATH=/source',
                        '-v', str(root) + ':/source:ro', '-w', '/source',
                        '--entrypoint', '/usr/bin/timeout', image, '--signal=KILL', '--',
                        str(POLICY.source_execution_seconds), *command]
                stage = 'spawn'
                try:
                    result = bounded_command(argv, timeout=POLICY.source_execution_seconds + 10)
                except subprocess.TimeoutExpired as exc:
                    stage = 'run'
                    raise _ClientTimeout(str(exc)) from exc
                stage = 'run'
                status = result.returncode
                # INV-RUNNER-001: the category comes from where the attempt ended and what it produced.
                verdict = classify_isolated_run(stage='run', exit_status=status, stdout=result.stdout,
                                                stderr=result.stderr, command=list(command))
                output = {'argv': argv, 'stdout': result.stdout[-POLICY.source_output_bytes:],
                          'stderr': result.stderr[-POLICY.source_output_bytes:], 'exit_status': status,
                          'output_tail_limit_bytes': POLICY.source_output_bytes,
                          'stdout_sha256': hashlib.sha256(result.stdout.encode('utf-8', 'surrogatepass')).hexdigest(),
                          'stderr_sha256': hashlib.sha256(result.stderr.encode('utf-8', 'surrogatepass')).hexdigest()}
                blocked = verdict['category'] != 'executed'
            except _ClientTimeout as exc:
                verdict = classify_isolated_run(stage='run', exit_status=None, stdout='', stderr='', command=list(command),
                                                client_timeout=True, error=str(exc))
                output, status, blocked = {'error': str(exc)}, 125, True
            except (OSError, subprocess.TimeoutExpired, ContractError, ValueError) as exc:
                # Isolation could not be established or the runner could not start: unavailable, never a
                # substitute execution in the host environment.
                verdict = classify_isolated_run(stage=stage if stage != 'run' else 'spawn', exit_status=None, stdout='',
                                                stderr='', command=list(command), error=type(exc).__name__ + ': ' + str(exc)[:300])
                output, status, blocked = {'error': str(exc)}, 125, True
            finally:
                # Remove only this uniquely named container, including a timed-out Docker client.
                try:
                    run_process(['docker', 'rm', '-f', name], timeout=20)
                except (OSError, subprocess.TimeoutExpired):
                    pass  # The in-container deadline also bounds orphaned execution.
            document = {**output, 'configuration': configuration, 'verdict': verdict, 'command': list(command),
                        'attempt': attempt, 'runner_mode': 'docker-networkless-readonly',
                        'note': 'passed is decided by category, denominator and output class; never by exit status alone'}
            ref = self.artifacts.put(canonical(document), 'host-isolated-source-execution')['ref']
        return ExecutionReceipt(source, digest(configuration), command,
            'docker-networkless-readonly-source-inert-links-no-credentials', status, ref,
            'harness:host-docker-source-runner-v1', blocked)

    def run_one(self, workflow):
        queue = SourceExecutions(workflow)
        row = queue.claim()
        if row:
            receipt = self.execute(SourceIdentity(**row['source']), row['command'], row['image'],
                                   attempt={'request_id': row['id'], 'owner': row['owner'], 'task_id': row['task']['id'],
                                            'generation': row['task']['generation'], 'release_id': row.get('release_id')})
            queue.complete(row, receipt)
        return row
