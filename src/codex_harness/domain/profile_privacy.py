"""Profile data flow as a versioned contract: what is read, what reaches a model, what is shown (INV-PROFILE-001).

The upstream profile feature promised the user automatic exclusion and no external transfer,
sampled message content and project paths into a model-input file before any redaction, then
redacted only `evidence` while rendering `evidence_quotes`, summaries, instructions and project
labels outside that pass and printed "None detected" when the redaction counter was zero. Here
the policy is a closed contract whose user notice must be entailed by the policy itself; consent
binds to the policy hash and keeps its cancel and questionnaire paths; every record is minimized
and scanned before it can become model input, and a blocked kind refuses the record rather than
masking it; evidence and evidence_quotes normalize to one schema; every rendered field is either
checked or named as unchecked, and "none detected" is never said about an unchecked field.
"""
import hashlib
import re

from codex_harness.domain.model import ContractError, digest, require

POLICY_VERSION = 1
TRANSPORTS = ('local', 'external')
RECORD_FIELDS = ('content', 'project_path', 'kind', 'session_id', 'observed_at')
INPUT_FIELDS = ('content', 'project_ref', 'kind', 'sequence')
RENDERED_FIELDS = ('summary', 'instruction', 'project', 'signal', 'evidence', 'metadata')
EVIDENCE_FIELDS = ('quote', 'source', 'signal')
CONSENT_CHOICES = ('grant', 'cancel', 'questionnaire')
KINDS = ('private_key', 'credential', 'token', 'email', 'user_path', 'card_number')
BLOCKING = ('private_key', 'credential', 'token')  # a record carrying one never becomes model input
PATTERNS = (
    ('private_key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)')),
    ('credential', re.compile(r'(?i)\b(?:password|passwd|pwd|secret|비밀번호|암호)\s*[:=]\s*\S+')),
    ('token', re.compile(r'\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})')),
    ('email', re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')),
    ('user_path', re.compile(r'(?i)(?:[A-Z]:\\Users\\|/mnt/[a-z]/Users/|/home/|/Users/|\\\\wsl\$\\[^\\]+\\home\\)[^\\/\s"\']+')),
    ('card_number', re.compile(r'\b(?:\d[ -]?){13,19}\b')),
)
MAX_CONTENT_CHARS = 4000


def _luhn(digits):
    total, alternate = 0, False
    for ch in reversed(digits):
        n = int(ch)
        if alternate:
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
        alternate = not alternate
    return total % 10 == 0


def scan(text):
    """Sensitive spans in text: kinds and counts, never the matched values."""
    require(type(text) is str, 'Only text is scanned')
    findings, spans = [], []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            if kind == 'card_number' and not _luhn(re.sub(r'[ -]', '', match.group())):
                continue
            if any(s <= match.start() < e for s, e in spans):
                continue
            spans.append((match.start(), match.end()))
            findings.append({'kind': kind, 'start': match.start(), 'length': match.end() - match.start()})
    return findings


def redact(text, findings):
    out, cursor = [], 0
    for finding in sorted(findings, key=lambda f: f['start']):
        out.append(text[cursor:finding['start']])
        out.append(f'[REDACTED {finding["kind"]}]')
        cursor = finding['start'] + finding['length']
    out.append(text[cursor:])
    return ''.join(out)


