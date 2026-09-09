"""Reuse a recorder format only; keep fresh workflow evidence local to this folder."""
from pathlib import Path

OUT = Path(__file__).resolve().parent
prior = OUT.parent / 'baldrix-gsd-templates-001/record_review.py'
text = prior.read_text(encoding='utf-8')
text = text.replace('baldrix-gsd-templates-001', 'baldrix-gsd-workflows-005')
text = text.replace('5acaeced22de71ae3eb8584643e00557762745c0', '31d5091407566d4988980485246ed031784203b2')
start = text.index('SCOPES = {')
end = text.index('\n\ndef sha(', start)
config = '''SCOPES = {
    'baldrix:get-shit-done/workflows:005': '0793c364d3a1426312c4800715fdd964ba23bbb7eeab42fd57b36649b4e184eb',
}
PRIMARY_RECEIPTS = [
    'b18c4d', 'b18c4d', '72f1d3', ['75ddc3', '44d13f'],
    ['44d13f', '7bcf14'], '4b255b', ['f0ece8', '36c571'],
]
# Every interval was freshly displayed and read; no prior semantic/body reuse.
SUPPORT = {
    'get-shit-done/bin/lib/uat.cjs': ([[1, 282]], ['trace', 'i06', 'i07'], ['f8e2a1', '1c6d19']),
    'get-shit-done/bin/lib/verify.cjs': ([[283, 399]], ['trace', 'i06'], ['f8e2a1']),
    'get-shit-done/bin/lib/init.cjs': ([[25, 48], [173, 226], [538, 695]], ['trace', 'i01', 'i02', 'i05', 'i07'], ['f8e2a1', '1c6d19', '77d214', '370e00', '7bcf14']),
    'get-shit-done/bin/lib/commands.cjs': ([[250, 348]], ['trace', 'i01', 'i05', 'i07'], ['f8e2a1']),
    'agents/kha-ui-checker.md': ([[153, 281]], ['trace', 'i01'], ['1c6d19']),
    'agents/kha-nyquist-auditor.md': ([[1, 171]], ['trace', 'i05'], ['1c6d19']),
    'agents/kha-ui-auditor.md': ([[330, 370], [447, 500]], ['trace', 'i02'], ['1c6d19']),
    'get-shit-done/bin/lib/core.cjs': ([[648, 686], [1303, 1342]], ['trace', 'zeus', 'i01', 'i07'], ['77d214']),
    'get-shit-done/bin/lib/config.cjs': ([[125, 150], [357, 405]], ['trace', 'i01', 'i05', 'i07'], ['77d214', 'db5f41']),
    'get-shit-done/workflows/execute-phase.md': ([[954, 1116]], ['trace', 'i06', 'i07'], ['77d214']),
    'get-shit-done/templates/VALIDATION.md': ([[1, 76]], ['trace', 'i05'], ['77d214']),
    'get-shit-done/templates/UAT.md': ([[1, 102]], ['trace', 'i07'], ['77d214']),
    'get-shit-done/bin/lib/phase.cjs': ([[652, 719], [899, 924]], ['trace', 'i06'], ['db5f41']),
    'get-shit-done/bin/gsd-tools.cjs': ([[450, 466], [540, 560], [725, 741], [785, 805]], ['trace', 'i05', 'i06', 'i07'], ['db5f41']),
    'get-shit-done/templates/phase-prompt.md': ([[603, 610]], ['trace', 'i06'], ['db5f41']),
    'agents/kha-ui-researcher.md': ([[75, 84], [99, 222], [314, 335]], ['trace', 'i01'], ['370e00']),
    'agents/kha-verifier.md': ([[494, 543]], ['trace', 'i06'], ['370e00']),
    'get-shit-done/templates/UI-SPEC.md': ([[1, 95]], ['trace', 'i01'], ['370e00']),
    'get-shit-done/templates/verification-report.md': ([[1, 37], [74, 114]], ['trace', 'i06', 'i07'], ['370e00', '7bcf14']),
    'skills/kha-spec-ui-phase/SKILL.md': ([[1, 57]], ['trace', 'i01'], ['db5f41']),
    'skills/kha-review-ui/SKILL.md': ([[1, 55]], ['trace', 'i02'], ['db5f41']),
    'skills/kha-revert-work/SKILL.md': ([[1, 61]], ['trace', 'i03'], ['db5f41']),
    'skills/kha-self-update/SKILL.md': ([[1, 59]], ['trace', 'i04'], ['db5f41']),
    'skills/kha-validate-nyquist-phase/SKILL.md': ([[1, 58]], ['trace', 'i05'], ['db5f41']),
    'skills/kha-verify-uat/SKILL.md': ([[1, 61]], ['trace', 'i07'], ['db5f41']),
}
'''
text = text[:start] + config + text[end:]
text = text.replace('range(1, 44)', 'range(1, 8)')
text = text.replace('== 43', '== 7').replace("'primary_files': 43", "'primary_files': 7")
text = text.replace('226301', '83538').replace('assert len(supports) == 27', 'assert len(supports) == 25')
text = text.replace(
    '43 template bodies read fresh. Template placeholders, commands, declared PASS and summary presence are not executed tests, actual human acceptance or deployment evidence.',
    '7 workflow bodies read fresh. Workflow declarations, helper static branches, text PASS and summary presence are not executed tests, actual human acceptance or deployment evidence.',
)
text = text.replace('template_contract_not_test_suite', 'workflow_declaration_not_executed_test_suite')
text = text.replace(
    'Fresh bounded direct template producer, workflow consumer, parser, schema and state authority trace; no original execution.',
    'Fresh bounded direct skill entry, workflow/agent consumer, helper/router/config/parser/template and state authority trace; no original execution.',
)
start = text.index("        'full_read_gap_repairs': {")
end = text.index('\n    }\n    write_json(\'verification.json\'', start)
text = text[:start] + '''        'full_read_gap_repairs': {},
        'search_only_not_body': ['0f54bb', 'b13c12', '7609ae', '2a6b55', '361b06'],
        'failed_read_not_counted': '7a6314 failed at line 2 with cp949 output encoding; complete successful fresh reads are f8e2a1 and 1c6d19.',
        'search_limits': 'No direct test bodies found in named identifier test/spec searches. Broad uat hits and truncated search output do not establish test absence. bin/install.js and update hook bodies were not obtained. No original tests ran.',
        'metadata_format_reuse': 'Previous recorder source format reused only; no prior source body or semantic finding reused.',
''' + text[end:]
text = text.replace(
    'Unlisted intervals, complete transitive consumer/config/test closure and actual template loader paths for copilot/debug-subagent/planner-subagent prompt files.',
    'Unlisted intervals, complete transitive consumer/config/test/hook closure, update installer and phase-manifest writer.',
)
text = text.replace(
    'Actual CJS UAT/human-heading parsing, template generation/select/validation/summary round trips and regression reproduction.',
    'Actual UAT/human-heading parser, empty-denominator helper, init path, update-target, cleanup and workflow-state observations.',
)
text = text.replace(
    'Session collector consent, privacy, retention and profile writer full closure; no collection performed.',
    'Human response identity, ambiguous response classification, interrupted batching, spec/scenario completeness and actual state consumers.',
)
text = text.replace("'review.md', 'record_review.py', 'files.json'", "'review.md', 'record_review.py', 'build_recorder.py', 'files.json'")
text = text.replace("'verification.json', 'record_review.py',", "'verification.json', 'record_review.py', 'build_recorder.py',")
(OUT / 'record_review.py').write_text(text, encoding='utf-8', newline='\n')
