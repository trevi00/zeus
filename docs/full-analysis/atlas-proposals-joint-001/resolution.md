# Atlas와 개선 제안 공동 검토: 53개, 정적 범위

Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2` Atlas validator 문서
38개/84994 bytes와 Harness `a3f8b3be9a0a389329de6e16a6c7db81782041a3`
제안 15개/190115 bytes를 다룬다. Codex 담당자들은 53개 모두 새 전문 독해했고,
루트는 전 파일별 판단과 보고서를 읽고 일부 소비 범위를 다시 확인했다.
[Atlas 판단](../baldrix-atlas-validators-001/file-reviews.md),
[제안 판단](../harness-proposed-002/review.md), [독립 Claude](claude-initial.md),
[루트 쟁점](root-followup.md), [토론 답변](claude-discussion.md)을 보존한다.
실제 Claude 세션 `747181c1-d16f-43af-8150-c61e2aac9f9a`의 두 단계 프로세스가
정상 종료했다. 원시 응답과 영수증은 같은 폴더에 있다. 담당자의 최초 미완료 표시는
역사 기록이며 이 공동 검토가 후속 근거다. 원본 코드 실행은 0회다.

## 합의와 루트 최종 정정

- 검증 대상 부재의 PASS, 출력만 보는 집계, 반환값을 버리는 registry dispatcher를
  실제 인수와 구분한다. Markdown/정규식/경로 존재를 확인하는 validator를 의미 검증,
  Mermaid parser 또는 no-mock 인수 체계로 부를 수 없다. 예외/종료코드/stderr,
  시도·검사·skip·unknown 분모와 실제 assertion을 함께 남겨야 한다.
- builtin registry는 문서의 27개와 다른 37개다. 동적 graduation을 함께 봐야 한다.
  읽은 고정 상태에는 두 TRACKED 항목 모두 graduated=false다. **그 상태 파일을
  로더가 사용한다는 조건에서** graduated 목록은 비어 있다. `STATE_DIR`가 외부 설정에
  의존하므로 고정 상태 JSON만으로 실제 배포 registry가 같다고 단정하지 않는다.
- Claude 답변의 "한 번도 승격한 적 없다"는 현재 false와 잘린 history_tail만으로
  입증되지 않는다. 현재 두 항목의 비승격 상태와 기록된 reset만 확정한다.
  "언제나 두 이름만 승격 가능"도 현재 TRACKED 정의에 한정한다.
- Claude의 "열한 개에 앞서 언급한 모든 no-mock 관련 이름이 포함된다"는 문장은
  틀렸다. 실제 builtin에 `code_blind_proceed`, `spec_bundle`, `spec_roundtrip`이
  명시돼 있다. 해당 문장을 채택하지 않는다. 비등록 개수와 후보 기능의 능력은 서로
  다른 주장이고, 파일 이름은 검사 능력의 근거가 아니다.
- malformed/missing state가 빈 map으로 내려가고 graduated_names가 빈 tuple을
  반환하는 경로는 실제 로더에서 확인된다. 미래/다른 상태의 집행 약화 위험이며,
  현재 읽은 비승격 snapshot에서 승격 항목이 사라진 실측은 아니다.
- `run_validator`는 반환값을 버린다. 이것을 모든 실제 실행 경로의 차단 실패로
  확대하지 않는다. registry, validate_project, run_all은 다른 소비 경로다.
- staging guard의 일치하는 literal caller를 못 찾았다는 것은 완전한 호출 그래프가
  아니다. writer가 고정 ROOT로 경로를 구성하는 방어는 존재한다. 정적 이름 검사와
  연결되지 않은 runtime helper만으로 실제 confinement를 보장할 수도 없다.
  Claude의 "존재하지 않는다"는 표현은 검색한 pin에서 해당 이름이 없었다는 범위로 제한한다.
- cohesion은 400커밋 창이고, sandbox 재확인과 mount 대상 역할의 동적 도출은 이미
  구현돼 있다. 역사적 카드의 미수정 주장 세 가지를 현재 결함으로 반복하지 않는다.
  현재 LOC 일치/불일치는 과거 작성 정확도나 변화의 원인을 증명하지 않는다.
- sandbox 실패 교집합과 다른 runner의 all-green 정책 차이는 남는다. 여기서 확인한
  두 분기는 모두 보류이며 잘못된 승격을 실행 재현한 것이 아니다. compose 문자열
  검사와 공유 state RW mount는 커널 격리나 역할별 저장소 격리의 실측이 아니다.
- historical PASS/approved/LOCK, resolved 집합, 경로 존재, reviewer의 도구 자기보고는
  사람 승인이나 현재 완료 증거가 아니다. 1개 겹치는 두 모집단을 disjoint라 부른 주장,
  read-only 평가자가 쓰기 소유자로 적힌 것만으로 결함이라는 단정도 정정한다.
- ModuleSpec를 통한 unknown caller 거절은 더 엄격한 기본값이지만 위조 불가능한
  권한 경계는 아니다. PG와 Git 책임을 나눠도 신원·정확한 revision·시도 권한의 확인이 필요하다.

## 이식 후보와 남은 범위

원본의 stage 0–11과 Zeus의 사용자 정의 8단계를 숫자로 대응하지 않는다. 스펙,
디자인/상호작용, 코드, 자체 검증, 알파, QA·사람 승인, 점진 라이브, CS를 유지한다.
Git은 계약·등록 집합·자격 기준을 정의하고 PG는 시도·검사 분모·상태·교정/재개·영수증을
기록하는 후보다. 검사 범위가 넓어지면 과거의 좁은 성공 연속 횟수를 재사용하지 않는
원칙은 기록된 reset 이유에서 얻을 수 있으나, 자동 집행과 모델 자격은 아직 증명되지 않았다.

제안별 completion predicate, curator 시점, Guardian 필터, 누락 evidence 제외,
snapshot replay, positive cache, queue/watermark 중복 가능성은 Codex 파일별 판단의
정적 범위를 유지한다. Claude가 독립 확인하지 않은 항목도 명시돼 있다. 전이 호출,
원본 시험 실행, 과거 측정 재현, 라이선스, Windows/Linux/WSL, 모델 자격, 사람 인수와
Zeus 채택은 미완료다. 이번 검토는 구현 변경이나 이슈 close/reopen을 수행하지 않는다.