def parse_policy(policy):
    """The versioned contract; the user notice may only claim what the policy enforces."""
    require(isinstance(policy, dict) and set(policy) == {'version', 'purpose', 'fields', 'read_scope', 'model', 'retention', 'notice'},
            'Policy requires version, purpose, fields, read_scope, model, retention, notice')
    require(policy['version'] == POLICY_VERSION, 'Unknown policy version')
    require(type(policy['purpose']) is str and policy['purpose'].strip(), 'Policy requires a purpose')
    fields = policy['fields']
    require(isinstance(fields, dict) and fields and set(fields) <= set(RECORD_FIELDS)
            and all(type(v) is str and v.strip() for v in fields.values()), 'fields map collected record fields to their purpose')
    scope = policy['read_scope']
    require(isinstance(scope, dict) and set(scope) == {'kinds', 'max_records', 'max_chars', 'projects'}
            and isinstance(scope['kinds'], list) and scope['kinds'] and all(type(k) is str for k in scope['kinds'])
            and type(scope['max_records']) is int and 0 < scope['max_records'] <= 10000
            and type(scope['max_chars']) is int and 0 < scope['max_chars'] <= MAX_CONTENT_CHARS
            and isinstance(scope['projects'], list) and all(type(p) is str and p for p in scope['projects']),
            'read_scope requires kinds, max_records, max_chars, projects')
    model = policy['model']
    require(isinstance(model, dict) and set(model) == {'name', 'transport'} and type(model['name']) is str and model['name']
            and model['transport'] in TRANSPORTS, 'model requires name and transport')
    retention = policy['retention']
    require(isinstance(retention, dict) and set(retention) == {'temporary', 'permanent'}
            and retention['temporary'] in {'run', 'none'} and retention['permanent'] in {'profile_only', 'none'},
            'retention names temporary (run|none) and permanent (profile_only|none)')
    notice = policy['notice']
    require(isinstance(notice, dict) and set(notice) == {'text', 'claims'} and type(notice['text']) is str and notice['text'].strip()
            and isinstance(notice['claims'], list) and all(c in {'no_external_transfer', 'automatic_exclusion', 'raw_not_retained'} for c in notice['claims']),
            'notice requires text and a closed list of claims')
    mismatches = []
    if 'no_external_transfer' in notice['claims'] and model['transport'] != 'local':
        mismatches.append('notice claims no external transfer but the model transport is external')
    if 'raw_not_retained' in notice['claims'] and retention['permanent'] != 'profile_only':
        mismatches.append('notice claims raw text is not retained but permanent retention is not profile_only')
    if 'automatic_exclusion' in notice['claims'] and not set(fields) <= set(RECORD_FIELDS):
        mismatches.append('notice claims automatic exclusion for fields the scan does not cover')
    require(not mismatches, 'Notice is wider than the policy: ' + '; '.join(mismatches))
    parsed = {'version': POLICY_VERSION, 'purpose': policy['purpose'], 'fields': dict(fields), 'read_scope': {**scope, 'projects': sorted(scope['projects'])},
              'model': dict(model), 'retention': dict(retention), 'notice': {'text': notice['text'], 'claims': sorted(notice['claims'])}}
    return {**parsed, 'policy_hash': digest(parsed)}


def parse_consent(consent, policy):
    """Consent binds to one policy hash; cancel and questionnaire are preserved as choices, never as approval to collect."""
    policy = parse_policy(policy) if 'policy_hash' not in policy else policy
    require(isinstance(consent, dict) and set(consent) == {'user', 'choice', 'policy_hash', 'at', 'projects'}, 'Consent requires user, choice, policy_hash, at, projects')
    require(type(consent['user']) is str and consent['user'], 'Consent requires a user')
    require(consent['choice'] in CONSENT_CHOICES, 'Consent choice must be grant, cancel or questionnaire')
    require(consent['policy_hash'] == policy['policy_hash'], 'Consent is bound to another policy version')
    require(type(consent['at']) is str and consent['at'], 'Consent requires a time')
    require(isinstance(consent['projects'], list) and all(type(p) is str and p for p in consent['projects']), 'Consent names projects')
    require(set(consent['projects']) <= set(policy['read_scope']['projects']), 'Consent cannot widen the read scope')
    return {**consent, 'projects': sorted(consent['projects']), 'collect': consent['choice'] == 'grant' and bool(consent['projects']),
            'note': 'a preference inferred later is never authorization; the current explicit instruction wins'}


def project_ref(path):
    """A stable, non-reversible project label for model input; the path itself never leaves."""
    require(type(path) is str and path, 'Project path must be text')
    return 'project:' + hashlib.sha256(path.replace('\\', '/').rstrip('/').lower().encode('utf-8', 'surrogatepass')).hexdigest()[:16]


def minimize(record, policy, consent):
    """One record to model input: consented project, policy fields only, content scanned; blocked kinds refuse."""
    policy = parse_policy(policy) if 'policy_hash' not in policy else policy
    if isinstance(record, Exception):
        return {'status': 'read_error', 'error': type(record).__name__, 'checked_fields': [], 'unchecked_fields': list(RECORD_FIELDS), 'findings': {}}
    if not isinstance(record, dict):
        return {'status': 'parse_error', 'error': 'record is not an object', 'checked_fields': [], 'unchecked_fields': list(RECORD_FIELDS), 'findings': {}}
    unsupported = sorted(set(record) - set(RECORD_FIELDS))
    if unsupported:
        return {'status': 'parse_error', 'error': 'unsupported fields: ' + ', '.join(unsupported), 'checked_fields': [], 'unchecked_fields': unsupported, 'findings': {}}
    missing = [f for f in ('content', 'project_path', 'kind') if f not in record]
    if missing:
        return {'status': 'parse_error', 'error': 'missing ' + ', '.join(missing), 'checked_fields': [], 'unchecked_fields': missing, 'findings': {}}
    if type(record['content']) is not str or type(record['project_path']) is not str or type(record['kind']) is not str:
        return {'status': 'parse_error', 'error': 'content, project_path and kind must be text', 'checked_fields': [], 'unchecked_fields': ['content', 'project_path', 'kind'], 'findings': {}}
    if record['kind'] not in policy['read_scope']['kinds']:
        return {'status': 'out_of_scope', 'error': 'kind not in read scope', 'checked_fields': ['kind'], 'unchecked_fields': [], 'findings': {}}
    if not consent['collect'] or record['project_path'] not in consent['projects']:
        return {'status': 'not_consented', 'error': 'project not covered by the consent', 'checked_fields': ['project_path'], 'unchecked_fields': [], 'findings': {}}
    content = record['content'][:policy['read_scope']['max_chars']]
    findings = scan(content)
    counts = {}
    for finding in findings:
        counts[finding['kind']] = counts.get(finding['kind'], 0) + 1
    checked = ['content', 'project_path', 'kind']
    dropped = sorted(set(record) - set(policy['fields']))
    if any(kind in BLOCKING for kind in counts):
        return {'status': 'blocked', 'error': 'record carries ' + ', '.join(sorted(k for k in counts if k in BLOCKING)),
                'checked_fields': checked, 'unchecked_fields': [], 'findings': counts, 'dropped_fields': dropped}
    return {'status': 'ready', 'checked_fields': checked, 'unchecked_fields': [], 'findings': counts, 'dropped_fields': dropped,
            'truncated': len(record['content']) > len(content),
            'input': {'content': redact(content, findings), 'project_ref': project_ref(record['project_path']), 'kind': record['kind']}}


