# 직접 지원 독해

- scripts/lib/mirror_drift.py 100~162, 178~240: manifest의 extractor/scopes가 실제 설정이며 scan은 같은 HEAD/clean tree/schema에서 파일 재독해 없이 fingerprint_match=True를 반환한다. git unavailable도 True와 unverifiable=True, 예외는 marker=False inert라서 단일 bool 소비는 위험하다. regenerate는 mode를 coarse로 바꾸기 전에 hash를 계산하여 기존 normalized scope 선언을 변형하면 저장 mode와 계산 hash가 어긋날 수 있다. manifest를 먼저 쓰고 structure/cargo/narrative를 뒤에 실행하므로 부분 성공이 남는다. 나머지 validate_manifest, write/narrative helper 전체는 이번 미독이며 선행 ledger 재사용으로 충당하지 않았다.
- scripts/tests/test_mirror_drift.py 1~196: fixture git init/add, regenerate 후 같은 compute 함수와 set equality, 주석/indent 무변경, body/URL 변경 stale, root detection, clean fast path를 검사한다. 같은 알고리즘 재계산은 정규화 충돌의 독립 오라클이 아니다. raw multiline string, 문자열 공백, 비UTF8/CRLF, rename, unreadable 파일 검사는 읽은 범위에 없다. git가 없으면 main은 0 passed/0 failed skipped를 출력하고 0 반환한다. test helper Git text 디코딩은 명시 UTF8이 아니며 fixture 명령 rc도 대부분 검사하지 않는다. 197~228 미독, 전체 실행0.

지원 범위는 supporting-evidence.json의 원시 해시에 결속한다. 기본 구성은 primary registry/scopes, 동적 manifest는 읽은 caller에서만 추적했다. 외부 문서/라이선스 및 실제 OS/cargo/모델 동등성은 확인하지 않았다. 검색 결과는 전문 대신 사용하지 않았다.
