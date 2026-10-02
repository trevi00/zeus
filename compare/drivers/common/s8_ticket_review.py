"""Shared S8 scenario steps (`intake.ticket_review`): M7 `adapters/ticket_review.py` (`render_ticket_review(review, packet_path)`: the
self-contained, inert human review page of a closure packet), characterized BEFORE the module moves (DESIGN-s8 §6 V11).

The module is one pure function over a `review` mapping (the shape `TicketLifecycle.review` returns: `ticket`, `packet`, `policy`,
`documents`, `packet_ref`, `time_status`) and a packet path; M7 `tests/test_ticket_review.py` has 7 tests, whose function-level
behaviour is mirrored here (each case labelled with its test name) and whose lifecycle-level refusals (stale ticket, corrupted
evidence, unmerged commit, the read-only CLI) are recorded as unreachable (they belong to `TicketLifecycle.review` / the ticket CLI, S10).

- **s1_page**: a full review rendered (the body from `<header>` on, plus the sha256 and size of the whole page), the humans/automation-only
  policy message (`test_review_cli_is_read_only_...` asserts `사람 승인 요구 없음`, `서명 기한`), every `time_status` message
  (`test_expired_packet_can_be_inspected_...`), an empty criteria/scope/signer list, the value types shown through `str()`, the page is deterministic
  and the review is never mutated.
- **s2_escaping**: `test_review_escapes_active_content_in_every_displayed_input` (markup in every displayed input: no `script`/`img`/`iframe`/
  `form`/`a`/`object`/`base` tag, no `on*` attribute, `&lt;script`, the CSP), quotes, apostrophes, ampersands and non-ASCII in every field, the packet path.
- **s3_preview**: `test_large_evidence_preview_is_bounded_and_truncation_visible` and
  `test_environment_preview_survives_exhausted_criterion_budget` (the 65536-byte per-document and 256 KiB total budgets, the notice, the
  environment document drawn FIRST, a multi-byte character cut at the budget, a repeated reference, the size line of the full document).
- **s4_malformed**: every missing key, wrong type, unknown `time_status`, out-of-range criterion index, signer without a role, non-JSON document and
  `NaN`, each as its exception type and message (a `StopIteration` inside the signer generator becomes a `RuntimeError`).

Layer: harness (never shipped)

This module never imports `codex_harness`: everything from the product arrives through `api`. Nothing here touches a file, a database or a
network; the reviews are built literals."""

from __future__ import annotations

import copy
import hashlib
import html
import re
from html.parser import HTMLParser

ENV = "sha256:" + "e1" * 32
EV1 = "sha256:" + "c1" * 32
EV2 = "sha256:" + "c2" * 32
PACKET_REF = "sha256:" + "9a" * 32
COMMIT = "a" * 40
FORBIDDEN_TAGS = {"script", "img", "iframe", "form", "a", "object", "base"}


def make(**over):
    review = {
        "ticket": {"id": "TKT-0001", "content": {
            "title": "Independent services", "problem": "Services share one failure domain.", "impact": "One outage stops every review.",
            "scope": ["split the queue", "split the store"], "acceptance_criteria": ["queue runs alone", "store runs alone"],
            "rollback": "Revert the merge commit."}},
        "packet": {"environment_ref": ENV, "criteria": [{"index": 0, "evidence_refs": [EV1]}, {"index": 1, "evidence_refs": [EV2]}],
                   "reason": "All criteria observed.", "revision": 2, "sequence": 3, "issued_at": "2026-09-22T00:00:00+00:00",
                   "expires_at": "2026-09-23T00:00:00+00:00", "solution_commit": COMMIT, "policy_commit": "b" * 40, "policy_hash": "sha256:" + "d4" * 32},
        "policy": {"required_human_signers": ["alice"], "required_signers": ["alice", "robot"],
                   "signers": [{"principal": "alice", "role": "owner"}, {"principal": "robot", "role": "automation"}]},
        "documents": {ENV: {"observed_at": "2026-09-22T00:00:01+00:00", "details": {"host": "ci"}},
                      EV1: {"observed_at": "2026-09-22T00:00:02+00:00", "details": {"queue": "ok"}},
                      EV2: {"observed_at": "2026-09-22T00:00:03+00:00", "details": {"store": "ok"}}},
        "packet_ref": PACKET_REF, "time_status": "recheck_at_close"}
    for path, value in over.items():
        node = review
        keys = path.split("__")
        for key in keys[:-1]:
            node = node[key]
        node[keys[-1]] = value
    return review


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attributes = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)


