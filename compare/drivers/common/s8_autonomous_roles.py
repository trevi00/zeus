"""Shared S8 scenario steps (`research.autonomous_roles`): M7 `adapters/autonomous_roles.py` (the `dge_role` executor action: the model-facing
output schemas, the role objectives, the council delivery projection and its admission, the role context, `execute_role`), characterized
BEFORE the module moves (DESIGN-s8 §6 V11; the branch table `branch-table-research.txt` section `adapters/autonomous_roles.py`: the module has
no explicit `raise` or `except`, every refusal is a `require(...)` ContractError; each one is covered, see `BRANCH_COVERAGE`).

- **s1_tables**: the sha256 of the canonical JSON of `SCHEMAS`, `OBJECTIVES`, `DELIVERY_GUIDANCE`, `CONSUMER_ENUMS`, `PRODUCED` and the tuple
  constants verbatim.
- **s2_objective**: `role_objective` for every role, and its refusals (non-object details for a council producer, a missing earlier payload).
- **s3_council_delivery**: `council_delivery` for each debate role (complete details, every missing mandatory input, wrong role, over-budget
  required blocks and the typed overflow), and that the inline values are deep copies.
- **s4_admitted_delivery**: the accepted projection and every refusal of the admission.
- **s5_isolation_context**: `isolation_reference`, `role_context`.
- **s6_role_schema**: `role_schema` for every role, the criterion roles over valid and refused criteria, the static schema unmodified.
- **s7_execute_role**: `execute_role` over a LABELLED fake executor (a git double and a `_run` recorder): success for a v1 role and for each
  debate role (the exact `_run` arguments and the `role_execution` block), every refusal, and what is not mapped (propagation).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. The executor, its git and its `_run` are LABELLED
fakes; nothing here touches a repository, a provider, a file or a database."""

from __future__ import annotations

import copy
import hashlib
import json

BASE = "a1" * 20
OTHER = "b2" * 20


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def seen(call):
    """The outcome of a call: its value, or the type and message of what it raised (a non-ContractError is observed too)."""
    try:
        return {"returned": call()}
    except BaseException as exc:  # noqa: BLE001 - what is NOT a ContractError is part of the observation
        return {"raised": type(exc).__name__, "message": str(exc), "args": [repr(a) for a in exc.args],
                "bases": [c.__name__ for c in type(exc).__mro__[:4]]}


def refused(call):
    out = seen(call)
    return out if "raised" in out else {"unexpectedly_returned": digest(out["returned"])}


PACKET = {"claims": [{"id": "c1", "kind": "fact", "text": "x", "source_ids": ["s1"]}], "questions": [], "sources": [{"id": "s1"}]}
DBA_REPORT = {"snapshot_digest": "sha256:" + "d1" * 32, "summary": "found", "claim_ids": ["c1"], "unknowns": []}
RESEARCH_PROPOSAL = {"summary": "plan", "claim_ids": ["c1"], "snapshot_digest": "sha256:" + "d1" * 32, "report_digest": "sha256:" + "d2" * 32}
IMPROVEMENT_PROPOSAL = {"summary": "alt", "decision": "improve", "rationale": "r", "claim_ids": ["c1"], "findings": []}


def details_for(role, **overrides):
    out = {"role": role, "run_id": "run-1", "base_revision": BASE, "round": 1, "packet": copy.deepcopy(PACKET), "packet_digest": "sha256:" + "p1" * 32,
           "dba_report": copy.deepcopy(DBA_REPORT), "snapshot_digest": "sha256:" + "d1" * 32, "report_digest": "sha256:" + "d2" * 32,
           "relay": {"from": "lead:dba"}, "acceptance_criteria": ["crit-a", "crit-b"], "blocker_rule": "only material blockers are critical",
           "research_proposal": copy.deepcopy(RESEARCH_PROPOSAL), "improvement_proposal": copy.deepcopy(IMPROVEMENT_PROPOSAL),
           "ssot": {"decision": "improve"}, "prior_outputs": [{"role": "researcher"}]}
    out.update(overrides)
    return out


def without(details, *keys):
    return {k: v for k, v in details.items() if k not in keys}


