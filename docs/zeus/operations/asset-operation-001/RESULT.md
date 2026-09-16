# Docker 정리 후 실제 자산 흡수 운영 1건

2026-09-16. 사용자가 선택한 Claude 1회 + Codex 검토 1회 범위에서 `investigation-discipline` 원칙을 worker-v1에 흡수했다. 실제 Redis 배정 → Claude 제출 → 명령 replay → 실제 Codex 수용 → PG decision 커밋을 마치고 `asset-operation-001`은 **2/2 · awaiting_operator**로 정지했다. 새 LocalCycle 객체도 추가 실행 없이 같은 상태를 반환한다. release_queue 0, 검토 입력 보충이나 원장 상태 덮어쓰기 없음.

## 흡수와 검증

- Claude 후보 `183df72507e2f3ed83b912f6d675ab1c4908f3e8`: 프로필 본문·manifest·ADOPTION.md 세 파일만 변경. 출처는 고정 blob과 SHA-256으로 결속했다.
- 원인 주장 전 실제 증거 확인, 관측·가설·미확정 구분, 유계 재현·대조, 사용자 트리를 되돌리지 않는 회귀 검증, 정해진 범위·예산에서 정지를 지침으로 추가했다. 모든 작업에 반복 조사나 변이 시험을 요구하지 않는다.
- 본문 4,989/6,000자, 이전 출처·훅·권한·런타임 유지. 독립 집중 테스트 **19 passed**, Ruff 통과. 실제 팀장도 별도 집중 검사 19 passed와 Ruff를 확인했다. 두 수치를 합산하지 않는다.
- worker 명령 두 개는 자동 replay에서 `all_checked`. task `61deb334-94a2-4f9a-ab82-3c34d9fad1ba`, decision `2126d50f-6f95-48ee-8803-2e2bd8443825`는 succeeded/accepted.
- 관측 worker 46 + lead 24 = 70건, sink_failures/conflicts/corrupt 0. 기계 호출 원장 15회를 보존하고 이번 2회만 추가해 **17/17**이다.

이번 구현은 이전 프로필로 시작했다. 새 지침은 병합 이후 호출이 로드하며, 그 행동 개선은 아직 실측하지 않았다. 기존 테스트는 로드·digest·변조 거절·프로토콜 전달 호환성을 검증한다. 실제 모델 운영은 Windows이고 Linux는 CI 범위다. 런타임 코드 변경이 없는 지침/manifest 작업이라 로컬 전체 스위트를 반복하지 않았고, 최종 전체 CI 결과는 PR에 기록한다. 전체 자산 흡수나 장기 무인 운영 완료를 뜻하지 않는다.

## Docker 정리

Zeus PG·Redis 외에 멈춘 과거 하네스·검증 컨테이너 8개와 빈 네트워크 2개를 제거했다. 각 컨테이너의 inspect/log와 파일시스템 export를 D에 보존하고 archive 읽기·SHA-256 검증 후 정확한 ID만 제거했다. Docker가 보고한 빌드 캐시 회수량은 **2.764GB**, export 합계는 **896,974,217 bytes**다. 태그된 이미지와 볼륨 79개는 유지했다.

정리 전후 운영 컨테이너 ID·StartedAt·mounts 일치를 확인했고 PG healthy, Redis PONG이다. 재부팅·Docker 재시작·VHD 압축은 하지 않았다. Docker 내부 회수량을 Windows C 드라이브 물리적 축소량으로 주장하지 않는다.

[Docker export 문서](https://docs.docker.com/reference/cli/docker/container/export/)에 따라 export는 볼륨을 포함하지 않는다. 따라서 DB 백업 완료라는 주장은 하지 않으며, 기존 볼륨을 삭제하지 않는 것으로 데이터를 보존했다. [Docker 정리 문서](https://docs.docker.com/engine/manage-resources/pruning/)의 자원별 정리 구분을 적용했다. 두 자료는 2026-09-16에 확인했다.

운영 원본은 `D:/workspaces/zeus/artifacts/asset-operation-001/`, 정리 복구 자료는 `D:/workspaces/zeus/artifacts/docker-operation-001/`이다. 후자의 inspect/log에는 설정이 포함될 수 있어 원본을 Git에 올리지 않는다. 공개 요약 `docker-cleanup.json`, 실행 결속 `evidence-summary.json`만 추적한다. Codex가 만든 source.json의 CRLF는 최종 기록에서 LF로 정규화했고 내용은 바꾸지 않았다.