def body_of(page):
    return page.split("</style></head><body>", 1)[1]


def shape(page):
    """What is recorded of a page: its sha256 and size, and the markers whose counts the M7 tests read."""
    pres = [html.unescape(p) for p in re.findall(r"<pre>(.*?)</pre>", page, re.S)]
    return {"sha256": hashlib.sha256(page.encode("utf-8", "surrogatepass")).hexdigest(), "bytes": len(page.encode("utf-8", "surrogatepass")), "chars": len(page),
            "truncated_notices": page.count("미리보기 일부만 표시됨"), "details": page.count("<details>"), "criteria": page.count('class="criterion"'),
            "pre_bytes": [len(p.encode("utf-8", "surrogatepass")) for p in pres], "pre_tails": [p[-24:] for p in pres[:-1]]}


def render(api, review, path="packet.json", full=True):
    before = copy.deepcopy(review)
    try:
        page = api.render_ticket_review(review, path)
    except BaseException as exc:  # noqa: BLE001 - the refusal type and message are the observation
        return {"outcome": "refused", "type": type(exc).__name__, "message": str(exc), "review_unchanged": review == before}
    out = {"outcome": "rendered", "is_str": type(page) is str, "review_unchanged": review == before, **shape(page)}
    if full:
        out["body"] = body_of(page)
    return out


def s1_page(api):
    out = {"full_review": render(api, make())}
    out["same_review_twice_is_identical"] = api.render_ticket_review(make(), "p.json") == api.render_ticket_review(make(), "p.json")
    page = api.render_ticket_review(make(), "p.json")
    out["document_frame"] = {"starts_with_doctype": page.startswith("<!doctype html>\n<html lang=\"ko\">"), "ends_with": page[-22:],
                             "csp_present": "script-src 'none'" in page and "default-src 'none'" in page and "form-action 'none'" in page,
                             "title": re.search(r"<title>(.*?)</title>", page).group(1), "style_bytes": len(page.split("<style>")[1].split("</style>")[0])}
    out["test_review_cli_reads: page names the ticket text and the packet_ref, no human approval, the signing deadline"] = {
        "automation_only": render(api, make(policy__required_human_signers=[], policy__required_signers=["robot"])),
        "mentions": [needle in page for needle in ("Independent services", PACKET_REF, "서명 기한")]}
    out["human_signers_are_joined"] = render(api, make(policy__required_human_signers=["alice", "bob"], policy__required_signers=["alice"]))
    out["time_status"] = {status: render(api, make(time_status=status)) for status in ("expired", "future", "recheck_at_close")}
    out["test_expired_packet_can_be_inspected"] = "서명 기한이 지났습니다" in api.render_ticket_review(make(time_status="expired"), "packet.json")
    out["empty_lists"] = {"scope": render(api, make(ticket__content__scope=[])), "criteria": render(api, make(packet__criteria=[])),
                          "signers": render(api, make(policy__required_signers=[])), "evidence_refs": render(api, make(packet__criteria=[{"index": 0, "evidence_refs": []}]))}
    out["values_pass_through_str"] = render(api, make(ticket__id=None, packet__revision=7, packet__sequence=None, packet__issued_at=12, packet__expires_at=1.5,
                                                    packet__solution_commit=b"x", packet__reason=["a", "b"], packet_ref=("t",)))
    out["negative_criterion_index_wraps"] = render(api, make(packet__criteria=[{"index": -1, "evidence_refs": [EV1]}]))
    out["repeated_evidence_reference"] = render(api, make(packet__criteria=[{"index": 0, "evidence_refs": [EV1, EV1]}]))
    out["a_review_of_a_different_ticket_changes_only_its_own_fields"] = render(api, make(ticket__id="TKT-0002", ticket__content__title="Other"), full=False)
    out["extra_keys_are_ignored"] = render(api, make(extra={"x": 1}, ticket__extra=1, packet__extra=2, policy__extra=3), full=False)
    out["same_page_for_equal_reviews"] = render(api, make(), full=False) == render(api, make(), full=False)
    return out


