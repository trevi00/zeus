"""Temporary profile bundles on disk, owned by a run and deleted only by their owner or an expired lease.

The upstream pipeline could return an output path it never created and cleaned temporary files by
age or prefix. Here a bundle is one directory per run with an owner sidecar and a lease; `write`
is atomic (temp + replace), `read` verifies the digest, `cleanup` deletes only a bundle whose owner
matches, and `sweep` deletes only bundles whose lease has expired, never another active run's data.
"""
import json
import os
import re
from pathlib import Path

from codex_harness.domain.model import ContractError, digest, require, utcnow

RUN_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z')


class ProfileScratch:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, run_id):
        require(type(run_id) is str and RUN_ID.fullmatch(run_id), 'Run id must be a token')
        return self.root / run_id

    def write(self, run_id, owner, lease_until, bundle):
        """Atomic write of the bundle and its owner sidecar; a second owner cannot take an existing run."""
        folder = self._dir(run_id)
        require(type(owner) is str and owner and type(lease_until) is str and lease_until, 'Bundle requires an owner and a lease')
        require(isinstance(bundle, dict), 'Bundle must be an object')
        folder.mkdir(exist_ok=True)
        sidecar = folder / 'owner.json'
        if sidecar.exists():
            current = json.loads(sidecar.read_text('utf-8'))
            require(current['owner'] == owner, f'Run {run_id} is owned by another worker')
        body = json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode('utf-8', 'surrogatepass')
        tmp = folder / 'bundle.json.tmp'
        tmp.write_bytes(body)
        os.replace(tmp, folder / 'bundle.json')
        sidecar_tmp = folder / 'owner.json.tmp'
        sidecar_tmp.write_text(json.dumps({'owner': owner, 'lease_until': lease_until, 'digest': digest(body.decode('utf-8', 'surrogatepass')),
                                           'written_at': utcnow()}), encoding='utf-8')
        os.replace(sidecar_tmp, sidecar)
        return {'run_id': run_id, 'path': str(folder / 'bundle.json'), 'bytes': len(body), 'owner': owner, 'lease_until': lease_until}

    def read(self, run_id, owner):
        folder = self._dir(run_id)
        sidecar = folder / 'owner.json'
        require(sidecar.exists(), f'Run {run_id} has no bundle')
        meta = json.loads(sidecar.read_text('utf-8'))
        require(meta['owner'] == owner, f'Run {run_id} is owned by another worker')
        path = folder / 'bundle.json'
        if not path.exists():
            raise ContractError(f'Run {run_id} bundle is missing although its sidecar exists; preserved for inspection')
        body = path.read_bytes()
        require(digest(body.decode('utf-8', 'surrogatepass')) == meta['digest'], f'Run {run_id} bundle digest mismatch; preserved, not used')
        return json.loads(body.decode('utf-8', 'surrogatepass'))

    def cleanup(self, run_id, owner):
        """Only the owner deletes its run; any other caller is refused and the files stay."""
        folder = self._dir(run_id)
        sidecar = folder / 'owner.json'
        if not folder.exists():
            return {'run_id': run_id, 'deleted': False, 'reason': 'absent'}
        require(sidecar.exists(), f'Run {run_id} has no owner sidecar; not deleting an unowned directory')
        meta = json.loads(sidecar.read_text('utf-8'))
        require(meta['owner'] == owner, f'Run {run_id} is owned by another worker; not deleted')
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()
        return {'run_id': run_id, 'deleted': True, 'owner': owner}

    def sweep(self, now):
        """Delete bundles whose lease expired before `now`; active leases and unowned directories are kept and named."""
        require(type(now) is str and now, 'Sweep needs the current time')
        deleted, kept = [], []
        for folder in sorted(p for p in self.root.iterdir() if p.is_dir()):
            sidecar = folder / 'owner.json'
            if not sidecar.exists():
                kept.append({'run_id': folder.name, 'reason': 'no owner sidecar'})
                continue
            meta = json.loads(sidecar.read_text('utf-8'))
            if meta['lease_until'] > now:
                kept.append({'run_id': folder.name, 'reason': 'lease active', 'owner': meta['owner']})
                continue
            for child in folder.iterdir():
                child.unlink()
            folder.rmdir()
            deleted.append({'run_id': folder.name, 'owner': meta['owner'], 'lease_until': meta['lease_until']})
        return {'deleted': deleted, 'kept': kept, 'note': 'age and name prefix never decide deletion; only an expired lease does'}
