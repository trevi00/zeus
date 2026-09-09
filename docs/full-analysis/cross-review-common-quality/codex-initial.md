# Codex 독립 초기 검토

Claude 초기 결과 파일을 읽기 전에 작성했다. 고정 Baldrix 원문의 지정 4개(스킬 절차 2개, `skill_trigger_eval.py`, `skill_quality_axes.py`)와 `lib/frontmatter.py`, `lib/skill_score.py`를 전문으로 읽었다. 실제 upstream 테스트는 이 기록 작성 시 0건이다.

- `run_eval`의 precision은 음성 쿼리 중 target 미매칭 비율이다. 표준 precision의 TP/(TP+FP)가 아니며, 해당 음성집합에서는 specificity에 해당한다. 따라서 F1도 표준 F1이 아니다. 다만 현재 PASS 조건이 음성 오탐 0이므로 지표 이름이 잘못됐다는 사실만으로 모든 PASS의 판정이 반대였다고 주장하지 않는다.
- 양성은 target의 match와 최고 점수 winner를 함께 요구하고 음성은 경쟁 승패와 무관한 match만 본다. winner 계산은 경쟁자의 match boolean을 버리므로 임계 미달 경쟁자가 target을 밀어낼 수 있다. tie는 먼저 넣은 target에 유리하고 winner 식별자가 stem뿐이어서 같은 stem의 서로 다른 파일을 구분하지 못한다.
- 음성집합이 비면 precision=1.0이다. 문서의 양성 7+/음성 5+ 요구를 코드가 강제하지 않는다. 입력 JSON shape, 원소 타입, 중복 쿼리, 양·음성 겹침도 명시 검사가 없다.
- `score_one`은 프로젝트 경로·파일 내용을 빈 집합으로 전달한다. `description` 자체는 점수에 쓰이지 않는다. 재귀 후보 탐색과 이 점수 결과는 실제 stack 필터·활성 후보·주입 예산을 포함한 실사용 평가와 구분해야 한다. `skill_score`의 역사적 주석도 잘못된 후보 집합 때문에 예전 precision 개선 주장이 틀렸다고 정정한다.
- G1은 Source 이후의 하이픈 줄 존재, G6은 `http://` 부재를 본다. HTTPS 인용·정확한 인용문·날짜·원문 의미 검증이 아니다. 스킬 자체도 G1이 quote 없이 통과할 수 있음을 Gotchas에 인정한다. 형식 검사를 출처 검증으로 부르는 데 과장이 있다.
- `requires`와 `tech-stack`을 각자 문자열 분할하므로 공통 정규화 경로와 동등하지 않다. frontmatter parser는 YAML 전체가 아닌 단순 `key: value` 파서다. 본문 절·Gotchas·품질 축은 실제 Markdown 구조를 파싱하지 않고 substring/구간으로 검사한다. 줄수는 끝 개행이 있어도 `count + 1`로 계산한다.
- main은 대상 디렉터리/파일 부재 또는 inspected=0에도 PASS를 출력한다. FAIL을 출력해도 종료 코드로 실패를 전파하는 CLI 계약은 없으므로 호출자의 stdout 집계까지 봐야 한다. 모듈 시작 시 stdin/stdout.reconfigure 호출 때문에 “never raises”는 일반 임베디드 stream까지 보장되지 않는다.
- 스킬 문서의 10필드 stub은 보이는 키가 flag 포함 9개이며 paths/patterns가 빠져 있다. 기존 노드에 절을 추가하라는 앞부분과 legacy 본문도 수정 금지라는 뒤 규율이 다르다. 항상 로드, 4–7개 디렉터리, 3–5개 채용공고면 충분, 자기증명 등의 문구는 실제 선택·품질·검수 보장이 아니다.

Zeus에 적응할 것은 출처·관측일·변경 가능성·양성/음성 회귀 데이터를 갖춘 스킬 평가 절차다. 입력 스키마, 혼동행렬의 정확한 이름과 분모, 실사용 후보/선택/주입 경로의 동일성, 미검사와 PASS의 구분, 실행 증거·독립 승인 결속을 보완해야 한다. 아직 이 기록은 구현 또는 승인 완료가 아니다.