def s1_tables(api):
    out = {name: digest(getattr(api, name)) for name in ("SCHEMAS", "OBJECTIVES", "DELIVERY_GUIDANCE", "PRODUCED")}
    out["CONSUMER_ENUMS"] = digest({k: sorted(v) for k, v in api.CONSUMER_ENUMS.items()})
    out["CONSUMER_ENUMS_keys"] = list(api.CONSUMER_ENUMS)
    out["schema_roles"] = list(api.SCHEMAS)
    out["objective_roles"] = list(api.OBJECTIVES)
    out["produced_sections"] = dict(api.PRODUCED)
    out["delivery_guidance_roles"] = list(api.DELIVERY_GUIDANCE)
    out["tuples"] = {name: list(getattr(api, name)) for name in ("CRITERION_ROLES", "COUNCIL_DEBATE_ROLES", "INLINE_DELIVERY", "POINTER_DELIVERY")}
    out["PROPOSAL_DELIVERY"] = {k: list(v) for k, v in api.PROPOSAL_DELIVERY.items()}
    out["READING"] = api.READING
    out["texts"] = {"UNSOURCED_KIND": api.UNSOURCED_KIND, "UNRESOLVED_STATUS": api.UNRESOLVED_STATUS,
                    "SOURCED_KINDS": sorted(api.SOURCED_KINDS), "ANSWERED_STATUSES": sorted(api.ANSWERED_STATUSES)}
    out["small_tables"] = {"TEXT": api.TEXT, "STRINGS": api.STRINGS, "NULLABLE_TEXT": api.NULLABLE_TEXT, "CITED": api.CITED, "BOOLEAN": api.BOOLEAN,
                           "NONBLOCKING": api.NONBLOCKING}
    out["fragments"] = {name: digest(getattr(api, name)) for name in ("CLAIM", "QUESTION", "TRANSITION", "SSOT", "SOURCE", "FINDING",
                                                                         "IMPROVEMENT_TRANSITION")}
    out["helpers"] = {"_object": api._object({"a": api.TEXT, "b": api.STRINGS}), "_enum": api._enum({"b", "a", "c"}),
                      "_limited": api._limited("dba", "summary"), "_limits": {r: api._limits(r) for r in ("dba", "improvement_lead")},
                      "_listed": api._listed({"z", "a", "m"}), "_claim": digest(api._claim({"fact"}, api.CITED)),
                      "_question": digest(api._question({"answered"}, api.BOOLEAN, api.CITED))}
    out["module_docstring_first_line"] = api.module.__doc__.splitlines()[0]
    return out


def s2_objective(api):
    out = {}
    for role in api.OBJECTIVES:
        details = details_for(role)
        text = api.role_objective(role, details)
        out[role] = {"digest": digest(text), "length": len(text), "static": text == api.OBJECTIVES[role], "produced": role in api.PRODUCED,
                     "suffix": text[len(api.OBJECTIVES[role]):] if role in api.PRODUCED else None}
    out["researcher_tail_is_the_packet_allowance"] = api.OBJECTIVES["researcher"].endswith(api.output_limit(api.PACKET, {}))
    out["static_roles_ignore_details"] = {r: api.role_objective(r, "not an object") == api.OBJECTIVES[r]
                                          for r in ("researcher", "proposer", "attacker", "arbiter", "conductor")}
    out["producer_with_smaller_details"] = {r: api.role_objective(r, {"packet": PACKET, "dba_report": DBA_REPORT, "research_proposal": RESEARCH_PROPOSAL})
                                            for r in api.PRODUCED}
    out["producer_with_extra_details_only"] = seen(lambda: api.role_objective("dba", {"unrelated": 1}))
    out["producer_extra_details_ignored"] = api.role_objective("dba", {"packet": PACKET, "unrelated": 1}) == api.role_objective("dba", {"packet": PACKET})
    out["details_not_an_object"] = {r: refused(lambda r=r: api.role_objective(r, d)) for r in api.PRODUCED for d in (None, [], "text")}
    out["missing_earlier_payload"] = {r: seen(lambda r=r: api.role_objective(r, {})) for r in ("research_lead", "improvement_lead")}
    out["missing_research_proposal"] = seen(lambda: api.role_objective("improvement_lead", {"packet": PACKET, "dba_report": DBA_REPORT}))
    out["unknown_role"] = seen(lambda: api.role_objective("nobody", {}))
    out["none_role"] = seen(lambda: api.role_objective(None, {}))
    return out


