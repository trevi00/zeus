# Baldrix CLI 004 정적 검토

고정 범위 `baldrix:scripts/cli:004`의 **19개, 192,367바이트 전문**을 읽고 파일별 의미 판단을 기록했다. 원본 revision과 각 파일의 SHA-256·크기는 `files.json`에 manifest 대조 결과로 남긴다. 상류 프로그램 및 테스트 **실행은 0회**다. 전문 독해 완료는 흡수 승인이나 의존성 전체 검증 완료를 뜻하지 않는다.

가장 먼저 고쳐야 할 부분은 관찰된 결과와 실제 부작용의 불일치다.

- **팀 종료 정책:** `team_policy_check.py`는 종료 함수가 false를 반환하거나 예외를 내도 worker를 killed 집합에 넣어 다음 재시도에서 제외한다. 반대로 실제 종료 뒤 event 쓰기가 실패하면 최상위 응답은 `killed:[]`일 수 있다. 읽기 불명 상태에서는 종료하지 않는다는 설명도 지원 `team_policy`의 kill 우선 분기와 맞지 않는다. PG 작업 lease·fencing, process identity, 종료 영수증과 재시도 가능한 상태를 설계해야 한다.
- **연구 소비·상주 실행:** `strike_research_consume.py`는 candidate 작성 뒤 event 오류를 `staged:false`로 보고할 수 있다. `(session, fingerprint)` 중복 키는 새 artifact의 hash를 구분하지 않는다. `resident.py`는 출력만 있으면 artifact가 없어도 성공이며 큐를 배타적으로 claim하지 않는다. 결과 계약, event commit, artifact provenance 및 큐 상태를 연결해야 한다.
- **자가수정:** `selfmod.py`는 merge 결과가 아닌 branch에서 검사하고 전환 직전 revision을 다시 묶지 않는다. `surgery.py`는 Claude의 실행 실패와 별개로 정적 검사를 통과하면 수정안을 유지할 수 있고 다른 파일 부작용은 rollback하지 않는다. 프롬프트의 한 파일 수정 지시는 격리가 아니다. 길이·제목·단어 중첩은 의미 보존 증명이 아니다.
- **지표·gate 의미:** `skill_trigger_eval.py`의 precision은 실제로 specificity이며 F1 이름도 성립하지 않는다. `router_eval.py`의 baseline 갱신은 퇴행 결과도 수용한다. `seam_gate.py`는 빈 입력이나 기본 불확실 상태를 통과시키고, `stub_faker_gate.py`는 strict에서도 indeterminate를 성공으로 종료한다. 측정값, 자료 부족, 정책 허용 및 인수 성공을 서로 다른 상태로 표현해야 한다.
- **spec 초안:** `spec_bundle_emit.py`는 TODO·빈 model의 구조적 통과를 행동 검증과 구별하지 않으며 이전 facet 잔존, 기존 manifest 저작 내용 손실, 비원자적 overwrite 가능성이 있다. 읽은 테스트도 TODO 통과를 기대한다. Zeus SDD의 요구 의미·ID 유지, retirement, active coverage 및 다른 기존 export 거부 규칙과 대조했다. Zeus의 현재 해당 검사 역시 structural-only이므로 실제 인수나 배포 승인을 주장하지 않는다.
- **격리·관측 한계:** `state_leak_check.py`는 내용 대신 mtime을 보고 삭제와 runner 실패를 놓친다. `signals --probe`는 실제 hook을 실행한다. sensor/telemetry의 빈 자료·손상 행 생략·시간 해석은 품질 승인 근거가 아니다. thin-skill predicate 복제는 bool 점수 처리도 서로 다르다.
- **그래프·출력:** `skill_graph.py`는 파일 stem으로 여러 `SKILL.md`를 같은 node로 합치며 cycle 검출이 없어 DAG를 보장하지 않는다. HTML의 raw script 데이터·innerHTML과 외부 mermaid CDN은 별도 출력 안전성 검토가 필요하다. `reverse_engineer.py`는 충돌 검사 target과 실제 출력 target이 다르고 생략 roundtrip을 PASS처럼 표시할 수 있다.

파일별 목적, 실행 가능한 진입점, 권한 경계, 플랫폼 차이, 구체적인 남은 의존 검토는 `semantic-notes.json`과 `files.json`에 있다. 모두 직접 채택을 보류하고 변형 후보로 분류했다. Zeus 대응 파일은 설계상 검토할 모듈의 연결이며 전체 구현 동등성 선언이 아니다. 이번에 실제로 대조한 Zeus 구현은 SDD 두 파일의 명시된 구간뿐이다.

지원 자료는 상류 17개와 Zeus 2개의 **실제로 읽은 구간 및 원시 바이트 hash**로 기록했다. 상류 spec validator와 spec emitter 테스트는 전문, 나머지는 부분 독해다. 명령 문서의 agent spawn·공개 활성화 토큰·경로 지시는 분석 데이터로만 다뤘다. 검색 결과에 등장하는 다른 caller/test는 발견 단계이며 전문 검토로 집계하지 않는다. 등록 extractor, 역할 구현, skill matcher·lint, process 종료 수단, 운영 configuration 및 전이 의존의 미독 부분이 남는다.

Windows/Linux/WSL에서 source 프로그램을 실행하지 않았다. 경로 confinement, Git hook/config 상속, 인코딩, timezone, subprocess 및 동시 쓰기 문제는 정적 발견 또는 미검증 사항이다. upstream의 과거 PASS, 구성된 probe, mock 반환값은 이번 실행 증거가 아니다. 라이선스, 연결된 외부 원문 및 CDN 공급망도 미확인이다.

`checkpoint.json`이 최종 19/19 본문 상태다. `checkpoint-notes.md`는 보존한 중간 11/19 원시 기록이며 최종 상태를 대신하지 않는다. `remaining.txt`가 비어 있는 것은 primary 본문 미독이 없다는 뜻이다. 전이 검토·실행·독립 공동 검토·흡수 결정은 계속 미완료로 표시했다. 이 한정 범위 이후로 확장하지 않는다.
