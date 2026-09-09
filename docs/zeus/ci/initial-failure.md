# 첫 GitHub 검증 실패와 수정

2026-09-09 11:59 KST에 시작한 [실행 34305370090](https://github.com/trevi00/zeus/actions/runs/34305370090)은 `fc4855b9cf55d53a1420fa6c047514191b6623e6` 검증이다. Windows/Python 3.12·3.14, Ubuntu/Python 3.12·3.14 및 integration의 다섯 작업 모두 동일한 `test_baseline_reconstruction_and_semantic_preservation`에서 실패했다.

이 테스트는 과거 고정 커밋 `09c1d58298b22337125f29842382d2aef960c7d2`의 research schema를 `git show`로 읽어 의미 보존을 비교한다. 당시 Actions checkout은 기본 shallow depth 1이라 비교할 과거 Git 객체가 없었다. 실패 로그의 직접 원인은 `git show ...:src/codex_harness/resources/research.schema.json` 종료 코드 128이다. 이것은 GitHub CI의 저장소 취득 설정 결함이다.

[수정 a4449df](https://github.com/trevi00/zeus/commit/a4449df3c817da27c93e9d390aa39a30cb58defa)는 `.github/workflows/validation.yml`의 두 checkout에 `fetch-depth: 0`을 지정했다. 비교 테스트를 삭제하거나 실패를 무시하지 않았다. 14:20 KST에 완료된 [실행 34314168207](https://github.com/trevi00/zeus/actions/runs/34314168207)은 `73e15186e09863352eb11509879ae983438e59fc`에서 다섯 작업 모두 성공했다. 실패·성공 실행의 정확한 job 상태는 같은 폴더의 ID별 JSON에 보존한다.

이 성공은 해당 커밋의 GitHub 검증 결과다. 원본 Claude 하네스 전체 흡수, 삼성 기기 인수, 실제 운영 배포의 완료 증거로 확대하지 않는다. 과거 실패 실행은 이력으로 남아 있으며 최신 실행의 성공 상태와 구별한다.
