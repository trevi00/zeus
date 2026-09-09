"""Validate only our inert review records and raw reference-byte identities."""

import hashlib
import json
import re
from pathlib import Path

OWN = Path(__file__).resolve().parent
ROOT = OWN.parents[2]
SOURCE = ROOT / ".runtime/absorption/sources/harness/pinned"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    primary = json.loads((OWN / "files.json").read_bytes())
    support = json.loads((OWN / "supporting.json").read_bytes())
    prior = json.loads((OWN / "prior-ledger.json").read_bytes())
    review = (OWN / "review.md").read_text(encoding="utf-8")
    assert len(primary) == 17 and sum(r["bytes"] for r in primary) == 182520
    assert len({r["path"] for r in primary}) == 17
    assert len({r["path"] for r in support}) == len(support)
    assert not ({r["path"] for r in primary} & {r["path"] for r in support})
    for record in primary + support:
        raw = (SOURCE / record["path"]).read_bytes()
        assert len(raw) == record["bytes"] and digest(raw) == record["pinned_sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == record["git_blob"]
        lines = raw.decode("utf-8").splitlines()
        assert all(1 <= a <= b <= len(lines) for a, b in record["read_ranges"])
        assert not record["tests_executed"]
        refs = record.get("review_refs", [record.get("review_ref")])
        for ref in refs:
            path, anchor = ref.split("#")
            assert (ROOT / path).is_file() and f"## {anchor}\n" in review
    ids = {r["id"] for r in support}
    assert set(re.findall(r"\bs\d\d\b", review)) <= ids
    for record in primary:
        assert set(record["supporting_ids"]) <= ids
        row = next(r for r in prior["rows"] if r["row_index"] == record["prior_ledger_row_index"])
        assert row["row"]["path"] == record["path"]
        assert row["row"]["pinned_sha256"] == record["pinned_sha256"]
        assert row["row"]["disposition"] == "unreviewed"
    hashes = {}
    for file in sorted(OWN.iterdir()):
        if not file.is_file() or file.name == "validation.json":
            continue
        raw = file.read_bytes()
        text = raw.decode("utf-8")
        assert "\ufffd" not in text and chr(63) * 3 not in text
        assert b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        assert all(line == line.rstrip() for line in text.splitlines())
        if file.suffix == ".json":
            json.loads(raw)
        hashes[file.name] = digest(raw)
    result = {"metadata_validation": "PASS", "primary": 17, "bytes": 182520,
              "supporting_paths": len(support), "source_operations_executed": 0,
              "checks": ["UTF8 and readable ASCII report", "exactly one LF and no trailing whitespace",
                         "raw SHA256/Gitblob/bytes", "range bounds", "review anchors",
                         "captured prior unreviewed rows", "primary/support denominator separation"],
              "source_tests_passed": None, "artifacts_sha256": hashes}
    (OWN / "validation.json").write_text(json.dumps(result, indent=2) + "\n",
                                         encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "artifacts_sha256"}))


if __name__ == "__main__":
    main()
