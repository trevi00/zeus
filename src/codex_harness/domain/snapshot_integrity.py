"""Confirmed-snapshot integrity as a strict, denominator-carrying check (INV-SNAPSHOT-001).

The upstream status CLI dropped broken and non-object JSONL lines everywhere, treated a missing
file or a malformed graduation document as an empty state, never required schema_version or id,
and returned success; its CI declared a snapshot job that path filters could skip. Here a
confirmed snapshot is verified against a manifest that names every required file, its kind and
schema version: every line must be an object with the required fields, a torn tail is tolerated
only in live mode, a missing file is not an empty one, dangling references fail, and the result
carries the full denominator so "0 records" is never ambiguous.
"""
import json
import math
import re

from codex_harness.domain.model import ContractError, digest, require

MODES = ('live', 'confirmed')
KINDS = ('jsonl', 'json')
FILE_STATES = ('valid', 'empty', 'missing', 'unreadable', 'corrupt', 'version_mismatch', 'torn_tail')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,199}\Z')
MAX_FILE_BYTES = 64 * 1024 * 1024


def parse_manifest(manifest):
    """Closed manifest: which files a snapshot must contain and what each must look like."""
    require(isinstance(manifest, dict) and set(manifest) == {'version', 'required'}, 'Manifest requires version and required')
    require(type(manifest['version']) is int and manifest['version'] == 1, 'Unknown manifest version')
    required = manifest['required']
    require(isinstance(required, dict) and required, 'Manifest must require at least one file')
    parsed = {}
    for name, spec in required.items():
        require(type(name) is str and NAME.fullmatch(name) and '..' not in name.split('/'), 'Manifest file name must be a relative path')
        require(isinstance(spec, dict) and set(spec) <= {'kind', 'schema_version', 'required_fields', 'references', 'allow_empty'}
                and spec.get('kind') in KINDS and type(spec.get('schema_version')) is int and spec['schema_version'] >= 1,
                f'Manifest entry {name} requires kind and schema_version')
        fields = spec.get('required_fields', ['schema_version', 'id'])
        require(isinstance(fields, list) and fields and all(type(f) is str and f for f in fields), f'{name}: required_fields must be names')
        references = spec.get('references', {})
        require(isinstance(references, dict) and all(type(k) is str and type(v) is str for k, v in references.items()),
                f'{name}: references must map a field to a file name')
        require(all(v in required for v in references.values()), f'{name}: references must point at a required file')
        require(type(spec.get('allow_empty', False)) is bool, f'{name}: allow_empty must be a boolean')
        parsed[name] = {'kind': spec['kind'], 'schema_version': spec['schema_version'], 'required_fields': list(fields),
                        'references': dict(references), 'allow_empty': spec.get('allow_empty', False)}
    return {'version': 1, 'required': parsed, 'manifest_hash': digest({'version': 1, 'required': parsed})}


def _finite(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, float) and not math.isfinite(item):
            return False
        if isinstance(item, dict):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return True


def _check_record(record, spec, number):
    if not isinstance(record, dict):
        return f'line {number}: not an object'
    if not _finite(record):
        return f'line {number}: non-finite number'
    missing = [f for f in spec['required_fields'] if f not in record]
    if missing:
        return f'line {number}: missing {", ".join(missing)}'
    if 'schema_version' in spec['required_fields'] and record['schema_version'] != spec['schema_version']:
        return f'line {number}: schema_version {record["schema_version"]!r} is not {spec["schema_version"]}'
    if 'id' in spec['required_fields'] and (type(record['id']) is not str or not record['id']):
        return f'line {number}: id must be non-empty text'
    return None