def s3_council_delivery(api):
    out = {}
    for role in api.COUNCIL_DEBATE_ROLES:
        details = details_for(role)
        before = copy.deepcopy(details)
        delivery = api.council_delivery(role, details)
        inline = delivery["inline"]
        out[role] = {
            "delivery": delivery, "inline_keys": list(inline), "inline_keys_expected": list(api.INLINE_DELIVERY + api.PROPOSAL_DELIVERY[role]),
            "not_inline": delivery["not_inline"], "details_unchanged": details == before,
            "inline_values_are_copies": all(inline[k] is not details[k] for k in inline if isinstance(details[k], (dict, list))),
            "inline_values_equal": all(inline[k] == details[k] for k in inline),
            "digest": digest(delivery), "admitted": api.admit_delivery(delivery, role)}
    mandatory = {}
    for role in api.COUNCIL_DEBATE_ROLES:
        fields = api.INLINE_DELIVERY + api.PROPOSAL_DELIVERY[role] + api.POINTER_DELIVERY
        mandatory[role] = {key: refused(lambda role=role, key=key: api.council_delivery(role, without(details_for(role), key))) for key in fields}
    out["missing_one_input"] = mandatory
    out["missing_several_are_sorted"] = refused(lambda: api.council_delivery("conductor", without(details_for("conductor"), "ssot", "packet", "relay")))
    out["extra_detail_not_inlined"] = {role: "unrelated" not in api.council_delivery(role, details_for(role, unrelated=1))["inline"] for role in api.COUNCIL_DEBATE_ROLES}
    out["research_lead_does_not_inline_proposals"] = {k: k in api.council_delivery("research_lead", details_for("research_lead"))["inline"]
                                                      for k in ("research_proposal", "improvement_proposal")}
    out["not_a_debate_role"] = {r: refused(lambda r=r: api.council_delivery(r, details_for(r))) for r in ("researcher", "proposer", "attacker", "arbiter", "dba", "nobody")}
    out["details_role_mismatch"] = {r: refused(lambda r=r: api.council_delivery(r, details_for("dba"))) for r in api.COUNCIL_DEBATE_ROLES}
    out["details_not_an_object"] = {label: refused(lambda d=d: api.council_delivery("conductor", d)) for label, d in
                                    (("none", None), ("list", [1]), ("text", "conductor"))}
    out["details_without_role"] = refused(lambda: api.council_delivery("conductor", without(details_for("conductor"), "role")))
    out["packet_not_an_object"] = {label: refused(lambda v=v: api.council_delivery("research_lead", details_for("research_lead", packet=v)))
                                   for label, v in (("list", []), ("none", None), ("text", "p"))}
    out["dba_report_not_an_object"] = {label: refused(lambda v=v: api.council_delivery("research_lead", details_for("research_lead", dba_report=v)))
                                       for label, v in (("list", []), ("none", None), ("text", "p"))}
    big = {"claims": [{"id": "c" + str(i), "text": "x" * 200} for i in range(120)]}
    out["over_budget_packet"] = {role: refused(lambda role=role: api.council_delivery(role, details_for(role, packet=big))) for role in api.COUNCIL_DEBATE_ROLES}
    out["over_budget_dba_report"] = {role: refused(lambda role=role: api.council_delivery(role, details_for(role, dba_report={"unknowns": ["u" * 5000]})))
                                     for role in api.COUNCIL_DEBATE_ROLES}
    out["over_budget_proposals"] = {
        "improvement_lead_research_proposal": refused(lambda: api.council_delivery("improvement_lead", details_for("improvement_lead", research_proposal={"summary": "s" * 6000}))),
        "conductor_improvement_proposal": refused(lambda: api.council_delivery("conductor", details_for("conductor", improvement_proposal={"summary": "s" * 9000})))}
    out["over_budget_wrapper"] = {role: refused(lambda role=role: api.council_delivery(role, details_for(role, relay={"note": "r" * 5000}))) for role in api.COUNCIL_DEBATE_ROLES}
    out["wrapper_just_inside"] = {role: api.council_delivery(role, details_for(role, relay={"note": "r" * 2500}))["inline"]["relay"] == {"note": "r" * 2500}
                                  for role in api.COUNCIL_DEBATE_ROLES}
    out["overflow_type"] = {role: type(seen_exc(lambda role=role: api.council_delivery(role, details_for(role, packet=big)))).__name__ for role in api.COUNCIL_DEBATE_ROLES}
    return out


def seen_exc(call):
    try:
        call()
    except BaseException as exc:  # noqa: BLE001
        return exc
    return None


