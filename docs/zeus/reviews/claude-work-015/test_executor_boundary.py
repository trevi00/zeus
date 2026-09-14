import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
import pytest
from test_claude_execution import build, run, receipt_of
from codex_harness.adapters.store import MemoryStore

@pytest.mark.parametrize('mode',['nonzero','wrong_session'])
def test_invalid_terminal_reaches_task_success(tmp_path,monkeypatch,mode):
    def alter(runtime):
        runtime.executable=str(Path.cwd()/'.runtime/review-072/terminal_child.py')
        monkeypatch.setattr(runtime,'__enter__',lambda:runtime)
        monkeypatch.setattr(runtime,'probe',lambda:{'passed':True,'version':'protocol-test'})
        monkeypatch.setattr(runtime,'_read_capabilities',lambda:tuple(runtime._planned_flags()))
    s=build(tmp_path,monkeypatch,MemoryStore(),scenario=mode,patch_runtime=alter)
    row=run(s)
    receipt=receipt_of(s,row)
    print(mode,'task status=',row['status'])
    assert row['status']=='succeeded'
    # These assert the defect, not the desired acceptance behavior.
    if mode=='nonzero': assert receipt['process']['exit_code']==7
    else: assert receipt['session']['match'] is False
