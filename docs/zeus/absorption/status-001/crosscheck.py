"""Read-only cross-check for the absorption status report (status-001).

Compares the committed full-analysis ledger with an optional live checkout,
profiles the unreviewed remainder, and snapshots working-tree drift of the
source repositories as a per-file SHA-256 manifest. Nothing is written outside
the output directory; source repositories are never modified.

Usage:
    python docs/zeus/absorption/status-001/crosscheck.py \
        --repo . --live C:/Users/rudtn/zeus \
        --source baldrix=C:/Users/rudtn/.claude \
        --source harness=C:/Users/rudtn/harness \
        --source guardian=C:/Users/rudtn/guardian \
        --source harness-design=C:/Users/rudtn/harness-design \
        --out docs/zeus/absorption/status-001
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
from pathlib import Path

PARTITION_PURPOSE_PREFIX = "Work partition only"


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def ledger_index(entries: list[dict]) -> dict[tuple[str, str], dict]:
    return {(entry["source"], entry["path"]): entry for entry in entries}


def disposition_counts(entries: list[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for entry in entries:
        counts[entry["source"]][entry["disposition"]] += 1
    return {source: dict(sorted(counter.items())) for source, counter in sorted(counts.items())}


def unreviewed_profile(entries: list[dict]) -> dict:
    unreviewed = [entry for entry in entries if entry["disposition"] == "unreviewed"]
    by_top = collections.Counter()
    for entry in unreviewed:
        top = entry["path"].split("/")[0] if "/" in entry["path"] else "<root>"
        by_top[f"{entry['source']}:{top}"] += 1
    return {
        "count": len(unreviewed),
        "bytes": sum(entry["bytes"] for entry in unreviewed),
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "by_source_top_level": dict(by_top.most_common()),
    }


def partition_profile(partitions: list[dict], index: dict[tuple[str, str], dict]) -> dict:
    rows = []
    listed: collections.Counter = collections.Counter()
    for partition in partitions:
        unreviewed = 0
        for item in partition["paths"]:
            key = (item["source"], item["path"])
            listed[key] += 1
            if index[key]["disposition"] == "unreviewed":
                unreviewed += 1
        if unreviewed:
            rows.append(
                {
                    "partition": partition["partition"],
                    "paths": len(partition["paths"]),
                    "unreviewed": unreviewed,
                    "bytes": partition["bytes"],
                    "scope_sha256": partition["scope_sha256"],
                }
            )
    rows.sort(key=lambda row: (-row["unreviewed"], row["partition"]))
    return {
        "partitions": len(partitions),
        "paths_listed": len(listed),
        "paths_listed_more_than_once": sum(1 for count in listed.values() if count > 1),
        "ledger_paths_not_partitioned": sum(1 for key in index if key not in listed),
        "partitions_with_unreviewed": len(rows),
        "rows": rows,
    }


def ledger_diff(committed: dict, live: dict) -> dict:
    changed = collections.Counter()
    for key, entry in committed.items():
        other = live.get(key)
        if other is None or other == entry:
            continue
        changed[
            (
                key[0],
                entry["disposition"],
                other["disposition"],
                "|".join(other.get("review_records") or []),
            )
        ] += 1
    return {
        "committed_entries": len(committed),
        "live_entries": len(live),
        "changed_entries": sum(changed.values()),
        "transitions": [
            {
                "source": source,
                "from": before,
                "to": after,
                "review_records": records,
                "count": count,
            }
            for (source, before, after, records), count in sorted(changed.items())
        ],
    }


def _argv_values(node: object) -> list[list[str]]:
    """Collect every `argv` list found anywhere inside a JSON document."""
    found: list[list[str]] = []
    if isinstance(node, dict):
        argv = node.get("argv")
        if isinstance(argv, list) and all(isinstance(item, str) for item in argv):
            found.append(argv)
        for value in node.values():
            found.extend(_argv_values(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_argv_values(value))
    return found


def execution_receipts(analysis: Path) -> dict:
    """Count JSON receipts under docs/full-analysis whose argv starts with `docker`.

    This is a mechanical rule: a `docker` argv is the isolated-execution path
    used by the existing joint reviews. Receipts that run only the review
    recorder, ruff, or inert reads are not counted. The rule can miss receipts
    with another shape; it never proves acceptance.
    """
    per_folder: collections.Counter = collections.Counter()
    for path in analysis.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if any(argv and argv[0] == "docker" for argv in _argv_values(document)):
            folder = path.relative_to(analysis).parts[0]
            per_folder[folder] += 1
    return {
        "rule": "JSON file under docs/full-analysis with any argv whose first item is 'docker'",
        "folders": len(per_folder),
        "receipts": sum(per_folder.values()),
        "per_folder": dict(sorted(per_folder.items())),
    }


def implementation_links(repo: Path) -> dict:
    records = sorted((repo / "docs" / "zeus" / "implementation").glob("*/README.md"))
    linked = [
        path.parent.name
        for path in records
        if "full-analysis" in path.read_text(encoding="utf-8")
    ]
    return {"records": len(records), "citing_full_analysis": len(linked), "names": linked}


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    ).stdout


def drift_manifest(name: str, root: Path) -> dict:
    head = git(root, "rev-parse", "HEAD").strip()
    entries = []
    for line in git(root, "status", "--porcelain", "--untracked-files=all").splitlines():
        code, rel = line[:2].strip(), line[3:]
        target = root / rel
        record = {"status": code, "path": rel, "bytes": None, "sha256": None}
        if target.is_file():
            data = target.read_bytes()
            record["bytes"] = len(data)
            record["sha256"] = hashlib.sha256(data).hexdigest()
        entries.append(record)
    return {
        "source": name,
        "root": str(root),
        "head": head,
        "tracked_paths": len(git(root, "ls-files").splitlines()),
        "modified": sum(1 for entry in entries if entry["status"] == "M"),
        "untracked": sum(1 for entry in entries if entry["status"] == "??"),
        "other": sum(1 for entry in entries if entry["status"] not in {"M", "??"}),
        "bytes": sum(entry["bytes"] or 0 for entry in entries),
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--live", type=Path)
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    analysis = args.repo / "docs" / "full-analysis"
    committed_entries = load(analysis / "path-ledger.json")
    committed = ledger_index(committed_entries)
    partitions = load(analysis / "partitions.json")
    coverage = load(analysis / "coverage.json")

    report = {
        "committed_revision": git(args.repo, "rev-parse", "HEAD").strip(),
        "coverage_tracked_paths": coverage.get("tracked_paths"),
        "coverage_whole_analysis_complete": coverage.get("whole_analysis_complete"),
        "committed_dispositions": disposition_counts(committed_entries),
        "adoption_status": dict(
            collections.Counter(entry["adoption_status"] for entry in committed_entries)
        ),
        "unreviewed": unreviewed_profile(committed_entries),
        "partitions": partition_profile(partitions, committed),
        "execution_receipts": execution_receipts(analysis),
        "implementation_links": implementation_links(args.repo),
    }
    if args.live:
        live_entries = load(args.live / "docs" / "full-analysis" / "path-ledger.json")
        report["live_checkout"] = str(args.live)
        report["live_dispositions"] = disposition_counts(live_entries)
        report["live_diff"] = ledger_diff(committed, ledger_index(live_entries))

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "ledger-crosscheck.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    drift = {}
    for spec in args.source:
        name, _, root = spec.partition("=")
        drift[name] = drift_manifest(name, Path(root))
    if drift:
        (args.out / "working-tree-drift.json").write_text(
            json.dumps(drift, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    for name, manifest in drift.items():
        print(
            f"{name}: head={manifest['head'][:12]} modified={manifest['modified']} "
            f"untracked={manifest['untracked']} bytes={manifest['bytes']}"
        )
    print(
        f"committed unreviewed={report['unreviewed']['count']} "
        f"partitions_with_unreviewed={report['partitions']['partitions_with_unreviewed']} "
        f"docker_receipt_folders={report['execution_receipts']['folders']} "
        f"docker_receipts={report['execution_receipts']['receipts']} "
        f"implementation_citing_analysis={report['implementation_links']['citing_full_analysis']}"
        f"/{report['implementation_links']['records']}"
    )


if __name__ == "__main__":
    main()
