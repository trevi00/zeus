"""Which provider executes an assignment: a Git-managed policy plus host configuration.

Zeus keeps Codex as the default executor. A second provider runs only where the packaged policy
permits that exact (role, action, workload, read_only) pairing *and* the host configuration
enables it. The assignment message, the task details and any model output never take part in the
decision (INV-CLAUDE-WORKER-001): they are data produced by or for the execution being decided.

Two refusals matter more than the selection itself. A host configuration that names a pairing the
packaged policy does not permit is refused as a whole, so a misconfiguration cannot quietly widen
what a provider may run. And a permitted, enabled pairing whose required controls (an explicit
model, a spend ceiling) are missing or malformed is refused before anything spawns, rather than
run by the default provider: an operator who asked for one provider and silently received another
would read the receipt as a measurement of the provider they asked for.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from codex_harness.domain.model import ContractError, digest, require
from codex_harness.domain.provider_stream import STREAMS

POLICY_VERSION = "provider-policy.v1"
MODEL_SOURCES = ("model_routing", "explicit_setting")
RESUME_STATES = ("supported", "unsupported")
CONTROL_KINDS = ("number", "integer", "path")
TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,99}$")
SETTING_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
PAIR = re.compile(r"^(?P<role>[a-z][a-z0-9_]*(?::[a-z0-9_]+)?)/(?P<action>[a-z][a-z0-9_]*)$")


def _token(value) -> bool:
    return type(value) is str and TOKEN.fullmatch(value) is not None


@dataclass(frozen=True)
class Provider:
    name: str
    identity: str
    transport: str
    model_source: str
    session_resume: str
    enable_setting: str | None
    model_setting: str | None
    model_pattern: str | None
    controls: dict
    runtime: dict

    def receipt(self) -> dict:
        return {"provider": self.name, "identity": self.identity, "transport": self.transport,
                "model_source": self.model_source, "session_resume": self.session_resume}


@dataclass(frozen=True)
class ProviderPolicy:
    version: str
    default_provider: str
    providers: dict
    assignments: tuple
    policy_digest: str

    def provider(self, name: str) -> Provider:
        require(name in self.providers, "Unknown execution provider: " + str(name))
        return self.providers[name]

    def permits(self, provider: str, *, role: str, action, workload: str, read_only: bool) -> bool:
        return any(rule for rule in self.assignments
                   if rule["provider"] == provider and role in rule["roles"]
                   and action is not None and action in rule["actions"]
                   and workload in rule["workloads"] and bool(read_only) == rule["read_only"])

    def permitted_pairs(self, provider: str) -> set:
        return {(role, action) for rule in self.assignments if rule["provider"] == provider
                for role in rule["roles"] for action in rule["actions"]}


def parse_policy(document) -> ProviderPolicy:
    """Validate the packaged execution policy; an unreadable or unexpected policy is never a default."""
    require(isinstance(document, dict), "Provider policy must be an object")
    require(document.get("version") == POLICY_VERSION, "Unsupported provider policy version")
    raw = document.get("providers")
    require(isinstance(raw, dict) and raw, "Provider policy must declare providers")
    providers = {}
    for name, body in sorted(raw.items()):
        require(_token(name), "Provider name must be a short token")
        require(isinstance(body, dict), f"Provider {name} entry must be an object")
        for key in ("identity", "transport", "model_source"):
            require(_token(body.get(key)), f"Provider {name} must declare {key}")
        require(body["model_source"] in MODEL_SOURCES, f"Provider {name} has an unknown model source")
        require(body["transport"] in STREAMS,
                f"Provider {name} names a transport nothing can read: " + body["transport"])
        require(body.get("session_resume") in RESUME_STATES, f"Provider {name} must declare session_resume")
        enable = body.get("enable_setting")
        require(enable is None or (type(enable) is str and SETTING_NAME.fullmatch(enable)),
                f"Provider {name} enable_setting must be an environment name or null")
        model_setting = body.get("model_setting")
        require(model_setting is None or (type(model_setting) is str and SETTING_NAME.fullmatch(model_setting)),
                f"Provider {name} model_setting must be an environment name or null")
        require((body["model_source"] == "explicit_setting") == bool(model_setting),
                f"Provider {name} needs a model setting exactly when its model is explicit")
        pattern = body.get("model_pattern")
        if pattern is not None:
            require(type(pattern) is str and bool(pattern), f"Provider {name} model_pattern must be text")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ContractError(f"Provider {name} model_pattern is not a regular expression") from exc
        controls = body.get("controls", {})
        require(isinstance(controls, dict), f"Provider {name} controls must be an object")
        for control, spec in sorted(controls.items()):
            require(_token(control) and isinstance(spec, dict), f"Provider {name} control {control} is malformed")
            require(type(spec.get("setting")) is str and SETTING_NAME.fullmatch(spec["setting"]),
                    f"Provider {name} control {control} needs a setting name")
            require(spec.get("kind") in CONTROL_KINDS, f"Provider {name} control {control} needs a known kind")
            require(type(spec.get("required")) is bool, f"Provider {name} control {control} needs required")
        runtime = body.get("runtime", {})
        require(isinstance(runtime, dict), f"Provider {name} runtime must be an object")
        providers[name] = Provider(name=name, identity=body["identity"], transport=body["transport"],
                                   model_source=body["model_source"], session_resume=body["session_resume"],
                                   enable_setting=enable, model_setting=model_setting, model_pattern=pattern,
                                   controls=controls, runtime=runtime)
    default = document.get("default_provider")
    require(_token(default) and default in providers, "Provider policy must name a known default provider")
    require(providers[default].enable_setting is None,
            "The default provider is not enabled by host configuration")
    rules = document.get("assignments", [])
    require(isinstance(rules, list), "Provider assignments must be a list")
    assignments = []
    for rule in rules:
        require(isinstance(rule, dict), "Provider assignment must be an object")
        require(rule.get("provider") in providers, "Provider assignment names an unknown provider")
        require(rule["provider"] != default, "The default provider needs no assignment rule")
        for key in ("roles", "actions", "workloads"):
            values = rule.get(key)
            require(isinstance(values, list) and values and all(type(v) is str and v for v in values),
                    f"Provider assignment {key} must be a non-empty list of names")
        require(type(rule.get("read_only")) is bool, "Provider assignment must state read_only")
        assignments.append({"provider": rule["provider"], "roles": list(rule["roles"]),
                            "actions": list(rule["actions"]), "workloads": list(rule["workloads"]),
                            "read_only": rule["read_only"]})
    return ProviderPolicy(version=document["version"], default_provider=default, providers=providers,
                          assignments=tuple(assignments), policy_digest=digest(document))


@dataclass(frozen=True)
class ProviderConfiguration:
    """What the host enabled. Values that could be secret are never stored here: the controls this
    holds are a model name, a spend ceiling, a timeout and an executable path, and the digest binds
    exactly those, so a receipt can prove which configuration ran without reprinting it."""
    enabled: dict = field(default_factory=dict)
    config_digest: str = ""

    def pairs(self, provider: str) -> tuple:
        entry = self.enabled.get(provider)
        return tuple(entry["pairs"]) if entry else ()


def _number(text, spec, name):
    try:
        value = float(text) if spec["kind"] == "number" else int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a {spec['kind']}") from exc
    require(value == value and value not in (float("inf"), float("-inf")), f"{name} must be finite")
    if spec.get("minimum") is not None:
        require(value >= spec["minimum"], f"{name} is below the policy minimum {spec['minimum']}")
    if spec.get("maximum") is not None:
        require(value <= spec["maximum"], f"{name} is above the policy maximum {spec['maximum']}")
    return value


def parse_configuration(policy: ProviderPolicy, settings: dict) -> ProviderConfiguration:
    """Read host enablement for every non-default provider; refuse the configuration as a whole when
    it names a pairing the packaged policy does not permit, or omits a required control."""
    require(isinstance(settings, dict), "Settings must be a mapping")
    enabled = {}
    for name, provider in sorted(policy.providers.items()):
        if provider.enable_setting is None:
            continue
        raw = settings.get(provider.enable_setting)
        if raw is None or not str(raw).strip():
            continue
        pairs = []
        for token in str(raw).split(","):
            token = token.strip()
            if not token:
                continue
            match = PAIR.fullmatch(token)
            require(match is not None,
                    f"{provider.enable_setting} entries are '<role>/<action>': " + token)
            pair = (match.group("role"), match.group("action"))
            require(pair in policy.permitted_pairs(name),
                    f"{provider.enable_setting} names a pairing the packaged policy does not permit: " + token)
            pairs.append(pair)
        require(pairs, f"{provider.enable_setting} is set but names no assignment")
        model = settings.get(provider.model_setting) if provider.model_setting else None
        if provider.model_source == "explicit_setting":
            require(type(model) is str and bool(model.strip()),
                    f"{provider.model_setting} must name the {name} model explicitly; it is never derived")
            model = model.strip()
            if provider.model_pattern:
                require(re.fullmatch(provider.model_pattern, model) is not None,
                        f"{provider.model_setting} is not a {name} model name: " + model)
        controls = {}
        for control, spec in sorted(provider.controls.items()):
            value = settings.get(spec["setting"])
            present = value is not None and str(value).strip() != ""
            require(present or not spec["required"],
                    f"{spec['setting']} is required before {name} may execute")
            if not present:
                continue
            controls[control] = (str(value).strip() if spec["kind"] == "path"
                                 else _number(str(value).strip(), spec, spec["setting"]))
        enabled[name] = {"pairs": tuple(pairs), "model": model, "controls": controls}
    return ProviderConfiguration(enabled=enabled,
                                 config_digest=digest({"policy": policy.policy_digest, "enabled": enabled}))


@dataclass(frozen=True)
class ExecutionAssignment:
    """The decided execution: who runs it, under which policy, with which declared controls."""
    provider: str
    identity: str
    transport: str
    model_source: str
    configured_model: str | None
    session_resume: str
    controls: dict
    runtime: dict
    policy_version: str
    policy_digest: str
    config_digest: str
    selected_by: str
    role: str
    action: str | None
    workload: str
    read_only: bool

    @property
    def is_default(self) -> bool:
        return self.selected_by == "packaged_default"

    def receipt(self) -> dict:
        """Everything a reviewer needs to know which policy chose this provider; no secret values."""
        return {"provider": self.provider, "identity": self.identity, "transport": self.transport,
                "model_source": self.model_source, "session_resume": self.session_resume,
                "policy_version": self.policy_version, "policy_digest": self.policy_digest,
                "config_digest": self.config_digest, "selected_by": self.selected_by,
                "role": self.role, "action": self.action, "workload": self.workload,
                "read_only": self.read_only, "controls": dict(self.controls)}


def select_execution(policy: ProviderPolicy, configuration: ProviderConfiguration, *, role: str,
                     action, workload: str, read_only: bool) -> ExecutionAssignment:
    """Decide the provider for one assignment, or refuse. Never falls back between providers."""
    require(type(role) is str and bool(role), "Provider selection needs the executing role")
    require(action is None or (type(action) is str and bool(action)), "Action must be a name or absent")
    require(type(workload) is str and bool(workload), "Provider selection needs the workload")
    require(type(read_only) is bool, "Provider selection needs the read_only flag")
    matched = [name for name in sorted(configuration.enabled) if (role, action) in configuration.pairs(name)]
    require(len(matched) <= 1, "Two providers are enabled for the same assignment: " + ", ".join(matched))
    for name in matched:
        provider = policy.provider(name)
        # Enabled for this pairing: the packaged policy must permit this exact shape, including the
        # workload and the read-only flag. A mismatch is refused here, before anything spawns.
        require(policy.permits(name, role=role, action=action, workload=workload, read_only=read_only),
                f"{name} is enabled for {role}/{action} but the packaged policy does not permit it as "
                f"workload={workload} read_only={read_only}")
        entry = configuration.enabled[name]
        return ExecutionAssignment(
            provider=name, identity=provider.identity, transport=provider.transport,
            model_source=provider.model_source, configured_model=entry["model"],
            session_resume=provider.session_resume, controls=dict(entry["controls"]),
            runtime=dict(provider.runtime), policy_version=policy.version,
            policy_digest=policy.policy_digest, config_digest=configuration.config_digest,
            selected_by="host_configuration", role=role, action=action, workload=workload,
            read_only=read_only)
    default = policy.provider(policy.default_provider)
    return ExecutionAssignment(
        provider=default.name, identity=default.identity, transport=default.transport,
        model_source=default.model_source, configured_model=None,
        session_resume=default.session_resume, controls={}, runtime=dict(default.runtime),
        policy_version=policy.version, policy_digest=policy.policy_digest,
        config_digest=configuration.config_digest, selected_by="packaged_default", role=role,
        action=action, workload=workload, read_only=read_only)
