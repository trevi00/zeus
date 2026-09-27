"""`zeus worker-credentials`: the operator's view of, and explicit transitions on, the named worker credentials
(INV-WORKER-CREDENTIALS-001). Every command invokes `application.worker_credentials`; nothing here decides.

* `status`: the redacted state (aliases, generations, eligibility codes, reservations by owner, cooldowns,
  observations as reported, the switch log).
* `observe --alias A`: one fresh provider usage observation of A's bound login (`claude -p /usage`, no model).
* `admit --owner O`: reserve one credential for O by the policy, or hold (one bounded observation may run).
* `select-env --owner O --path P`: the same admission, then the ONE-variable EnvironmentFile of the reserved
  credential at P (private, under the secret root) for the NEXT managed generation. The value is never printed.
* `release --owner O [--cause usage-limit|authentication] [--resets-at T]`: return O's reservation and apply
  what the provider did to it.
* `record-refusal --alias A --cause usage-limit|authentication --evidence sha256:D [--resets-at T]`: an owner records
  a provider refusal of A observed outside a Fleet dispatch, with the digest of that observation's evidence.

Output carries aliases, generations, owners, codes, times and percentages; never a secret or a path's content.
"""
from __future__ import annotations

from codex_harness.domain.model import ContractError

__all__ = ["add_parser", "execute", "refusal"]

CAUSES = {"none": None, "usage-limit": "claude-provider-usage-limit-exceeded",
          "authentication": "claude-provider-authentication-failed"}


def add_parser(commands) -> None:
    root = commands.add_parser("worker-credentials", help="Named worker credentials: primary-preferred admission "
                                                          "with a provider-usage bound (redacted)")
    sub = root.add_subparsers(dest="worker_credentials_command", required=True)
    sub.add_parser("status", help="Redacted state and the switch log")
    observe = sub.add_parser("observe", help="One fresh provider usage observation (no model call)")
    observe.add_argument("--alias", required=True, choices=("primary", "secondary"))
    admit = sub.add_parser("admit", help="Reserve one eligible credential for an owner, or hold")
    admit.add_argument("--owner", required=True)
    select_env = sub.add_parser("select-env", help="Admit, then write the reserved credential's EnvironmentFile")
    select_env.add_argument("--owner", required=True)
    select_env.add_argument("--path", required=True)
    release = sub.add_parser("release", help="Return an owner's reservation with the provider outcome")
    release.add_argument("--owner", required=True)
    release.add_argument("--cause", choices=tuple(CAUSES), default="none")
    release.add_argument("--resets-at", dest="resets_at")
    recorded = sub.add_parser("record-refusal", help="Record a provider refusal observed outside a Fleet dispatch")
    recorded.add_argument("--alias", required=True, choices=("primary", "secondary"))
    recorded.add_argument("--cause", required=True, choices=("usage-limit", "authentication"))
    recorded.add_argument("--evidence", required=True)
    recorded.add_argument("--resets-at", dest="resets_at")


def execute(service, args, *, host=None, credentials=None) -> dict:
    from codex_harness.adapters.worker_credentials import (
        CONFIG_SETTING,
        configured_credentials,
        write_selected_env,
    )
    from codex_harness.domain.worker_credentials import CredentialRefused
    if credentials is None:
        if host is None:
            from codex_harness.adapters.configuration import settings
            host = settings()
        credentials = configured_credentials(service.store, host)
    if credentials is None:
        raise CredentialRefused("credentials_unconfigured", CONFIG_SETTING)
    command = args.worker_credentials_command
    if command == "status":
        return {**credentials.status(), "exit_code": 0}
    if command == "observe":
        observation = credentials.observe(args.alias)
        return {"observation": observation, "exit_code": 0}
    if command in ("admit", "select-env"):
        grant = credentials.admit_fresh(args.owner)
        view = {k: grant.get(k) for k in ("granted", "cached", "owner", "alias", "generation", "reason_code",
                                          "reasons", "primary", "secondary", "refreshed") if k in grant}
        if not grant["granted"]:
            # A hold is a definite answer, not an error: the owner keeps the work and nothing is selected.
            return {**view, "status": "held", "exit_code": 1}
        if command == "select-env":
            write_selected_env(args.path, credentials.token(grant))
            view["written"] = True
        return {**view, "status": "granted", "exit_code": 0}
    if command == "release":
        return {**credentials.release(args.owner, cause=CAUSES[args.cause], resets_at=args.resets_at), "exit_code": 0}
    if command == "record-refusal":
        return {**credentials.record_refusal(args.alias, cause=CAUSES[args.cause], evidence_ref=args.evidence,
                                             resets_at=args.resets_at), "exit_code": 0}
    raise CredentialRefused("command_unknown", "command")


def refusal(exc: Exception) -> dict:
    return {"status": "refused", "reason_code": getattr(exc, "reason_code", None)
            or ("contract_refused" if isinstance(exc, ContractError) else "error"),
            "error_type": type(exc).__name__, "exit_code": 1}