def normalize_evidence(dimension):
    """evidence and evidence_quotes become one list of {quote, source, signal}; conflicts and unknown fields refuse."""
    require(isinstance(dimension, dict), 'Dimension must be an object')
    unsupported = sorted(set(dimension) - {'evidence', 'evidence_quotes', 'summary', 'instruction', 'project', 'signal', 'metadata', 'confidence'})
    require(not unsupported, 'Unsupported dimension fields: ' + ', '.join(unsupported))
    forms = {name: dimension[name] for name in ('evidence', 'evidence_quotes') if name in dimension}
    items = []
    for name, value in forms.items():
        require(isinstance(value, list), f'{name} must be a list')
        for entry in value:
            if type(entry) is str:
                entry = {'quote': entry}
            require(isinstance(entry, dict) and set(entry) <= set(EVIDENCE_FIELDS) and type(entry.get('quote')) is str,
                    f'{name} entries need a quote and only quote, source, signal')
            items.append({'quote': entry['quote'], 'source': entry.get('source', ''), 'signal': entry.get('signal', ''), 'from': name})
    if len(forms) == 2:
        left = [(i['quote'], i['source'], i['signal']) for i in items if i['from'] == 'evidence']
        right = [(i['quote'], i['source'], i['signal']) for i in items if i['from'] == 'evidence_quotes']
        require(left == right, 'evidence and evidence_quotes disagree; refusing to choose one silently')
        items = [i for i in items if i['from'] == 'evidence']
    return [{k: v for k, v in i.items() if k != 'from'} for i in items]


def check_render(profile):
    """Every rendered field of every dimension is scanned or named unchecked; the verdict never says none for unchecked."""
    require(isinstance(profile, dict) and isinstance(profile.get('dimensions'), dict) and profile['dimensions'], 'Profile requires dimensions')
    unsupported = sorted(set(profile) - {'dimensions', 'profile_version'})
    require(not unsupported, 'Unsupported profile fields: ' + ', '.join(unsupported))
    report, total, unchecked = {}, {}, []
    for name, dimension in profile['dimensions'].items():
        try:
            evidence = normalize_evidence(dimension)
        except ContractError as exc:
            report[name] = {'status': 'parse_error', 'error': str(exc)}
            unchecked.append(f'{name}.evidence')
            continue
        fields = {'evidence': '\n'.join(e['quote'] + '\n' + e['source'] + '\n' + e['signal'] for e in evidence)}
        for field in ('summary', 'instruction', 'project', 'signal'):
            if field in dimension:
                fields[field] = dimension[field] if type(dimension[field]) is str else None
        if 'metadata' in dimension:
            meta = dimension['metadata']
            fields['metadata'] = '\n'.join(f'{k}={v}' for k, v in sorted(meta.items())) if isinstance(meta, dict) and all(type(v) in {str, int, float, bool} for v in meta.values()) else None
        per_field = {}
        for field, text in fields.items():
            if text is None:
                per_field[field] = {'status': 'unchecked', 'reason': 'not text'}
                unchecked.append(f'{name}.{field}')
                continue
            counts = {}
            for finding in scan(text):
                counts[finding['kind']] = counts.get(finding['kind'], 0) + 1
                total[finding['kind']] = total.get(finding['kind'], 0) + 1
            per_field[field] = {'status': 'checked', 'findings': counts}
        report[name] = {'status': 'checked', 'fields': per_field}
    verdict = ('unchecked_fields' if unchecked else 'findings' if total else 'none_detected_in_checked_fields')
    return {'verdict': verdict, 'findings': total, 'unchecked': sorted(unchecked), 'dimensions': report,
            'note': 'none detected is said only about checked fields; an unchecked field is named, never safe'}