def s4_admitted_delivery(api):
    out = {}
    for role in api.COUNCIL_DEBATE_ROLES:
        agent, stage = api.AGENTS[role], "dge:" + role
        details = details_for(role)
        delivery = api.council_delivery(role, details)
        out[role] = {"accepted": api.admitted_delivery(agent, "dge_role", True, stage, details, delivery),
                     "accepted_equals_admit": api.admitted_delivery(agent, "dge_role", True, stage, details, delivery) == api.admit_delivery(delivery, role),
                     "agent": agent}
    role = "research_lead"
    agent, stage, details = api.AGENTS[role], "dge:" + role, details_for(role)
    good = api.council_delivery(role, details)
    run = lambda *a: refused(lambda: api.admitted_delivery(*a))  # noqa: E731
    out["wrong_action"] = {str(a): run(agent, a, True, stage, details, good) for a in ("execute", "dge", None, "")}
    out["not_read_only"] = {str(r): run(agent, "dge_role", r, stage, details, good) for r in (False, None, 1, "true", 0)}
    out["no_role_not_a_dict"] = {label: run(agent, "dge_role", True, stage, details, d) for label, d in (("none", None), ("list", []), ("text", "delivery"))}
    out["no_role_inline_not_a_dict"] = {label: run(agent, "dge_role", True, stage, details, d) for label, d in
                                        (("none", {"inline": None}), ("text", {"inline": "x"}), ("missing", {}))}
    out["no_role_in_inline"] = run(agent, "dge_role", True, stage, details, {"inline": {}})
    out["role_not_a_debate_role"] = {r: run(agent, "dge_role", True, stage, details, {"inline": {"role": r}}) for r in ("researcher", "dba", "attacker", "nobody")}
    out["stage_mismatch"] = {repr(s): run(agent, "dge_role", True, s, details, good) for s in (None, "dge:conductor", "dge_role", "")}
    out["agent_mismatch"] = {repr(a): run(a, "dge_role", True, stage, details, good) for a in ("conductor", "lead:improvement", "", None)}
    other = api.council_delivery("conductor", details_for("conductor"))
    out["delivery_of_another_role"] = run(agent, "dge_role", True, stage, details, other)
    trimmed = copy.deepcopy(good)
    trimmed["inline"]["packet"] = {"claims": []}
    out["trimmed_inline"] = run(agent, "dge_role", True, stage, details, trimmed)
    foreign_task = details_for(role, run_id="another-run")
    out["foreign_task_details"] = run(agent, "dge_role", True, stage, foreign_task, good)
    inflated = copy.deepcopy(good)
    inflated["inline"]["extra"] = "x" * 100
    out["inflated_inline"] = run(agent, "dge_role", True, stage, details, inflated)
    edited = copy.deepcopy(good)
    edited["guidance"] = "Propose anything."
    out["edited_wrapper"] = run(agent, "dge_role", True, stage, details, edited)
    out["details_missing_input_after_the_agreement"] = run(agent, "dge_role", True, stage, without(details, "ssot"), good)
    out["details_role_mismatch_after_the_agreement"] = run(agent, "dge_role", True, stage, details_for("dba"), good)
    out["first_failure_wins"] = {"action_before_role": run(agent, "execute", False, None, details, None),
                                 "read_only_before_role": run(agent, "dge_role", False, stage, details, None)}
    return out


def s5_isolation_context(api):
    out = {"none": api.isolation_reference(None)}
    out["valid"] = api.isolation_reference({"mode": "container", "digest": "sha256:" + "i1" * 32, "image": "ignored"})
    out["valid_keeps_only_mode_and_digest"] = sorted(api.isolation_reference({"mode": "m", "digest": "d", "worker": {"x": 1}}))
    out["missing_digest"] = refused(lambda: api.isolation_reference({"mode": "container"}))
    out["empty_digest"] = refused(lambda: api.isolation_reference({"mode": "container", "digest": ""}))
    out["non_string_digest"] = {label: refused(lambda v=v: api.isolation_reference({"mode": "container", "digest": v})) for label, v in (("int", 7), ("none", None), ("list", ["d"]))}
    out["not_a_dict"] = {label: refused(lambda v=v: api.isolation_reference(v)) for label, v in (("list", []), ("text", "x"), ("int", 3))}
    out["empty_dict"] = refused(lambda: api.isolation_reference({}))
    out["missing_mode"] = seen(lambda: api.isolation_reference({"digest": "d"}))
    out["mode_is_not_checked"] = api.isolation_reference({"mode": None, "digest": "d"})
    out["context_without_isolation"] = api.role_context()
    out["context_with_none"] = api.role_context(None)
    out["context_with_isolation"] = api.role_context({"mode": "container", "digest": "sha256:" + "i1" * 32, "image": "x"})
    out["context_keys"] = list(api.role_context())
    out["context_refuses_a_digestless_isolation"] = refused(lambda: api.role_context({"mode": "container"}))
    out["context_instruction_is_static"] = api.role_context()["instruction"] == api.role_context({"mode": "m", "digest": "d"})["instruction"]
    return out