def s2_escaping(api):
    payload = '<script src="https://invalid.example/x"></script><img src=x onerror="alert(1)">'
    review = make(ticket__content__title=payload, ticket__content__problem=payload, ticket__content__impact=payload, ticket__content__scope=[payload],
                  ticket__content__acceptance_criteria=[payload, payload], ticket__content__rollback=payload, ticket__id=payload,
                  packet__reason=payload, packet__solution_commit=payload, packet__policy_commit=payload, packet__policy_hash=payload,
                  packet__issued_at=payload, packet__expires_at=payload, packet_ref=payload, policy__required_human_signers=[payload],
                  policy__required_signers=[payload], policy__signers=[{"principal": payload, "role": payload}])
    review["documents"][ENV]["observed_at"] = payload
    review["documents"][ENV]["details"] = {payload: payload}
    page = api.render_ticket_review(review, payload)
    parser = Tags()
    parser.feed(page)
    out = {"test_review_escapes_active_content_in_every_displayed_input": {
        "forbidden_tags_present": sorted(set(parser.tags) & FORBIDDEN_TAGS), "on_attributes": [n for n, _ in parser.attributes if n.startswith("on")],
        "escaped_script_present": "&lt;script" in page, "csp_script_none": "script-src 'none'" in page,
        "unescaped_markup_count": page.count("<script") + page.count("<img"), "tags": sorted(set(parser.tags)), "attribute_names": sorted({n for n, _ in parser.attributes}),
        "page": shape(page)}}
    out["hostile_page_body"] = render(api, review, payload)
    text = "He said \"hi\" & 'bye' <b>bold</b> 한글 ünïcode 😀 \x00 \t \\ /"
    out["quotes_ampersands_non_ascii_in_every_field"] = render(api, make(
        ticket__content__title=text, ticket__content__problem=text, ticket__content__impact=text, ticket__content__scope=[text],
        ticket__content__acceptance_criteria=[text, text], ticket__content__rollback=text, packet__reason=text, packet_ref=text), path=text)
    out["packet_path_variants"] = {label: render(api, make(), path=value, full=False) | {"path_in_page": html.escape(str(value), quote=True) in api.render_ticket_review(make(), value)}
                                   for label, value in (("windows", "C:\\Users\\x\\packet.json"), ("quote", 'a"b'), ("apostrophe", "a'b"), ("angle", "<p>"),
                                                        ("none", None), ("int", 7), ("empty", ""), ("korean", "패킷.json"), ("long", "p" * 5000))}
    doc = {"observed_at": "t", "details": {"note": "한글 \"q\" 'a' <i>x</i> & \u00e9 😀", "n": [1, 2.5, None, True], "nested": {"k": "<v>"}}}
    out["document_preview_is_escaped_and_not_ascii_escaped"] = render(api, make(documents={ENV: doc, EV1: doc, EV2: doc}))
    out["observed_at_is_escaped"] = render(api, make(documents={ENV: {"observed_at": "<b>&\"'"}, EV1: {"observed_at": "x"}, EV2: {"observed_at": "y"}}), full=False)
    out["title_with_newlines_is_kept"] = render(api, make(ticket__content__title="line1\nline2\r\n<tab>\t"), full=False)
    return out


def big(value, n):
    return {"observed_at": "2026-09-22T00:00:00+00:00", "details": {"large": value * n}}


