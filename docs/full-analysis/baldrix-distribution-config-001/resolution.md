# 배포 구성·스냅샷 검사 공동 검토

Primary는 pinned Baldrix `cbb5c3e6c9c4af6f86626474f4d7d62fd8e8a6d2`의 CI workflow, marketplace, plugin manifest, 자체 tech-stack 총 4개/3912바이트다. Root와 실제 Claude가 독립 검토했다. 초기 판단과 원문을 보존하고 [토론 입력](codex-discussion-input.md)으로 잘못 읽은 부분과 과도한 결론을 정정하도록 요청했다. 전체 소스 분석과 채택은 미완료다.

[실제 Claude 후속 답변](claude-discussion.md)은 브랜치 역독해, JSON/JSONL 분모 혼합, gitignore와 tracked 상태의 혼동, 유일한 실패 유형이라는 일반화, status의 프로그램 처리 불가능 주장, 실행 수 추정, 영구 fallback 부재 및 설치 완료처럼 읽히는 표현을 철회했다. Root는 이 정정을 수용한다. 다만 extensions 추가는 우선 후보 집합을 바꾸는 것이며 항상 tree/fallback 분기 자체를 바꾸는 것은 아니다. graduation의 승인 플래그를 snapshot에 그대로 복제하지 않는 것도 곧바로 결함이 아니며 재검증 계약과 대조해야 한다. 새 수치/전이 주장은 추가 독해·실행 없이 확대하지 않는다.

## 파일별 판단

### CI workflow

현재 push 브랜치는 main이며 과거 master 필터 오류를 고친 상태다. 주석의 과거 실행 횟수는 이번 원격 검증이 아니다. paths는 scripts, get-shit-done, 해당 workflow, requirements만 포함한다. 따라서 일반적인 brain-only 변경이나 skills/agents/commands/atlas/배포 metadata/스택 선언만의 변경은 이 workflow의 자동 검사 대상에 들어가지 않는다. 수동 dispatch는 가능하다. GitHub 문서의 필터 계약과 큰 diff 등 예외를 [플랫폼 대조](platform-references.md)에 연결했으며 원본 원격 workflow를 실제 발화시키지는 않았다.

두 job은 Ubuntu와 Python 3.13을 선언하며 regression job만 Node 22를 설치한다. 이것은 해당 workflow의 범위다. 다른 환경의 모든 과거 Windows 실행을 부정하지 않는다. dependency 하한·액션 major tag·ubuntu-latest만으로 동일 설치 바이트와 도구 버전을 보장하지 않는다. 원격 token 권한/필수 check 정책은 이번에 조회하지 않았다.

### Marketplace와 plugin manifest

`khaness-marketplace`의 source `./`와 `khaness` version `0.1.0`은 배포 식별 metadata다. 명령·에이전트·스킬 발견 선언과 실제 설치·훅 배선·의존성 설치·캐시 위치·업데이트/롤백은 별도의 검증 대상이다. Claude는 일부 settings의 절대 Windows 경로를 발견했지만 root는 그 파일 전문을 이번에 읽지 않았다. 명령 몇 개의 경로 발견을 모든 설치 구성의 실행 결과로 확대하지 않는다. 이름 차이 자체도 자동으로 기능 결함은 아니다. 실제 plugin 설치는 하지 않았다.

### 자체 tech-stack

root에서 원본 loader의 후보는 `_common`, `python/lang`, `python`이고 실제 존재하는 후보 디렉터리는 `_common`이다. 이는 자체 선언의 의도와 맞는다. 같은 loader를 `/source/scripts` cwd로 호출하면 None이다. matcher는 프로젝트 유형의 상향 탐색과 달리 load_tech_stack에 원래 cwd를 전달하므로 하위 cwd에서 fallback 후보 수집으로 바뀔 수 있다. loader 관측과 consumer 정적 경로를 연결한 판단이며 full matcher 주입은 실행하지 않았다. `_common` 선택을 슬래시 명령 미등록이나 무조건적인 결함으로 취급하지 않는다.

