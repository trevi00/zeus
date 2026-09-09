# 스킬 라우팅 런타임 공동 검토

고정 Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 예산·임계 정책·스택·단계 추천·렌더·실제 hook 6개를 검토했다. 새 primary 6개는 전부 `body_reviewed_call_test_trace_pending`이다. 전문 읽은 supporting 13개에는 앞 회차에서 읽은 동일 pinned 의존성도 포함되며, supporting을 primary 커버리지로 중복 승격하지 않는다. 원본과 Zeus 실행 코드는 수정하지 않았다.

실제 Claude 세션 `b5cc63e9-1109-441c-8356-845d6c3ce763`에서 독립 1차 검토와 Codex 증거를 대조한 2차 토론을 수행했다. 두 프로세스 모두 exit0/is_error=false다. Codex 초기 판단은 Claude 1차 결과를 읽기 전에 기록했으며, 이전 common-quality 회차의 배경지식은 유지했다. Claude는 Read/Glob/Grep만 사용했고 프로그램 실행자는 Codex다. `claude-initial*`, `claude-discussion*`, 두 prompt, `codex-initial.md`에 발언·원본 응답·사용 모델·usage·해시를 보존했다. 원래 보고서의 오류는 수정 덮어쓰기 대신 아래 정정으로 남긴다.

## 실행 증거

| 실제 실행 | 결과 | 범위 |
|---|---|---|
| `tests.test_skill_token_budget` | 18 PASS | 순수 문자 예산·축약·수술 helper |
| `tests.test_tech_stack` | 17 PASS | 임시 프로젝트 입력과 스택 parser |
| `tests.test_skill_match_render` | 22 PASS | 조언·교차참조 렌더 helper |
| `observe_components.py` | exit0, 아래 관측 수집 | 원본 component API, 임시 프로젝트·문자 입력 |

원본 테스트 3개는 불변 Python Alpine 이미지 `7415fbc3…`, 별도 관측은 PyYAML6.0.3이 있는 검증 이미지 `39d4f226…`를 사용했다. 전체 digest·argv·시간·stdout/stderr 해시·바이트는 각 `*.receipt.json`과 원시 출력에 기록했다. 원본 1,648개 바이트의 전후 해시가 모두 일치한다. 실행은 network-none/read-only/비특권/제한된 tmpfs·자원·기한 환경이며 원본 설정·인증정보·세션은 전달하지 않았다. 검증 이미지의 서비스 entrypoint도 명시적으로 교체했다.

57개 PASS는 단위 함수/fixture 검증이다. full hook main, 실제 모델 입력 도달·동작, threshold writer, 실제 overlay 병합, Windows/WSL의 이 원본 경로, 사용자 인수·배포 검증은 실행하지 않았다. 이전 Zeus 자체의 Windows/WSL CI 결과를 이 원본 검증의 증거로 가져오지 않는다.

## 합의와 실제 관측

- **문자 예산과 전체 입력을 분리해야 한다.** MAX_CONTEXT_CHARS4000/PER_BODY_CAP3000/FULL_BODY_TOP_K3은 전체 모델 토큰 상한이 아니다. phase·pointer·교차참조·XML·advisory가 별도로 붙는다. 특히 교차참조는 개수 상한이 없다. 실제 tokenizer 비용·모델 행동은 아직 측정하지 않았다.
- **과거 1위 무제한 버그는 이미 수정됐다.** 현재 fit_top_skill은 첫 스킬도 예산 안에 넣으므로 낡은 hook 주석을 현행 동작으로 읽으면 안 된다. 작은 cap0/1/20에서는 40자 절단 마커 때문에 cap을 넘는 동작을 실제 관측했다. 기본4000에서는 결과도4000이었다. 작은-cap API 경계와 현재 기본 설정의 동작을 구분한다.
- **사후 본문 cap의 후조건이 없다(정적).** hook은 level2 결과 길이를 재확인하지 않고, no-heading fallback은3000자 뒤에 마커를 추가한다. 먼저 배정한 뒤 다시 자르므로 생긴 여유를 드롭된 다음 후보에 재배정하지 않는다. full hook에서의 실제 최종 문자열은 아직 실행하지 않았다.
- **후보 신원이 끝까지 보존되지 않는다.** 수집은 상대경로를 쓰지만 meta/base score/render 키는 파일명 또는 SKILL의 name으로 다시 축약된다. 같은 이름의 일반 파일·SKILL 후보가 충돌할 수 있다(정적). 실제 helper에 meta 키를 `b`로 넣으면 requires 추천0개, `b.md`로 넣으면1개였다. corpus 전체 영향 규모는 미측정이다.
- **프로젝트 루트 해석이 다르다.** 실제 입력에서 root의 후보는 `_common, python/lang, python`, `root/src`는None이었다. 상위 marker를 찾는 project-type resolver와 exact-cwd stack/pipeline resolver를 같은 계약으로 결속해야 한다. None 이후의 실제 전체 코퍼스 선택은 이번 관측에서 실행하지 않았다.
- **단계 추천은 완료 증명이 아니다.** a 산출물이 없고 b가0바이트인데 verify가 추천됐다. 모든 산출물이 있어도 마지막 verify를 다시 추천했고, optional 단계가 next가 되거나 디렉터리를 산출물 존재로 셌다. 이는 스킬 추천 컴포넌트의 약한 휴리스틱을 보여주며 실제 승인·인수를 우회했다는 실행 증거는 아니다.
- **YAML 표기와 소비 타입이 불일치한다.** 실제 parse_stages는 block skills를list로 남기고 picker가 `AttributeError: 'list' object has no attribute 'strip'`를 냈다. hook main의 catch-all이 이 오류를 삼키는 귀결은 정적 코드 추적이며 이번에는 main을 실행하지 않았다. overlay의 input/skills 정규화와 project override 경로도 구분한다.
- **로그가 최종 전달 상태를 입증하지 않는다(정적).** telemetry top5·matched_count는 배정 전 후보를 바탕으로 하고 드롭된 전문은 pointer로 전환되지 않는다. 일부 집계 차이로 누락 수를 추론할 수 있지만 최종 본문 신원·해시·이유가 없다. 실패 자체의 관측 부재와 선행 telemetry가 전혀 없다는 주장은 다르다.
- **임계 변경의 근거 결속이 약하다(정적).** 등록 이름만 확인하는 reader, finite/domain 검증 부재, 이름별 ready-file 존재, 현재 override 대신 default에 대한 방향 비교, 비원자적 파일/flag/history 변경을 발견했다. registry의5개 중 실제 라우터에 연결된 것은 FULL_BODY_MIN_SCORE 하나이며 direction=either다. 다른4개 선언의 방향 문제를 현재 라우터에 곧바로 적용된 동작으로 표시하지 않는다.

