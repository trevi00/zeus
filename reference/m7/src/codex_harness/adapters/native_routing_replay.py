"""Replay complete immutable routing manifests, not lossy historical top-N scores."""
from codex_harness.adapters.skill_routing import frontmatter
from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.skill_admission import ADMISSION_MODEL, select_bodies
from codex_harness.domain.skill_ranking import FULL_BODY_TOP_K, MAX_CONTEXT_CHARS, PER_BODY_CAP
from codex_harness.domain.threshold_replay import finite_number


class NativeRoutingReplay:
    def __init__(self, artifacts):
        self.artifacts = artifacts

    def _manifest(self, ref, values):
        manifest = self.artifacts.document(ref)
        routing = manifest['routing']
        require(routing.get('admission_model') == ADMISSION_MODEL, 'Unsupported admission model')
        policy = routing['policy']
        require(policy['top_k'] == FULL_BODY_TOP_K and policy['body_characters'] == MAX_CONTEXT_CHARS
                and policy['per_body'] == PER_BODY_CAP, 'Different body budget policy')
        rows = manifest['skills']
        require(len({r['path'] for r in rows}) == len(rows), 'Duplicate routing identity')
        ranked, base, refs, baseline = [], {}, [], {}
        for row in rows:
            if row['tier'] == 'legacy':
                continue
            require(type(row.get('routing_eligible')) is bool and finite_number(row.get('base_score'))
                    and finite_number(row.get('score')), 'Incomplete native scores')
            require(finite_number(row.get('pipeline_boost'))
                    and row['score'] == row['base_score'] + row['pipeline_boost'], 'Inconsistent native scores')
            require(row['tier'] in {'unmatched', 'full', 'pointer', 'external_pointer'}
                    and row['routing_eligible'] == (row['tier'] != 'unmatched'), 'Incomplete routing eligibility')
            if not row['routing_eligible']:
                continue
            ref_body = row['content_ref']
            text = self.artifacts.text(ref_body, 1024 * 1024)
            meta, body = frontmatter(text)
            require(meta is not None and len(body) == row['body_chars'], 'Body evidence mismatch')
            ranked.append((row['score'], row['path'], row['dimensions'], body))
            base[row['path']] = row['base_score']
            refs.append(ref_body)
            if row['tier'] == 'full':
                baseline[row['path']] = row['rendered_hash']
        def selection(value):
            fitted, truncated = select_bodies(ranked, base, value)
            return {'threshold': value, 'selected': {path: digest(body) for _, path, _, body in fitted},
                    'body_characters': sum(len(body) for _, _, _, body in fitted), 'truncated': truncated}
        original = selection(policy['min_full_score'])
        # INV-NATIVE-REPLAY-001: do not report counterfactuals unless the observed baseline reproduces.
        require(original['selected'] == baseline and len(baseline) == routing['full']
                and original['truncated'] == routing['truncated'], 'Native baseline does not reproduce')
        return {'manifest_ref': ref, 'body_refs': sorted(set(refs)), 'baseline': original,
                'alternatives': [selection(value) for value in values], 'status': 'replayed'}

    def evaluate(self, events, values):
        require(all(finite_number(value) for value in values), 'Invalid native replay values')
        cache, observations = {}, []
        for index, event in enumerate(events):
            ref = event.get('manifest_ref') if isinstance(event, dict) else None
            if not isinstance(ref, str):
                observations.append({'event_index': index, 'status': 'unavailable', 'reason': 'manifest_required'})
                continue
            if ref not in cache:
                try:
                    cache[ref] = self._manifest(ref, values)
                except (ContractError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
                    cache[ref] = {'manifest_ref': ref, 'status': 'unavailable', 'reason': type(exc).__name__}
                    if isinstance(exc, ContractError):
                        # Contract messages are fixed by our validators; do not expose raw OS/backend errors.
                        cache[ref]['detail'] = str(exc)
            observations.append({'event_index': index, 'manifest_ref': ref, 'status': cache[ref]['status']})
        replayed = sum(row['status'] == 'replayed' for row in observations)
        return {'status': 'complete' if replayed == len(events) and events else 'partial' if replayed else 'unavailable',
                'model': ADMISSION_MODEL, 'values': values, 'observations': observations,
                'manifests': cache, 'distinct_manifests': len(cache), 'replayed_events': replayed,
                'total_events': len(events), 'activation_ready': False,
                'limitations': ['Reuses recorded matching scores; does not rerun matching against a changed prompt.',
                    'Full-body selection only; excludes legacy bodies, pointers, advice and final context compilation.',
                    'Selection and character pressure do not measure task success or authorize activation.']}