def s6_role_schema(api):
    out = {}
    for role in api.SCHEMAS:
        schema = api.role_schema(role, details_for(role))
        out[role] = {"digest": digest(schema), "equals_static": schema == api.SCHEMAS[role], "is_a_copy": schema is not api.SCHEMAS[role]
                     and schema["properties"] is not api.SCHEMAS[role]["properties"], "keys": list(schema["properties"]), "criterion_enum": role in api.CRITERION_ROLES}
    for role in api.CRITERION_ROLES:
        item = api.role_schema(role, details_for(role))["properties"]["findings"]["items"]["properties"]["criterion"]
        out[role]["criterion"] = item
    static_before = digest(api.SCHEMAS)
    out["criteria_order_kept"] = api.role_schema("attacker", {"acceptance_criteria": ["z", "a", "m"]})["properties"]["findings"]["items"]["properties"]["criterion"]
    out["single_criterion"] = api.role_schema("improvement_lead", {"acceptance_criteria": ["only"]})["properties"]["findings"]["items"]["properties"]["criterion"]
    out["two_executions_are_independent"] = (
        api.role_schema("attacker", {"acceptance_criteria": ["one"]})["properties"]["findings"]["items"]["properties"]["criterion"]["enum"],
        api.role_schema("attacker", {"acceptance_criteria": ["two"]})["properties"]["findings"]["items"]["properties"]["criterion"]["enum"])
    bad = {"missing": {}, "none": {"acceptance_criteria": None}, "empty": {"acceptance_criteria": []}, "not_a_list": {"acceptance_criteria": "crit"},
           "tuple": {"acceptance_criteria": ("a",)}, "duplicated": {"acceptance_criteria": ["a", "a"]}, "non_string": {"acceptance_criteria": ["a", 3]},
           "empty_string": {"acceptance_criteria": ["a", ""]}, "str_subclass": {"acceptance_criteria": [_Text("a")]},
           "none_member": {"acceptance_criteria": [None]}}
    out["refused_criteria"] = {role: {label: refused(lambda role=role, d=d: api.role_schema(role, d)) for label, d in bad.items()} for role in api.CRITERION_ROLES}
    out["other_roles_ignore_criteria"] = {role: api.role_schema(role, {"acceptance_criteria": []}) == api.SCHEMAS[role]
                                          for role in api.SCHEMAS if role not in api.CRITERION_ROLES}
    out["details_not_a_dict_for_a_criterion_role"] = seen(lambda: api.role_schema("attacker", None))
    out["details_not_a_dict_for_another_role"] = api.role_schema("arbiter", None) == api.SCHEMAS["arbiter"]
    out["unknown_role"] = seen(lambda: api.role_schema("nobody", {}))
    out["static_schemas_unmodified"] = digest(api.SCHEMAS) == static_before
    out["static_attacker_criterion_stays_text"] = api.SCHEMAS["attacker"]["properties"]["findings"]["items"]["properties"]["criterion"]
    return out


class _Text(str):
    pass


class Git:
    """LABELLED fake of the executor's git: scripted `rev-parse HEAD` answers and `status --porcelain` answer; records every call."""

    def __init__(self, heads=(BASE, BASE), status="", workspace_fault=None):
        self.heads, self.status, self.calls, self.workspace_fault = list(heads), status, [], workspace_fault

    def review_workspace(self, base, task_id):
        self.calls.append(["review_workspace", base, task_id])
        if self.workspace_fault is not None:
            raise self.workspace_fault
        return "/fake/review/" + str(task_id)

    def _git(self, *args, cwd=None):
        self.calls.append(["_git", list(args), cwd])
        if args == ("rev-parse", "HEAD"):
            return self.heads.pop(0) if self.heads else BASE
        if args == ("status", "--porcelain"):
            return self.status
        raise AssertionError("unexpected git call " + repr(args))


class Executor:
    """LABELLED fake of the executor: `git` and a `_run` recorder returning `result` (or raising `fault`)."""

    def __init__(self, git=None, result=None, fault=None):
        self.git, self.fault = git or Git(), fault
        self.result = {"output": {"ok": True}} if result is None else result
        self.runs = []

    def _run(self, *args, **kwargs):
        self.runs.append((args, kwargs))
        if self.fault is not None:
            raise self.fault
        return self.result


