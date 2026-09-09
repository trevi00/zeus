"""Review metadata only; preserve all raw execution receipts byte-for-byte."""
import hashlib
import json
from pathlib import Path
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
SRC = ROOT / '.runtime/absorption/sources/baldrix'
manifest = json.loads((SRC / 'manifest.json').read_text(encoding='utf-8-sig'))
inventory = {x['path']: x for x in manifest['inventory']}
receipts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.glob('*.json') if 'receipt' in p.name or 'probe' in p.name}
ledger = json.loads((OUT / 'supporting-evidence.json').read_text(encoding='utf-8'))
for path in ['scripts/lib/debate_convergence.py', 'scripts/cli/debate_converge_check.py', 'commands/harness-debate.md', 'scripts/validators/skill_quality_axes.py', 'scripts/cli/skill_trigger_eval.py']:
    if any(x['path'] == path and x['source'] == 'baldrix' for x in ledger):
        continue
    raw = (SRC / 'pinned' / path).read_bytes()
    entry = inventory[path]
    sha = hashlib.sha256(raw).hexdigest()
    assert sha == entry['snapshot_sha256']
    ledger.append(dict(source='baldrix', path=path, sha256=sha, bytes=len(raw), read_extent='full', tests_executed=False, revision=manifest['revision'], git_blob=entry['object'], manifest_matches=True, review_workspace='C:/Users/rudtn/zeus'))
(OUT / 'supporting-evidence.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
p = OUT / 'REVIEW.md'
body = p.read_text(encoding='utf-8')
body = body.replace('This checkpoint contains **81 / 98 common files semantically reviewed; 17 remain unreviewed**.', 'This checkpoint contains **98 / 98 common files semantically reviewed; 0 bodies remain unreviewed**.')
body = body.replace('All 81 reviewed files', 'All 98 reviewed files')
body = body.replace('(its **body\nremains unreviewed**)', '(its body is now fully reviewed)')
body = body.replace('Zeus HEAD observed:', 'Historical pre-migration HEAD observed:')
intro = '''## 최종 본문 검토 상태 — 2026-09-09

고정 revision의 98개 파일, 979,411바이트를 모두 읽고 파일별 의미·호출 가능성·의존성·운영체제 차이·Zeus 대응·결정·미해결을 기록했다. 모든 source SHA-256과 크기가 manifest와 일치한다. `files.json`과 `status.json`은 98/98, `remaining.txt`는 빈 목록이다. 본문 전수 검토를 완료한 것이며, 모든 의존 구현·라이선스·외부 원문·테스트를 검증하거나 채택을 승인했다는 뜻은 아니다. 따라서 `body_coverage_complete=true`, `partition_complete=false`, `adoption_ready=false`를 구분해 유지한다.

81개 이후 기록은 `diagnosis-notes.json`, `skill-pipeline-notes.json`, `rubric-convention-notes.json`, `craft-security-notes.json`, `pattern-catalog-notes.json`에 있다. 마지막 두 문서는 구간을 이어 전문을 읽은 뒤 기록했다. 아래의 이전 checkpoint 서술과 역사적 테스트 영수증은 당시 증거를 설명한다.

### 주요 발견

- 트리거 평가기의 `precision`은 실제로 TN/(TN+FP), 즉 특이도다. 이를 정밀도라고 부른 F1도 표준 F1과 다르다. 오프라인 평가의 후보 수집·동률·예산 조건도 실제 matcher와 달라 결과를 라이브 정확도로 옮길 수 없다.
- 품질 검사의 heading·substring·인용 모양 검사는 내용의 정확성과 원문 검증이 아니다. 비어 있는 검사 집합의 PASS, 출력된 FAIL과 프로세스 성공 종료를 구별해야 한다. spec bundle의 빈 요구/TODO 통과와 Zeus SDD 준비단계의 인수·배포 차단은 `spec-bundle-zeus-comparison.md`에 별도로 대조했다.
- 과거 개인 프로젝트의 성공 횟수·commit 인용·토론 합의는 현재 승인이나 실행 증거가 아니다. 설계 snapshot의 canonical hash와 구현 의미의 동등성도 다르다. V19의 필수 4세대와 1·2세대 성공 예시, V20의 3개 crate 기준과 예외가 서로 맞지 않는다.
- nested `_common/mock-prototype/SKILL.md`는 일반 immediate tree 라우팅에 수집되지 않는다. fallback 재귀 스캔 가능성과 실제 pipeline 등록은 별개의 문제다. 문서의 +3 점수 설명만으로 호출 가능하다고 볼 수 없다.
- 디자인 문서의 글자 크기·광학 정렬·격자·숫자 스타일 지침이 상충하며, OKLCH 밝기 값이나 고정 폰트 규칙은 접근성·대비 검증을 대신하지 않는다. 실제 렌더링과 사용자 요구 확인이 남았다.
- pattern detector는 검색 recipe와 조언 문서다. 검색 결과 0은 호출자·저장 경로·관대한 문자열 비교가 없다는 증명이 아니다. 신규 모듈·짧은 함수·컴파일 통과·atomic commit은 회귀 위험 0을 보장하지 않는다.

### 실제 테스트와 남은 검증

실제 upstream 실행은 기존 Linux 격리 영수증의 tech-stack 테스트 17개 PASS뿐이다. 별도 reviewer probe 1회는 YAML inline-comment 결함을 재현했다. 두 논리 실행과 최초 인코딩 오염 capture/재실행 원시 증거를 보존했다. 이 파티션에서 추가 source 실행, native Windows 실행, 전체 hook/session/운영 실행은 하지 않았다. 부모 작업의 Windows/Linux CI 성공은 별도 Zeus 증거이며 upstream 98개 파일의 테스트 성공으로 합산하지 않는다.

`supporting-evidence.json`은 실제 전문/부분 읽기 범위를 구분한다. event_store 및 미완료 의존 구현, 추가 lint/surgery·trigger/quality/convergence 테스트, mock pipeline 등록, 외부 Rust 구현·개인 commit·원본 라이선스·원격 링크는 여전히 미확인이다. 검색 hit는 전수 검토로 올리지 않았다. 파일별 `remaining`은 이 후속 검증과 독립 검토·채택 결정을 유지한다. 새 구현이나 자동 채택으로 진행하지 않고 이 98개 범위에서 중지한다.

### 경로 이전과 증거 보존

81개 checkpoint 이후 작업은 독립 저장소 `C:/Users/rudtn/zeus`에서 수행했다. 이전 경로가 담긴 원시 영수증과 역사적 checkpoint는 변경하지 않았다. `checkpoint98.json`의 receipt SHA-256은 현재 원시 바이트 보존 확인값이다. 소스·설정·credentials·운영 상태·구현 코드·commit/push는 이 검토에서 수정하거나 실행하지 않았다.

'''
if '## 최종 본문 검토 상태' not in body:
    body = body.replace('## Actual activation and body consumption', intro + '## Actual activation and body consumption')
p.write_text(body, encoding='utf-8')
assert receipts == {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in receipts}
state = json.loads((OUT / 'status.json').read_text(encoding='utf-8'))
assert state['semantically_reviewed'] == 98 and state['unreviewed'] == 0
(OUT / 'checkpoint98.json').write_text(json.dumps(dict(workspace=str(ROOT), status=state, supporting_records=len(ledger), preserved_raw_receipt_sha256=receipts, stop_reason='Bounded 98 source-body semantic review complete; unresolved dependencies, original licenses/links, matched tests and adoption gates remain explicit.'), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(dict(reviewed=98, unreviewed=0, supporting_records=len(ledger), preserved_receipts=receipts), ensure_ascii=False))
