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
    # `unconfirmed` is the honest third state: the transport has a mechanism for the option but this
    # harness has not verified that the mechanism enforces the option's meaning. Asking for it is
    # refused rather than assumed, and asking for its absence is accepted because nothing is claimed.
    'claude_cli': {'model': 'supported', 'timeout': 'supported', 'output_schema': 'supported',
                   'max_budget_usd': 'supported', 'permission_mode': 'supported',
                   'read_only': 'unconfirmed', 'session_resume': 'unsupported',
                   'system': 'unsupported', 'temperature': 'unsupported',
                   'max_output_tokens': 'unsupported', 'response_format': 'unsupported'},
}
SUPPORT_STATES = ('supported', 'unsupported', 'unconfirmed')
USAGE_SOURCES = ('unknown', 'thread/tokenUsage/updated', 'claude/result.usage')
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
    unproven = sorted(key for key, value in options.items() if matrix[key] == 'unconfirmed' and value)
    require(not unproven, f'Options {transport} cannot prove it applies (not assumed): ' + ', '.join(unproven))
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
    if 'max_budget_usd' in options:
        budget = options['max_budget_usd']
        require(type(budget) in (int, float) and math.isfinite(budget) and budget > 0,
                'max_budget_usd must be finite and positive')
        accepted['max_budget_usd'] = float(budget)
    if 'permission_mode' in options:
        require(type(options['permission_mode']) is str and bool(options['permission_mode'].strip()),
                'permission_mode must be a non-empty string')
        accepted['permission_mode'] = options['permission_mode']
    return {'transport': transport, 'options': accepted,
            'unsupported': [k for k, v in matrix.items() if v == 'unsupported'],
            'unconfirmed': [k for k, v in matrix.items() if v == 'unconfirmed']}


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
        return 'invalid_output' if '-output-' in cause else 'provider_failure'
    if result.get('inspection_blocked'):
        return 'inspection_blocked'
    if result.get('interrupted'):
        return 'interrupted'
    if result.get('answer') is not None:
        return 'accepted'
    observed_tools = result.get('tool_items')
    if observed_tools is None:
        observed_tools = _tool_items(result.get('events', []))
    if not (result.get('model_answer_text') or '') and observed_tools:
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


CLAUDE_USAGE_PARTS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens',
                      'cache_read_input_tokens')


def _claude_usage(result, record):
    """Claude Code reports usage once, in its terminal result message.

    Only that message is read. Assistant messages and any redelivered or partial message carry
    counts for the same work, so adding them would count it twice; the basis says which totals the
    number contains, and a missing part stays null rather than becoming a zero that sums cleanly.
    """
    usage = result.get('usage') if isinstance(result, dict) else None
    parts = {}
    for name in CLAUDE_USAGE_PARTS:
        value = usage.get(name) if isinstance(usage, dict) else None
        parts[name] = value if type(value) is int and value >= 0 else None
    known = [value for value in parts.values() if value is not None]
    cost = (result.get('cost') or {}).get('reported_usd') if isinstance(result, dict) else None
    record.update(parts=parts, reported_cost_usd=cost if type(cost) in (int, float) else None,
                  cost_source='provider_estimate' if type(cost) in (int, float) else 'unknown',
                  cost_note='the provider\'s own estimate for this run, never a billed amount')
    if known:
        record.update(source='claude/result.usage', total_tokens=sum(known), last_tokens=None,
                      basis='result_total_including_cache',
                      usage_note='the terminal result message only; no message is added twice')
    else:
        record.update(source='unknown', total_tokens=None, last_tokens=None, basis=None,
                      usage_note='the provider reported no usage; unknown is not zero')
    return record


def usage_record(result, transport='app_server'):
    """Measured usage with its source; absent usage is `unknown`, never zero."""
    events = result.get('events', []) if isinstance(result, dict) else []
    usage = result.get('usage') if isinstance(result, dict) else None
    reported = result.get('reported_model') if isinstance(result, dict) else None
    confirmed = reported if transport == 'claude_cli' else confirmed_model(events)
    record = {'requested_model': result.get('requested_model'), 'confirmed_model': confirmed,
              'model_confirmation': 'transport_reported' if confirmed else 'unknown',
              'stream_hash': stream_hash(events), 'event_count': len(events)}
    if transport == 'claude_cli':
        return _claude_usage(result, record)
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