def s3_preview(api):
    out = {}
    env = make()
    env["documents"][ENV] = big("<", 300000)
    out["test_large_evidence_preview_is_bounded_and_truncation_visible"] = render(api, env, full=False) | {
        "environment_ref_in_page": ENV in api.render_ticket_review(env, "packet.json"),
        "under_400000": len(api.render_ticket_review(env, "packet.json").encode("utf-8")) < 400000}
    review = make()
    criterion = review["packet"]["criteria"][0]
    criterion["evidence_refs"] = [EV1] * 5
    review["documents"][EV1]["details"] = {"large": "x" * 100000}
    review["documents"][ENV]["details"] = {"environment_marker": "ENVIRONMENT_STILL_VISIBLE"}
    page = api.render_ticket_review(review, "packet.json")
    out["test_environment_preview_survives_exhausted_criterion_budget"] = render(api, review, full=False) | {
        "marker_visible": "ENVIRONMENT_STILL_VISIBLE" in page, "notice_shown": "미리보기 일부만 표시됨" in page}
    out["a_document_just_under_the_per_document_budget"] = render(api, make(documents={ENV: big("a", 65000), EV1: big("b", 10), EV2: big("c", 10)}), full=False)
    out["a_document_exactly_at_the_per_document_budget"] = {n: render(api, make(documents={ENV: big("a", n), EV1: big("b", 10), EV2: big("c", 10)}), full=False)
                                                           for n in (65450, 65480, 65481, 65482, 65483, 65484, 65600)}
    out["a_second_document_after_the_first_used_the_budget"] = render(api, make(documents={ENV: big("a", 70000), EV1: big("b", 70000), EV2: big("c", 70000)}), full=False)
    out["the_total_budget_is_exhausted_after_four_documents"] = render(api, make(
        packet__criteria=[{"index": 0, "evidence_refs": [EV1] * 6}], documents={ENV: big("e", 70000), EV1: big("a", 70000), EV2: big("c", 10)}), full=False)
    out["environment_first_then_criteria_in_order"] = render(api, make(
        packet__criteria=[{"index": 1, "evidence_refs": [EV2, EV1]}, {"index": 0, "evidence_refs": [EV1]}]), full=False) | {
        "order": [m.group(0) for m in re.finditer(r"sha256:(?:e1|c1|c2)(?:e1|c1|c2)", api.render_ticket_review(make(
            packet__criteria=[{"index": 1, "evidence_refs": [EV2, EV1]}, {"index": 0, "evidence_refs": [EV1]}]), "p"))]}
    # three bytes per character: the budget cuts a character, the partial bytes are dropped (errors="ignore")
    out["multi_byte_text_cut_at_the_budget"] = {label: render(api, make(documents={ENV: big(ch, n), EV1: big("b", 10), EV2: big("c", 10)}), full=False)
                                                for label, ch, n in (("hangul", "한", 40000), ("emoji", "😀", 40000), ("mixed_accent", "é", 40000))}
    out["every_document_small_leaves_no_notice"] = render(api, make(), full=False)["truncated_notices"]
    out["the_size_line_counts_the_whole_document_not_the_preview"] = [
        m for m in re.findall(r"증거 내용 보기 · ([\d,]+) bytes", api.render_ticket_review(env, "packet.json"))]
    out["a_document_with_a_huge_scalar_key"] = render(api, make(documents={ENV: {"observed_at": "t", "k" * 70000: 1}, EV1: big("b", 1), EV2: big("c", 1)}), full=False)
    return out


class NotJson:
    pass


def _no(api, **over):
    return render(api, make(**over), full=False)


