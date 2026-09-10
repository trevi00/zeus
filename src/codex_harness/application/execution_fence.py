"""Durable per-row generation fences: row or process existence never re-issues authority.

The upstream file lease re-issued epoch 1 after its file was deleted, so an old holder passed the
guard again (FA-003). Zeus generations advance only through this ledger, which outlives the
execution row itself: a recreated row or a regressed generation is rejected, never re-armed.
"""
from codex_harness.domain.model import require, utcnow

BUCKET = 'execution_fences'


def key(bucket, row_id):
    return bucket + ':' + row_id


def current(tx, bucket, row_id):
    return tx.get(BUCKET, key(bucket, row_id))


def require_unused(tx, bucket, row_id):
    # INV-EXECUTION-IDENTITY-001: a fenced identity is never recreated from generation 0.
    require(current(tx, bucket, row_id) is None, 'Execution identity was used before; rows are never recreated')


def advance(tx, bucket, row_id, generation, owner=None):
    require(type(generation) is int and generation > 0, 'Fence generation must be a positive integer')
    fence = current(tx, bucket, row_id)
    require(fence is None or (type(fence.get('generation')) is int and generation > fence['generation']),
            'Execution generation regressed behind its durable fence')
    tx.put(BUCKET, key(bucket, row_id), {'id': key(bucket, row_id), 'bucket': bucket, 'row_id': row_id,
                                         'generation': generation, 'owner': owner, 'at': utcnow()})
