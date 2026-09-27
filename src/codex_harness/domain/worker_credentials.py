"""Named worker credentials: primary-preferred selection with a provider-usage bound (INV-WORKER-CREDENTIALS-001).

Pure policy over data. A versioned host configuration names credentials by ALIAS and GENERATION and says where
each secret lives (a reference, never the bytes); runtime records hold only aliases, generations, codes, times
and provider-reported percentages. Selection is primary-preferred:

* PRIMARY is used whenever it is actually eligible: configured, not revoked, not cooling down after a provider
  rate limit (until the provider-reported reset, or a bounded default when none was reported), and within its
  in-flight bound. A static long-lived token reports no pre-dispatch usage, so the primary is never held for
  "unknown usage"; its unavailability is learned from its own refusal. When the reset was NOT reported and the
  primary has bound telemetry, the switch back needs a fresh known observation taken after the refusal that
  shows both windows below 100 percent; without telemetry the bounded default is the only reset evidence.
* A primary that is merely BUSY (at its in-flight bound) is not unavailable: new work waits for it and never
  spends the secondary's quota.
* SECONDARY is used ONLY while the primary is not eligible AND a FRESH provider observation of THIS secondary
  generation reports weekly usage strictly below the configured bound (at most 80 percent used) and a five-hour
  window that is not exhausted. Missing, stale, future-dated, malformed, error or generation-foreign telemetry is
  a HOLD, never an assumed zero.
* Both unavailable is a HOLD: queued work keeps its owner and waits; nothing is retried in a loop.

The observed percentage is what the provider reported at `observed_at`; it bounds nothing that happens after it
(other devices, in-flight calls and provider latency can cross it). A fresh observation before each admission
and one reservation per credential bound this process's own overshoot; they are not a billing cap."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from codex_harness.domain.model import ContractError

CONFIG_SCHEMA = "urn:zeus:worker-credentials:1"
OBSERVATION_SCHEMA = "urn:zeus:worker-credential-observation:1"
PRIMARY, SECONDARY = "primary", "secondary"
ALIASES = (PRIMARY, SECONDARY)
SECRET_KINDS = ("env_file_key", "token_file")
TELEMETRY_KINDS = ("claude_cli_usage",)
TOKEN_NAME = "CLAUDE_CODE_OAUTH_TOKEN"
SECRET_ROOT = "/srv/zeus/secrets"
# The user's bound: the secondary is admitted only while provider-reported weekly usage is STRICTLY below it.
MAX_SECONDARY_WEEKLY_PERCENT = 80
DEFAULT_TELEMETRY_MAX_AGE = 300
MAX_TELEMETRY_MAX_AGE = 3600
DEFAULT_UNKNOWN_RESET_SECONDS = 3600
DEFAULT_RESERVATION_SECONDS = 7200
GENERATION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
PATH_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
# Outcome effects of one dispatched worker on the credential that served it.
EFFECT_NONE, EFFECT_COOLDOWN, EFFECT_REVOKED = "none", "cooldown", "revoked"
USAGE_LIMIT_CAUSES = frozenset({"claude-provider-usage-limit-exceeded"})
# A provider authentication refusal, or a granted secret that could not be read as a private well-shaped token:
# the generation is unusable until an owner provisions a NEW generation (never silently re-read in a loop).
SECRET_UNAVAILABLE = "worker-credential-secret-unavailable"
AUTH_CAUSES = frozenset({"claude-provider-authentication-failed", SECRET_UNAVAILABLE})


class CredentialRefused(ContractError):
    """A definite, named refusal of a credential configuration, observation or transition."""

    def __init__(self, reason_code: str, field: str | None = None):
        super().__init__("worker credential refused: " + reason_code + (" (" + field + ")" if field else ""))
        self.reason_code, self.field = reason_code, field


def _refuse(condition, reason_code: str, field: str | None = None) -> None:
    if not condition:
        raise CredentialRefused(reason_code, field)


def secret_path(value) -> bool:
    """An absolute path directly or one directory under the private secret root; no traversal, no other root."""
    if not isinstance(value, str) or not value.startswith(SECRET_ROOT + "/"):
        return False
    parts = value[len(SECRET_ROOT) + 1:].split("/")
    return 1 <= len(parts) <= 2 and all(PATH_PART.fullmatch(part) for part in parts)


def validate_config(document) -> dict:
    """The versioned named-credential configuration, exactly; every defect is `credentials_config_invalid`."""
    _refuse(isinstance(document, dict) and set(document) == {"schema", "credentials", "policy"},
            "credentials_config_invalid", "document")
    _refuse(document["schema"] == CONFIG_SCHEMA, "credentials_config_invalid", "schema")
    rows = document["credentials"]
    _refuse(isinstance(rows, list) and 1 <= len(rows) <= len(ALIASES), "credentials_config_invalid", "credentials")
    seen = {}
    for row in rows:
        _refuse(isinstance(row, dict) and set(row) == {"alias", "generation", "secret", "telemetry", "max_in_flight"},
                "credentials_config_invalid", "credential")
        alias = row["alias"]
        _refuse(alias in ALIASES and alias not in seen, "credentials_config_invalid", "alias")
        _refuse(isinstance(row["generation"], str) and GENERATION.fullmatch(row["generation"]) is not None,
                "credentials_config_invalid", "generation")
        _refuse(type(row["max_in_flight"]) is int and 1 <= row["max_in_flight"] <= 16,
                "credentials_config_invalid", "max_in_flight")
        secret = row["secret"]
        _refuse(isinstance(secret, dict) and secret.get("kind") in SECRET_KINDS, "credentials_config_invalid",
                "secret")
        if secret["kind"] == "env_file_key":
            _refuse(set(secret) == {"kind", "path", "key"} and secret["key"] == TOKEN_NAME,
                    "credentials_config_invalid", "secret")
        else:
            _refuse(set(secret) == {"kind", "path"}, "credentials_config_invalid", "secret")
        _refuse(secret_path(secret["path"]), "credentials_config_invalid", "secret.path")
        telemetry = row["telemetry"]
        if telemetry is not None:
            _refuse(isinstance(telemetry, dict) and set(telemetry) == {"kind", "login_credentials_path", "cli_version",
                                                                       "binding"}
                    and telemetry["kind"] in TELEMETRY_KINDS and secret_path(telemetry["login_credentials_path"])
                    and telemetry["login_credentials_path"] != secret["path"]
                    and isinstance(telemetry["cli_version"], str)
                    and re.fullmatch(r"\d+\.\d+\.\d+", telemetry["cli_version"]) is not None,
                    "credentials_config_invalid", "telemetry")
            binding = telemetry["binding"]
            # The association of the telemetry login with THIS token generation is a provisioning record:
            # who attested it, when, and for which generation. It cannot be verified pre-dispatch from supported
            # interfaces (the token has no profile scope), so it is named, never implied.
            _refuse(isinstance(binding, dict) and set(binding) == {"generation", "attested_by", "attested_at"}
                    and binding["generation"] == row["generation"] and isinstance(binding["attested_by"], str)
                    and 0 < len(binding["attested_by"]) <= 64 and _instant(binding["attested_at"]) is not None,
                    "credentials_config_invalid", "telemetry.binding")
        seen[alias] = row
    _refuse(PRIMARY in seen, "credentials_config_invalid", "primary")
    paths = [r["secret"]["path"] + "#" + r["secret"].get("key", "") for r in rows]
    _refuse(len(set(paths)) == len(paths), "credentials_config_invalid", "secret.path")
    policy = document["policy"]
    _refuse(isinstance(policy, dict) and set(policy) == {"secondary_weekly_below_percent", "telemetry_max_age_seconds",
                                                          "unknown_reset_seconds", "reservation_seconds"},
            "credentials_config_invalid", "policy")
    # The bound may be made STRICTER, never looser than the user's 80 percent.
    _refuse(type(policy["secondary_weekly_below_percent"]) is int
            and 1 <= policy["secondary_weekly_below_percent"] <= MAX_SECONDARY_WEEKLY_PERCENT,
            "credentials_config_invalid", "policy.secondary_weekly_below_percent")
    _refuse(type(policy["telemetry_max_age_seconds"]) is int
            and 1 <= policy["telemetry_max_age_seconds"] <= MAX_TELEMETRY_MAX_AGE,
            "credentials_config_invalid", "policy.telemetry_max_age_seconds")
    for key in ("unknown_reset_seconds", "reservation_seconds"):
        _refuse(type(policy[key]) is int and 60 <= policy[key] <= 7 * 86400, "credentials_config_invalid",
                "policy." + key)
    return {"schema": CONFIG_SCHEMA, "credentials": [dict(r) for r in rows], "policy": dict(policy)}


def credential(config: dict, alias: str) -> dict | None:
    return next((row for row in config["credentials"] if row["alias"] == alias), None)


def _instant(value):
    if not isinstance(value, str) or not re.search(r"(Z|[+-]\d{2}:\d{2})$", value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _window(value) -> dict | None:
    if not (isinstance(value, dict) and set(value) == {"used_percent", "resets_at"}):
        return None
    used, resets = value["used_percent"], value["resets_at"]
    if type(used) is not int or not 0 <= used <= 100:
        return None
    if resets is not None and not (isinstance(resets, str) and 0 < len(resets) <= 64):
        return None
    return {"used_percent": used, "resets_at": resets}


def validate_observation(document) -> dict:
    """One provider observation of one credential generation; defects are `observation_invalid`."""
    _refuse(isinstance(document, dict) and set(document) == {"schema", "alias", "generation", "source", "observed_at",
                                                             "status", "reason_code", "weekly", "five_hour"},
            "observation_invalid", "document")
    _refuse(document["schema"] == OBSERVATION_SCHEMA, "observation_invalid", "schema")
    _refuse(document["alias"] in ALIASES, "observation_invalid", "alias")
    _refuse(isinstance(document["generation"], str) and GENERATION.fullmatch(document["generation"]) is not None,
            "observation_invalid", "generation")
    source = document["source"]
    _refuse(isinstance(source, dict) and set(source) == {"kind", "cli_version", "isolated_config", "cache_free"}
            and source["kind"] in TELEMETRY_KINDS and isinstance(source["cli_version"], str)
            and type(source["isolated_config"]) is bool and type(source["cache_free"]) is bool,
            "observation_invalid", "source")
    _refuse(_instant(document["observed_at"]) is not None, "observation_invalid", "observed_at")
    _refuse(document["status"] in ("known", "unknown"), "observation_invalid", "status")
    code = document["reason_code"]
    _refuse(code is None or (isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,64}", code)), "observation_invalid",
            "reason_code")
    if document["status"] == "known":
        weekly, five = _window(document["weekly"]), _window(document["five_hour"])
        _refuse(weekly is not None and five is not None and source["isolated_config"] and source["cache_free"],
                "observation_invalid", "windows")
        return {**document, "source": dict(source), "weekly": weekly, "five_hour": five}
    _refuse(document["weekly"] is None and document["five_hour"] is None and code is not None,
            "observation_invalid", "windows")
    return {**document, "source": dict(source)}


def _cooling(state: dict, now: datetime):
    cooldown = (state or {}).get("cooldown")
    until = _instant((cooldown or {}).get("until"))
    return cooldown if until is not None and until > now else None


def _in_flight(state: dict, now: datetime) -> int:
    return sum(1 for r in ((state or {}).get("reservations") or {}).values()
               if (_instant(r.get("until")) or now) > now)


def eligibility(config: dict, alias: str, state: dict | None, now: datetime) -> dict:
    """Whether ONE credential may serve a new dispatch NOW, with the named reason. Pure."""
    row = credential(config, alias)
    if row is None:
        return {"alias": alias, "eligible": False, "reason_code": alias + "_unconfigured"}
    state = state or {}
    if state.get("generation") not in (None, row["generation"]):
        return {"alias": alias, "eligible": False, "reason_code": alias + "_generation_changed"}
    if state.get("revoked"):
        return {"alias": alias, "eligible": False, "reason_code": alias + "_revoked"}
    cooldown = _cooling(state, now)
    if cooldown is not None:
        return {"alias": alias, "eligible": False, "reason_code": alias + "_cooling_down",
                "until": cooldown.get("until")}
    if _in_flight(state, now) >= row["max_in_flight"]:
        return {"alias": alias, "eligible": False, "reason_code": alias + "_in_flight_bound"}
    if alias == PRIMARY:
        elapsed = (state.get("cooldown") or {})
        if elapsed and not elapsed.get("reset_reported") and row["telemetry"] is not None:
            # The refusal reported no reset: the bounded default elapsed, and the switch back is confirmed only
            # by a fresh provider observation taken AFTER the refusal with both windows below 100 percent.
            reading = _reading(config, alias, row, state, now, after=_instant(elapsed.get("at")))
            if reading["reason_code"] is not None:
                return {"alias": alias, "eligible": False, "reason_code": "primary_reset_unconfirmed",
                        "telemetry": reading["reason_code"]}
            if reading["weekly"]["used_percent"] >= 100 or reading["five_hour"]["used_percent"] >= 100:
                return {"alias": alias, "eligible": False, "reason_code": "primary_reset_unconfirmed",
                        "telemetry": "window_exhausted", **reading["facts"]}
            return {"alias": alias, "eligible": True, "reason_code": "primary_eligible", "reset_confirmed": True,
                    **reading["facts"]}
        # A provider-REPORTED reset that has passed is itself the confirmation; the bounded default is not.
        return {"alias": alias, "eligible": True, "reason_code": "primary_eligible",
                **({"reset_confirmed": bool(elapsed.get("reset_reported"))} if elapsed else {})}
    policy = config["policy"]
    # After its own refusal, a reading from before the refusal says nothing about the secondary either.
    reading = _reading(config, alias, row, state, now, after=_instant((state.get("cooldown") or {}).get("at")))
    if reading["reason_code"] is not None:
        return {"alias": alias, "eligible": False, "reason_code": "secondary_" + reading["reason_code"],
                **reading["facts"]}
    weekly, five, facts = reading["weekly"], reading["five_hour"], reading["facts"]
    if weekly["used_percent"] >= policy["secondary_weekly_below_percent"]:
        return {"alias": alias, "eligible": False, "reason_code": "secondary_weekly_at_or_above_bound", **facts}
    if five["used_percent"] >= 100:
        return {"alias": alias, "eligible": False, "reason_code": "secondary_five_hour_exhausted", **facts}
    return {"alias": alias, "eligible": True, "reason_code": "secondary_eligible", **facts}


def _reading(config: dict, alias: str, row: dict, state: dict, now: datetime, after=None) -> dict:
    """The alias's recorded observation as a FRESH known reading, or the named telemetry defect. Pure."""
    def defect(code: str, **facts) -> dict:
        return {"reason_code": code, "facts": facts}
    if row["telemetry"] is None:
        return defect("telemetry_unconfigured")
    observation = state.get("observation")
    if not isinstance(observation, dict):
        return defect("telemetry_missing")
    try:
        observation = validate_observation(observation)
    except CredentialRefused:
        return defect("telemetry_invalid")
    if observation["alias"] != alias or observation["generation"] != row["generation"]:
        return defect("telemetry_foreign")
    if observation["source"]["cli_version"] != row["telemetry"]["cli_version"]:
        return defect("telemetry_version_unpinned")
    if observation["status"] != "known":
        return defect("telemetry_unknown", observation_reason=observation["reason_code"])
    observed = _instant(observation["observed_at"])
    age = (now - observed).total_seconds()
    if age < -5:
        return defect("telemetry_future")
    if age > config["policy"]["telemetry_max_age_seconds"] or (after is not None and observed <= after):
        return defect("telemetry_stale", age_seconds=int(age))
    weekly, five = observation["weekly"], observation["five_hour"]
    return {"reason_code": None, "weekly": weekly, "five_hour": five,
            "facts": {"weekly_used_percent": weekly["used_percent"], "weekly_resets_at": weekly["resets_at"],
                      "five_hour_used_percent": five["used_percent"], "age_seconds": int(age)}}


