"""Real Windows suspended process; inject only a failed job assignment, then clean up our PID."""
import json
import subprocess
import sys
from pathlib import Path
import codex_harness.adapters.process_tree as m

original_assign = m._assign
original_spawn = m.subprocess.Popen
children = []
def capture(*args, **kwargs):
    process = original_spawn(*args, **kwargs)
    children.append(process)
    return process
m._assign = lambda *args: False
m.subprocess.Popen = capture
result = {}
try:
    try:
        m.ProcessTree.spawn([sys.executable, '-c', 'import time; time.sleep(60)'],
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except m.TreeOwnershipError as exc:
        result['error'] = str(exc)
    result['still_alive_after_refusal'] = [process.poll() is None for process in children]
finally:
    m._assign = original_assign
    m.subprocess.Popen = original_spawn
    for process in children:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
print(json.dumps(result, indent=2))
assert result['still_alive_after_refusal'] == [True], 'The defect is no longer reproduced'
