"""Shared S8 scenario steps (`research.autonomous_evidence`): M7 `adapters/autonomous_evidence.py` (`EvidenceUnavailable`,
`ExecutionEvidence.document`: the execution artifact behind an `execution_ref` and the mapping of every store failure to a fixed code),
characterized BEFORE the module moves (DESIGN-s8 §6 V11; the branch table `branch-table-research.txt` section
`adapters/autonomous_evidence.py`: every raise and every except of the module is covered, see `BRANCH_COVERAGE`).

- **s1_exception**: the message `"execution evidence " + code`, `reason_code`, the `ContractError` base, no other state.
- **s2_document**: a success returns the store's document unchanged (the very object), the reference passed to the store unchanged, a
  non-`str` reference refused before the store is asked.
- **s3_failures**: every store failure and its single outcome (code, message, type of `__cause__`, `__suppress_context__`, the
  reference as the store saw it), the `FileNotFoundError` branch that precedes the `OSError` one, the `ContractError` messages (all
  `evidence_corrupt`: the `ContractError` except is shadowed by the `ValueError` one) and the exceptions outside the mapping that propagate unchanged.

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. The `artifacts` store is a LABELLED fake
(M7's is `FileArtifacts`, whose errors are scripted here by type and message); nothing here touches a file, a database or a network."""

from __future__ import annotations

UNSET = object()
DOCUMENT = {"answer": "ok", "stage": "executed", "nested": {"k": [1, 2]}}
REF = "sha256:" + "ab" * 32


class Artifacts:
    """LABELLED fake of `FileArtifacts.document(ref)`: records the references it was asked for, then returns `result` or raises
    `fault`."""

    def __init__(self, result=DOCUMENT, fault=None):
        self.result, self.fault, self.asked = result, fault, []

    def document(self, ref):
        self.asked.append(ref)
        if self.fault is not None:
            raise self.fault
        return self.result


def name_of(value):
    return None if value is None else type(value).__name__


def drive(api, reference=REF, fault=None, result=DOCUMENT):
    artifacts = Artifacts(result, fault)
    port = api.ExecutionEvidence(artifacts)
    out = {"store_is_kept": port.artifacts is artifacts}
    try:
        document = port.document(reference)
    except api.EvidenceUnavailable as exc:
        out.update(
            outcome="refused", code=exc.reason_code, message=str(exc), args=list(exc.args), is_contract_error=isinstance(exc, api.ContractError),
            cause_type=name_of(exc.__cause__), cause_is_the_fault=exc.__cause__ is fault and fault is not None,
            context_type=name_of(exc.__context__), suppress_context=exc.__suppress_context__)
    except BaseException as exc:  # noqa: BLE001 - what is NOT mapped is part of the observation
        out.update(outcome="propagated", type=type(exc).__name__, message=str(exc), is_the_fault=exc is fault,
                   is_evidence_unavailable=isinstance(exc, api.EvidenceUnavailable), cause_type=name_of(exc.__cause__),
                   context_type=name_of(exc.__context__))
    else:
        out.update(outcome="returned", is_the_stored_object=document is result, document=document)
    out["asked"] = [repr(r) for r in artifacts.asked]
    out["asked_the_reference_unchanged"] = len(artifacts.asked) == 1 and artifacts.asked[0] is reference
    return out


class FileNotFound(FileNotFoundError):
    pass


class Unreadable(OSError):
    pass


def s1_exception(api):
    out = {}
    for code in ("evidence_missing", "evidence_corrupt", "evidence_invalid", "", "anything else", "x" * 3):
        exc = api.EvidenceUnavailable(code)
        out["code_" + (code.replace(" ", "_") or "empty")] = {
            "message": str(exc), "args": list(exc.args), "reason_code": exc.reason_code, "is_contract_error": isinstance(exc, api.ContractError),
            "is_value_error": isinstance(exc, ValueError), "is_exception": isinstance(exc, Exception), "repr": repr(exc),
            "dict_keys": sorted(vars(exc)), "cause_is_none": exc.__cause__ is None, "context_is_none": exc.__context__ is None}
    out["mro"] = [c.__name__ for c in api.EvidenceUnavailable.__mro__]
    out["module_attribute"] = api.EvidenceUnavailable.__name__
    out["raises_and_catches_as_a_contract_error"] = _catch_as_contract_error(api)
    out["one_positional_argument_only"] = _arity(api)
    out["non_string_code_is_a_type_error"] = _non_string_code(api)
    return out


