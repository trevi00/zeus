"""Runner-observed output validation and durable execution failure evidence."""
import json

from jsonschema import Draft202012Validator, ValidationError

from codex_harness.adapters.output_schema import preflight
from codex_harness.domain.model import ContractError, ExecutionFailure, canonical, digest

TOOL_ITEMS = ('commandExecution', 'fileChange', 'mcpToolCall')


def evidence_json(value):
    # Preserve normal UTF-8 content addresses and escape only invalid code units.
    return canonical(value).encode('utf-8', errors='backslashreplace').decode('utf-8')


def _constant(value):
    raise ValueError('Non-JSON constant')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate output property')
        result[key] = value
    return result


def completed_output(text, schema):
    """Validate explicit text input; a completed transport turn is not acceptance.

    The result always carries `structural`: which checks ran, which did not, and the preflight
    receipt of the schema they ran against. A schema the subset refuses is a configuration-owner
    error (`owner: configuration`), never an agent output defect (`owner: agent_output`).
    """
    reason, detail, owner = None, {}, 'agent_output'
    checks = {'text': 'checked', 'json': 'unchecked', 'finite': 'unchecked', 'schema': 'unchecked'}
    try:
        receipt = preflight(schema)
    except ContractError as exc:
        receipt = {'schema_hash': digest(schema) if _encodable(schema) else None, 'configuration_error': str(exc)}
        reason, owner = 'schema_configuration', 'configuration'
        checks['schema'] = 'configuration_error'
    if not isinstance(text, str):
        reason = reason or 'invalid_text'
        checks['text'] = 'failed'
    elif not text.strip():
        reason = reason or 'empty'
        checks['text'] = 'failed'
    else:
        try:
            answer = json.loads(text, parse_constant=_constant, object_pairs_hook=_object)
            checks['json'] = 'checked'
            # Reject overflowed floats and unpaired surrogates before durable writes.
            json.dumps(answer, ensure_ascii=False, allow_nan=False).encode('utf-8')
            checks['finite'] = 'checked'
        except (ValueError, UnicodeError, RecursionError):
            reason = reason or 'invalid_json'
            checks['json' if checks['json'] == 'unchecked' else 'finite'] = 'failed'
        else:
            if checks['schema'] != 'configuration_error':
                try:
                    # The same dialect the preflight receipt names; `format` stays an annotation.
                    Draft202012Validator(schema, format_checker=None).validate(answer)
                    checks['schema'] = 'checked'
                except ValidationError as exc:
                    reason = 'schema_mismatch'
                    checks['schema'] = 'failed'
                    detail = {'instance_path': list(exc.absolute_path), 'schema_path': list(exc.absolute_schema_path)}
    result = {'answer': None if reason else answer, 'model_answer_text': text,
              'structural': {'checks': checks, 'schema': receipt,
                             'note': 'checked means the named check ran and passed; unchecked means it never ran'}}
    if reason:
        result['output_schema'] = schema
        result['failure'] = {'cause': 'codex-output-' + reason.replace('_', '-'), 'owner': owner,
                             'output_reason': reason, 'schema_hash': digest(schema) if _encodable(schema) else None,
                             **detail}
    return result


def _encodable(value):
    try:
        json.dumps(value, allow_nan=False)
        return True
    except (TypeError, ValueError, RecursionError):
        return False


def tool_usage(result):
    """Runner-observed tool items beside any self-report; a declaration never certifies the observation."""
    events = result.get('events', []) if isinstance(result, dict) else []
    observed = {kind: [] for kind in TOOL_ITEMS}
    for event in events:
        if not isinstance(event, dict) or event.get('method') != 'item/completed':
            continue
        params = event.get('params')
        item = params.get('item') if isinstance(params, dict) else None
        if isinstance(item, dict) and item.get('type') in observed and isinstance(item.get('id'), str):
            observed[item['type']].append(item['id'])
    answer = result.get('answer') if isinstance(result, dict) else None
    declared = answer.get('tool_calls') if isinstance(answer, dict) else None
    if not isinstance(declared, list):
        comparison = 'not_declared'
    else:
        comparison = 'consistent' if len(declared) == sum(len(v) for v in observed.values()) else 'differs'
    return {'runner_observed': {kind: {'count': len(ids), 'ids': ids} for kind, ids in observed.items()},
            'self_reported': declared if isinstance(declared, list) else None, 'comparison': comparison,
            'source': 'transport item/completed events; the answer text certifies nothing about tool use'}


def persist_result(artifacts, result, *, key, agent, lease, basis_revision, context_ref):
    """Store the exact runner result before exposing a failure to the workflow."""
    if result.get('failure'):
        result.update(task_id=key, attempt=lease.get('attempt') if lease else None,
                      basis_revision=basis_revision, context_ref=context_ref)
    receipt = artifacts.put(evidence_json(result), 'execution:' + key)
    if result.get('failure') and not result.get('inspection_blocked'):
        failure = {**result['failure'], 'scope': agent + '/codex-turn',
                   'execution_ref': receipt['ref'], 'task_id': key,
                   'attempt': lease.get('attempt') if lease else None,
                   'thread_id': result['thread_id'], 'turn_id': result['turn_id'],
                   'basis_revision': basis_revision, 'context_ref': context_ref}
        raise ExecutionFailure(failure['cause'], failure)
    return receipt
