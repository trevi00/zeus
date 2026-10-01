"""Static lint of the deployment: compose denied configurations, `docker inspect` hardening, the collector read allowlist.

Purpose: reject the A57 denied configurations on a compose file (raw YAML structure or `docker compose config
--format json`) and on `docker inspect` JSON, and state the collector's input allowlist in one place.
Layer: tooling (stdlib only, like all of tokobs). Owns: `COLLECTOR_READ_ALLOWLIST`, `S9_READ_ALLOWLIST`,
`allowed_input`, `lint_compose`, `lint_inspect`. Does-not-own: running Docker, parsing YAML, any reader's behavior
(the readers open what they open; the allowlist test in W2a observes it).
Implements: ACCEPTANCE A55 (hardening facts shared with the topology), A57 (denied configurations, read allowlist);
DESIGN §7 (runbook post-check 4); W1-CLARIFICATIONS C-W1-4 (`*-codex-prestart.json`).
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Mapping

LOOPBACK = "127.0.0.1"
DENIED_PORTS = frozenset({9469, 9090})  # collector exporter, Prometheus: never published (DESIGN §7)
USER = "1000:1000"

# Root-relative, matched SEGMENT BY SEGMENT with equal segment counts (not `PurePath.match`, which matches from the
# right, so `*-events.jsonl` would match at any depth).
COLLECTOR_READ_ALLOWLIST = (
    "routine-runs/*/record.jsonl",
    "routine-runs/*/events-*.jsonl",
    "routine-runs/*/receipt-*.json",
    "*-events.jsonl",
    "*-codex-run.sh",
    "*-codex-prestart.json",  # C-W1-4
    "evidence/*/events*.jsonl",
    "evidence/*/run*.json",
    "credential-selection/*.json",
)
S9_READ_ALLOWLIST = ("monitoring.json",)


def allowed_input(rel: str) -> bool:
    """True when the root-relative path (`/` separators) matches an allowlist pattern segment by segment."""
    segments = rel.split("/")
    if not rel or any(s in ("", ".", "..") for s in segments):
        return False
    for pattern in COLLECTOR_READ_ALLOWLIST:
        parts = pattern.split("/")
        if len(parts) == len(segments) and all(fnmatch.fnmatchcase(s, p) for s, p in zip(segments, parts)):
            return True
    return False


# -- compose ------------------------------------------------------------------

def _port_numbers(text: str) -> set[int]:
    """Ports of `N` or `N-M` (a range is expanded only as far as a denied port can fall inside it)."""
    text = text.strip()
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", text)
    if not match:
        return set()
    low = int(match.group(1))
    high = int(match.group(2) or low)
    return {p for p in DENIED_PORTS if low <= p <= high} | ({low} if low in DENIED_PORTS else set())


def _parse_short_port(text: str) -> tuple[str | None, str, str]:
    """`[HOST_IP:][HOST:]CONTAINER[/proto]` -> (host_ip or None, host port text or '', container port text)."""
    body = text.split("/", 1)[0]
    host_ip: str | None = None
    if body.startswith("["):  # [v6]:host:container
        end = body.index("]")
        host_ip, body = body[1:end], body[end + 1:].lstrip(":")
        parts = body.split(":") if body else []
    else:
        parts = body.split(":")
        if len(parts) == 3:
            host_ip, parts = parts[0], parts[1:]
    if len(parts) == 2:
        return host_ip, parts[0], parts[1]
    return host_ip, "", parts[0] if parts else ""


def _port_violations(service: str, port: object) -> list[str]:
    if isinstance(port, Mapping):
        host_ip = port.get("host_ip")
        target, published = str(port.get("target", "")), str(port.get("published", "") or "")
        label = f"{published or '?'}:{target}"
    else:
        host_ip, published, target = _parse_short_port(str(port))
        label = str(port)
    out = []
    if host_ip != LOOPBACK:
        out.append(f"{service}: publish {label} has no host_ip {LOOPBACK}"
                   + (f" (host_ip {host_ip})" if host_ip else ""))
    denied = sorted(_port_numbers(target) | _port_numbers(published))
    if denied:
        out.append(f"{service}: publish {label} exposes denied port {denied[0]}")
    return out


def _volume_source(volume: object) -> str:
    if isinstance(volume, Mapping):
        return str(volume.get("source") or "")
    return str(volume).split(":", 1)[0]


def lint_compose(config: Mapping) -> list[str]:
    """A57 violations of a compose structure, one string each, naming the service."""
    out: list[str] = []
    services = config.get("services") if isinstance(config, Mapping) else None
    for name, service in sorted((services or {}).items()):
        if not isinstance(service, Mapping):
            continue
        if service.get("network_mode") == "host":
            out.append(f"{name}: network_mode host")
        if service.get("privileged") is True:
            out.append(f"{name}: privileged")
        if service.get("pid") == "host":
            out.append(f"{name}: pid host")
        if service.get("ipc") == "host":
            out.append(f"{name}: ipc host")
        if service.get("cap_add"):
            out.append(f"{name}: cap_add {sorted(map(str, service['cap_add']))}")
        for volume in service.get("volumes") or []:
            if _volume_source(volume).endswith("docker.sock"):
                out.append(f"{name}: mounts the Docker socket {_volume_source(volume)}")
        for port in service.get("ports") or []:
            out.extend(_port_violations(name, port))
    return out


# -- docker inspect -----------------------------------------------------------

def _binding_violations(name: str, bindings: Mapping) -> list[str]:
    out = []
    for key, entries in sorted(bindings.items()):
        for entry in entries or []:
            host_ip = (entry or {}).get("HostIp", "")
            if host_ip != LOOPBACK:
                out.append(f"{name}: PortBindings {key} HostIp {host_ip!r} is not {LOOPBACK}")
            ports = _port_numbers(key.split("/", 1)[0]) | _port_numbers(str((entry or {}).get("HostPort", "")))
            if ports:
                out.append(f"{name}: PortBindings {key} publishes denied port {sorted(ports)[0]}")
    return out


def lint_inspect(containers: list) -> list[str]:
    """Runbook post-check (4) on `docker inspect` JSON (a list of container objects)."""
    out: list[str] = []
    for index, container in enumerate(containers):
        container = container if isinstance(container, Mapping) else {}
        host = container.get("HostConfig") or {}
        config = container.get("Config") or {}
        name = str(container.get("Name") or f"container[{index}]").lstrip("/")
        if host.get("NetworkMode") == "host":
            out.append(f"{name}: NetworkMode host")
        if host.get("Privileged"):
            out.append(f"{name}: Privileged")
        sources = [str((m or {}).get("Source") or "") for m in container.get("Mounts") or []]
        sources += [str(b).split(":", 1)[0] for b in host.get("Binds") or []]
        if any(s.endswith("docker.sock") for s in sources):
            out.append(f"{name}: mounts the Docker socket")
        if host.get("PidMode") == "host":
            out.append(f"{name}: PidMode host")
        if host.get("IpcMode") == "host":
            out.append(f"{name}: IpcMode host")
        if host.get("CapAdd"):
            out.append(f"{name}: CapAdd {sorted(map(str, host['CapAdd']))}")
        out.extend(_binding_violations(name, host.get("PortBindings") or {}))
        if "ALL" not in [str(c).upper() for c in host.get("CapDrop") or []]:
            out.append(f"{name}: CapDrop lacks ALL")
        if host.get("ReadonlyRootfs") is not True:
            out.append(f"{name}: ReadonlyRootfs is not true")
        if config.get("User") != USER:
            out.append(f"{name}: Config.User is {config.get('User')!r}, not {USER}")
        if "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
            out.append(f"{name}: SecurityOpt lacks no-new-privileges:true")
    return out