def _catch_as_contract_error(api):
    try:
        raise api.EvidenceUnavailable("evidence_invalid")
    except api.ContractError as exc:
        return [type(exc).__name__, str(exc)]


def _arity(api):
    out = {}
    for label, call in (("none", lambda: api.EvidenceUnavailable()), ("two", lambda: api.EvidenceUnavailable("a", "b")),
                        ("keyword", lambda: api.EvidenceUnavailable(reason_code="evidence_missing"))):
        try:
            exc = call()
            out[label] = ["built", str(exc), exc.reason_code]
        except TypeError as exc:
            out[label] = ["TypeError"]
    return out


def _non_string_code(api):
    out = {}
    for label, value in (("none", None), ("int", 3), ("bytes", b"x")):
        try:
            api.EvidenceUnavailable(value)
            out[label] = "built"
        except TypeError:
            out[label] = "TypeError"
    return out


def s2_document(api):
    out = {"returns_the_document": drive(api)}
    out["returns_an_empty_document"] = drive(api, result={})
    out["returns_a_non_dict_unchanged"] = drive(api, result=["not", "a", "dict"])
    out["returns_none_unchanged"] = drive(api, result=None)
    out["reference_passed_through_unchanged"] = drive(api, reference="  odd ref/with spaces ")
    out["empty_string_reference_reaches_the_store"] = drive(api, reference="")
    out["a_str_subclass_reaches_the_store"] = drive(api, reference=_Ref("sha256:subclass"))
    refused = {}
    for label, ref in (("none", None), ("int", 7), ("bytes", b"sha256:abc"), ("bytearray", bytearray(b"x")), ("list", ["a"]),
                       ("dict", {"a": 1}), ("float", 1.5), ("true", True), ("tuple", ("a",)), ("object", object)):
        refused[label] = drive(api, reference=ref)
    out["non_str_reference_is_missing_without_asking_the_store"] = refused
    out["non_str_reference_has_no_chain"] = all(
        r["outcome"] == "refused" and r["code"] == "evidence_missing" and r["cause_type"] is None and r["context_type"] is None
        and r["asked"] == [] for r in refused.values())
    out["a_store_fault_is_not_consulted_for_a_non_str_reference"] = drive(api, reference=None, fault=RuntimeError("never raised"))
    return out


class _Ref(str):
    pass


