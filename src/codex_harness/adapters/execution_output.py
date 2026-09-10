"""Runner-observed output validation and durable execution failure evidence."""
import json

from jsonschema import ValidationError, validate

from codex_harness.domain.model import ExecutionFailure, canonical, digest


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
    """Validate explicit text input; a completed transport turn is not acceptance."""
    reason, detail = None, {}
    if not isinstance(text, str):
        reason = 'invalid_text'
    elif not text.strip():
        reason = 'empty'
    else:
        try:
            answer = json.loads(text, parse_constant=_constant, object_pairs_hook=_object)
            # Reject overflowed floats and unpaired surrogates before durable writes.
            json.dumps(answer, ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, UnicodeError, RecursionError):
            reason = 'invalid_json'
        else:
            try:
                validate(answer, schema)
            except ValidationError as exc:
                reason = 'schema_mismatch'
                detail = {'instance_path': list(exc.absolute_path), 'schema_path': list(exc.absolute_schema_path)}
    result = {'answer': None if reason else answer, 'model_answer_text': text}
    if reason:
        result['output_schema'] = schema
        result['failure'] = {'cause': 'codex-output-' + reason.replace('_', '-'),
                             'output_reason': reason, 'schema_hash': digest(schema), **detail}
    return result


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
