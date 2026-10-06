"""Upstream experience (lesson) records preserved as claims; INV-EXPERIENCE-001.

An upstream curator increments `occurrences` on every harvest of the same note and tags it with
cumulative gate-PASS counters, so those numbers measure ingestion, not independent incidents.
Zeus keeps the original fields verbatim as data and recomputes independence only from evidence
tokens that identify one incident each. Nothing here feeds INV-RECURRENCE-001 counting.
"""
import hashlib
import re

from codex_harness.domain.model import ContractError, digest, require

CLAIM_VERSION = 1
MAX_LESSON_BYTES = 256 * 1024
MAX_EVIDENCE_TOKENS = 4096
FRONTMATTER = re.compile(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', re.DOTALL)
SOURCE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
REVISION = re.compile(r'[0-9a-f]{40}')
# Cumulative project-wide PASS count at harvest time: the same value is stamped on every note.
COUNTER_TOKEN = re.compile(r'ledger:PASS x[0-9]+')
# Where the note was read from, not which failure it describes.
SOURCE_TOKEN = re.compile(r'repair-notes:\S+')
# One token identifies one incident, retry attempt or ledger event; repeats collapse to one.
IDENTITY_TOKEN = re.compile(r'(incident|occurrence|ledger-event|task):[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}')
BASIS_KINDS = ('pinned', 'observed')


def split_frontmatter(data):
    """Return (frontmatter text, body text) from lesson bytes; the YAML itself is parsed by the adapter."""
    require(isinstance(data, bytes) and len(data) <= MAX_LESSON_BYTES, 'Lesson exceeds byte limit')
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ContractError('Lesson bytes are not UTF-8') from exc
    match = FRONTMATTER.match(text)
    require(match is not None, 'Lesson frontmatter missing')
    return match.group(1), text[match.end():]


def validate_fields(fields):
    """Parsed frontmatter must be a string-keyed mapping of strings, lists and mappings only."""
    require(isinstance(fields, dict), 'Lesson frontmatter must be a mapping')
    pending = [fields]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            require(all(isinstance(key, str) for key in node), 'Frontmatter keys must be strings')
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
        else:
            require(isinstance(node, str), 'Frontmatter scalars must be strings')
    return fields


def classify_evidence(tokens):
    require(isinstance(tokens, list) and len(tokens) <= MAX_EVIDENCE_TOKENS
            and all(isinstance(token, str) and token.strip() for token in tokens),
            'Evidence tokens must be non-empty strings')
    groups = {'identities': set(), 'counters': [], 'sources': [], 'unclassified': []}
    for token in tokens:
        if IDENTITY_TOKEN.fullmatch(token):
            groups['identities'].add(token)
        elif COUNTER_TOKEN.fullmatch(token):
            groups['counters'].append(token)
        elif SOURCE_TOKEN.fullmatch(token):
            groups['sources'].append(token)
        else:
            groups['unclassified'].append(token)
    groups['identities'] = sorted(groups['identities'])
    return groups


def validate_basis(basis):
    require(isinstance(basis, dict) and basis.get('kind') in BASIS_KINDS, 'Basis must be pinned or observed')
    revision = basis.get('revision')
    if basis['kind'] == 'pinned':
        require(isinstance(revision, str) and REVISION.fullmatch(revision) is not None,
                'Pinned basis requires a full commit revision')
    else:
        require(revision is None, 'Observed bytes are not a commit; omit the revision')
    return {'kind': basis['kind'], 'revision': revision}


def upstream_count(value):
    """The upstream occurrence counter as an integer when it is one; anything else stays unknown."""
    return int(value) if isinstance(value, str) and re.fullmatch(r'[0-9]{1,12}', value) else None


def experience_claim(source, path, data, basis, fields):
    """Bind one upstream lesson's bytes and parsed frontmatter to a claim without Zeus authority."""
    require(isinstance(source, str) and SOURCE_NAME.fullmatch(source) is not None, 'Invalid experience source name')
    require(isinstance(path, str) and path and '\x00' not in path and not path.startswith('/')
            and '..' not in path.split('/'), 'Invalid lesson path')
    basis = validate_basis(basis)
    frontmatter, body = split_frontmatter(data)
    fields = validate_fields(fields)
    evidence = classify_evidence(fields.get('evidence', []))
    sha256 = hashlib.sha256(data).hexdigest()
    independent = len(evidence['identities'])
    return {'id': digest([CLAIM_VERSION, source, path, sha256]), 'version': CLAIM_VERSION,
            'source': {'name': source, 'path': path, 'sha256': sha256, 'bytes': len(data), **basis},
            'upstream': fields,
            'upstream_occurrences': upstream_count(fields.get('occurrences')),
            'frontmatter_sha256': hashlib.sha256(frontmatter.encode('utf-8')).hexdigest(),
            'body_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest(),
            'independent_occurrences': {'count': independent, **evidence},
            'status': 'independently_recomputed' if independent else 'upstream_occurrences_unverified',
            'authority': 'advisory; not recurrence, trust or qualification evidence'}
