"""Fetch one pinned official PyPI wheel, verify digest, extract only uv binary."""
import hashlib
import io
import json
from pathlib import Path
import sys
import urllib.request
import zipfile

root = Path(sys.argv[1])
url = "https://pypi.org/pypi/uv/0.12.2/json"
with urllib.request.urlopen(url, timeout=90) as response:
    metadata = response.read()
Path(__file__).with_name("uv-pypi-metadata.json").write_bytes(metadata)
record = next(item for item in json.loads(metadata)["urls"] if item["filename"] == "uv-0.12.2-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl")
with urllib.request.urlopen(record["url"], timeout=180) as response:
    wheel = response.read()
actual = hashlib.sha256(wheel).hexdigest()
assert actual == record["digests"]["sha256"], (actual, record["digests"])
(root / record["filename"]).write_bytes(wheel)
with zipfile.ZipFile(io.BytesIO(wheel)) as archive:
    members = [name for name in archive.namelist() if name.endswith("/scripts/uv")]
    assert len(members) == 1, members
    binary = archive.read(members[0])
directory = root / "uv-bin"
directory.mkdir(exist_ok=True)
target = directory / "uv"
target.write_bytes(binary)
target.chmod(0o755)
print(json.dumps({"metadata_url": url, "wheel_url": record["url"], "wheel_sha256": actual,
                  "metadata_sha256": hashlib.sha256(metadata).hexdigest(),
                  "binary_sha256": hashlib.sha256(binary).hexdigest(), "target": str(target)}))
