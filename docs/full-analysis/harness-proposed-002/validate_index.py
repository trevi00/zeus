"""Validate this report's metadata and byte identities, not upstream behavior."""

import hashlib
import json
from pathlib import Path

OWN = Path(__file__).resolve().parent
ROOT = OWN.parents[2]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    files = json.loads((OWN / "files.json").read_bytes())
    support = json.loads((OWN / "supporting.json").read_bytes())
    checkpoint = json.loads((OWN / "checkpoint.json").read_bytes())
    assert len(files) == 15 and len(support) == 24
    assert sum(r["bytes"] for r in files) == 190115
    for row in files + support:
        base = ROOT / ".runtime/absorption/sources" / row["source"]
        raw = (base / "pinned" / row["path"]).read_bytes()
        assert sha(raw) == row["pinned_sha256"] and len(raw) == row["bytes"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == row["git_blob"]
        assert all(1 <= a <= b <= len(raw.decode("utf-8").splitlines()) for a, b in row["read_ranges"])
        refs = row.get("review_refs", [row.get("review_ref")])
        for ref in refs:
            path, anchor = ref.split("#")
            assert f"## {anchor}\n" in (ROOT / path).read_text(encoding="utf-8")
        assert row["tests_executed"] == []
    for row in files:
        assert row["prior_row"]["pinned_sha256"] == row["pinned_sha256"]
        assert row["prior_row"]["disposition"] == "unreviewed"
        assert row["read_kind"] == "fresh_full"
    for name, expected in checkpoint["hashes"].items():
        assert sha((OWN / name).read_bytes()) == expected
    for path in OWN.iterdir():
        if not path.is_file():
            continue
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        assert b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
        assert all(line == line.rstrip() for line in text.splitlines())
        assert chr(0xfffd) not in text and chr(63) * 3 not in text
        if path.suffix == ".json":
            json.loads(text)
    result = {
        "metadata_validation": "pass", "primary": 15, "supporting": 24,
        "primary_bytes": 190115, "original_execution": 0,
        "checks": ["UTF-8 and readable ASCII prose", "exactly one LF and no trailing spaces",
                   "raw SHA-256, Git blob, bytes, line ranges", "prior row identities",
                   "real report anchors and checkpoint hashes"],
        "limits": "Metadata checks do not execute upstream tests or prove behavioral closure.",
    }
    (OWN / "validation.json").write_text(json.dumps(result, indent=2) + "\n",
                                          encoding="utf-8", newline="\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
