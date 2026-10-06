"""Baldrix b9586c59 scoring/budget functions adapted to pure, supplied evidence.

Source: scripts/lib/{skill_score,frontmatter_norm,frontmatter,skill_token_budget}.py.
No host-file reads. Constants retain original defaults; all originals remain auditable.
"""
import re
from typing import Any, Sequence

from codex_harness.domain.model import require


def split_list_field(value) -> list[str]:
    if isinstance(value, list):
        # Already parsed by the YAML loader; only quote stripping remains for legacy spellings.
        return [token for token in (str(item).strip().strip('"\'') for item in value) if token]
    require(isinstance(value, str), 'Skill list field must be a string or list of strings')
    s = value.strip()
    if not s:
        return []
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
        values = [t.strip().rstrip(',').rstrip(';').strip('\"\'') for t in s.split(',')]
        return [token for token in values if token]
    return s.split()

_split_list_field = split_list_field

def is_ascii(text: str) -> bool:
    return all((ord(c) < 128 for c in text))

def keyword_in_prompt(kw_lower: str, prompt_lower: str) -> bool:
    if is_ascii(kw_lower):
        return bool(re.search('(?<![a-zA-Z0-9])' + re.escape(kw_lower) + '(?![a-zA-Z0-9])', prompt_lower))
    return kw_lower in prompt_lower

def intent_in_prompt(intent_lower: str, prompt_lower: str) -> bool:
    prompt_nospace = prompt_lower.replace(' ', '')
    if not is_ascii(intent_lower) and len(intent_lower) >= 3:
        stem = intent_lower[:-1]
        return stem in prompt_lower or stem in prompt_nospace
    if is_ascii(intent_lower):
        return bool(re.search('(?<![a-zA-Z0-9])' + re.escape(intent_lower) + '(?![a-zA-Z0-9])', prompt_lower))
    return intent_lower in prompt_lower or intent_lower in prompt_nospace

def _intent_covers_keyword(kw_lower: str, matched_intent_lowers: list[str]) -> bool:
    if not kw_lower:
        return False
    for it in matched_intent_lowers:
        if is_ascii(it):
            if kw_lower == it or kw_lower in re.split('[-_ ]+', it):
                return True
        else:
            stem = it[:-1] if len(it) >= 2 else it
            if kw_lower == it or kw_lower == stem:
                return True
            if len(kw_lower) >= 2 and it.startswith(kw_lower):
                return True
    return False

def _split_path_segments(p: str) -> list[str]:
    return [s for s in p.lower().replace('\\', '/').strip('/').split('/') if s]

def _path_segment_match(skill_path: str, detected_path: str) -> bool:
    sp = _split_path_segments(skill_path)
    dp = _split_path_segments(detected_path)
    if not sp or len(sp) > len(dp):
        return False

    def seg_eq(skill_seg: str, det_seg: str) -> bool:
        if det_seg == skill_seg:
            return True
        stem = det_seg.rsplit('.', 1)[0] if '.' in det_seg else det_seg
        return stem == skill_seg
    return any((all((seg_eq(sp[j], dp[i + j]) for j in range(len(sp)))) for i in range(len(dp) - len(sp) + 1)))

HIGH_DF_INTENT: frozenset[str] = frozenset({'검증해', '구현해', '마이그레이션', '만들어', '설계', '수정해', '추가해'})

HIGH_DF_THRESHOLD = 10

def score_skill(meta: dict[str, Any], prompt_lower: str, detected_paths: set[str], file_contents_cache: dict[str, str]) -> tuple[bool, int, list[str]]:
    score = 0
    matched_dims: list[str] = []
    intents = _split_list_field(meta.get('intent', ''))
    matched_intent_lowers: list[str] = []
    for intent in intents:
        intent_lower = intent.lower()
        if intent_in_prompt(intent_lower, prompt_lower):
            score += 1 if intent_lower in HIGH_DF_INTENT else 2
            matched_dims.append(f'intent:{intent}')
            matched_intent_lowers.append(intent_lower)
    keywords = _split_list_field(meta.get('keywords', ''))
    matched_positions: set[tuple[int, int]] = set()
    for kw in sorted(keywords, key=len, reverse=True):
        kw_lower = kw.lower()
        if not keyword_in_prompt(kw_lower, prompt_lower):
            continue
        if _intent_covers_keyword(kw_lower, matched_intent_lowers):
            continue
        pos = prompt_lower.find(kw_lower)
        if pos >= 0 and any((start <= pos < start + length for start, length in matched_positions)):
            continue
        score += 1
        matched_dims.append(f'kw:{kw}')
        matched_positions.add((pos, len(kw_lower)))
    skill_paths = _split_list_field(meta.get('paths', ''))
    if skill_paths and detected_paths:
        for sp in skill_paths:
            for dp in detected_paths:
                if _path_segment_match(sp, dp):
                    score += 2
                    matched_dims.append(f'path:{sp}')
                    break
    patterns = _split_list_field(meta.get('patterns', ''))
    if patterns and detected_paths:
        for dp in detected_paths:
            if dp not in file_contents_cache:
                file_contents_cache[dp] = ''
            content_lower = file_contents_cache[dp].lower()
            if content_lower:
                for pat in patterns:
                    if pat.lower() in content_lower:
                        score += 1
                        matched_dims.append(f'pat:{pat}')
    raw_min = str(meta.get('min_score', '1'))
    require(bool(re.fullmatch(r'[0-9]+', raw_min)) and len(raw_min) <= 5, 'Invalid skill minimum score')
    min_score = int(raw_min)
    return (score >= min_score, score, matched_dims)

