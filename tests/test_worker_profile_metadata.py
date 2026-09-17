"""Worker profile metadata command (INV-WORKER-PROFILE-001, issue 124): real subprocesses.

Every checkout here is a synthetic fixture under tmp_path; the command runs as the worker would run
it, `python -m codex_harness.adapters.worker_profile_metadata` with the checkout as cwd.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from codex_harness.adapters import worker_profile
from codex_harness.adapters import worker_profile_metadata as module

SOURCE = Path(module.__file__).resolve().parents[2]
COMMAND = [sys.executable, "-m", "codex_harness.adapters.worker_profile_metadata"]
CANARY = "CANARY-5b1f0c9e7a3d4f2b8c6e"
RESOURCES = ("src", "codex_harness", "resources")


def checkout(tmp_path, document=None, manifest=None, name="checkout"):
    """A synthetic checkout. `document`/`manifest` are bytes written as they are; None omits the file."""
    root = tmp_path / name
    directory = root.joinpath(*RESOURCES)
    directory.mkdir(parents=True)
    if document is not None:
        (directory / "worker-profile-v1.md").write_bytes(document)
    if manifest is not None:
        (directory / "worker-profile-v1.json").write_bytes(manifest)
    return root


def manifest_for(document_sha256, **changes):
    body = {"id": "worker-v1", "version": "1", "document": "worker-profile-v1.md",
            "document_sha256": document_sha256, "character_limit": 6000, **changes}
    return json.dumps(body).encode("utf-8")


def loader_digest(data: bytes) -> str:
    """The loader's own normalization and hash, applied to the text the loader would read."""
    return worker_profile._sha256(data.decode("utf-8"))


def run(root, *extra):
    completed = subprocess.run([*COMMAND, *extra], cwd=str(root), capture_output=True, timeout=60,
                               stdin=subprocess.DEVNULL,
                               env={**os.environ, "PYTHONPATH": str(SOURCE), "PYTHONIOENCODING": "utf-8"})
    assert b"Traceback" not in completed.stderr, completed.stderr
    return completed.returncode, json.loads(completed.stdout.decode("utf-8")), completed.stdout