## 독립 검토에서 정정한 내용

1. Claude의 ‘3900자 트리가 cap 이후3000 이하가 된다’는 반례는 틀렸다. level2 후 길이 검사 누락으로3900이 남는 것이 정적 코드상 결과다. 여유 재배정 문제의 반례와 cap 후조건 문제를 분리했다.
2. 하드 절단 마커는 다른 생략 마커로 바뀐다. 특정 기계 식별자의 동일성이 깨지는 것과 사람에게 아무 생략 안내도 없는 것은 다르다. 후자의 일반화는 철회됐다.
3. 원본 budget 테스트가 모두8000이라는 주장은 철회됐다. 800/1500/2000/2500/4000·계산된 cap·기본값 사례도 있다. 남은 검증 공백은 **실제 hook의 cap 조립 경로**다.
4. BOM/서브디렉터리면 pipeline이 무조건 꺼진다는 주장은 철회됐다. 언어가 없어도 프로젝트 override가 선택되거나 전역 stages 파일로 폴백할 수 있다. Claude2차의 ‘실제 결과는 항상 Java pipeline’ 역시 조건을 생략한 표현이다. 프로젝트 override 부재·전역 파일 존재·실제 전역 내용이 모두 필요하며 그 전체 경로는 이번에 실행하지 않았다.
5. 현대 Windows 메모장 기본 인코딩과 한글 문자당 토큰 비용의 배수 주장은 이번 검증 근거가 없어 삭제했다. BOM은 읽은 parser의 정적 가설이며 실제 파일 시험은 남았다.
6. 일반적인 SKILL name과 filename 기반 부스트의 불일치는 유지하되 ‘영원히 부스트 불가’는 철회됐다. `skills: [SKILL]` 같은 특별 입력은 반대로 여러 SKILL.md를 같이 부스트할 수 있다(정적).
7. 적은 수정 줄 수만으로 Terra 자격을 부여하지 않는다. 후보 집합·권한·예산·실패 관측에 영향을 주는 변경은 동일 행동·회귀·독립 검토로 검증해야 한다. PG 트랜잭션도 외부 모델의 입력 도달·행동·부작용을 혼자 원자화하지 못한다.

## Zeus 적용 방향과 미완료

이 결과는 [FA-012 / GitHub #13](https://github.com/trevi00/zeus/issues/13)의 실제 선택·주입 경로 검토를 확장한다. 단일 후보 신원, 공통 프로젝트 root, producer/consumer 스키마, 최종 전달된 본문과 제외 이유, 명시적인 문자/토큰 예산, 검토된 정책값·기저·증거의 원자적 결속을 설계 후보로 둔다. 원본의 과거 성공·임계값·정책 토큰을 Zeus의 운영 승인으로 승계하지 않는다.

threshold package의 proposer/breaker_proposer 전이 의존성, 실제 hook·overlay/전역 단계표, corpus 규모 영향, BOM·Windows/WSL 실행, 라이선스와 외부 인용, 모델의 실제 행동과 인수는 남아 있다. 모든 primary 상태와 `checkpoint.json`은 전체 분석·채택 미완료를 유지한다. 구현은 전체 분석과 공동 검토 이후 주 Codex가 맡는다.