def s4_malformed(api):
    out = {}
    base = make()
    removed = {}
    for path in ("ticket", "packet", "policy", "documents", "packet_ref", "time_status", "ticket__id", "ticket__content", "ticket__content__title",
                 "ticket__content__problem", "ticket__content__impact", "ticket__content__scope", "ticket__content__acceptance_criteria",
                 "ticket__content__rollback", "packet__environment_ref", "packet__criteria", "packet__reason", "packet__revision", "packet__sequence",
                 "packet__issued_at", "packet__expires_at", "packet__solution_commit", "packet__policy_commit", "packet__policy_hash",
                 "policy__required_human_signers", "policy__required_signers", "policy__signers"):
        review = copy.deepcopy(base)
        node, keys = review, path.split("__")
        for key in keys[:-1]:
            node = node[key]
        del node[keys[-1]]
        removed[path] = render(api, review, full=False)
    out["missing_key"] = removed
    for label, bad in (("not_a_mapping_none", None), ("list", []), ("str", "review"), ("empty_dict", {}), ("int", 3)):
        out["review_" + label] = render(api, bad, full=False)
    out["wrong_types"] = {
        "ticket_none": _no(api, ticket=None), "content_list": _no(api, ticket__content=[]), "criteria_none": _no(api, packet__criteria=None),
        "criteria_int": _no(api, packet__criteria=3), "scope_none": _no(api, ticket__content__scope=None), "scope_int": _no(api, ticket__content__scope=7),
        "scope_str_is_iterated_by_character": _no(api, ticket__content__scope="ab"), "signers_none": _no(api, policy__signers=None),
        "required_signers_str_iterates_characters": _no(api, policy__required_signers="alice"), "human_signers_none": _no(api, policy__required_human_signers=None),
        "human_signers_str": _no(api, policy__required_human_signers="alice"), "human_signers_with_non_str": _no(api, policy__required_human_signers=["a", 1]),
        "documents_list": _no(api, documents=[]), "document_is_list": _no(api, documents={ENV: [], EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
        "document_is_none": _no(api, documents={ENV: None, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
        "document_without_observed_at": _no(api, documents={ENV: {"details": 1}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
        "criterion_is_a_list": _no(api, packet__criteria=[[0, [EV1]]]), "criterion_without_index": _no(api, packet__criteria=[{"evidence_refs": [EV1]}]),
        "criterion_without_evidence_refs": _no(api, packet__criteria=[{"index": 0}]), "criterion_index_is_str": _no(api, packet__criteria=[{"index": "0", "evidence_refs": []}]),
        "criterion_index_is_float": _no(api, packet__criteria=[{"index": 0.0, "evidence_refs": []}]), "criterion_index_is_true": _no(api, packet__criteria=[{"index": True, "evidence_refs": []}]),
        "evidence_refs_none": _no(api, packet__criteria=[{"index": 0, "evidence_refs": None}]), "criteria_item_none": _no(api, packet__criteria=[None]),
        "time_status_none": _no(api, time_status=None), "time_status_list_is_unhashable": _no(api, time_status=[]),
        "environment_ref_unhashable": _no(api, packet__environment_ref=["x"]), "revision_missing_format_is_plain": _no(api, packet__revision=None),
        "acceptance_criteria_none": _no(api, ticket__content__acceptance_criteria=None), "acceptance_criteria_dict": _no(api, ticket__content__acceptance_criteria={0: "x", 1: "y"}),
        "title_non_str_is_str_converted": _no(api, ticket__content__title=3)}
    out["unknown_time_status"] = {s: _no(api, time_status=s) for s in ("", "Expired", "closed", "RECHECK_AT_CLOSE")}
    out["criterion_index_out_of_range"] = {n: _no(api, packet__criteria=[{"index": n, "evidence_refs": []}]) for n in (2, 5, -3, 100)}
    out["a_required_signer_without_a_role_entry"] = _no(api, policy__required_signers=["alice", "nobody"])
    out["a_signer_entry_without_principal"] = _no(api, policy__signers=[{"role": "x"}])
    out["a_signer_entry_without_role"] = _no(api, policy__signers=[{"principal": "alice"}, {"principal": "robot", "role": "r"}])
    out["a_signer_with_two_roles_uses_the_first"] = render(api, make(policy__signers=[{"principal": "alice", "role": "first"}, {"principal": "alice", "role": "second"},
                                                                                       {"principal": "robot", "role": "automation"}]), full=False)
    out["an_evidence_reference_not_in_documents"] = _no(api, packet__criteria=[{"index": 0, "evidence_refs": ["sha256:missing"]}])
    out["the_environment_reference_not_in_documents"] = _no(api, packet__environment_ref="sha256:missing")
    out["non_json_document"] = {"set": _no(api, documents={ENV: {"observed_at": "t", "details": {1, 2}}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "object": _no(api, documents={ENV: {"observed_at": "t", "details": NotJson()}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "bytes": _no(api, documents={ENV: {"observed_at": "t", "details": b"x"}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "nan": _no(api, documents={ENV: {"observed_at": "t", "details": float("nan")}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "infinity": _no(api, documents={ENV: {"observed_at": "t", "details": float("inf")}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "tuple_key": _no(api, documents={ENV: {"observed_at": "t", "details": {(1, 2): 1}}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "int_keys_are_stringified": _no(api, documents={ENV: {"observed_at": "t", "details": {1: "a", 2: "b"}}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "lone_surrogate": _no(api, documents={ENV: {"observed_at": "t", "details": "\ud800"}, EV1: {"observed_at": "t"}, EV2: {"observed_at": "t"}}),
                                "lone_surrogate_in_title": _no(api, ticket__content__title="\ud800")}
    return out


BRANCH_COVERAGE = {
    "render_ticket_review: esc (html.escape(str(value), quote=True))": "s2_escaping (every field, the quotes, non-ASCII), s1_page.values_pass_through_str",
    "document: the preview loop within the per-document and total budgets": "s3_preview (the budgets, the exact cut, the total exhausted, a repeated reference)",
    "document: clipped -> the notice; not clipped -> no notice": "s3_preview.every_document_small_leaves_no_notice, s1_page.full_review",
    "document: the multi-byte cut (errors='ignore')": "s3_preview.multi_byte_text_cut_at_the_budget",
    "document: ref not in documents / value without observed_at / not a mapping": "s4_malformed.an_evidence_reference_not_in_documents, wrong_types",
    "humans empty / non-empty": "s1_page.test_review_cli_reads, human_signers_are_joined",
    "signers: next() without a match (StopIteration inside the generator)": "s4_malformed.a_required_signer_without_a_role_entry",
    "criteria rows (the index, the evidence refs)": "s1_page.full_review, empty_lists, negative_criterion_index_wraps; s4_malformed.criterion_index_out_of_range",
    "time_message: expired / future / recheck_at_close / any other (KeyError)": "s1_page.time_status; s4_malformed.unknown_time_status",
    "the page template (CSP, header, grid, sections, the signing identity, the exact JSON)": "s1_page.full_review.body, s1_page.document_frame",
    "canonical(value) / canonical(packet) (byte counts and the exact signing JSON)": "s1_page.full_review.body; s4_malformed.non_json_document",
}

M7_TESTS = {
    "tests/test_ticket_review.py::test_review_cli_is_read_only_and_preserves_canonical_signing_file": {
        "unreachable": "the ticket CLI, the artifact store and the lifecycle (S10); the page contents it asserts are s1_page.test_review_cli_reads"},
    "tests/test_ticket_review.py::test_review_escapes_active_content_in_every_displayed_input": "s2_escaping.test_review_escapes_active_content_in_every_displayed_input",
    "tests/test_ticket_review.py::test_expired_packet_can_be_inspected_but_cannot_be_closed": {
        "rendered": "s1_page.test_expired_packet_can_be_inspected", "unreachable": "the close refusal belongs to TicketLifecycle.close (S10)"},
    "tests/test_ticket_review.py::test_review_rejects_stale_ticket_and_corrupted_evidence": {"unreachable": "TicketLifecycle.review (S10), not the renderer"},
    "tests/test_ticket_review.py::test_large_evidence_preview_is_bounded_and_truncation_visible": "s3_preview.test_large_evidence_preview_is_bounded_and_truncation_visible",
    "tests/test_ticket_review.py::test_review_rejects_an_existing_unmerged_solution_commit": {"unreachable": "TicketLifecycle.review over a real git object (S10)"},
    "tests/test_ticket_review.py::test_environment_preview_survives_exhausted_criterion_budget": "s3_preview.test_environment_preview_survives_exhausted_criterion_budget",
}


def run(api) -> dict:
    result = {"s1_page": s1_page(api), "s2_escaping": s2_escaping(api), "s3_preview": s3_preview(api), "s4_malformed": s4_malformed(api)}
    result["s5_m7_tests"] = M7_TESTS
    result["branch_coverage"] = BRANCH_COVERAGE
    result["cases_per_group"] = {name: len(result[name]) for name in ("s1_page", "s2_escaping", "s3_preview", "s4_malformed")}
    return result