## 원본 실행으로 확인한 무결성 검사 경계

[불변 실행 영수증](attempts/d9b82d63392f4a33bfb0e4076a23288c/receipt.json)과 [전체 stdout](attempts/d9b82d63392f4a33bfb0e4076a23288c/stdout.txt)에 7개 실제 CLI argv/환경/결과와 파생 입력의 원문·bytes·SHA를 남겼다. 원본 코드를 바꾸거나 프로세스 결과를 mock하지 않았다.

| 입력 | 원본 status 결과 |
|---|---|
| committed source snapshot | rc0, L1 910/철회249, L2 fact2/철회0/evidence20 |
| snapshot 전체 부재 | rc0, 빈 카운트 |
| 정상 JSON 사이의 손상된 중간 행 | rc0, 잘못된 행을 건너뛰고 2개로 표시 |
| 배열/null/숫자 행 | rc0, 0개로 표시 |
| schema_version과 id가 없는 객체 | rc0, 1개로 표시 |
| 깨진 graduation JSON | rc0, 빈 validators |
| 명시적인 schema_version 999 | rc1, 스키마 불일치 진단 |

status는 읽을 수 있는 dict의 버전이 존재할 때 그 값의 불일치를 검사한다. 모든 행과 필수 필드, 파일 존재, 참조·철회 관계를 인증하는 엄격한 snapshot validator는 아니다. 라이브 append의 torn-line 관용성과 확정된 committed snapshot의 무결성 요건을 분리해야 한다. Unicode 오류 등 다른 예외 가능성은 남아 있으므로 '오직 버전 오류만 실패한다'고 일반화하지 않는다.

baseline의 live_validators는 2였다. gitignore가 이미 추적 중인 파일을 제거하지 않으므로 gitignored라는 설명만으로 항상 0을 기대할 수 없다. 관측 JSONL 카운트 합은 1181이며 이것은 전체 원문의 의미·schema·참조 무결성 검토가 아니다. 20개 evidence 행을 모두 철회 레코드라고 세지 않는다. 서로 다른 자료 형식의 필수 schema_version 여부도 해당 계약으로 검증해야 한다.

status JSON을 별도 프로그램으로 파싱해 divergence를 판단할 수 있다. 다만 rc0 자체는 미저장 차이가 없다는 뜻이 아니다. ID 및 수량 비교는 같은 ID의 payload 동등성이나 실제 유효한 학습 효과를 인증하지 않는다.

## 검토·실행의 경계

Root supporting은 8개 전문과 skill_match 일부 범위로 총 9개다. test_brain_store 전문에는 합집합·철회 sidecar·버전 불일치·torn live line·graduation 재검증과 기본 status shape 검사가 있다. 실제 query의 철회 적용이나 전체 CLI 무결성을 시험한 것으로 확대하지 않는다. 원본 수동 suite는 이번에 실행하지 않았다. save/restore의 atomic_json/graduation 등 추가 실행 의존 closure를 완료하지 않고 host에서 시험하지 않는다.

실행은 네트워크 없는 immutable Docker에서 source를 읽기 전용으로 마운트하고 제한된 scratch에만 입력을 만들었다. source 1648개는 전후 동일했고 컨테이너 정리는 성공했다. 이는 실제 Windows/WSL 동작, GitHub scheduler, plugin 설치, 기기·서비스·사람 인수나 모델 자격의 증거가 아니다.

원본의 상태 읽기·명시 버전 거부·source/runtime 경로 분리·철회 보존 의도는 변형 후보로 남긴다. Zeus에서는 Git 정의와 PG 런타임 정본에 맞춰 필수 변경 분모, 엄격한 확정 데이터 검증, 실패 원문 보존과 실제 설치·복구 인수를 결속해야 한다. 전체 분석·독립 채택 검토가 끝나기 전 운영 하네스로 활성화하지 않는다.
