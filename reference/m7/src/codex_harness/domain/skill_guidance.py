"""Pure phase/guidance functions migrated from Baldrix b9586c59.

Source: scripts/lib/phase_detector.py and skill_match_render.py.
Signals and phase/sensor prose are retained; tool guidance uses workspace capabilities.
"""
import re
from pathlib import PurePosixPath
from typing import Any

from codex_harness.domain.skill_ranking import split_list_field

PHASE_SIGNALS: dict[str, tuple[str, ...]] = {'plan': ('설계', '계획', '구조', '아키텍처', '어떻게', '방법', '전략', '구상', '분석', 'plan', 'design', 'architecture', 'strategy', 'approach', 'how'), 'implement': ('만들', '구현', '추가', '생성', '코딩', '작성', '개발', 'implement', 'create', 'add', 'build', 'develop', 'write', 'code'), 'review': ('검토', '리뷰', '확인', '체크', '점검', 'review', 'check', 'inspect', 'audit'), 'deploy': ('배포', '릴리즈', '출시', '운영', 'deploy', 'release', 'ship', 'launch', 'production'), 'debug': ('디버그', '에러', '버그', '오류', '안돼', '안됨', '실패', '고쳐', 'debug', 'error', 'bug', 'fix', 'broken', 'fail', 'issue')}

STRICT_DESIGN_KEYWORDS: frozenset[str] = frozenset({'architecture', '아키텍처', '설계', '구조', 'refactor', '리팩토링', '재구성'})

def _is_ascii(text: str) -> bool:
    return all((ord(c) < 128 for c in text))

def _signal_matches(signal: str, prompt_lower: str) -> bool:
    sig = signal.lower()
    if _is_ascii(sig):
        return bool(re.search('(?<![a-zA-Z0-9])' + re.escape(sig) + '(?![a-zA-Z0-9])', prompt_lower))
    return sig in prompt_lower

def detect_phase(prompt: str) -> set[str]:
    if not prompt:
        return set()
    prompt_lower = prompt.lower()
    phases: set[str] = set()
    for phase, signals in PHASE_SIGNALS.items():
        for signal in signals:
            if _signal_matches(signal, prompt_lower):
                phases.add(phase)
                break
    return phases

def is_strict_design_intent(prompt: str) -> bool:
    if not prompt:
        return False
    prompt_lower = prompt.lower()
    return any((_signal_matches(kw, prompt_lower) for kw in STRICT_DESIGN_KEYWORDS))

PROMPT_TOOL_ROUTING_HINTS: list[tuple[list[str], str]] = [(['파일 검색', '파일 찾', 'find file', 'find files', '파일을 찾', '파일 탐색', '파일 목록', 'list files', '파일이 어디'], '파일 검색에는 Bash(find)가 아닌 Glob 도구를 사용하세요'), (['내용 검색', '콘텐츠 검색', '텍스트 검색', 'grep', '문자열 찾', '코드 검색', 'search content', 'search for', '찾아줘', '어디에 있'], '콘텐츠 검색에는 Bash(grep)가 아닌 Grep 도구를 사용하세요'), (['파일 읽', '파일 확인', '내용 확인', 'cat ', 'read file', '파일 내용', '파일을 읽', '파일 보여', '파일을 보'], '파일 읽기에는 Bash(cat)가 아닌 Read 도구를 사용하세요'), (['파일 수정', '파일 편집', '파일 변경', 'sed ', 'edit file', '파일을 수정', '파일을 편집', '수정해줘', '바꿔줘', '변경해줘'], '파일 편집에는 Bash(sed)가 아닌 Edit 도구를 사용하세요')]

_PHASE_NAMES: dict[str, str] = {'plan': '계획/설계 (Plan)', 'implement': '구현 (Implement)', 'review': '검토/리뷰 (Review)', 'deploy': '배포 (Deploy)', 'debug': '디버그/수정 (Debug)'}

_PHASE_GUIDANCE: dict[str, str] = {'plan': '설계와 아키텍처 결정에 집중하세요. 체크리스트의 구조 관련 항목을 우선 확인하세요.', 'implement': '구현 가이드와 코드 패턴을 참고하세요. 체크리스트를 따라 빠짐없이 구현하세요.', 'review': '체크리스트를 기준으로 검토하세요. 보안, 성능, 에러 처리를 점검하세요.', 'deploy': '배포 전 체크리스트를 확인하세요. 환경 설정과 시크릿 관리를 점검하세요.', 'debug': '에러 로그와 스택 트레이스를 분석하세요. 관련 패턴을 참고하여 원인을 찾으세요.'}

