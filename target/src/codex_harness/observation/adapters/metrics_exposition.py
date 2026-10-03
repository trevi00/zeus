"""Prometheus text exposition 0.0.4 of the metric snapshot rows (DESIGN-s9-X §2.2).

Layer: adapters
Context: observation
Owns: `CONTENT_TYPE` and `render`
Does not own: the rows (`MetricsProjector.snapshot`) or their families (`observation.domain.metric_families`)
Entry points: CONTENT_TYPE, render
Contracts: INV-OBSERVATION-001

Rows are owner-built, not input: an unknown type raises `ValueError`. Per family, `# HELP` then `# TYPE`, then the
samples; families in name order, series in the order given; no timestamps; stdlib only.
"""
from __future__ import annotations

import math

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
INF = 'le="+Inf"'
TYPES = ("counter", "gauge", "histogram")


def _help(text) -> str:
    return str(text).replace("\\", "\\\\").replace("\n", "\\n")


def _label(value) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _number(value) -> str:
    if type(value) is float:
        if math.isinf(value):
            return "+Inf" if value > 0 else "-Inf"
        return "NaN" if math.isnan(value) else repr(value)
    return str(value)


def _pairs(names, values, extra=()) -> str:
    pairs = [f'{name}="{_label(value)}"' for name, value in zip(names, values)] + list(extra)
    return "{" + ",".join(pairs) + "}" if pairs else ""


def render(rows) -> str:
    lines = []
    for row in sorted(rows, key=lambda item: item["metric"]):
        name, kind = row["metric"], row["type"]
        if kind not in TYPES:
            raise ValueError("Unknown metric type: " + str(kind))
        lines.append(f"# HELP {name} {_help(row['help'])}")
        lines.append(f"# TYPE {name} {kind}")
        for item in row["series"]:
            labels, value = item["labels"], item["value"]
            if kind != "histogram":
                lines.append(f"{name}{_pairs(row['labels'], labels)} {_number(value)}")
                continue
            for bound, count in zip(row["buckets"], value["buckets"]):
                le = 'le="' + repr(float(bound)) + '"'
                lines.append(f"{name}_bucket{_pairs(row['labels'], labels, [le])} {count}")
            lines.append(f"{name}_bucket{_pairs(row['labels'], labels, [INF])} {value['count']}")
            lines.append(f"{name}_sum{_pairs(row['labels'], labels)} {_number(value['sum'])}")
            lines.append(f"{name}_count{_pairs(row['labels'], labels)} {value['count']}")
    return "\n".join(lines) + "\n" if lines else ""
