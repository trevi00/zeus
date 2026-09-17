# Correction implementation record (worker, uncommitted; reviewer decides)

Kept beside SPEC.md rather than inside it: the operation manifest pins SPEC.md by sha256, so the
frame's bytes are left exactly as the owner wrote them.

R1 `domain/project_evidence.py` `PROFILE_ARGV_PREFIXES`/`enforceable`: refusal at parse and again
before capture. Consequence: the candidate's own tests used `python -m <probe module>` checks, which
R1 refuses by design; they now run real `python -m pytest probes/test_*.py` children (a failing
pytest exits 1, so the negative check expects 1, not 3).

R2 `ProjectEvidenceInspector._check` takes the absolute deadline and an injectable `clock`; findings
add `timeouts_seconds`. Follow-up, NOT changed here: legacy `EvidenceInspector.inspect_command` has
the same per-repeat allowance pattern; the batch says legacy stays untouched.

R3 `worker_delivery`/`shell_command` -> `Executor._open_runtime(..., cwd, action)` ->
`ClaudeCodeRuntime(project_delivery=...)`: exact wildcard-free allow rules (whole command, `cd`
part, run part), host section appended to the system prompt, process PYTHONPATH unset, workspace
mismatch refused before spawn; worker-profile-v1.md interpreter sentence corrected (5998/6000
characters) and manifest digest updated. Command text is POSIX sh (Claude Code's Bash tool; Git Bash
on Windows). Unknown until the canary: whether the installed CLI matches an exact rule against an
env-assignment-prefixed compound command; if it does not, the rules' text form is the single place
to adjust.

Regressions: tests/test_project_evidence.py (R1, R2 deterministic clock + one real timed
subprocess), tests/test_project_delivery.py (real `sh` execution of delivered text, protocol-child
transport settings/prompt/environment, refusals, executor seam).
