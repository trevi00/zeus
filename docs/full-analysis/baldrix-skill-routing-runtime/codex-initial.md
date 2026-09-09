# Codex 독립 초기 판단

이번 Claude 초기 결과를 읽기 전에 작성했다. 이전 common-quality 공동 검토의 배경 지식은 유지하지만 새 6파일 검토의 Claude 발견은 아직 읽지 않았다. 고정 원문은 cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2다. skill_token_budget/threshold_policy/tech_stack/pipeline_stage_picker/skill_match_render 전문을 읽고, 앞선 회차에서 전문 읽은 skill_match의 같은 pinned 바이트와 호출을 대조했다. 추가로 skill_surgery, pipeline_yaml 및 budget/tech_stack/render 원본 테스트 전문을 읽었다. 현재 이 범위의 원본 테스트 실행은 0이다.

- **역사적 버그와 현재 코드 분리:** budget 문서 상단은 1위가 무조건 전문이라고 하지만 현재 fit_top_skill은 1위도 예산 안에 넣는다. 1위 무제한 주입을 현행 결함으로 다시 주장하면 안 된다. 단, 작은 max_chars가 TRUNCATION_MARKER보다 짧으면 표식만으로 예산을 넘을 수 있다. 기본4000에서는 이 작은-cap 반례가 직접 발생하지 않는다.
- **문자 예산과 실제 전체 입력은 다르다:** MAX_CONTEXT_CHARS4000, PER_BODY_CAP3000, FULL_BODY_TOP_K3은 문자 기반이다. phase/tool/sensor/pointer/교차참조/XML 포장과 추가 주석은 별도다. 토큰 상한이나 전체 additionalContext 상한이 아니다.
- **두 번째 절단의 후조건 누락:** skill_match의 per-body 단계는 level1이3000을 넘으면 level2로 바꾸지만 level2 길이를 다시 확인하지 않는다. fallback의 c[:3000]+마커도3000을 초과한다. 더욱이 budget 할당 뒤 이 단계가 실행돼 절단으로 생긴 여유를 다음 후보에 다시 배정하지 않는다. 실제 hook 전체 실행은 아직 하지 않았다.
- **식별자 충돌:** collect_skill_files의 relative-path 키로 같은 SKILL.md 수집 누락은 개선됐다. 그러나 main의 all_skills_meta/base_scores는 _disp(일반 파일명 또는 SKILL의 name)로 다시 키잉한다. 서로 다른 경로의 동명 파일이나 같은 name은 metatada/base score를 덮어쓸 수 있다. 수집 단계의 수정이 렌더·예산·교차참조 전체 신원 보존을 뜻하지 않는다.
- **선택과 표시 차이:** telemetry top5는 pre-budget matched 목록이고 pointer_count도 표시 상한8 이전 수다. cross references는 예산 때문에 빠진 후보도 matched로 취급하고 req+'.md' 키로 찾아 SKILL name 기반 후보와 다를 수 있다. 실제 본문 도달·읽기·행동 성공은 이 로그에서 입증되지 않는다.
- **프로젝트 경로 해석 차이:** detect_project_type은 상위 프로젝트 marker를 찾지만 tech_stack/pipeline은 현재 cwd의 .claude만 본다. 서브디렉터리 실행이 더 넓은 후보 폴백과 다른 단계 선택을 만들 수 있다. extensions와 언어 경로는 confinement 검사가 없으나, 의도된 사용자 확장 권한 범위를 확인하기 전 취약점·공격 성공이라고 단정하지 않는다.
- **단계 추천 휴리스틱:** _stage_done은 산출물 중 하나의 exists면 true이고 디렉터리도 존재로 본다. detect는 마지막으로 완료 표시된 stage의 바로 다음을 고르므로 앞선 미완료·optional-next·전부완료를 다루는 의미가 약하다. 이는 스킬 추천 입력의 문제이며 실제 인수·배포 승인 전체를 건너뛴다는 증거는 아니다.
- **YAML producer/consumer:** pipeline_yaml은 block sequence를 native list로 남기면서 소비자가 없다고 설명하지만 skills/output은 picker에서 str 메서드를 사용한다. 문서상 동등성 주장은 block 형태 입력과 구분해야 한다. 필요한 PyYAML·overlay 경로는 아직 실행하지 않았다.
- **threshold 계약:** resolve는 등록 여부만 보고 numeric override를 반환하며 finite/범위/형식 재검증을 하지 않는다. _coerce_num은 nan/inf도 float로 읽을 수 있다. apply의 risky 방향은 현재 override가 아니라 registry default와 비교한다. ready flag는 이름별 exists만 보고 해당 값·기저·후보·증거와 결속하지 않는다. 직접 write→flag unlink→best-effort history는 원자적 CAS·복구 영수증이 아니다. registry와 proposer 전체·실제 쓰기는 아직 미검증이다.
- **내용 보존의 의미:** skill_surgery의 제목/길이/어휘 중복은 참고할 기계 지표지만 문장의 의미 보존을 증명하지 않는다. 과거 sample4와 MIN_DERIVED_RATIO0.55를 새 환경의 모델 자격으로 복사하지 않는다.

Zeus에 가져올 것은 계층별 비용·후보·최종 입력을 명시하는 방식, 절단·누락을 관측하는 방식, 원본 수치 오진을 바로잡은 이력이다. 실제 후보 신원과 producer→consumer의 동등성, 정상/오류/빈 데이터/경계값의 검증, 정책 변경과 승인된 근거의 결속이 더 필요하다. 실제 모델 자격·인수·배포는 여전히 미완료다.
