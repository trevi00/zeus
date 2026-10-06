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


def require_current(tx, bucket, row_id, generation, owner=None):
    """Every write by an existing handle checks the row against the durable fence, not only claims.

    A row restored to an older running generation while the fence has moved on (partial restore,
    manual repair) must not re-arm the old holder. A legacy row without a fence passes; a corrupted
    fence fails closed.
    """
    fence = current(tx, bucket, row_id)
    if fence is None:
        return
    require(type(fence.get('generation')) is int and fence['generation'] == generation,
            'Execution row is behind its durable fence')
    require(fence.get('owner') is None or owner is None or fence['owner'] == owner,
            'Execution owner differs from the durable fence')


def advance(tx, bucket, row_id, generation, owner=None):
    require(type(generation) is int and generation > 0, 'Fence generation must be a positive integer')
    fence = current(tx, bucket, row_id)
    require(fence is None or (type(fence.get('generation')) is int and generation > fence['generation']),
            'Execution generation regressed behind its durable fence')
    tx.put(BUCKET, key(bucket, row_id), {'id': key(bucket, row_id), 'bucket': bucket, 'row_id': row_id,
                                         'generation': generation, 'owner': owner, 'at': utcnow()})
