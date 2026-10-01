"""Composition of the release runner: its verification environment and the wiring of the deployment adapter (DESIGN-s7 adapters-move §13).

Layer: composition
Owns: `ENVIRONMENT_KEYS` and `verification_environment` (M7 `adapters/verification.py`, moved ahead of S8; the rest of verification.py stays S8)
Does not own: VerificationServices, the release suite and the hooks (S8/S10)
Entry points: ENVIRONMENT_KEYS, verification_environment
Contracts: INV-RELEASE-001, INV-ENCODING-001

Moved ahead of its slice from M7 `adapters/verification.py` (SOURCE e38aa722) through named rules (A/evidence/rebuild/s7/deployment-move/move_aheads.py); the only change is the home of `python_channel_environment` (host_os.adapters.process_groups, which only composition may import); the body is otherwise M7's.
"""
from __future__ import annotations

import os

from codex_harness.host_os.adapters.process_groups import python_channel_environment


ENVIRONMENT_KEYS = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL", "UV_CACHE_DIR",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "HOMEDRIVE", "HOMEPATH", "ALLUSERSPROFILE",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE"}


def verification_environment(endpoints, environ=None):
    source = os.environ if environ is None else environ
    env = {key: value for key, value in source.items() if key.upper() in ENVIRONMENT_KEYS}
    # INV-RELEASE-001: old incumbent tests mutate HARNESS_*; remove inherited Zeus aliases.
    env.update(HARNESS_INTEGRATION="1", HARNESS_DATABASE_URL=endpoints["database_url"],
               HARNESS_REDIS_URL=endpoints["redis_url"], HARNESS_REDIS_NAMESPACE="zeus-verification")
    # INV-ENCODING-001: release pytest is a Python child; the allowlist above already dropped
    # any inherited PYTHONIOENCODING/PYTHONUTF8, so the channel is bound here explicitly.
    return python_channel_environment(env)
