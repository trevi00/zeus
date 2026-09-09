# 기록 검증 이력

최초 inert inventory/원장 snapshot 명령 ba17a7은 snapshot 저장 뒤 첫 primary 본문을 stdout에 출력하는 과정에서 cp949 UnicodeEncodeError로 중단했다. 본문 출력 실패에는 독해 coverage를 부여하지 않았다. 이후 Get-Content -Encoding UTF8로 6017d9부터 모든 primary 전문을 실제 읽었다. 원본 프로그램의 실행 오류가 아니다. Python 기록기에 한국어 본문을 pipe로 전달하지 않았으며 설명은 apply_patch로 작성하고 bf48ca에서 주요 본문을 readback했다.

기록 구조는 tests006의 자체 recorder/checker를 바탕으로 scope/HEAD/32개 분모/바이트/36개 supporting 명세를 교체했다. 이전 semantic review 결론이나 전문을 재사용하지 않았다. 현재 기록기·Ruff·metadata 검사는 ad7069에서 통과했고 verification-receipt.json에 별도 남겼다. 최초 output 실패와 미완료 범위는 read-receipts.json 및 checkpoint에 보존한다. 원본 import/실행·공유 coverage·runtime·src/tests·티켓·commit/push 변경은 없다.
