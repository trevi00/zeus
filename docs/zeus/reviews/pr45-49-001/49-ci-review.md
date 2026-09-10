Codex 추가 검토 — **[P2] CI 실패: 두 번 읽은 시계 값의 완전 일치를 요구함**

대상 `5165ca38b0cd5eed0cef82dd9388203086f4048e`.

실제 [PR CI run 34441283803](https://github.com/trevi00/zeus/actions/runs/34441283803)에서 Ubuntu 3.12/3.14, Windows 3.14, integration이 실패했습니다. `tests/test_execution_progress.py:90`의 `collected_at == at` 검사입니다. 예: integration에서 `05:30:35.629090`과 `05:30:35.629087`로 3µs 차이입니다.

`observe()`는 `at=utcnow(), collected_at=utcnow()`로 따로 호출합니다. 같은 수집 순간을 나타내는 호환 필드라면 한 번 읽은 값을 두 필드에 쓰고, 다른 의미라면 테스트를 그 계약에 맞춰야 합니다. Windows 3.12의 독립 관련 검사 61 passed는 이 CI 실패를 상쇄하지 않습니다. OS 시계를 변경하거나 재부팅할 필요가 없는 코드 문제입니다.
