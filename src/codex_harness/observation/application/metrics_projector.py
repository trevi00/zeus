"""The metrics projection, applied inline in the Collector's transaction (DESIGN-s9-X §2.2).

Layer: application
Context: observation
Owns: `METRICS_BUCKET`, `MetricsProjector` (apply, snapshot) and `ProjectingStore`
Does not own: the metric families and the row-to-sample rule (`observation.domain.metric_families`), the text format
    (`observation.adapters.metrics_exposition`), the observation buckets (`observation.application.observations`)
Entry points: METRICS_BUCKET, MetricsProjector, MetricsProjector.apply, MetricsProjector.snapshot, ProjectingStore
Contracts: INV-OBSERVATION-001

The Collector is unchanged. S10 hands it a `ProjectingStore` over the real store: a put of a NEW `observations` row
is queued, and when the Collector's transaction body returns, the queued rows are projected in that same inner
transaction, so a row is counted exactly when it is stored (replays and duplicates never put, a rolled-back batch
applies nothing). A counter series is an int; a histogram series is `{"buckets": [cumulative counts], "sum", "count"}`
and the series key is `json.dumps(list(label_values))`. No timestamps are stored.
"""
from __future__ import annotations

import json
import math
from contextlib import contextmanager

from codex_harness.observation.application.observations import EVENT_BUCKET
from codex_harness.observation.domain.metric_families import FAMILIES, REJECTIONS, samples

METRICS_BUCKET = "observation_metrics"


class MetricsProjector:
    def __init__(self, *, providers):
        self.providers = frozenset(providers)

    def apply(self, tx, rows) -> dict:
        counts = {}  # family -> {series key: sample values}
        observations = rejections = 0
        for row in rows:
            made, refused = samples(row, providers=self.providers)
            observations += 1
            for family, labels, value in made:
                counts.setdefault(family, []).append((json.dumps(list(labels)), value))
            for family in refused:
                rejections += 1
                counts.setdefault(REJECTIONS, []).append((json.dumps([family]), 1))
        # The rejection family is applied LAST: a histogram sample refused below (a sum that would leave the finite
        # range, S9 round 1 F1) is counted there in the same transaction, and the sample changes nothing else.
        for name in [*sorted(n for n in counts if n != REJECTIONS), REJECTIONS]:
            if name not in counts:
                continue
            family = FAMILIES[name]
            document = tx.get(METRICS_BUCKET, "family:" + name)
            series = dict(document["series"]) if document else {}
            for key, value in counts[name]:
                if family.type == "histogram":
                    current = series.get(key) or {"buckets": [0] * len(family.buckets), "sum": 0.0, "count": 0}
                    total = current["sum"] + float(value)
                    if not math.isfinite(total):
                        rejections += 1
                        counts.setdefault(REJECTIONS, []).append((json.dumps([name]), 1))
                        continue
                    series[key] = {"buckets": [n + (1 if value <= bound else 0)
                                               for n, bound in zip(current["buckets"], family.buckets)],
                                   "sum": total, "count": current["count"] + 1}
                else:
                    series[key] = series.get(key, 0) + value
            tx.put(METRICS_BUCKET, "family:" + name, {"series": series})
        return {"observations": observations, "rejections": rejections}

    def snapshot(self, tx) -> list:
        rows = []
        for name in sorted(FAMILIES):
            document = tx.get(METRICS_BUCKET, "family:" + name)
            if document is None:
                continue
            family = FAMILIES[name]
            series = sorted(({"labels": json.loads(key), "value": value} for key, value in document["series"].items()),
                            key=lambda item: item["labels"])
            rows.append({"metric": name, "type": family.type, "help": family.help, "labels": list(family.labels),
                         "buckets": list(family.buckets), "series": series})
        return rows


class _ProjectingTransaction:
    def __init__(self, tx):
        self.tx = tx
        self.queued, self._keys = [], set()

    def __getattr__(self, name):
        return getattr(self.tx, name)

    def put(self, bucket, key, body):
        if bucket == EVENT_BUCKET and key not in self._keys and self.tx.get(bucket, key) is None:
            self._keys.add(key)
            self.queued.append(body)
        self.tx.put(bucket, key, body)


class ProjectingStore:
    def __init__(self, store, projector):
        self.store, self.projector = store, projector

    def __getattr__(self, name):
        return getattr(self.store, name)

    @contextmanager
    def transaction(self):
        with self.store.transaction() as inner:
            proxy = _ProjectingTransaction(inner)
            yield proxy
            self.projector.apply(inner, proxy.queued)
