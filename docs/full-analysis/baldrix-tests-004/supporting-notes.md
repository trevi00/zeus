# 직접 지원 구간의 후속 판단

supporting-evidence.json의 구간만 새로 읽었다. 전체 primary는 24개이며 지원 파일은 전역 primary로 승격하지 않는다. 과거 보고서의 의미 판단은 재사용하지 않았다. README·검색 결과·함수 목록은 전문 독해를 대신하지 않는다.

- dashboard_model 126~182: registry는 validator/cron/role/skill 수를 파생하고 unwired는 import_graph 결과 상위 12개만 렌더링한다. collect는 현재 시각과 각 section을 호출한다. 나머지 reader/HTML renderer/cron 등록의 전체 전이는 미완료다.
- ddl main과 er main: 누락 파일은 PASS skip, 발견된 오류는 FAIL을 출력하면서도 None을 반환한다. validator registry 1~87의 stdout 계약 및 run_units 48~210의 validator 제외·failure token·pytest 분기가 함께 읽혔다. 일반 rc0만으로 검증 PASS라 할 수 없다. DDL ENGINE/CHARSET는 합친 전체 SQL의 단일 존재 검사이며 테이블별 PG 적합성 검사가 아니다. ER는 heading 또는 entity 단어와 관계 regex만 확인한다.
- debate_aggregate 119~160: OSError를 빈 목록, malformed JSON 줄을 생략한다. 숫자 epoch/millisecond 보정은 있지만 문자열은 날짜 검증 없이 반환한다. 세션 집계·최종 planner 렌더 전체는 미완료다.
- debate_landing 59~138: type/event fallback, 종류 없는 행의 unknown 보존은 유용하다. 그러나 typed 한 행만 있으면 혼합 unknown이 unreadable 분모에서 사라지고 읽기 실패/전부 malformed는 빈 rows로 접힌다. landing 값은 문자열 존재이며 실제 산출물 확인이 아니다.
- convergence 118~끝: gen1 approved는 snapshot 없이 converged이고 snapshot_missing 검사도 not converged 조건으로 우회한다. 다음 세대와 같은 hash만으로 의미 동등성을 입증하지 않는다. severity 및 동일 세대 충돌을 실패로 전이시키는 방어는 유지 후보이나 상류 event parsing 전체는 이번 지원 독해 범위 밖이다.
- output_audit 88~끝: ledger 인용 개수와 events 문자열 개수가 같으면 token을 제거한다. bare sid를 추가하며 non-string은 빈 결과다. 따라서 invalid input과 clean을 구분하지 않는다. 공유 regex 정의 및 실제 worker 정보흐름 전이는 미완료다.
- stagnation_check 84~148: caller가 approved를 주면 EventStore 생성 전에 skip한다. recommendation와 convergence는 두 번 append하며 순차 중복 조회는 동시성/CAS 원자성을 보장하지 않는다. 실제 terminal worker 종료는 범위 밖이다.
- stagnation _self_check 434~끝: 합성 이벤트로 ABA, stable, snapshot fields 파생, blocker 추세와 window를 검사한다. 실제 home 세션이 없을 때 두 case를 True로 넣고 상세는 실패일 때만 출력하여 skip이 성공 집계에 가려진다. 원문 real-session 명칭도 합성 dictionary인 사례가 있어 실행 provenance와 구분해야 한다. detector 구현 1~433은 미독이며 전체 추적은 아직 닫히지 않았다.
- debate_trigger 249~끝과 settings 122~131: hook main에 TTL 감소·ack 갱신·origin guard·선택·저장 연결은 있다. 테스트가 그 루프를 실행하지 않는다. 전체 예외는 exit0이며 telemetry에 prompt preview와 cwd가 포함된다. settings의 Windows 절대 command는 Linux/WSL에서 그대로 쓸 수 없다. 권한은 데이터다.
- decision_memory 260~380와 role_orchestrator 140~169: 현재 survey에서 사라지면 닫힘으로 간주하고, 저장된 거절의 현재 근거가 없으면 유지할 수 있다. orchestrator는 recall/rejections를 둘 다 부르며 실패를 빈 목록으로 덮는다. 부분 survey 실패는 실제 해결과 구분해야 한다. 과거 결정을 인수나 승인 정본으로 쓰지 않는다.
- deferral 51~끝: JSON 손상 줄을 건너뛰고 읽기 실패는 빈 counter로 취급한다. 모르는 marker/예외는 보류가 아닌 상태로 돌려 결함을 숨기지 않는 방어다. 그러나 surgery 행 개수에는 실패/중복도 포함되며 권한이나 충분한 관측 기간이 아니다.
- design_slop_a11y 169~끝: 읽기/UTF-8 오류는 continue, findings 상한에서 조기 중단한다. 빈 findings는 OK이고 실제 scanned/skip 분모가 없다. 등록 여부로 BLOCKING으로 변하므로 테스트의 advisory exit0 제목은 안정된 계약이 아니다.
- dispatch_retry 전문과 external_jury 152~200: retry는 BaseException까지 잡고 permanent 이외 모든 분류를 재시도한다. KeyboardInterrupt/SystemExit 취소 처리 검사가 없다. caller는 acquire 뒤 model resolve를 try/finally 전에 수행하므로 그 함수가 예외를 내면 해제 보장을 별도 확인해야 한다. breaker success는 permanent 오류에서도 provider reached 의미로 기록되어 과업 성공과 다르다. 실제 provider와 breaker 내부는 미완료다.
- doc_classifier 63~158 및 ingest_docs 전문: discovery cap200에 도달한 뒤 정렬하므로 큰 디렉터리에서 선택 집합의 결정성은 미확인이다. content는 첫1200자만 본다. CLI는 두 번 별도 scan하고 3출력을 직접 덮어써 스냅샷 일관성·no-overwrite·원자적 bundle을 보장하지 않는다. dry-run 무쓰기와 liberal 연결은 유지 후보다. safe_read/전체 registry 전이는 미완료다.
- doc_code_drift 281~끝: vault 부재는 0분모이고 graduation 예외는 advisory로 남으며 drift가 있어도 advisory main은 PASS 출력한다. 테스트의 live 최소분모는 이 공허 성공을 발견하려는 방어이나 native execution은 하지 않았다. 실제 graduation 상태·AST resolver·frontmatter 전이는 미완료다.
- endpoint_graph 전문 및 fleet_atlas 59~117/ontology_query 43~102: 둘 다 seam_scan을 쓰지만 atlas는 drift 값을 개수로 축약하고 matched2 이상만 공유값으로 남긴다. ontology는 drift edges를 유지한다. query_repo/query_value를 직접 호출하면 unknown도 resolved=True가 될 수 있어 query dispatcher와 계약이 다르다. example YAML/enum 및 seam_scan 전체는 root 별도 작업이며 이 지원 원장에 읽은 것으로 계상하지 않는다.
- engines 전문: 두 항목의 정적 tuple와 import된 STATE_DIR를 반환할 뿐 실행 엔진 등록/기동은 없다. paths 79~143은 호출 시 환경 재평가와 legacy monkeypatch 우선순위를 제공하지만 상수 import는 별도 상태를 가질 수 있다. native 플랫폼 등가성은 미확인이다.
- ensemble aggregate 374~488 및 self-check 489~끝: threshold는 ceil(N/2), 동점은 escalate, paradox 실패는 approved를 낮춘다. N4에서 2/1/1 같은 비과반 plurality도 threshold를 만족할 수 있다. completeness 전체 참은 aggregate의 필수조건이 아니며 실제 provider 중복/독립성·동일 artifact·자격 증거가 없다. emit 실패 뒤 approved를 유지하는 계약은 PG 정본 판정 저장 성공과 다르다. meta_rules ImportError는 두 True case로 숨겨진다. self-check의 provider 문자열은 실제 모델 실행이 아니다.
- evaluator 229~291: validators/units를 bool()로 강제하므로 문자열 'false'도 truthy다. known_defects는 int검사라 False도0으로 취급할 수 있다. paradox_guard도 test_pass/ontology_match 엄격 bool 검사가 아니다. 이 입력 오라클을 Zeus의 실제 영수증 검증으로 대체해야 한다. 이후 clamp 반환 마지막 부분과 dispatcher 전체는 미독이다.

모든 판단은 정적 독해다. 실제 Claude 독립 전체 검토, 라이선스/외부 링크 원문, Windows/Linux/WSL, 실제 모델, 전체 호출·설정·테스트 전이, Zeus 적용 및 사람 인수는 미완료다.
