"""Transaction-local adoption checks shared by admission and execution."""
from codex_harness.domain.model import digest, require
from codex_harness.domain.research import research_origin

AUDIT_EVIDENCE_BUCKETS = ('research_paths', 'research_subsystems', 'research_partitions',
                          'research_observed_assets')


def binding(tx, audit_id, proposal):
    audit = tx.get('research_audits', audit_id)
    require(audit is not None, 'Unknown audit')
    evidence = {bucket: sorted((r for r in tx.scan(bucket) if r['audit_id'] == audit_id),
                              key=digest)
                for bucket in AUDIT_EVIDENCE_BUCKETS}
    receipt_ids = {receipt for bucket in ('research_paths', 'research_subsystems')
                   for row in evidence[bucket] for receipt in row['record']['receipt_ids']}
    evidence['receipts'] = {key: tx.get('research_receipts', key) for key in sorted(receipt_ids)}
    active = tx.get('deployment', 'active')
    release = tx.get('releases', (active or {}).get('release_id', ''))
    require(release is not None and release['status'] == 'active', 'No active evaluator')
    return digest({'audit': audit, 'evidence': evidence, 'proposal': proposal,
                   'revision': active['revision'], 'policy': release['policy_hash'],
                   'graph': tx.get('research_control', 'graph')})


def require_adoption(tx, details):
    if not (research_origin(details) or 'proposal' in details):
        return
    # INV-RESEARCH-004: authority is a retained approval ID, never a model verdict.
    def ids(value):
        if isinstance(value, dict):
            return ([value['audit_approval']] if 'audit_approval' in value else []) + [
                x for v in value.values() for x in ids(v)]
        if isinstance(value, list):
            return [x for v in value for x in ids(v)]
        return []
    approvals = set(ids(details))
    require(len(approvals) == 1, 'Research adoption deferred: approval required')
    approval = tx.get('research_approvals', approvals.pop())
    control = tx.get('research_control', 'activation') or {}
    active = tx.get('deployment', 'active') or {}
    require(approval is not None and control.get('release_id') == active.get('release_id')
            and control.get('status') == 'active', 'Research adoption deferred: rollout paused')
    require(approval.get('status', 'approved') == 'approved', 'Research adoption deferred: approval revoked')
    reviews = tx.scan('research_reviews')
    actors = set()
    for key in approval.get('reviews', []):
        row = tx.get('research_reviews', key)
        require(row is not None and digest(row['review']) == key
                and row['review']['binding'] == approval['binding'] and row['review']['accepted'],
                'Research adoption deferred: changed independent review')
        # INV-RESEARCH-004: an earlier acceptance never outranks this actor's latest review.
        latest = max((r for r in reviews if r['review']['binding'] == approval['binding']
                      and r['review']['actor'] == row['review']['actor']),
                     key=lambda r: (r.get('sequence', 0), r.get('at', '')))
        require(latest['review']['accepted'], 'Research adoption deferred: rejected by a later review')
        receipt_id = row['review']['execution_id']
        receipt = tx.get('research_receipts', receipt_id)
        require(receipt is not None and digest(receipt) == receipt_id
                and receipt['receipt']['exit_status'] == 0 and not receipt['receipt']['inspection_blocked'],
                'Research adoption deferred: changed independent inspection')
        actors.add(row['review']['actor'])
    require(actors == {'lead:research', 'conductor'}, 'Research adoption deferred: reviews incomplete')
    def provenance(value):
        if isinstance(value, dict):
            for key, expected in [('audit_id', approval['audit_id']),
                                  ('source_url', approval['proposal']['source']['repository']),
                                  ('source_revision', approval['proposal']['source']['commit']),
                                  ('proposal', approval['proposal'])]:
                if key in value:
                    require(value[key] == expected, 'Research adoption deferred: changed provenance')
            for item in value.values():
                provenance(item)
        elif isinstance(value, list):
            for item in value:
                provenance(item)
    provenance(details)
    require(approval['binding'] == binding(tx, approval['audit_id'], approval['proposal']),
            'Research adoption deferred: stale evidence, graph, revision or policy')
    return approval


def inspect_approval(tx, details, artifacts):
    """Re-read immutable bytes at execution, including transitive evidence handles."""
    # INV-RESEARCH-004: inspect exactly the approval admitted above, even without audit_id.
    approval = require_adoption(tx, details)
    if approval is None:
        return
    import re

    references = set()
    def collect(value, reference_slot=False):
        if isinstance(value, dict):
            for key, child in value.items():
                # INV-RESEARCH-003: Docker digests and command output are not artifact edges.
                collect(child, key == 'ref' or key.endswith(('_ref', '_refs')))
        elif isinstance(value, list):
            for child in value:
                collect(child, reference_slot)
        elif isinstance(value, str) and reference_slot:
            require(re.fullmatch(r'sha256:[0-9a-f]{64}', value) is not None,
                    'Invalid declared artifact reference')
            references.add(value)
    collect(approval)
    collect(tx.get('research_audits', approval['audit_id']))
    for bucket in (*AUDIT_EVIDENCE_BUCKETS, 'research_receipts'):
        for row in tx.scan(bucket):
            if row['audit_id'] == approval['audit_id']:
                collect(row)
    visited = set()
    while references - visited:
        ref = next(iter(references - visited))
        visited.add(ref)
        artifacts.inspect(ref)
        # Full document traversal is mechanical validation; model context stays bounded.
        try:
            document = artifacts.document(ref)
        except ValueError:
            continue  # Plain text has no declared structured reference edges.
        collect(document)
