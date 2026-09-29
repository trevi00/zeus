"""Task-session names a container request carries (INV-WORKER-SESSION-001): the two modes and the two
evidence subdirectories of a session archive.

Layer: domain
Context: execution
Owns: MODE_FRESH, MODE_RESUME, EXPORT_DIRECTORY, RESTORE_DIRECTORY (the M7 values, unchanged)
Does not own: the session policy, archive verification and staging (the rest of M7
    `domain/worker_sessions` and `adapters/worker_sessions`, which move here with RunTask in S4)
Entry points: MODE_FRESH, MODE_RESUME, EXPORT_DIRECTORY, RESTORE_DIRECTORY
Contracts: INV-WORKER-SESSION-001

Moved ahead of S4 because the S3 Claude container transport names them in its request and bind layout.
"""

from __future__ import annotations

MODE_FRESH = "fresh"
MODE_RESUME = "native_resume"
EXPORT_DIRECTORY = "session-export"
RESTORE_DIRECTORY = "session-restore"
