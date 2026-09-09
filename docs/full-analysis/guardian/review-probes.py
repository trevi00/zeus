"""Review-only probes. Execute solely in the documented source-only Docker sandbox."""
import importlib
import json
import os
import tempfile
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    guardian = root / 'guardian'
    guardian.mkdir()
    os.environ['GUARDIAN_HOME'] = str(guardian)
    import watchdog
    import ledger_seal
    import issue_token
    importlib.reload(watchdog)
    importlib.reload(ledger_seal)
    importlib.reload(issue_token)
    state = root / 'hstate'
    state.mkdir()
    notification = state / 'notifications.jsonl'
    notification.write_text('{"message":"A"}\n{"message":"B"}\n')
    sf = guardian / 'state' / 'watchdog.json'
    watchdog._relay_notifications({}, state, sf)
    notification.write_text('{"message":"C"}\n')
    watchdog._relay_notifications({}, state, sf)
    log = (guardian / 'alerts.log').read_text(encoding='utf-8')
    print(json.dumps({'probe':'relay_truncation','relays_C':' C' in log,
                      'drift_alert':'통지 파일 변조 감지' in log}))
    notification.write_text('[]\n[]\n[]\n')
    try:
        watchdog._relay_notifications({}, state, sf)
        scalar = 'accepted'
    except Exception as exc:
        scalar = type(exc).__name__
    print(json.dumps({'probe':'valid_json_non_object_notification','result':scalar}))
    ledger = root / 'events.jsonl'
    ledger.write_text('{"id":"a"}\n')
    ledger_seal.seal(ledger)
    ledger.write_text('{"id":"forged"}\n')
    print(json.dumps({'probe':'sealed_prefix_changed','verdict':ledger_seal.verify(ledger)[0]}))
    ledger.with_name('events.jsonl.compacted.synthetic').write_text('{}\n')
    print(json.dumps({'probe':'same_tamper_plus_new_sidecar','verdict':ledger_seal.verify(ledger)[0]}))
    print(json.dumps({'probe':'invalid_duration_cli','results':{
        v: issue_token._hours(['issue_token.py','issue','--hours',v])[0]
        for v in ['nan','inf','-1','0']}}))