def tree(root):
    return {str(path.relative_to(root)): (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("label,document", [
    ("lf", b"# Profile\n\nline one\nline two\n"),
    ("crlf", b"# Profile\r\n\r\nline one\r\nline two\r\n"),
    ("unicode", "# 프로필\n\n검증 — naïve ✓ \U0001f600\n".encode("utf-8")),
])
def test_matching_metadata_agrees_with_the_loader_and_exits_zero(tmp_path, label, document):
    normalized = document.replace(b"\r\n", b"\n")
    expected = hashlib.sha256(normalized).hexdigest()
    assert loader_digest(document) == expected
    code, body, _ = run(checkout(tmp_path, document, manifest_for(expected)))
    assert code == 0, body
    assert body["schema"] == "zeus.worker-profile-metadata/v1" and body["status"] == "ok"
    assert body["document_sha256"] == expected and body["digest_matches"] and body["within_limit"]
    assert body["characters"] == len(normalized.decode("utf-8")) and body["character_limit"] == worker_profile.MAX_CHARACTERS
    assert "load_profile" in body["authority"]


def test_lf_and_crlf_checkouts_report_the_same_metadata(tmp_path):
    lf = b"# Profile\n\nbody\n"
    digest = hashlib.sha256(lf).hexdigest()
    first = run(checkout(tmp_path, lf, manifest_for(digest), name="lf"))
    second = run(checkout(tmp_path, lf.replace(b"\n", b"\r\n"), manifest_for(digest), name="crlf"))
    assert first[0] == second[0] == 0 and first[1] == second[1]


def test_a_stale_digest_keeps_the_computed_metadata_for_repair(tmp_path):
    document = ("# Profile\n\n" + CANARY + "\n").encode("utf-8")
    root = checkout(tmp_path, document, manifest_for("0" * 64))
    code, body, raw = run(root)
    assert code == 1 and body["status"] == "mismatch"
    assert body["digest_matches"] is False and body["within_limit"] is True
    assert body["document_sha256"] == loader_digest(document) and body["characters"] == len(document.decode("utf-8"))
    assert CANARY.encode() not in raw, "document content never reaches the output"
    # The worker repairs the manifest with the reported digest; the same command then passes.
    root.joinpath(*RESOURCES, "worker-profile-v1.json").write_bytes(manifest_for(body["document_sha256"]))
    assert run(root)[0] == 0
    missing_digest = json.dumps({"id": "worker-v1", "document": "worker-profile-v1.md", "character_limit": 6000}).encode()
    code, body, _ = run(checkout(tmp_path, document, missing_digest, name="no-digest"))
    assert code == 1 and body["digest_matches"] is False and body["document_sha256"] == loader_digest(document)


def test_the_character_limit_is_the_loaders_boundary(tmp_path):
    exact = ("é" * 5999 + "\n").encode("utf-8")  # 6000 characters, more than 6000 bytes
    code, body, _ = run(checkout(tmp_path, exact, manifest_for(loader_digest(exact)), name="exact"))
    assert code == 0 and body["characters"] == 6000 and body["within_limit"] is True
    over = ("é" * 6000 + "\n").encode("utf-8")
    code, body, _ = run(checkout(tmp_path, over, manifest_for(loader_digest(over)), name="over"))
    assert code == 1 and body["status"] == "mismatch"
    assert body["characters"] == 6001 and body["within_limit"] is False and body["digest_matches"] is True
    assert body["document_sha256"] == loader_digest(over), "the overlong document is still measured"
    crlf = b"x\r\n" * 3000  # 9000 bytes, 6000 normalized characters
    code, body, _ = run(checkout(tmp_path, crlf, manifest_for(loader_digest(crlf)), name="crlf"))
    assert code == 0 and body["characters"] == 6000


DOCUMENT = b"# Profile\n"
GOOD = manifest_for(hashlib.sha256(DOCUMENT).hexdigest())


@pytest.mark.parametrize("document,manifest,kind,file", [
    (None, GOOD, "missing_file", "worker-profile-v1.md"),
    (DOCUMENT, None, "missing_file", "worker-profile-v1.json"),
    (b"\xff\xfe" + CANARY.encode(), GOOD, "invalid_utf8", "worker-profile-v1.md"),
    (DOCUMENT, b"\xff{}", "invalid_utf8", "worker-profile-v1.json"),
    (DOCUMENT, b'{"id": "worker-v1", ' + CANARY.encode(), "invalid_json", "worker-profile-v1.json"),
    (DOCUMENT, b"[" * 100000, "invalid_json", "worker-profile-v1.json"),
    (DOCUMENT, b'["worker-v1"]', "manifest_not_object", "worker-profile-v1.json"),
    (DOCUMENT, manifest_for("0" * 64, id="worker-v2"), "wrong_id", "worker-profile-v1.json"),
    (DOCUMENT, manifest_for("0" * 64, document="../../../" + CANARY + ".md"), "wrong_document", "worker-profile-v1.json"),
    (DOCUMENT, manifest_for("0" * 64, character_limit=6001), "wrong_character_limit", "worker-profile-v1.json"),
    (DOCUMENT, manifest_for("0" * 64, character_limit=True), "wrong_character_limit", "worker-profile-v1.json"),
    (DOCUMENT, manifest_for("0" * 64, character_limit="6000"), "wrong_character_limit", "worker-profile-v1.json"),
    (b"x" * (module.MAX_DOCUMENT_BYTES + 1), GOOD, "input_too_large", "worker-profile-v1.md"),
    (DOCUMENT, GOOD + b" " * module.MAX_MANIFEST_BYTES, "input_too_large", "worker-profile-v1.json"),
], ids=lambda value: value if type(value) is str else "bytes")
def test_invalid_input_is_a_named_safe_failure(tmp_path, document, manifest, kind, file):
    code, body, raw = run(checkout(tmp_path, document, manifest))
    assert code == 1
    assert body == {"schema": "zeus.worker-profile-metadata/v1", "status": "error", "error": {"kind": kind, "file": file}}
    assert CANARY.encode() not in raw


def test_a_directory_in_place_of_a_file_is_refused(tmp_path):
    root = checkout(tmp_path, None, GOOD)
    root.joinpath(*RESOURCES, "worker-profile-v1.md").mkdir()
    code, body, _ = run(root)
    assert code == 1 and body["error"] == {"kind": "not_a_file", "file": "worker-profile-v1.md"}


def _link(link, target, directory=False):
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        if directory and os.name == "nt":  # an unprivileged Windows host can still make a junction
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return
        pytest.skip("this host does not let the test create a symbolic link: " + type(exc).__name__)


def test_a_link_that_leaves_the_checkout_is_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "worker-profile-v1.md").write_bytes(DOCUMENT)
    root = checkout(tmp_path, None, GOOD)
    _link(root.joinpath(*RESOURCES, "worker-profile-v1.md"), outside / "worker-profile-v1.md")
    code, body, _ = run(root)
    assert code == 1 and body["error"] == {"kind": "path_outside_cwd", "file": "worker-profile-v1.md"}


def test_a_linked_directory_that_leaves_the_checkout_is_refused(tmp_path):
    outside = checkout(tmp_path, DOCUMENT, GOOD, name="outside")
    root = tmp_path / "checkout"
    root.mkdir()
    _link(root / "src", outside / "src", directory=True)
    code, body, _ = run(root)
    assert code == 1 and body["error"]["kind"] == "path_outside_cwd"


def test_parent_directories_are_never_searched(tmp_path):
    root = checkout(tmp_path, DOCUMENT, GOOD)
    nested = root / "nested" / "deeper"
    nested.mkdir(parents=True)
    code, body, _ = run(nested)
    assert code == 1 and body["error"] == {"kind": "missing_file", "file": "worker-profile-v1.json"}


@pytest.mark.parametrize("extra", [["--help"], ["src/codex_harness/resources/worker-profile-v1.md"], ["--root", ".."], [""]])
def test_any_argument_is_an_invalid_invocation(tmp_path, extra):
    code, body, _ = run(checkout(tmp_path, DOCUMENT, GOOD), *extra)
    assert code == 2 and body["status"] == "error" and body["error"] == {"kind": "invalid_invocation"}
    assert "document_sha256" not in body


def test_the_command_is_deterministic_and_writes_nothing(tmp_path):
    root = checkout(tmp_path, DOCUMENT, manifest_for("0" * 64))
    before = tree(root)
    first, second = run(root), run(root)
    assert first[0] == second[0] == 1 and first[2] == second[2], "identical bytes for identical input"
    assert tree(root) == before, "no file is created, changed or touched"
    assert sorted(path.name for path in root.iterdir()) == ["src"]


def test_the_observation_matches_the_loader_for_this_checkouts_packaged_profile():
    """The one non-synthetic case: this checkout's packaged profile, as the loader verifies it."""
    profile = worker_profile.load_profile("worker-v1")
    code, body, _ = run(SOURCE.parent)
    assert code == 0 and body["document_sha256"] == profile["document_sha256"]
    assert body["characters"] == profile["characters"]