def refreshable(decision: dict) -> tuple:
    """The aliases whose missing, stale or unknown telemetry a fresh observation could change. Pure."""
    codes = {PRIMARY: ("primary_reset_unconfirmed",),
             SECONDARY: ("secondary_telemetry_missing", "secondary_telemetry_stale", "secondary_telemetry_unknown",
                         "secondary_telemetry_foreign", "secondary_telemetry_version_unpinned",
                         "secondary_telemetry_invalid")}
    return tuple(alias for alias in ALIASES if (decision.get(alias) or {}).get("reason_code") in codes[alias])


def select(config: dict, states: dict, now: datetime) -> dict:
    """Primary-preferred selection for ONE new dispatch. Pure; states are keyed by alias."""
    primary = eligibility(config, PRIMARY, states.get(PRIMARY), now)
    if primary["eligible"]:
        return {"granted": True, "alias": PRIMARY, "reason_code": "primary_eligible", "primary": primary}
    if primary["reason_code"] == PRIMARY + "_in_flight_bound":
        # Busy is not unavailable: the secondary's quota is spent only for a primary that cannot serve.
        return {"granted": False, "alias": None, "reason_code": "held_primary_in_flight_bound", "primary": primary,
                "secondary": {"alias": SECONDARY, "eligible": False, "reason_code": "secondary_not_considered"}}
    secondary = eligibility(config, SECONDARY, states.get(SECONDARY), now)
    if secondary["eligible"]:
        return {"granted": True, "alias": SECONDARY, "reason_code": "primary_unavailable_secondary_eligible",
                "primary": primary, "secondary": secondary}
    return {"granted": False, "alias": None, "reason_code": "held_no_eligible_credential", "primary": primary,
            "secondary": secondary}


