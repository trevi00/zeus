# Root 독립 초기 검토

실제 Claude 결과를 읽기 전에 작성했다. 고정 primary 4개/3912바이트 전문과 brain_snapshot CLI/brain_store/tech_stack/paths/test_brain_store, skill_match 지정 범위를 읽었다. 원본 실행은 아직 하지 않았다.

1. CI push는 main 및 paths, PR은 paths로 제한한다. brain 스냅샷 검사 job이 있지만 brain-only 변경은 paths에 없다. skills/agents/commands/atlas/플러그인 metadata/tech-stack 변경도 단독으로는 포함되지 않는다. workflow_dispatch 방어는 있으나 매 변경 자동 검사라는 설명을 충족하지 않는다. 기존 브랜치 오류를 main으로 수정한 사실과 역사적 실행 수 주장은 구분한다.
2. brain status는 스키마 버전이 존재할 때 불일치를 거부한다. 반면 JSON 오류를 마지막 행뿐 아니라 모든 행에서 건너뛰고 비객체 행을 버리며 schema_version·id의 존재를 강제하지 않는다. graduation 파싱 오류는 빈 validators가 된다. missing 파일도 빈 상태다. 가변 live reader의 관용성을 committed snapshot 무결성 검증에 그대로 사용하면 누락/손상을 통과시킬 수 있다.
3. 수동 brain_store 시험은 save/restore의 합집합·철회 sidecar·명시 버전 불일치·끝의 torn line 등을 검사한다. status 시험은 dict 및 l1 존재만 확인한다. sidecar 출력 검사는 query의 실제 억제를 검사하지 않으며 CLI의 'operator ONLY' 설명은 라이브러리의 Stop autosave 설명과 다르다. 전체 호출·원자성은 이번 미완료다.
4. Ubuntu/Python3.13/Node22만 선언되어 있고 dependency 하한에는 상한·lock/hash가 없다. 최신 도구를 쓰는 스모크와 동일 환경 재현은 별도다. plugin manifest/marketplace는 이름·상대 source·버전 metadata이며 실제 패키지 설치·훅 연결·다른 컴퓨터 자격을 인증하지 않는다.
5. root tech-stack은 python/lang, python 후보 중 존재하는 디렉터리가 없어 _common만 수집할 의도와 맞는다. 다만 load_tech_stack은 cwd 바로 아래 파일만 읽고 누락/해석 불가면 None을 반환한다. matcher는 별도 project-type 탐색과 달리 그대로 cwd를 전달하므로 하위 작업 디렉터리에서는 전체 재귀 fallback 후보가 될 수 있다. matcher의 실제 주입 전체는 미실행이다.

제안은 필수 변경 분모와 엄격한 committed-data 검증을 분리하고, 패키지/OS/설치/런타임 인수 증거를 각각 결속하는 것이다. 기존 운영 하네스에 수정·설치를 하지 않는다. 전체 분석·흡수·모델/사람 인수는 미완료다.