def build_phase_guidance(detected_phases: set[str] | list[str], matched_skills: Any=None) -> str:
    if not detected_phases:
        return ''
    parts: list[str] = []
    for phase in sorted(detected_phases):
        name = _PHASE_NAMES.get(phase, phase)
        guidance = _PHASE_GUIDANCE.get(phase, '')
        parts.append(f'{name}: {guidance}')
    return '\n'.join(parts)

def detect_tool_routing_hints(prompt_lower: str) -> list[str]:
    hints: list[str] = []
    for signals, message in PROMPT_TOOL_ROUTING_HINTS:
        for signal in signals:
            if signal.lower() in prompt_lower:
                hints.append(message)
                break
    return hints

def build_sensor_reminder(detected_phases: set[str] | list[str]) -> list[str]:
    reminders: list[str] = []
    if 'implement' in detected_phases:
        reminders.append('구현 후 테스트/린터를 실행하여 피드백 루프를 완성하세요 (Sensor)')
    if 'review' in detected_phases:
        reminders.append('정적 분석 도구와 테스트 결과를 확인하세요 (Sensor)')
    return reminders

_TOOL_MESSAGES = (
    "Find workspace files with rg --files when available; otherwise use a bounded shell directory query.",
    "Search workspace content with rg when available; otherwise use the available shell search command with bounded output.",
    "Read the supplied artifact or workspace file with bounded line ranges using an available reader or shell command.",
    "Use the available patch/edit facility for targeted workspace edits; inspect the resulting diff. Follow the task's read-only constraints.",
)
PROMPT_TOOL_ROUTING_HINTS = [(signals, message) for (signals, _), message in
                             zip(PROMPT_TOOL_ROUTING_HINTS, _TOOL_MESSAGES)]


def cross_references(records):
    """Resolve one-hop references inside the already eligible skill inventory."""
    eligible = {r['path']: r for r in records}
    active = {'full', 'pointer', 'external_pointer'}
    selected = {r['path'] for r in records if r.get('tier') in active}
    origins = sorted((r for r in records if r['path'] in selected),
                     key=lambda r: (-r.get('score', 0), r['path']))
    aliases = {}
    for path, record in eligible.items():
        relative = path.removeprefix('.harness/skills/')
        pp = PurePosixPath(relative)
        names = {relative, pp.name, pp.stem}
        if pp.name == 'SKILL.md':
            names.add(pp.parent.name)
        name = record.get('metadata', {}).get('name')
        if name:
            names.add(name)
        for name in names:
            aliases.setdefault(name, set()).add(path)
    resolved, unresolved, seen = [], [], set()
    for origin in origins:
        origin_path = PurePosixPath(origin['path'])
        language = origin['path'].removeprefix('.harness/skills/').split('/', 1)[0]
        for name in split_list_field(origin.get('metadata', {}).get('requires', '')):
            # INV-SKILL-001: names only select existing eligible records; no filesystem lookup.
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or '\\' in name:
                unresolved.append({'origin': origin['path'], 'name': name, 'reason': 'invalid'})
                continue
            candidates = sorted(aliases.get(name, set()) | aliases.get(name + '.md', set()))
            if '/' not in name:
                same_dir = [p for p in candidates if PurePosixPath(p).parent == origin_path.parent]
                same_language = [p for p in candidates if p.startswith('.harness/skills/' + language + '/')]
                common = [p for p in candidates if p.startswith('.harness/skills/_common/')]
                candidates = same_dir or same_language or common or (candidates if language == '_common' else [])
            if len(candidates) != 1:
                unresolved.append({'origin': origin['path'], 'name': name,
                                   'reason': 'ambiguous' if candidates else 'unavailable',
                                   'candidates': candidates})
                continue
            path = candidates[0]
            if path in selected or path in seen:
                continue
            seen.add(path)
            target = eligible[path]
            resolved.append({'origin': origin['path'], 'path': path,
                             'content_ref': target['content_ref'], 'file': target['file'],
                             'keywords': split_list_field(target.get('metadata', {}).get('keywords', ''))[:3]})
    return {'resolved': resolved, 'unresolved': unresolved}


def guidance(objective, records, pipeline_phases=()):
    phases = detect_phase(objective) | (set(pipeline_phases) & set(PHASE_SIGNALS))
    return {'phases': sorted(phases), 'phase_guidance': build_phase_guidance(phases),
            'strict_design_intent': is_strict_design_intent(objective),
            'sensor_reminders': build_sensor_reminder(phases),
            'tool_hints': detect_tool_routing_hints(objective.lower()),
            'cross_references': cross_references(records),
            'advisory_only': True}