def task_for(role, agent=None, api=None, **details_overrides):
    details = details_for(role, **details_overrides)
    return {"id": "task-" + role, "agent": agent or api.AGENTS[role], "message": {"what": {"details": details}, "where": {"revision": details.get("base_revision")}}}


def run_role(api, role, executor=None, task=None, heartbeat=None):
    executor = executor or Executor()
    task = task or task_for(role, api=api)
    heartbeat = heartbeat or (lambda *a: None)
    outcome = seen(lambda: api.execute_role(executor, task, heartbeat))
    out = {"outcome": outcome["raised"] if "raised" in outcome else "returned", "git_calls": executor.git.calls, "run_calls": len(executor.runs)}
    if "raised" in outcome:
        out.update(message=outcome["message"], bases=outcome["bases"])
    else:
        out["result"] = outcome["returned"]
        out["result_is_the_run_result"] = outcome["returned"] is executor.result
    if executor.runs:
        args, kwargs = executor.runs[-1]
        details = task["message"]["what"]["details"]
        out["run_positional_count"] = len(args)
        out["run"] = {
            "agent": args[0], "task_id": args[1], "objective_digest": digest(args[2]), "objective_is_role_objective": args[2] == api.role_objective(role, details),
            "details_is_the_task_details": args[3] is details, "cwd": args[4], "schema_digest": digest(args[5]), "schema_is_role_schema": args[5] == api.role_schema(role, details),
            "read_only_flag": args[6], "heartbeat_is_passed": args[7] is heartbeat, "task_is_passed": args[8] is task,
            "kwargs": {k: (v if k != "delivery" else None) for k, v in sorted(kwargs.items())},
            "delivery_is_none": kwargs["delivery"] is None,
            "delivery_is_council_delivery": kwargs["delivery"] == api.council_delivery(role, details) if kwargs["delivery"] is not None else None,
            "delivery_digest": digest(kwargs["delivery"]) if kwargs["delivery"] is not None else None}
    return out


