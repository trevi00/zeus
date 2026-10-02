"""Shared S8 scenario steps (`intake.ticket_authority`): M7 `adapters/ticket_authority.py` (`TicketAuthority`: `policy`, `verify`, `require_merged`),
characterized BEFORE the module moves into INTAKE (S8 batch B1: R-ta1 the injected `run_process`, R-ta2 the injected `clock`). The golden is
placement-neutral: it observes SOURCE behaviour only.

- **a_surface**: the module's constants, the positional constructor parameters (the keyword-only ports are the target's R-ta1/R-ta2 and are not in
  the golden), the method signatures, the attributes the constructor keeps.
- **b_trust**: the trust commit source (explicit, `ZEUS_TICKET_TRUST_COMMIT`, absent, invalid, an explicit empty string) and the `git` replies.
- **c_policy**: `policy()` over the scripted `git`: a missing or invalid trust commit, an unavailable anchor, a non-regular file, the 65536-byte budget,
  invalid JSON/schema, every signer, list and window rule, a valid policy; the heartbeats and the `git` calls (arguments, `strip`).
- **d_verify**: `verify(...)`: the signature accepted and rejected (the stderr tail), an incomplete signer set, a revoked, expired, not-yet-valid or
  duplicate signer, an unenrolled principal, every envelope shape, a stale policy, a packet that is not the canonical bytes, the missing/oversize
  artifacts, `at`, the unmerged solution commit, a signer expiring during verification, the missing `ssh-keygen`, the heartbeats; what the runner
  receives (argv, stdin digest, the timeout, the environment filter, the two files' contents) and that the temporary directory is removed.
- **e_merged**: `require_merged`.

Each case is labelled with the M7 test it mirrors (`m7_test`), or `none`. M7's `TicketAuthority` cases are in `tests/test_ticket_lifecycle.py` (the
`lifecycle` fixture builds a real git repository and a real `ssh-keygen` key; 22 tests drive it through the lifecycle, GitHub and the CLI). Unreachable
here, reported in `m7_tests`: the real `ssh-keygen` signatures, the real git trust repository and its commit, GitHub sync; no real signer, key,
network or database is used.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything arrives through `api`. LABELLED doubles (nothing here is an actual signature verification):
- `FakeGit`: `_git(*args, cwd=None, strip=True)` answers the scripted reply for `rev-parse`, `ls-tree`, `show` and `merge-base` and records every call;
- `FakeArtifacts`: `text(ref, max_bytes)` over a dict, with the real byte bound;
- `FakeRun`: the `run_process` replacement; it answers a scripted return code per principal (default 0), and records what the module handed it: the
  argv, the stdin digest, the timeout, the environment keys, the contents of the two files it was told to read. The reference side patches the SOURCE
  module's `run_process` with it, the target side injects it (R-ta1). The clock is the harness's (the SOURCE module's `datetime` is patched by the
  harness; the target receives the same clock through R-ta2).
The masked temporary-directory paths: the module creates `zeus-ticket-verify-XXXX` under the OS temporary directory; the runner records every path
and every environment value containing that directory with the directory replaced by `<verify-dir>` (the count of replacements is recorded). Nothing
else is masked: not an argv word, a principal, a hash or a reason.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import re
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

NAMESPACE = "zeus-ticket-close-v1"
COMMIT = "a" * 40
SOLUTION = "b" * 40
OTHER_COMMIT = "c" * 40
HUMAN = "alice@zeus.invalid"
BOT = "bot@zeus.invalid"
OLD = "old@zeus.invalid"
VERIFY_DIR = re.compile(r"\S*zeus-ticket-verify-[A-Za-z0-9_]+")
ENV_NAME = "ZEUS_TICKET_TRUST_COMMIT"

M7_TESTS = {
    "covered": ["test_signed_close_reopen_and_new_cycle_invalidate_old_work (the TicketAuthority.verify acceptance, through a labelled runner)",
                "test_closure_rejects_missing_failed_stale_or_unsigned_evidence (the authority halves: unsigned, wrong namespace/principal, stale policy)",
                "test_signature_authority_is_not_an_actor_string",
                "test_repo_commit_cannot_replace_anchored_signers (the trust commit anchor)",
                "test_invalid_or_untrusted_policy_cannot_authorize_close (policy refusals: missing, invalid, non-regular, oversize, schema)",
                "test_crlf_signature_armor_and_explicit_required_signers_receipt (CRLF armor normalised, the receipt fields)",
                "test_slow_verification_renews_owned_lease_between_bounded_operations (the heartbeats)"],
    "unreachable": {"the real ssh-keygen -Y sign/verify and the real key": "no real signer or key in a characterization",
                    "the real git trust repository (git init, commit, ls-tree)": "labelled FakeGit scripts the replies",
                    "the lifecycle, GitHub and CLI halves of the 22 tests": "other families (intake.ticket_lifecycle) and S10"}}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=repr).encode()).hexdigest()[:16]


def key(n):
    return "ssh-ed25519 " + base64.b64encode(bytes([n]) * 32).decode()


def policy_document(**over):
    document = {"version": 1, "scope": "test-only-ticket-authority",
                "signers": [{"principal": HUMAN, "role": "human", "public_key": key(1), "valid_after": "2020-01-01T00:00:00+00:00",
                             "valid_before": "2099-01-01T00:00:00+00:00"},
                            {"principal": BOT, "role": "automation", "public_key": key(2), "valid_after": "2020-01-01T00:00:00+00:00",
                             "valid_before": "2099-01-01T00:00:00+00:00"},
                            {"principal": OLD, "role": "automation", "public_key": key(3), "valid_after": "2020-01-01T00:00:00+00:00",
                             "valid_before": "2099-01-01T00:00:00+00:00"}],
                "required_signers": [HUMAN, BOT], "required_human_signers": [HUMAN], "revoked": [OLD], "max_evidence_age_seconds": 86400}
    document.update(over)
    return document


def with_signer(document, principal, **over):
    document = deepcopy(document)
    for signer in document["signers"]:
        if signer["principal"] == principal:
            signer.update(over)
    return document


class Boom(Exception):
    """LABELLED scripted fault of a double."""


class FakeGit:
    def __init__(self, api, document=None, raw=None):
        self.api, self.calls, self.faults = api, [], {}
        self.document = policy_document() if document is None else document
        self.raw = raw
        self.replies = {"rev-parse": COMMIT, "ls-tree": "100644 blob " + "d" * 40 + "\t.zeus/ticket-trust.json", "merge-base": SOLUTION}

    def text(self):
        return self.raw if self.raw is not None else self.api.canonical(self.document)

    def _git(self, *args, cwd=None, strip=True):
        self.calls.append([list(args), cwd, strip])
        if args[0] in self.faults:
            raise self.faults[args[0]]
        if args[0] == "show":
            return self.text()
        return self.replies[args[0]]


class FakeArtifacts:
    def __init__(self, api):
        self.api, self.bodies, self.calls = api, {}, []

    def put(self, body):
        ref = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
        self.bodies[ref] = body
        return ref

    def text(self, ref, max_bytes):
        self.calls.append([ref, max_bytes])
        if ref not in self.bodies:
            raise FileNotFoundError(ref)
        self.api.require(len(self.bodies[ref].encode("utf-8")) <= max_bytes, "Artifact exceeds text budget")
        return self.bodies[ref]


class FakeRun:
    """The `run_process` double. `results` maps a principal to (returncode, stderr); `hook` runs once per call (clock moves, a scripted fault)."""

    def __init__(self, api):
        self.api, self.calls, self.results, self.fault, self.hook = api, [], {}, None, None
        self.replacements, self.dirs = 0, []

    def mask(self, value):
        text, count = VERIFY_DIR.subn("<verify-dir>", value)
        self.replacements += count
        return text

    def __call__(self, argv, cwd=None, timeout=120, input_text=None, env=None):
        files = {}
        for flag in ("-f", "-s"):
            path = argv[argv.index(flag) + 1]
            self.dirs.append(os.path.dirname(path))
            files[flag] = {"name": os.path.basename(path), "exists": os.path.isfile(path),
                           "text": open(path, encoding="utf-8", newline="").read() if os.path.isfile(path) else None}
        env = env or {}
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "PROGRAMDATA", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE"}
        self.calls.append({
            "argv": [self.mask(a) for a in argv], "cwd": cwd, "timeout": timeout, "input_sha": sha(input_text), "input_len": len(input_text or ""),
            "env_extra_keys": sorted(set(env) - allowed), "env_keys_subset": set(env) <= allowed,
            "home_is_userprofile": env.get("HOME") == env.get("USERPROFILE"), "home_is_the_verify_dir": env.get("HOME") == os.path.dirname(argv[argv.index("-f") + 1]),
            "sentinel_filtered": "ZEUS_SENTINEL_SECRET" not in env,
            "allowed_signers": files["-f"]["text"].replace(os.path.dirname(argv[argv.index("-f") + 1]), "<verify-dir>") if files["-f"]["text"] else None,
            "allowed_name": files["-f"]["name"], "signature_name": files["-s"]["name"], "signature_text": files["-s"]["text"],
            "files_existed": [files["-f"]["exists"], files["-s"]["exists"]]})
        if self.hook is not None:
            hook, self.hook = self.hook, None
            hook()
        if self.fault is not None:
            raise self.fault
        code, err = self.results.get(argv[argv.index("-I") + 1], (0, ""))
        return SimpleNamespace(returncode=code, stdout="", stderr=err)


def shape(value):
    if isinstance(value, dict):
        return {str(k): shape(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [shape(v) for v in value]
    return value


class World:
    def __init__(self, api, document=None, raw=None, trust=COMMIT, environ=None):
        api.clock.reset()
        self.api, self.heartbeats = api, 0
        self.git, self.artifacts, self.run = FakeGit(api, document, raw), FakeArtifacts(api), FakeRun(api)
        saved = os.environ.get(ENV_NAME)
        if environ is None:
            os.environ.pop(ENV_NAME, None)
        else:
            os.environ[ENV_NAME] = environ
        os.environ["ZEUS_SENTINEL_SECRET"] = "must-not-reach-the-runner"
        self.restore = saved
        self.authority = api.make(self.git, self.artifacts, trust, self.run)

    def close(self):
        os.environ.pop("ZEUS_SENTINEL_SECRET", None)
        if self.restore is None:
            os.environ.pop(ENV_NAME, None)
        else:
            os.environ[ENV_NAME] = self.restore

    def beat(self):
        self.heartbeats += 1

    def packet(self, **over):
        policy = self.authority.policy()
        return {"version": 1, "ticket_id": "ZEUS-000000000001", "solution_commit": SOLUTION, "issued_at": self.api.clock.now(self.api.utc).isoformat(),
                **{k: policy[k] for k in ("policy_commit", "policy_hash", "scope")}, **over}

    def signed(self, packet, principals=(HUMAN, BOT), body=None):
        ref = self.artifacts.put(self.api.canonical(packet) if body is None else body)
        out = []
        for principal in principals:
            out.append({"principal": principal, "signature_ref": self.artifacts.put("SIGNATURE:" + principal + ":" + ref + "\n")})
        return ref, out

    def observe(self, call):
        git_before, run_before, heart_before, art_before = len(self.git.calls), len(self.run.calls), self.heartbeats, len(self.artifacts.calls)
        try:
            out = {"outcome": "returned", "value": shape(call())}
        except BaseException as exc:  # noqa: BLE001 - what propagates is part of the observation
            out = {"outcome": "raised", "type": type(exc).__name__, "message": str(exc), "is_contract_error": isinstance(exc, self.api.ContractError),
                   "cause_type": None if exc.__cause__ is None else type(exc.__cause__).__name__}
        out.update(git_calls=self.git.calls[git_before:], runner_calls=self.run.calls[run_before:], heartbeats=self.heartbeats - heart_before,
                   artifact_reads=len(self.artifacts.calls) - art_before)
        return out


def a_surface(api):
    cases = {"constants": {"POLICY_PATH": api.POLICY_PATH, "PRINCIPAL": api.PRINCIPAL.pattern}}
    params = list(inspect.signature(api.TicketAuthority.__init__).parameters.values())
    cases["constructor_positional"] = [p.name for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    cases["constructor_trust_commit_default"] = params[3].default
    cases["methods"] = {n: str(inspect.signature(getattr(api.TicketAuthority, n))) for n in ("policy", "verify", "require_merged")}
    w = World(api)
    try:
        cases["attributes"] = {"git": w.authority.git is w.git, "artifacts": w.authority.artifacts is w.artifacts, "trust_commit": w.authority.trust_commit}
    finally:
        w.close()
    return {"surface": cases}


def b_trust(api):
    cases = {}
    for name, trust, environ in (("explicit", COMMIT, None), ("env_only", None, COMMIT), ("explicit_beats_env", COMMIT, OTHER_COMMIT),
                                 ("absent", None, None), ("explicit_empty_does_not_fall_back", "", COMMIT), ("explicit_short", "a" * 39, None),
                                 ("explicit_upper", "A" * 40, None), ("explicit_not_text", 5, None), ("env_invalid", None, "xyz"), ("explicit_41", "a" * 41, None),
                                 ("explicit_non_hex", "g" * 40, None)):
        w = World(api, trust=trust, environ=environ)
        try:
            cases[name] = {"trust_commit": w.authority.trust_commit, "policy": w.observe(lambda: w.authority.policy())}
        finally:
            w.close()
    return {"trust": cases}


def c_policy(api):
    cases = {}
    base = policy_document()

    def run(name, document=None, raw=None, setup=None, trust=COMMIT):
        w = World(api, document, raw, trust)
        try:
            if setup:
                setup(w)
            cases[name] = w.observe(lambda: w.authority.policy(w.beat))
        finally:
            w.close()

    run("valid")
    w = World(api)
    try:
        cases["valid_without_heartbeat"] = w.observe(lambda: w.authority.policy())
        one, two = w.authority.policy(), w.authority.policy()
        cases["valid_is_stable"] = [one == two, one["policy_hash"] == api.digest(base), set(one) == {"policy_commit", "policy_hash", "scope", "definition", "enrolled"},
                                    sorted(one["enrolled"])]
    finally:
        w.close()
    run("anchor_unavailable", setup=lambda w: w.git.replies.update({"rev-parse": OTHER_COMMIT}))
    run("anchor_git_fault", setup=lambda w: w.git.faults.update({"rev-parse": Boom("rev-parse failed")}))
    run("ls_tree_empty", setup=lambda w: w.git.replies.update({"ls-tree": ""}))
    for mode in ("100755", "120000", "040000", "160000"):
        run("ls_tree_mode_" + mode, setup=lambda w, m=mode: w.git.replies.update({"ls-tree": m + " blob " + "d" * 40 + "\t.zeus/ticket-trust.json"}))
    run("show_fault", setup=lambda w: w.git.faults.update({"show": Boom("show failed")}))
    pad = lambda n: api.canonical(base) + " " * (n - len(api.canonical(base).encode("utf-8")))  # noqa: E731
    run("budget_exact_65536_accepted", raw=pad(65536))
    run("budget_65537_refused", raw=pad(65537))
    run("budget_counts_bytes_not_characters", raw=api.canonical({**base, "scope": "é" * 100}) + " " * 65400)
    run("json_invalid", raw="{not json")
    run("json_duplicate_key", raw='{"version": 1, "version": 1}')
    run("json_not_an_object", raw="[1]")
    run("json_empty", raw="")
    for name, mutate in {
        "missing_field": lambda d: d.pop("revoked"), "extra_field": lambda d: d.update(extra=1), "version_2": lambda d: d.update(version=2),
        "version_true": lambda d: d.update(version=True), "version_string": lambda d: d.update(version="1"),
        "scope_empty": lambda d: d.update(scope=""), "scope_not_text": lambda d: d.update(scope=1), "scope_201": lambda d: d.update(scope="s" * 201),
        "scope_200": lambda d: d.update(scope="s" * 200), "age_59": lambda d: d.update(max_evidence_age_seconds=59),
        "age_60": lambda d: d.update(max_evidence_age_seconds=60), "age_86400": lambda d: d.update(max_evidence_age_seconds=86400),
        "age_86401": lambda d: d.update(max_evidence_age_seconds=86401), "age_bool": lambda d: d.update(max_evidence_age_seconds=True),
        "age_float": lambda d: d.update(max_evidence_age_seconds=3600.0),
        "signers_empty": lambda d: d.update(signers=[], required_signers=[], required_human_signers=[], revoked=[]),
        "signers_not_list": lambda d: d.update(signers="x"),
        "signers_21": lambda d: d.update(signers=[{**d["signers"][0], "principal": "p%d@z" % i, "public_key": key(10 + i)} for i in range(21)], required_signers=["p0@z"],
                                         required_human_signers=["p0@z"], revoked=[]),
        "signer_not_dict": lambda d: d["signers"].__setitem__(0, "x"), "signer_extra": lambda d: d["signers"][0].update(extra=1),
        "signer_missing": lambda d: d["signers"][0].pop("role"), "principal_invalid_start": lambda d: d["signers"][1].update(principal="-x"),
        "principal_space": lambda d: d["signers"][1].update(principal="a b"), "principal_100": lambda d: (d["signers"][2].update(principal="p" * 100), d.update(revoked=["p" * 100])),
        "principal_101": lambda d: (d["signers"][2].update(principal="p" * 101), d.update(revoked=["p" * 101])), "principal_duplicate": lambda d: d["signers"][1].update(principal=HUMAN),
        "principal_not_text": lambda d: d["signers"][1].update(principal=3), "role_invalid": lambda d: d["signers"][1].update(role="root"),
        "key_newline": lambda d: d["signers"][1].update(public_key=key(2) + "\n"), "key_cr": lambda d: d["signers"][1].update(public_key=key(2) + "\r"),
        "key_one_part": lambda d: d["signers"][1].update(public_key="ssh-ed25519"), "key_three_parts": lambda d: d["signers"][1].update(public_key=key(2) + " comment"),
        "key_type_unsupported": lambda d: d["signers"][1].update(public_key="ssh-dss " + key(2).split()[1]),
        "key_rsa_type": lambda d: d["signers"][1].update(public_key="ssh-rsa " + key(2).split()[1]),
        "key_sk_type": lambda d: d["signers"][1].update(public_key="sk-ssh-ed25519@openssh.com " + key(2).split()[1]),
        "key_base64_invalid": lambda d: d["signers"][1].update(public_key="ssh-ed25519 !!!"), "key_not_text": lambda d: d["signers"][1].update(public_key=7),
        "key_duplicate": lambda d: d["signers"][1].update(public_key=key(1)),
        "validity_equal": lambda d: d["signers"][1].update(valid_before=d["signers"][1]["valid_after"]),
        "validity_reversed": lambda d: d["signers"][1].update(valid_after="2099-01-01T00:00:00+00:00", valid_before="2020-01-01T00:00:00+00:00"),
        "validity_not_iso": lambda d: d["signers"][1].update(valid_after="yesterday"), "validity_naive": lambda d: d["signers"][1].update(valid_after="2020-01-01T00:00:00"),
        "validity_not_text": lambda d: d["signers"][1].update(valid_before=5),
        "required_not_list": lambda d: d.update(required_signers=HUMAN), "required_unenrolled": lambda d: d.update(required_signers=[HUMAN, "ghost@z"]),
        "required_duplicate": lambda d: d.update(required_signers=[HUMAN, HUMAN]), "required_empty": lambda d: d.update(required_signers=[], required_human_signers=[]),
        "required_not_text": lambda d: d.update(required_signers=[HUMAN, 5]), "human_not_required": lambda d: d.update(required_human_signers=[HUMAN, OLD]),
        "human_is_automation": lambda d: d.update(required_human_signers=[BOT]), "human_unenrolled": lambda d: d.update(required_human_signers=["ghost@z"]),
        "revoked_unenrolled": lambda d: d.update(revoked=["ghost@z"]), "revoked_duplicate": lambda d: d.update(revoked=[OLD, OLD]),
        "revoked_required": lambda d: d.update(revoked=[BOT]), "revoked_not_list": lambda d: d.update(revoked=OLD),
        "human_empty_ok": lambda d: d.update(required_human_signers=[]), "revoked_empty_ok": lambda d: d.update(revoked=[])}.items():
        document = deepcopy(base)
        mutate(document)
        run("schema_" + name, document)
    return {"policy": cases}


def d_verify(api):
    cases = {}

    def world(**kw):
        return World(api, **kw)

    def go(name, mutate=None, *, principals=(HUMAN, BOT), packet_over=None, at=None, results=None, document=None, body_for=None, signatures=None,
           setup=None, ref=None, use_heartbeat=True, tick=0):
        w = world(document=document)
        try:
            packet = w.packet(**(packet_over or {}))
            ref_, sigs = w.signed(packet, principals)
            if body_for is not None:
                ref_ = w.artifacts.put(body_for(packet))
            if signatures is not None:
                sigs = signatures(sigs)
            if setup:
                setup(w)
            for principal, outcome in (results or {}).items():
                w.run.results[principal] = outcome
            if tick:
                w.api.clock.advance(tick)
            kwargs = {"heartbeat": w.beat} if use_heartbeat else {}
            if at is not None:
                kwargs["at"] = at(w) if callable(at) else at
            cases[name] = w.observe(lambda: w.authority.verify(ref if ref is not None else ref_, packet, sigs, **kwargs))
            cases[name]["dirs_removed"] = [not os.path.exists(d) for d in sorted(set(w.run.dirs))]
            cases[name]["mask_replacements"] = w.run.replacements
        finally:
            w.close()

    go("accepted")
    go("accepted_without_heartbeat", use_heartbeat=False)
    go("accepted_clock_later", tick=3600)
    go("accepted_human_only_required", document=policy_document(required_signers=[HUMAN], required_human_signers=[HUMAN]), principals=(HUMAN,))
    go("accepted_extra_unrequired_signer", principals=(HUMAN, BOT, OLD), document=policy_document(revoked=[]))
    go("accepted_crlf_signature_armor", setup=lambda w: [w.artifacts.bodies.__setitem__(k, v.replace("\n", "\r\n")) for k, v in list(w.artifacts.bodies.items())
                                                           if v.startswith("SIGNATURE:")])
    go("rejected_one_signer", results={BOT: (1, "x" * 400 + "tail of the verifier error")})
    go("rejected_first_signer_stops_the_rest", results={HUMAN: (255, "no matching principal")})
    go("rejected_empty_stderr", results={BOT: (1, "")})
    go("rejected_short_stderr", results={BOT: (2, "short")})
    go("incomplete_signer_set", principals=(BOT,))
    go("incomplete_human_missing", principals=(BOT, OLD), document=policy_document(revoked=[]))
    go("revoked_signer", principals=(HUMAN, BOT, OLD))
    go("unenrolled_principal", signatures=lambda s: [{**s[0], "principal": "ghost@zeus.invalid"}, s[1]])
    go("duplicate_principal", signatures=lambda s: [s[0], s[0]])
    go("envelope_extra_key", signatures=lambda s: [{**s[0], "extra": 1}, s[1]])
    go("envelope_missing_key", signatures=lambda s: [{"principal": HUMAN}, s[1]])
    go("envelope_not_a_dict", signatures=lambda s: ["x", s[1]])
    go("envelope_ref_invalid", signatures=lambda s: [{**s[0], "signature_ref": "sha256:xyz"}, s[1]])
    go("envelope_ref_not_text", signatures=lambda s: [{**s[0], "signature_ref": 5}, s[1]])
    go("envelope_principal_not_text", signatures=lambda s: [{**s[0], "principal": 5}, s[1]])
    go("signature_artifact_missing", signatures=lambda s: [{**s[0], "signature_ref": "sha256:" + "9" * 64}, s[1]])
    go("signatures_not_a_list", signatures=lambda s: {"x": 1})
    go("signatures_empty", signatures=lambda s: [])
    go("signatures_21", signatures=lambda s: [s[0]] * 21)
    go("stale_policy_commit", packet_over={"policy_commit": OTHER_COMMIT})
    go("stale_policy_hash", packet_over={"policy_hash": "0" * 64})
    go("stale_policy_scope", packet_over={"scope": "another-scope"})
    go("packet_not_canonical_bytes", body_for=lambda p: api.canonical(p) + " ")
    go("packet_artifact_missing", ref="sha256:" + "8" * 64)
    go("packet_artifact_oversize", body_for=lambda p: "x" * (1024 * 1024 + 1))
    go("signer_expired_at_the_given_time", at=lambda w: w.api.clock.now(w.api.utc) + timedelta(days=36525),
       document=with_signer(policy_document(), BOT, valid_before="2030-01-01T00:00:00+00:00"))
    go("signer_not_yet_valid_at_issue", document=with_signer(policy_document(), BOT, valid_after="2030-01-01T00:00:00+00:00", valid_before="2031-01-01T00:00:00+00:00"))
    go("at_before_issue", at=lambda w: w.api.clock.now(w.api.utc) - timedelta(seconds=1))
    go("at_equal_to_issue_accepted", at=lambda w: w.api.clock.now(w.api.utc))
    go("at_equal_to_valid_before_refused", at=lambda w: w.api.clock.now(w.api.utc),
       document=with_signer(policy_document(), BOT, valid_before="2026-09-22T00:00:00+00:00"))
    go("valid_before_a_second_after_issue", document=with_signer(policy_document(), BOT, valid_before="2026-09-22T00:00:01+00:00"))
    go("signer_expires_during_verification", document=with_signer(policy_document(), BOT, valid_before="2026-09-22T00:00:30+00:00"),
       setup=lambda w: setattr(w.run, "hook", lambda: w.api.clock.advance(60)))
    go("unmerged_solution_commit", setup=lambda w: w.git.replies.update({"merge-base": OTHER_COMMIT}))
    go("solution_commit_invalid", packet_over={"solution_commit": "short"})
    go("solution_commit_missing", packet_over={"solution_commit": None})
    go("merge_base_fault", setup=lambda w: w.git.faults.update({"merge-base": Boom("merge-base failed")}))
    go("ssh_keygen_missing", setup=lambda w: setattr(w.run, "fault", FileNotFoundError("ssh-keygen")))
    go("runner_other_fault_propagates", setup=lambda w: setattr(w.run, "fault", Boom("runner failed")))
    go("runner_timeout_propagates", setup=lambda w: setattr(w.run, "fault", TimeoutError("timed out")))
    go("git_fault_in_policy", setup=lambda w: w.git.faults.update({"ls-tree": Boom("ls-tree failed")}))
    go("policy_changed_after_packet", setup=lambda w: w.git.replies.update({"rev-parse": OTHER_COMMIT}))

    # the packet mutated after the signatures (the packet is the one signed; the artifact still holds the old bytes)
    w = world()
    try:
        packet = w.packet()
        ref, sigs = w.signed(packet)
        cases["packet_changed_after_signing"] = w.observe(lambda: w.authority.verify(ref, {**packet, "ticket_id": "ZEUS-000000000002"}, sigs))
        cases["packet_missing_policy_field"] = w.observe(lambda: w.authority.verify(ref, {k: v for k, v in packet.items() if k != "scope"}, sigs))
        for name, edit in (("missing_issued_at", lambda p: {k: v for k, v in p.items() if k != "issued_at"}), ("issued_at_invalid", lambda p: {**p, "issued_at": "later"}),
                           ("issued_at_naive", lambda p: {**p, "issued_at": "2026-09-22T00:00:00"}), ("issued_at_not_text", lambda p: {**p, "issued_at": 5}),
                           ("issued_at_in_the_future", lambda p: {**p, "issued_at": "2026-09-23T00:00:00+00:00"})):
            signed_packet = edit(packet)
            signed_ref, signed_sigs = w.signed(signed_packet)
            cases["packet_" + name] = w.observe(lambda r=signed_ref, p=signed_packet, g=signed_sigs: w.authority.verify(r, p, g))
    finally:
        w.close()
    return {"verify": cases}


def e_merged(api):
    cases = {}
    for name, commit, reply, fault in (("merged", SOLUTION, SOLUTION, None), ("not_merged", SOLUTION, OTHER_COMMIT, None), ("invalid_short", "abc", SOLUTION, None),
                                       ("invalid_none", None, SOLUTION, None), ("invalid_upper", "A" * 40, SOLUTION, None), ("invalid_not_text", 7, SOLUTION, None),
                                       ("git_fault", SOLUTION, SOLUTION, Boom("merge-base failed"))):
        w = World(api)
        try:
            w.git.replies["merge-base"] = reply
            if fault:
                w.git.faults["merge-base"] = fault
            cases[name] = w.observe(lambda c=commit: w.authority.require_merged(c))
        finally:
            w.close()
    return {"merged": cases}


def run(api) -> dict:
    groups = {}
    for step in (a_surface, b_trust, c_policy, d_verify, e_merged):
        groups.update(step(api))
    return {**groups, "m7_tests": M7_TESTS, "cases_per_group": {k: len(v) for k, v in groups.items()}}