def verify_file(name, data, spec, mode):
    """One file against its manifest entry: state, counts and the ids it declares."""
    require(mode in MODES, 'Unknown verification mode')
    if data is None:
        return {'name': name, 'state': 'missing', 'lines': 0, 'records': 0, 'corrupt': 0, 'ids': [], 'errors': ['file absent']}
    if isinstance(data, Exception):
        return {'name': name, 'state': 'unreadable', 'lines': 0, 'records': 0, 'corrupt': 0, 'ids': [],
                'errors': [type(data).__name__ + ': ' + str(data)[:200]]}
    require(isinstance(data, bytes), 'Snapshot file content must be bytes')
    if len(data) > MAX_FILE_BYTES:
        return {'name': name, 'state': 'corrupt', 'lines': 0, 'records': 0, 'corrupt': 0, 'ids': [], 'errors': ['exceeds size cap']}
    result = {'name': name, 'state': 'valid', 'lines': 0, 'records': 0, 'corrupt': 0, 'ids': [], 'errors': [], 'bytes': len(data)}
    if not data.strip():
        result['state'] = 'empty' if spec['allow_empty'] else 'corrupt'
        result['errors'] = [] if spec['allow_empty'] else ['empty file where records are required']
        return result
    if spec['kind'] == 'json':
        try:
            record = json.loads(data.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            return {**result, 'state': 'corrupt', 'errors': ['document: ' + type(exc).__name__]}
        error = _check_record(record, spec, 1)
        if error:
            state = 'version_mismatch' if 'schema_version' in error and 'is not' in error else 'corrupt'
            return {**result, 'state': state, 'lines': 1, 'errors': [error]}
        return {**result, 'lines': 1, 'records': 1, 'ids': [record['id']] if 'id' in record else []}
    lines = data.split(b'\n')
    torn = lines[-1] != b''  # no final newline: the last line may be a live append in progress
    complete = lines[:-1] if torn else lines[:-1]
    for number, raw in enumerate(complete, start=1):
        if not raw.strip():
            continue
        result['lines'] += 1
        try:
            record = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            result['corrupt'] += 1
            result['errors'].append(f'line {number}: ' + type(exc).__name__)
            continue
        error = _check_record(record, spec, number)
        if error:
            result['corrupt'] += 1
            result['errors'].append(error)
            if 'is not' in error and 'schema_version' in error:
                result['state'] = 'version_mismatch'
            continue
        result['records'] += 1
        if 'id' in record:
            result['ids'].append(record['id'])
    if torn:
        result['lines'] += 1
        if mode == 'live':
            result['torn_tail'] = True
            result['errors'].append('torn tail tolerated in live mode; not part of the confirmed set')
        else:
            result['corrupt'] += 1
            result['state'] = 'corrupt'
            result['errors'].append('torn tail: a confirmed snapshot ends with a complete line')
    if result['corrupt'] and result['state'] == 'valid':
        result['state'] = 'corrupt'
    if result['records'] == 0 and result['state'] == 'valid':
        result['state'] = 'empty' if spec['allow_empty'] else 'corrupt'
        if not spec['allow_empty']:
            result['errors'].append('no records where records are required')
    return result


def verify_snapshot(files, manifest, mode='confirmed'):
    """Every required file, every line, every reference; the verdict carries the whole denominator."""
    manifest = parse_manifest(manifest)
    require(isinstance(files, dict), 'Snapshot files must map names to bytes')
    reports = {name: verify_file(name, files.get(name), spec, mode) for name, spec in manifest['required'].items()}
    ids = {name: set(report['ids']) for name, report in reports.items()}
    dangling = []
    for name, spec in manifest['required'].items():
        report = reports[name]
        data = files.get(name)
        if not spec['references'] or not isinstance(data, bytes) or report['state'] not in {'valid', 'torn_tail'}:
            continue
        for number, raw in enumerate(data.split(b'\n'), start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            for field, target in spec['references'].items():
                if field in record and record[field] not in ids.get(target, set()):
                    dangling.append({'file': name, 'line': number, 'field': field, 'target': target, 'value': record[field]})
    extra = sorted(set(files) - set(manifest['required']))
    denominator = {'files_required': len(manifest['required']), 'files_present': sum(files.get(n) is not None and not isinstance(files.get(n), Exception) for n in manifest['required']),
                   'files_valid': sum(r['state'] == 'valid' for r in reports.values()),
                   'files_empty': sum(r['state'] == 'empty' for r in reports.values()),
                   'files_missing': sum(r['state'] == 'missing' for r in reports.values()),
                   'files_unreadable': sum(r['state'] == 'unreadable' for r in reports.values()),
                   'files_corrupt': sum(r['state'] in {'corrupt', 'version_mismatch'} for r in reports.values()),
                   'lines_total': sum(r['lines'] for r in reports.values()), 'records_valid': sum(r['records'] for r in reports.values()),
                   'lines_corrupt': sum(r['corrupt'] for r in reports.values()), 'torn_tails': sum(bool(r.get('torn_tail')) for r in reports.values()),
                   'dangling_references': len(dangling), 'extra_files': extra}
    valid = all(r['state'] in {'valid', 'empty'} for r in reports.values()) and not dangling
    snapshot_hash = digest({name: digest(files[name].decode('latin-1')) if isinstance(files.get(name), bytes) else None for name in sorted(files)})
    return {'status': 'valid' if valid else 'invalid', 'mode': mode, 'manifest_hash': manifest['manifest_hash'],
            'snapshot_hash': snapshot_hash, 'files': reports, 'dangling_references': dangling, 'denominator': denominator,
            'note': 'empty means a required file legitimately holds no records; missing, unreadable and corrupt are not empty'}


def required_checks(changed_paths, policy):
    """Map changed paths to the checks they oblige; an unmapped change is named, never silently unchecked."""
    require(isinstance(policy, dict) and policy and all(type(k) is str and isinstance(v, list) and v and all(type(c) is str for c in v)
            for k, v in policy.items()), 'Check policy maps path prefixes to check names')
    require(isinstance(changed_paths, list) and all(type(p) is str for p in changed_paths), 'Changed paths must be text')
    obligations, unmapped = {}, []
    for path in sorted(set(changed_paths)):
        prefixes = [prefix for prefix in policy if path == prefix or path.startswith(prefix.rstrip('/') + '/')]
        if not prefixes:
            unmapped.append(path)
            continue
        for prefix in prefixes:
            for check in policy[prefix]:
                obligations.setdefault(check, []).append(path)
    return {'changes': len(set(changed_paths)), 'checks_required': sorted(obligations), 'obligations': obligations,
            'unmapped': unmapped, 'status': 'no_checks_required' if not obligations and not unmapped else
            'unmapped_changes' if unmapped else 'checks_required',
            'note': 'a change that obliges no check is stated as such; it is never a passed check'}


class SnapshotError(ContractError):
    pass