def s7_execute_role(api):
    out = {}
    v1 = {}
    for role in ("researcher", "proposer", "attacker", "arbiter", "dba"):
        v1[role] = run_role(api, role)
    out["v1_and_dba_roles_succeed"] = v1
    out["debate_roles_succeed"] = {role: run_role(api, role) for role in api.COUNCIL_DEBATE_ROLES}
    out["distinct_run_results"] = run_role(api, "proposer", Executor(result={"output": {"v": 1}, "role_execution": "overwritten", "keep": [1]}))
    out["a_provided_result_is_mutated_in_place"] = run_role(api, "arbiter", Executor(result={}))
    tuple_of_refusals = {}
    tuple_of_refusals["unknown_role"] = run_role(api, "proposer", task=_unknown(api))
    tuple_of_refusals["missing_role"] = run_role(api, "proposer", task=_without_role(api))
    tuple_of_refusals["wrong_agent"] = {role: run_role(api, role, task=task_for(role, agent="lead:somebody-else", api=api)) for role in ("researcher", "dba", "conductor")}
    tuple_of_refusals["agent_of_another_role"] = run_role(api, "proposer", task=task_for("proposer", agent=api.AGENTS["attacker"], api=api))
    mismatch = task_for("proposer", api=api)
    mismatch["message"]["where"]["revision"] = OTHER
    tuple_of_refusals["base_mismatch"] = run_role(api, "proposer", task=mismatch)
    tuple_of_refusals["no_where_revision"] = run_role(api, "proposer", task=_no_revision(api))
    tuple_of_refusals["checkout_not_at_base"] = run_role(api, "proposer", Executor(Git(heads=(OTHER, BASE))))
    tuple_of_refusals["modified_checkout"] = {s: run_role(api, "proposer", Executor(Git(status=s))) for s in (" M file.py", "?? new.txt", "x")}
    tuple_of_refusals["changed_commit"] = run_role(api, "proposer", Executor(Git(heads=(BASE, OTHER))))
    tuple_of_refusals["modified_and_changed_reports_the_modification"] = run_role(api, "proposer", Executor(Git(heads=(BASE, OTHER), status=" M f")))
    tuple_of_refusals["debate_role_modified_checkout"] = run_role(api, "conductor", Executor(Git(status=" M f")))
    tuple_of_refusals["debate_role_changed_commit"] = run_role(api, "research_lead", Executor(Git(heads=(BASE, OTHER))))
    out["refusals"] = tuple_of_refusals
    council = {}
    for role in api.COUNCIL_DEBATE_ROLES:
        council[role + "_missing_input_refused_before_the_provider"] = run_role(api, role, task=_task_without(api, role, "ssot"))
        council[role + "_over_budget_refused_before_the_provider"] = run_role(api, role, task=_task_with(api, role, packet={"claims": ["x" * 20000]}))
    council["research_lead_missing_dba_report"] = run_role(api, "research_lead", task=_task_without(api, "research_lead", "dba_report"))
    council["conductor_missing_improvement_proposal"] = run_role(api, "conductor", task=_task_without(api, "conductor", "improvement_proposal"))
    out["council_delivery_refusals"] = council
    out["details_without_a_role_objective_input"] = {role: run_role(api, role, task=_task_without(api, role, "packet")) for role in ("dba", "research_lead")}
    packet_digest = {}
    for label, value in (("missing", None), ("empty", ""), ("text", "sha256:x")):
        d = without(details_for("proposer"), "packet_digest") if label == "missing" else details_for("proposer", packet_digest=value)
        packet_digest["debate_" + label] = run_role(api, "proposer", task=_task_from(api, "proposer", d))
    packet_digest["debate_none_value"] = run_role(api, "attacker", task=_task_from(api, "attacker", details_for("attacker", packet_digest=None)))
    packet_digest["debate_zero_value"] = run_role(api, "arbiter", task=_task_from(api, "arbiter", details_for("arbiter", packet_digest=0)))
    packet_digest["researcher_without_digest_is_not_checked"] = run_role(api, "researcher", task=_task_from(api, "researcher", without(details_for("researcher"), "packet_digest")))
    packet_digest["dba_without_digest_is_not_checked"] = run_role(api, "dba", task=_task_from(api, "dba", without(details_for("dba"), "packet_digest")))
    out["packet_digest_check"] = packet_digest
    unmapped = {}
    unmapped["task_without_message"] = run_role(api, "proposer", task={"id": "t", "agent": "x"})
    unmapped["details_without_base_revision"] = run_role(api, "proposer", task=_task_from(api, "proposer", without(details_for("proposer"), "base_revision")))
    unmapped["details_not_a_dict"] = run_role(api, "proposer", task={"id": "t", "agent": "x", "message": {"what": {"details": []}, "where": {}}})
    unmapped["workspace_fault"] = run_role(api, "proposer", Executor(Git(workspace_fault=RuntimeError("no workspace"))))
    unmapped["run_fault"] = run_role(api, "proposer", Executor(fault=RuntimeError("provider failed")))
    unmapped["run_contract_error_is_not_remapped"] = run_role(api, "proposer", Executor(fault=api.ContractError("Provider refused")))
    unmapped["result_not_a_dict"] = run_role(api, "proposer", Executor(result=["not", "a", "dict"]))
    unmapped["agent_missing_from_task"] = run_role(api, "proposer", task={"id": "t", "message": task_for("proposer", api=api)["message"]})
    out["not_mapped"] = unmapped
    return out


def _unknown(api):
    task = task_for("proposer", api=api)
    task["message"]["what"]["details"]["role"] = "nobody"
    return task


def _without_role(api):
    task = task_for("proposer", api=api)
    del task["message"]["what"]["details"]["role"]
    return task


def _no_revision(api):
    task = task_for("proposer", api=api)
    task["message"]["where"] = {}
    return task


def _task_from(api, role, details):
    return {"id": "task-" + role, "agent": api.AGENTS[role], "message": {"what": {"details": details}, "where": {"revision": details.get("base_revision")}}}


def _task_without(api, role, *keys):
    return _task_from(api, role, without(details_for(role), *keys))


def _task_with(api, role, **overrides):
    return _task_from(api, role, details_for(role, **overrides))


