"""Model invocation contract: what a transport supports, what a result proves, what usage is known.

The upstream providers accepted any request fields and dropped the ones a path did not use,
returned the requested model name as if it were the responding model, turned a clean exit with
empty output into a normal answer and read absent usage as zero. Here each transport declares
its support matrix, an unsupported option is refused before execution rather than ignored, the
result is classified by what was actually observed, and unknown stays unknown (INV-INVOCATION-001).
"""
import hashlib
import math

from codex_harness.domain.model import ContractError, canonical, require

# One row per transport: every request option is supported, unsupported or (never) silently dropped.
SUPPORT = {
    'app_server': {'model': 'supported', 'timeout': 'supported', 'output_schema': 'supported',
                   'read_only': 'supported', 'system': 'unsupported', 'temperature': 'unsupported',
                   'max_output_tokens': 'unsupported', 'response_format': 'unsupported'},
}
OUTCOMES = ('accepted', 'empty_answer', 'invalid_output', 'tool_only', 'interrupted', 'inspection_blocked',
            'provider_failure')
AVAILABILITY = ('executable_missing', 'executable_found', 'version_confirmed')


def parse_request(transport, options):
    """Validate one invocation request against the transport's support matrix before execution.

    Returns the accepted options. Unknown options and unsupported-but-present options are refused
    with their names, so a caller can never believe a `temperature` or `system` took effect.
    """
    require(transport in SUPPORT, 'Unknown invocation transport')
    require(isinstance(options, dict), 'Invocation options must be an object')
    matrix = SUPPORT[transport]
    unknown = sorted(set(options) - set(matrix))
    require(not unknown, 'Unknown invocation options: ' + ', '.join(unknown))
    unsupported = sorted(key for key, value in options.items() if matrix[key] == 'unsupported' and value is not None)
    require(not unsupported, f'Options not supported by {transport} (not ignored): ' + ', '.join(unsupported))
    accepted = {}
    if 'model' in options:
        require(type(options['model']) is str and bool(options['model'].strip()), 'model must be a non-empty string')
        accepted['model'] = options['model']
    if 'timeout' in options:
        timeout = options['timeout']
        require(type(timeout) in (int, float) and math.isfinite(timeout) and timeout > 0,
                'timeout must be finite and positive')
        accepted['timeout'] = timeout
    if 'output_schema' in options:
        require(isinstance(options['output_schema'], dict) and bool(options['output_schema']),
                'output_schema must be a non-empty object')
        accepted['output_schema'] = options['output_schema']
    if 'read_only' in options:
        require(type(options['read_only']) is bool, 'read_only must be a boolean')
        accepted['read_only'] = options['read_only']
    return {'transport': transport, 'options': accepted, 'unsupported': [k for k, v in matrix.items() if v == 'unsupported']}


def availability(probe):
    """What a probe proves: an executable and maybe a version. Never model readiness or qualification."""
    if not isinstance(probe, dict) or not probe.get('executable'):
        state = 'executable_missing'
    elif probe.get('passed') and isinstance(probe.get('version'), str) and probe['version'].strip():
        state = 'version_confirmed'
    else:
        state = 'executable_found'
    return {'state': state, 'model_ready': 'unknown', 'qualified': False,
            'reason': 'a probe checks the executable, not the requested model or any qualification'}


def _tool_items(events):
    return sum(1 for event in events if event.get('method') == 'item/completed'
               and event.get('params', {}).get('item', {}).get('type') in {'commandExecution', 'fileChange', 'mcpToolCall'})


def classify_result(result):
    """Name what the run actually produced; only `accepted` is a usable answer."""
    require(isinstance(result, dict), 'Invocation result must be an object')
    if result.get('failure'):
        cause = str(result['failure'].get('cause', ''))
        return 'invalid_output' if cause.startswith('codex-output-') else 'provider_failure'
    if result.get('inspection_blocked'):
        return 'inspection_blocked'
    if result.get('interrupted'):
        return 'interrupted'
    if result.get('answer') is not None:
        return 'accepted'
    if not (result.get('model_answer_text') or '') and _tool_items(result.get('events', [])):
        return 'tool_only'
    return 'empty_answer'


def confirmed_model(events):
    """The model the transport itself reported for this thread or turn; None when it never said."""
    for event in events:
        params = event.get('params', {}) if isinstance(event, dict) else {}
        for holder in (params.get('thread'), params.get('turn'), params):
            model = holder.get('model') if isinstance(holder, dict) else None
            if type(model) is str and model.strip():
                return model
    return None


def stream_hash(events):
    return 'sha256:' + hashlib.sha256(canonical(events).encode('utf-8', 'surrogatepass')).hexdigest()


def usage_record(result):
    """Measured usage with its source; absent usage is `unknown`, never zero."""
    events = result.get('events', []) if isinstance(result, dict) else []
    usage = result.get('usage') if isinstance(result, dict) else None
    record = {'requested_model': result.get('requested_model'), 'confirmed_model': confirmed_model(events),
              'model_confirmation': 'transport_reported' if confirmed_model(events) else 'unknown',
              'stream_hash': stream_hash(events), 'event_count': len(events)}
    def count(part):
        value = usage.get(part, {}).get('totalTokens') if isinstance(usage, dict) and isinstance(usage.get(part), dict) else None
        return value if type(value) is int and value >= 0 else None
    total, last = count('total'), count('last')
    if total is not None or last is not None:
        record.update(source='thread/tokenUsage/updated', total_tokens=total if total is not None else last,
                      last_tokens=last, basis='total' if total is not None else 'last_only')
    else:
        record.update(source='unknown', total_tokens=None, last_tokens=None, basis=None)
    return record


def outcome_check(outcome):
    if outcome not in OUTCOMES:
        raise ContractError('Unknown invocation outcome')
    return outcome