def outcome_effect(cause, *, resets_at=None, now: datetime, unknown_reset_seconds: int) -> dict:
    """What one finished dispatch means for the credential that served it. Pure.

    A provider usage limit cools the credential down until the provider-reported reset (or a bounded default
    when none was reported); an authentication failure revokes it until an owner re-provisions a new
    generation; anything else changes nothing. The same worker is never replayed from here."""
    if cause in USAGE_LIMIT_CAUSES:
        until = _instant(resets_at) if resets_at is not None else None
        if until is None or until <= now:
            until = now + timedelta(seconds=unknown_reset_seconds)
            reported = False
        else:
            reported = True
        return {"effect": EFFECT_COOLDOWN, "reason_code": "provider_usage_limited", "until": until.isoformat(),
                "reset_reported": reported}
    if cause in AUTH_CAUSES:
        return {"effect": EFFECT_REVOKED, "reason_code": "secret_unavailable" if cause == SECRET_UNAVAILABLE
                else "provider_authentication_failed"}
    return {"effect": EFFECT_NONE, "reason_code": None}


__all__ = ["ALIASES", "AUTH_CAUSES", "CONFIG_SCHEMA", "DEFAULT_RESERVATION_SECONDS", "DEFAULT_TELEMETRY_MAX_AGE",
           "DEFAULT_UNKNOWN_RESET_SECONDS", "EFFECT_COOLDOWN", "EFFECT_NONE", "EFFECT_REVOKED",
           "MAX_SECONDARY_WEEKLY_PERCENT", "OBSERVATION_SCHEMA", "OWNER", "PRIMARY", "SECONDARY", "SECRET_KINDS",
           "SECRET_UNAVAILABLE",
           "SECRET_ROOT", "TELEMETRY_KINDS", "TOKEN_NAME", "USAGE_LIMIT_CAUSES", "CredentialRefused", "credential",
           "eligibility", "outcome_effect", "refreshable", "secret_path", "select", "validate_config", "validate_observation"]