BRANCH_COVERAGE = {
    "_object, _enum, _limited, _limits, _listed, _claim, _question (one return each)": "s1_tables.helpers",
    "role_objective return 1 (no PRODUCED section: the static text)": "s2_objective (researcher, proposer, attacker, arbiter, conductor, static_roles_ignore_details)",
    "role_objective require(isinstance(details, dict), 'Role details must be an object')": "s2_objective.details_not_an_object",
    "role_objective return 2 (the allowance for a producer)": "s2_objective (dba, research_lead, improvement_lead), missing_earlier_payload",
    "council_delivery require(role in COUNCIL_DEBATE_ROLES, ...)": "s3_council_delivery.not_a_debate_role",
    "council_delivery require(isinstance(details, dict) and details.get('role') == role, ...)": "s3_council_delivery.details_role_mismatch, details_not_an_object, details_without_role",
    "council_delivery require(not missing, 'Council delivery input missing: ...')": "s3_council_delivery.missing_one_input, missing_several_are_sorted",
    "council_delivery require(packet and dba_report objects)": "s3_council_delivery.packet_not_an_object, dba_report_not_an_object",
    "council_delivery admit_delivery(...) (the typed needs_scope_split overflow)": "s3_council_delivery.over_budget_packet, over_budget_dba_report, over_budget_proposals, over_budget_wrapper, overflow_type",
    "admitted_delivery require(action == 'dge_role' and read_only is True)": "s4_admitted_delivery.wrong_action, not_read_only",
    "admitted_delivery role from a dict delivery with a dict inline, else None": "s4_admitted_delivery.no_role_not_a_dict, no_role_inline_not_a_dict, no_role_in_inline",
    "admitted_delivery require(role in COUNCIL_DEBATE_ROLES, 'names no debate role')": "s4_admitted_delivery.role_not_a_debate_role",
    "admitted_delivery require(stage and agent agree)": "s4_admitted_delivery.stage_mismatch, agent_mismatch",
    "admitted_delivery require(delivery == council_delivery(role, details))": "s4_admitted_delivery.delivery_of_another_role, trimmed_inline, foreign_task_details, inflated_inline, edited_wrapper",
    "admitted_delivery return admit_delivery(...)": "s4_admitted_delivery (accepted per role)",
    "isolation_reference return 1 (None)": "s5_isolation_context.none",
    "isolation_reference require(dict with a non-empty str digest)": "s5_isolation_context.missing_digest, empty_digest, non_string_digest, not_a_dict, empty_dict",
    "isolation_reference return 2": "s5_isolation_context.valid",
    "role_context": "s5_isolation_context.context_*",
    "role_schema (non-criterion role)": "s6_role_schema (every role), other_roles_ignore_criteria",
    "role_schema require(criteria ...)": "s6_role_schema.refused_criteria",
    "role_schema criterion enum for the criterion roles": "s6_role_schema.attacker/improvement_lead criterion, criteria_order_kept, two_executions_are_independent",
    "execute_role require(role in AGENTS)": "s7_execute_role.refusals.unknown_role, missing_role",
    "execute_role require(task agent == AGENTS[role])": "s7_execute_role.refusals.wrong_agent, agent_of_another_role",
    "execute_role require(where.revision == base)": "s7_execute_role.refusals.base_mismatch, no_where_revision",
    "execute_role require(rev-parse HEAD == base) before the run": "s7_execute_role.refusals.checkout_not_at_base",
    "execute_role council_delivery for a debate role, else None": "s7_execute_role.debate_roles_succeed, v1_and_dba_roles_succeed, council_delivery_refusals",
    "execute_role require(not status --porcelain, 'modified its checkout')": "s7_execute_role.refusals.modified_checkout, debate_role_modified_checkout",
    "execute_role require(rev-parse HEAD == base) after the run": "s7_execute_role.refusals.changed_commit, debate_role_changed_commit",
    "execute_role if role in DEBATE_ROLES: require(packet_digest == (packet_digest or ''))": "s7_execute_role.packet_digest_check",
    "execute_role the role_execution block (input_policy for a delivery, else None)": "s7_execute_role.debate_roles_succeed, v1_and_dba_roles_succeed",
    "KeyError/other faults propagate unchanged (no except in the module)": "s7_execute_role.not_mapped",
}

M7_TESTS = {
    "tests/test_autonomous_roles.py (schema enums against the consumers, claim/question variants, objectives naming the finite values)": "s1_tables (the schema and objective digests; consumers are research.domain.dge and are goldened by research.dge)",
    "tests/test_autonomous_roles.py::test_finding_criterion_is_the_exact_pinned_plan_enum_per_execution": "s6_role_schema",
    "tests/test_council_*.py (council_delivery, admitted_delivery, role_context through the executor)": {"unreachable": "the executor is not part of this family; the pure functions and execute_role over a fake executor are s3, s4, s5, s7"},
}


def run(api) -> dict:
    result = {"s1_tables": s1_tables(api), "s2_objective": s2_objective(api), "s3_council_delivery": s3_council_delivery(api),
              "s4_admitted_delivery": s4_admitted_delivery(api), "s5_isolation_context": s5_isolation_context(api),
              "s6_role_schema": s6_role_schema(api), "s7_execute_role": s7_execute_role(api)}
    result["s8_m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = {name: len(result[name]) for name in ("s1_tables", "s2_objective", "s3_council_delivery", "s4_admitted_delivery",
                                                                      "s5_isolation_context", "s6_role_schema", "s7_execute_role")}
    return result
