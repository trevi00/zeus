"""Call immutable upstream functions against explicit temporary inputs, without mocks."""
import contextlib
import datetime
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time

from cli import telemetry_report as tr
from cli import validate_project as vp


def main():
    results = {"kind": "actual_original_component_observations", "timezone": os.environ["TZ"]}
    time.tzset()
    stamp = "2026-05-01T06:15:35Z"
    expected = datetime.datetime.fromisoformat(stamp).timestamp()
    actual = tr._ts_to_epoch(stamp)
    results["timestamp"] = {"input": stamp, "expected_utc": expected, "actual": actual, "delta_seconds": actual - expected}
    now = time.time()
    recent = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60)), "name": "one-minute-old"}
    results["one_hour_filter"] = {"input": recent, "kept": tr._filter_since([recent], 3600)}
    results["error_without_duration"] = tr.report_hook_latency([{"name": "failed-hook", "status": "error"}])
    results["boolean_duration"] = tr.report_hook_latency([{"name": "bool-hook", "duration_ms": True}])
    results["unknown_time_kept"] = tr._filter_since([{"ts": "broken"}], 60)
    try:
        tr._ts_to_epoch(1)
    except Exception as exc:
        results["numeric_timestamp_error"] = type(exc).__name__
    results["nan_window_accepted"] = math.isnan(tr._parse_since_arg("nanh"))
    results["frontend_discovery"] = []
    for marker, body in (("package.json", '{"name":"review-input"}'), ("pubspec.yaml", "name: review_input\n")):
        with tempfile.TemporaryDirectory(prefix="zeus-cli005-") as d:
            root = Path(d)
            (root / marker).write_text(body, encoding="utf-8")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                rc = vp.main(["--root", str(root), "--json"])
            results["frontend_discovery"].append({"marker": marker, "returncode": rc, "output": json.loads(stream.getvalue())})
    print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
