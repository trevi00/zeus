"""Observation spool drop counts as a state read (DESIGN-s10 §17b).

Sources: the Prometheus metric types guidance (S1: a counter "can only increase or be reset to zero on restart"; "do not use a counter to
expose a value that can decrease ... use a gauge") and the Prometheus naming practice (S2: an accumulating count has `total` as a suffix).
The sum over the retained per-run health records decreases when a run is pruned, so it is a gauge without a `_total` suffix.

`SpoolFacts(root).rows()` reads `SpoolDirectory(root).read_health()` only and writes nothing. Unavailable is never zero: a missing spool
directory or a read that raised makes `zeus_observation_spool_facts_available` 0 and exports NO dropped or unreadable series. No run id,
component, path or exception text reaches the output.

Layer: adapters
Context: observation
Owns: `SpoolFacts` and its row families (dropped records by reason, availability, unreadable health records)
Does not own: the renderer (`metrics_exposition.render` consumes `rows()`), the health writer (`Observer.health`), wiring (`composition.monitor`)
Entry points: SpoolFacts
Contracts: INV-OBSERVATION-001
"""
from pathlib import Path

from codex_harness.observation.adapters.observation_spool import SpoolDirectory

# reason label -> the health counter it sums (`Observer.counters`, written by `Observer.health`).
REASONS = (("spool_full", "dropped_spool_full"), ("append_failed", "spool_failures"),
           ("run_refused", "dropped_run_refused"), ("refused", "refused"),
           ("alerts_pending_dropped", "alerts_pending_dropped"))

_FAMILIES = {
    "zeus_observation_spool_dropped_records": (
        "gauge", ("reason",),
        "Records dropped by the retained observation spool runs, summed over their health records by reason; it can decrease when runs are pruned."),
    "zeus_observation_spool_facts_available": (
        "gauge", (), "1 when the observation spool health records were read and 0 when the directory is missing or the read failed."),
    "zeus_observation_spool_unreadable_health_records": (
        "gauge", (), "Number of observation spool health records that could not be read, excluded from the dropped sums."),
}


def _count(value):
    return value if type(value) is int and value >= 0 else 0


class SpoolFacts:
    """`root` is the spool directory (`<runtime>/observations`)."""

    def __init__(self, root):
        self._root = Path(root)

    def _read(self):
        if not self._root.is_dir():
            return None
        dropped = {reason: 0 for reason, _ in REASONS}
        unreadable = 0
        for record in SpoolDirectory(self._root).read_health():
            if not isinstance(record, dict) or record.get("unreadable"):
                unreadable += 1
                continue
            counters = record.get("counters") if isinstance(record.get("counters"), dict) else {}
            for reason, counter in REASONS:
                dropped[reason] += _count(counters.get(counter))
        return dropped, unreadable

    def rows(self):
        try:
            facts = self._read()
        except Exception:  # noqa: BLE001 - any read failure makes the facts unavailable; no exception text is exported
            facts = None
        series = {name: [] for name in _FAMILIES}
        series["zeus_observation_spool_facts_available"].append({"labels": [], "value": 0 if facts is None else 1})
        if facts is not None:
            dropped, unreadable = facts
            series["zeus_observation_spool_dropped_records"] = [{"labels": [reason], "value": dropped[reason]}
                                                                for reason, _ in REASONS]
            series["zeus_observation_spool_unreadable_health_records"].append({"labels": [], "value": unreadable})
        rows = []
        for name in sorted(_FAMILIES):
            kind, labels, help_text = _FAMILIES[name]
            ordered = sorted(series[name], key=lambda item: item["labels"])
            rows.append({"metric": name, "type": kind, "help": help_text, "labels": list(labels), "buckets": [], "series": ordered})
        return rows
