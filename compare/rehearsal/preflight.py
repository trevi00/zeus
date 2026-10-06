"""The rehearsal path preflight (RH-1b; rehearsal design "Path preflight", critique #6).

Layer: harness (never shipped). Standard library only. Scans data that is PASSED IN (JSON/text exports, Redis string,
hash and stream values) for absolute POSIX and Windows drive paths; reads no file and no Redis. Distinct prefixes
(depth <= 4) are counted and classified against the namespace spec. It FAILS closed: a prefix that reaches a writable
mount outside ROOT, or that no mount of the spec covers (`unclassified`), or a cleanup target outside ROOT.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .namespace import NamespaceSpec, _under

MAX_DEPTH = 4
MAX_RECORDED = 60  # the evidence writer bounds a list at 64 items
WINDOWS = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]):[\\/]+((?:[^\s\"'<>|*?:,;\\/]+[\\/]*)*)")
POSIX = re.compile(r"(?<![\w/.~$%@\-])(/(?:[A-Za-z0-9_.@+%=,~-]+/)*[A-Za-z0-9_.@+%=,~-]+)")
FAILING = frozenset({"unclassified", "rw-outside-ROOT"})


@dataclass(frozen=True)
class PreflightResult:
    ok: bool
    prefixes: list[dict]  # {prefix, count, class}, most frequent first
    failures: list[dict]  # {code, subject}


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, (bytes, bytearray)):
        yield bytes(value).decode("utf-8", "replace")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _strings(item)
    elif value is not None and not isinstance(value, (bool, int, float)):
        yield str(value)


FILE_LEAF = re.compile(r"^[^.].*\.[A-Za-z0-9_-]{1,10}$")


def _prefix(segments: list[str]) -> str:
    """The directory part, depth <= 4: a final segment that looks like a file (`x.dump`) is a leaf, not a prefix."""
    if len(segments) > 1 and FILE_LEAF.match(segments[-1]):
        segments = segments[:-1]
    return "/".join(segments[:MAX_DEPTH])


def scan_text(text: str) -> Counter:
    """Count the distinct prefixes (depth <= 4) of every absolute path in `text`."""
    text = text.replace("\\/", "/").replace("\\\\", "\\").replace("file://", " ")
    found: Counter = Counter()
    for match in WINDOWS.finditer(text):
        segments = [s for s in re.split(r"[\\/]+", match.group(2)) if s]
        found[f"{match.group(1).upper()}:/" + _prefix(segments)] += 1
    text = WINDOWS.sub(" ", text)
    for match in POSIX.finditer(text):
        segments = [s for s in match.group(1).split("/") if s]
        found["/" + _prefix(segments)] += 1
    return found


def classify(spec: NamespaceSpec, prefix: str) -> str:
    """rw-under-ROOT | rw-outside-ROOT | ro | overlay | masked | unclassified | windows-drive (no mount can reach it)."""
    if not prefix.startswith("/"):
        return "windows-drive"
    best = None
    for mount in spec.mounts:
        if mount.kind in ("proc", "dev") and not _under(prefix, mount.dest):
            continue
        if _under(prefix, mount.dest) and (best is None or len(mount.dest) >= len(best.dest)):
            best = mount
    if best is None:
        return "unclassified"
    if best.kind == "tmpfs":
        return "unclassified" if best.tag == "srv-base" else "masked"
    if best.kind in ("dir", "proc", "dev"):
        return "masked"
    if best.kind == "ro-bind":
        return "ro"
    if best.kind == "overlay":
        return "overlay"
    root = os.path.realpath(spec.root)
    return "rw-under-ROOT" if best.src and _under(os.path.realpath(best.src), root) else "rw-outside-ROOT"


def path_preflight(spec: NamespaceSpec, *, texts: Mapping[str, str] | None = None, redis_values: Iterable | None = None,
                   cleanup_targets: Iterable[str] = (), evidence=None) -> PreflightResult:
    counts: Counter = Counter()
    for text in (texts or {}).values():
        for chunk in _strings(text):
            counts.update(scan_text(chunk))
    for value in redis_values or ():
        for chunk in _strings(value):
            counts.update(scan_text(chunk))
    prefixes = [{"prefix": p, "count": n, "class": classify(spec, p)} for p, n in counts.items()]
    prefixes.sort(key=lambda item: (-item["count"], item["prefix"]))
    failures = [{"code": "writable_outside_root" if item["class"] == "rw-outside-ROOT" else "unclassified_prefix",
                 "subject": item["prefix"]} for item in prefixes if item["class"] in FAILING]
    root = os.path.realpath(spec.root)
    for target in cleanup_targets:
        if not os.path.isabs(target) or not _under(os.path.realpath(target), root):
            failures.append({"code": "cleanup_outside_root", "subject": str(target)})
    result = PreflightResult(not failures, prefixes, failures)
    if evidence is not None:
        shown = [{"prefix": ("<redacted>" if "secrets" in p["prefix"].split("/") else p["prefix"]),
                  "count": p["count"], "class": p["class"]} for p in prefixes[:MAX_RECORDED]]
        evidence.step("path_preflight", "pass" if result.ok else "fail",
                      {"distinct_prefixes": len(prefixes), "prefixes": shown, "failure_count": len(failures),
                       "failure_codes": sorted({f["code"] for f in failures})})
    return result
