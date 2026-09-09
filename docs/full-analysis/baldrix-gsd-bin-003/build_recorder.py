"""Create this folder's recorder from the previous metadata format, not findings."""
from pathlib import Path

OUT = Path(__file__).resolve().parent
prior = OUT.parent / 'baldrix-gsd-templates-001/record_review.py'
text = prior.read_text(encoding='utf-8')
text = text.replace('baldrix-gsd-templates-001', 'baldrix-gsd-bin-003')
start = text.index('SCOPES = {')
end = text.index('\n\ndef sha(', start)
config = '''SCOPES = {
    'baldrix:get-shit-done/bin:003': 'efd1cb12da5b31c451989c5c0c2f4af49269e667efffa9dd618dd92b688c3522',
}
PRIMARY_RECEIPTS = [
    ['e34c05', '2cbe62'], '2cbe62', 'e34c05', '060016',
    ['83b599', 'fc51cb', '4bc094', '76c294'], '1f7013', '1f7013',
    ['7199de', '71dee6', '04f779'], '157232',
]
# All intervals were freshly displayed and read. No semantic/body reuse.
SUPPORT = {
    'get-shit-done/bin/gsd-tools.cjs': ([[159, 443], [484, 565], [635, 650], [702, 744], [832, 901], [948, 975], [1047, 1055]], ['trace', 'i01', 'i02', 'i03', 'i04', 'i05', 'i06', 'i07', 'i08', 'i09'], ['f05d20']),
    'get-shit-done/bin/lib/core.cjs': ([[145, 453], [531, 870], [1253, 1308], [1412, 1491]], ['trace', 'i01', 'i02', 'i05', 'i06', 'i07', 'i08', 'i09'], ['9e74ac', '51db6f', '3dae65', '9792d6']),
    'get-shit-done/workflows/execute-phase.md': ([[885, 960]], ['trace', 'i03', 'i08'], ['d17485', '51db6f']),
    'get-shit-done/workflows/audit-uat.md': ([[1, 109]], ['trace', 'i07'], ['d17485']),
    'get-shit-done/workflows/profile-user.md': ([[1, 185], [416, 435]], ['trace', 'i01'], ['d17485', '51db6f']),
    'agents/kha-verifier.md': ([[207, 234], [314, 345]], ['trace', 'i08'], ['d17485']),
    'get-shit-done/workflows/progress.md': ([[40, 55], [108, 128], [155, 191]], ['trace', 'i02', 'i05', 'i07'], ['d17485', '3dae65']),
    'get-shit-done/workflows/health.md': ([[1, 125]], ['trace', 'i08'], ['3dae65']),
    'get-shit-done/workflows/plan-phase.md': ([[911, 934]], ['trace', 'i05'], ['3dae65']),
    'get-shit-done/templates/UAT.md': ([[1, 125]], ['trace', 'i07'], ['51db6f']),
    'get-shit-done/templates/verification-report.md': ([[1, 112]], ['trace', 'i07', 'i08'], ['51db6f']),
    'get-shit-done/templates/phase-prompt.md': ([[9, 116]], ['trace', 'i06', 'i08'], ['3dae65']),
    'get-shit-done/templates/state.md': ([[1, 115]], ['trace', 'i05'], ['3dae65']),
    'get-shit-done/bin/lib/frontmatter.cjs': ([[195, 313]], ['trace', 'i06', 'i08'], ['9792d6', '9338bd', 'final-parser-tail-read']),
    'get-shit-done/workflows/verify-work.md': ([[225, 245]], ['trace', 'i07'], ['9792d6']),
    'get-shit-done/bin/lib/config.cjs': ([[330, 398]], ['trace', 'i05', 'i08', 'i09'], ['9792d6']),
}
'''
text = text[:start] + config + text[end:]
text = text.replace('range(1, 44)', 'range(1, 10)')
text = text.replace('== 43', '== 9').replace("'primary_files': 43", "'primary_files': 9")
text = text.replace('226301', '183887').replace('assert len(supports) == 27', 'assert len(supports) == 16')
text = text.replace('43 template bodies read fresh. Template placeholders, commands, declared PASS and summary presence are not executed tests, actual human acceptance or deployment evidence.', '9 implementation bodies read fresh. Static control flow and helper return values are not executed tests, qualified model behavior, actual human acceptance or deployment evidence.')
text = text.replace('template_contract_not_test_suite', 'implementation_static_review_not_executed_suite')
text = text.replace('Fresh bounded direct template producer, workflow consumer, parser, schema and state authority trace; no original execution.', 'Fresh bounded actual CLI router, workflow consumer, config/path/lock/parser and template contract trace; no original execution.')
start = text.index("        'full_read_gap_repairs': {")
end = text.index('\n    }\n    write_json(\'verification.json\'', start)
text = text[:start] + '''        'full_read_gap_repairs': {},
        'search_only_not_body': ['034824', '7c9e31', 'ad8408', '06ea89', '29bd9b', 'b767f5', 'a1d1e2', '77b2e9'],
        'search_limits': 'No direct tests were found with the named identifier searches in pinned test/spec paths. This is not proof of whole-tree test absence. No tests ran.',
        'metadata_format_reuse': 'Previous recorder source format reused; no source semantic/body evidence reused.',
        'final_parser_tail_read': 'Fresh frontmatter.cjs lines 295-304 displayed after receipt 9338bd. Current tool receipt is not embedded recursively.',
''' + text[end:]
text = text.replace('Unlisted intervals, complete transitive consumer/config/test closure and actual template loader paths for copilot/debug-subagent/planner-subagent prompt files.', 'Unlisted intervals and complete transitive consumer/config/test/hook closure; no direct test bodies found in bounded named searches.')
text = text.replace('Actual CJS UAT/human-heading parsing, template generation/select/validation/summary round trips and regression reproduction.', 'Actual CJS parser/template/summary/schema-drift round trips, lock contention, rollback failure, temp lifetime and path/OS behavior.')
text = text.replace('Tool authorization, runtime hook registration, all config consumers and atomic crash/concurrency behavior.', 'Tool authorization, runtime hook registration, all shared/scoped config consumers, atomic crash/concurrency and complete rollback behavior.')
text = text.replace("'review.md', 'record_review.py', 'files.json'", "'review.md', 'record_review.py', 'build_recorder.py', 'files.json'")
text = text.replace("'verification.json', 'record_review.py',", "'verification.json', 'record_review.py', 'build_recorder.py',")
(OUT / 'record_review.py').write_text(text, encoding='utf-8', newline='\n')
