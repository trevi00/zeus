"""Loss-aware projection of Baldrix JSONL into explicitly unversioned history."""
import base64
import hashlib
import json
import math
import re
from collections import deque

from codex_harness.domain.model import canonical, digest, require
from codex_harness.domain.skill_history import MAX_EVENTS, TOP_MATCHES

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_LINE_BYTES = 64 * 1024
MAX_IMPORT_SCORE = 2**31 - 1
MAX_NAME_BYTES = 512
MAX_DIMENSIONS = 128
MAX_DIMENSION_BYTES = 512
IMPORT_VERSION = 1


def validate_source(source):
    require(isinstance(source, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', source)),
            'Source ID must identify one append-only log segment')


def source_document(data, source):
    validate_source(source)
    require(isinstance(data, bytes) and len(data) <= MAX_INPUT_BYTES, 'Import exceeds byte limit')
    return {'encoding': 'base64', 'source_id': source, 'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data), 'body': base64.b64encode(data).decode('ascii')}


def project_jsonl(data, source, *, start=0, line_offset=0):
    validate_source(source)
    require(isinstance(data, bytes) and len(data) <= MAX_INPUT_BYTES, 'Import exceeds byte limit')
    require(0 <= start <= len(data) and line_offset >= 0, 'Invalid import cursor')
    events, issues = deque(maxlen=MAX_EVENTS), []
    counts = {'lines': 0, 'events': 0, 'invalid_lines': 0, 'invalid_entries': 0, 'blank_lines': 0}
    offset = start
    unknown_version = 'legacy-version-unknown:' + digest(source)
    # JSONL is delimited by LF only. A torn final append may become valid later.
    while True:
        end = data.find(b'\n', offset)
        if end < 0:
            break
        line = data[offset:end + 1]
        offset = end + 1
        counts['lines'] += 1
        number = line_offset + counts['lines']
        try:
            require(len(line) <= MAX_LINE_BYTES, 'Oversized line')
            if not line.strip():
                counts['blank_lines'] += 1
                continue
            record = json.loads(line.decode('utf-8'), parse_constant=lambda _: require(False, 'Non-finite JSON'))
            canonical(record).encode('utf-8')  # reject lone surrogates before PostgreSQL serialization
            pending = [record]
            while pending:
                value = pending.pop()
                if isinstance(value, str):
                    require('\x00' not in value, 'NUL is not representable in PostgreSQL JSONB strings')
                elif isinstance(value, float):
                    require(math.isfinite(value), 'Non-finite JSON number')
                elif isinstance(value, dict):
                    pending.extend(value.keys())
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
            require(isinstance(record, dict) and isinstance(record.get('top'), list), 'Invalid envelope')
            require(len(record['top']) <= TOP_MATCHES, 'Too many top entries')
        except (ValueError, UnicodeError, RecursionError):
            counts['invalid_lines'] += 1
            if len(issues) < 20:
                issues.append({'line': number, 'reason': 'invalid_or_oversized_record'})
            continue
        top = []
        for index, entry in enumerate(record['top']):
            if (not isinstance(entry, dict) or not isinstance(entry.get('name'), str)
                    or not entry['name']
                    or not isinstance(entry.get('score'), int) or isinstance(entry['score'], bool)
                    or not 0 <= entry['score'] <= MAX_IMPORT_SCORE):
                counts['invalid_entries'] += 1
                if len(issues) < 20:
                    issues.append({'line': number, 'entry': index, 'reason': 'invalid_top_entry'})
                continue
            dims = entry.get('dims')
            if (len(entry['name'].encode('utf-8')) > MAX_NAME_BYTES
                    or (isinstance(dims, list) and (len(dims) > MAX_DIMENSIONS
                        or any(isinstance(d, str) and len(d.encode('utf-8')) > MAX_DIMENSION_BYTES for d in dims)))):
                counts['invalid_entries'] += 1
                if len(issues) < 20:
                    issues.append({'line': number, 'entry': index, 'reason': 'oversized_top_entry'})
                continue
            item = {'path': 'legacy-name:' + entry['name'], 'content_ref': unknown_version,
                    'score': entry['score'], 'legacy_name': entry['name']}
            if isinstance(dims, list):
                item['dimensions'] = [d if isinstance(d, str) else 'unknown' for d in dims]
            size = entry.get('body_chars')
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                item['body_chars'] = size
            top.append(item)
        if record['top'] and not top:
            counts['invalid_lines'] += 1
            if len(issues) < 20:
                issues.append({'line': number, 'reason': 'no_valid_top_entries'})
            continue
        events.append({'id': digest([source, number]),
                       'at': record.get('ts') if isinstance(record.get('ts'), str) else None, 'top': top,
                       'kind': 'legacy_skill_selection', 'source_line': number,
                       'raw_line_sha256': hashlib.sha256(line).hexdigest()})
        counts['events'] += 1
    return {'events': list(events), 'counts': counts, 'issues': issues, 'consumed_bytes': offset,
            'pending_bytes': len(data) - offset, 'prefix_sha256': hashlib.sha256(data[:offset]).hexdigest()}