def s3_failures(api):
    from_contract = lambda text: api.ContractError(text)  # noqa: E731

    class Modified(api.ContractError):
        pass

    out = {}
    missing = {"file_not_found": FileNotFoundError(2, "No such file"), "file_not_found_subclass": FileNotFound("gone"),
               "file_not_found_with_message": FileNotFoundError("sha256:" + "00" * 32)}
    out["missing"] = {label: drive(api, fault=exc) for label, exc in missing.items()}
    corrupt = {"os_error": OSError("disk"), "permission_error": PermissionError(13, "denied"), "is_a_directory": IsADirectoryError("dir"),
               "os_error_subclass": Unreadable("reset"), "timeout_error": TimeoutError("slow"), "value_error": ValueError("bad json"),
               "json_like_value_error": ValueError("Expecting value: line 1 column 1 (char 0)"),
               "unicode_decode_error": UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
               "unicode_error_subclass_of_value_error": UnicodeDecodeError("ascii", b"\xc3", 0, 1, "ordinal not in range")}
    out["corrupt"] = {label: drive(api, fault=exc) for label, exc in corrupt.items()}
    contracts = {
        "modified": "Artifact modified: sha256:" + "ab" * 32, "modified_lowercase_word_inside": "The artifact was modified on disk",
        "modified_uppercase_is_not_matched": "Artifact MODIFIED", "invalid_reference": "Invalid artifact reference",
        "object_required": "Evidence document must be an object", "unrelated": "something else entirely", "empty_message": "",
        "modified_in_the_middle": "x modified y", "unmodified_contains_the_word": "unmodified"}
    out["contract_errors"] = {label: drive(api, fault=from_contract(text)) for label, text in contracts.items()}
    # `ContractError` is a `ValueError`, so the `(OSError, ValueError, UnicodeDecodeError)` except precedes the `ContractError` one: every
    # `ContractError` (whatever its message) is `evidence_corrupt` and `evidence_invalid` is never produced by M7.
    out["contract_error_is_a_value_error"] = issubclass(api.ContractError, ValueError)
    out["evidence_invalid_is_never_produced"] = all(r["code"] == "evidence_corrupt" for r in out["contract_errors"].values())
    out["contract_error_subclass_is_mapped_by_message"] = drive(api, fault=Modified("Artifact modified"))
    out["an_evidence_unavailable_from_the_store_is_remapped"] = drive(api, fault=api.EvidenceUnavailable("evidence_missing"))
    out["propagated"] = {label: drive(api, fault=exc) for label, exc in {
        "key_error": KeyError("k"), "runtime_error": RuntimeError("boom"), "type_error": TypeError("t"), "attribute_error": AttributeError("a"),
        "assertion_error": AssertionError("x"), "lookup_error": LookupError("l"), "keyboard_interrupt": KeyboardInterrupt(),
        "stop_iteration": StopIteration()}.items()}
    out["a_raising_document_call_reference_is_unchanged"] = drive(api, reference="ref-A", fault=OSError("x"))
    out["every_refusal_is_a_fixed_code"] = sorted({(r["code"], r["message"]) for group in ("missing", "corrupt", "contract_errors")
                                                   for r in out[group].values() if r["outcome"] == "refused"})
    out["every_mapped_refusal_chains_from_the_fault"] = all(
        r["cause_is_the_fault"] and r["suppress_context"] and r["context_type"] == r["cause_type"]
        for group in ("missing", "corrupt", "contract_errors") for r in out[group].values())
    return out


BRANCH_COVERAGE = {
    "EvidenceUnavailable.__init__": "s1_exception (every code, the arity, the base class)",
    "ExecutionEvidence.__init__": "s2_document.returns_the_document.store_is_kept",
    "ExecutionEvidence.document raise EvidenceUnavailable('evidence_missing') (non-str reference)": "s2_document.non_str_reference_is_missing_without_asking_the_store",
    "ExecutionEvidence.document except FileNotFoundError -> raise EvidenceUnavailable('evidence_missing')": "s3_failures.missing",
    "ExecutionEvidence.document except (OSError, ValueError, UnicodeDecodeError) -> raise EvidenceUnavailable('evidence_corrupt')": "s3_failures.corrupt",
    "ExecutionEvidence.document except ContractError -> raise EvidenceUnavailable(...)": "s3_failures.contract_errors: UNREACHABLE in M7 (ContractError is a ValueError, caught by the preceding except), so every ContractError message is evidence_corrupt; recorded as contract_error_is_a_value_error, evidence_invalid_is_never_produced",
    "ExecutionEvidence.document calls self.artifacts.document": "s2_document.returns_the_document, reference_passed_through_unchanged",
    "an exception outside the three excepts propagates": "s3_failures.propagated",
}

M7_TESTS = {
    "tests/test_research_recovery.py (ExecutionEvidence over an empty LABELLED store: no such artifact)": "s3_failures.missing",
    "tests/test_autonomous.py (EvidenceUnavailable('evidence_corrupt') as the FileArtifacts-backed port raises)": "s1_exception, s3_failures.corrupt",
    "tests/test_continuation_research.py (the port is replaced by a forbidden double)": {"unreachable": "a monkeypatch of the module attribute; the port itself is s2_document"},
}


def run(api) -> dict:
    result = {"s1_exception": s1_exception(api), "s2_document": s2_document(api), "s3_failures": s3_failures(api)}
    result["s4_m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = {name: len(result[name]) for name in ("s1_exception", "s2_document", "s3_failures")}
    return result