def extract_section(content: str, heading: str) -> str:
    pattern = re.compile('(^##\\s+' + re.escape(heading) + '.*?)(?=\\n##\\s|\\Z)', re.MULTILINE | re.DOTALL)
    m = pattern.search(content)
    return m.group(1).strip() if m else ''

MAX_CONTEXT_CHARS = 4000

PER_BODY_CAP = 3000

FULL_BODY_TOP_K = 3

DEFAULT_MAX_CONTEXT_CHARS = MAX_CONTEXT_CHARS

def truncate_skill_content(content: str, level: int) -> str:
    decision_tree = extract_section(content, '의사결정 트리')
    if level == 2:
        return decision_tree if decision_tree else ''
    gotchas = extract_section(content, 'Gotchas')
    parts = [s for s in [decision_tree, gotchas] if s]
    return '\n\n'.join(parts) if parts else ''

TRUNCATION_MARKER = '\n\n…[컨텍스트 예산 초과로 잘림 — 필요하면 스킬 파일을 직접 읽어라]'

def fit_top_skill(content: str, max_chars: int) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return (content, False)
    lvl1 = truncate_skill_content(content, 1)
    if lvl1 and len(lvl1) <= max_chars:
        return (lvl1, True)
    lvl2 = truncate_skill_content(content, 2)
    if lvl2 and len(lvl2) <= max_chars:
        return (_fill_remaining(lvl2, content, max_chars), True)
    keep = max(max_chars - len(TRUNCATION_MARKER), 0)
    return (content[:keep] + TRUNCATION_MARKER, True)

PARTIAL_MARKER = chr(10) * 2 + '…[이 절은 예산까지만 — 나머지는 스킬 파일에 있다]'

MIN_FILL_CHARS = 200

def _fill_remaining(base: str, content: str, max_chars: int) -> str:
    gotchas = extract_section(content, 'Gotchas')
    if not gotchas:
        return base
    room = max_chars - len(base) - len(PARTIAL_MARKER) - 2
    if room < MIN_FILL_CHARS:
        return base
    kept: list[str] = []
    used = 0
    for line in gotchas.split(chr(10)):
        need = len(line) + 1
        if used + need > room:
            break
        kept.append(line)
        used += need
    body = chr(10).join(kept).rstrip()
    if len(body) < MIN_FILL_CHARS:
        return base
    partial = len(body) < len(gotchas.rstrip())
    return base + chr(10) + chr(10) + body + (PARTIAL_MARKER if partial else '')

def apply_token_budget(matched_skills: Sequence[tuple[float, str, dict, str]], max_chars: int=DEFAULT_MAX_CONTEXT_CHARS) -> tuple[list[tuple[float, str, dict, str]], bool]:
    if not matched_skills:
        return (list(matched_skills), False)
    total_chars = sum((len(content) for _, _, _, content in matched_skills))
    if total_chars <= max_chars:
        return (list(matched_skills), False)
    top_score, top_name, top_dims, top_content = matched_skills[0]
    fitted, top_cut = fit_top_skill(top_content, max_chars)
    result: list[tuple[float, str, dict, str]] = [(top_score, top_name, top_dims, fitted)]
    remaining_budget = max_chars - len(fitted)
    was_truncated = top_cut
    for score, name, dims, content in matched_skills[1:]:
        if remaining_budget >= len(content):
            result.append((score, name, dims, content))
            remaining_budget -= len(content)
            continue
        truncated = truncate_skill_content(content, level=1)
        if truncated and remaining_budget >= len(truncated):
            result.append((score, name, dims, truncated))
            remaining_budget -= len(truncated)
            was_truncated = True
            continue
        truncated2 = truncate_skill_content(content, level=2)
        if truncated2 and remaining_budget >= len(truncated2):
            result.append((score, name, dims, truncated2))
            remaining_budget -= len(truncated2)
            was_truncated = True
            continue
        was_truncated = True
    return (result, was_truncated)

def extract_paths_from_prompt(prompt):
    patterns = ['[A-Za-z]:[/\\\\][\\w\\uAC00-\\uD7A3./\\\\-]+', '(?<!\\w)\\.{0,2}/[\\w\\uAC00-\\uD7A3./\\\\-]+', '[\\w\\uAC00-\\uD7A3-]+/[\\w\\uAC00-\\uD7A3./\\\\-]+']
    paths = set()
    for p in patterns:
        for match in re.findall(p, prompt):
            cleaned = match.rstrip('/\\.,;:)')
            if len(cleaned) > 3:
                paths.add(cleaned)
    return paths

FULL_BODY_MIN_SCORE = 3
MAX_POINTERS = 8
