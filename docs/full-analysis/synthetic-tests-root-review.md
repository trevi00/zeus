# Synthetic fleet와 테스트 006–008 교차 검토

이 묶음은 고정 Baldrix 소스의 신규 primary 111개다. Root는 synthetic-fleet 38개/41587바이트를 전문 독해했고 실제 Claude의 독립 검토와 후속 토론을 대조했다. 세 Codex 검토자는 테스트 73개를 전문 정적 검토했다. Root는 그 보고서와 supporting 설명을 읽었으며 73개 원문을 독립적으로 다시 읽거나 실행했다고 주장하지 않는다.

## 실행과 공동 판단

[공동 결론](baldrix-synthetic-fleet-001/resolution.md), [Claude 토론](baldrix-synthetic-fleet-001/claude-discussion.md), [원본 관측](baldrix-synthetic-fleet-001/attempts/e65fe3592ee04408b901634842c74144/stdout.txt)에 입력·출력과 정정을 보존했다. 원본 ontology 수동 테스트는 5/5 통과했고 별도 committed-fleet 관측은 4 OK/2 DRIFT/0 BLOCKED였다. 수동 테스트와 dump CLI는 총 2개 subprocess이며 나머지 helper 관측은 같은 Python 프로세스에서 실행했다. 1648개 pinned source는 실행 전후 동일하고 격리 컨테이너 정리는 성공했다.

원래 두 DRIFT는 의도된 부정 예제다. 이를 성공으로 바꾸기 위해 게이트를 약하게 하는 제안은 철회했다. 선택한 proto 필드의 집합 일치는 파일·패키지·서비스·타입의 동등성이 아니다. scratch 사본에서 amount 타입과 RPC 이름을 함께 변경해도 원본 scan 전체 결과가 같았고, 후속 Dart errorCode 타입 변경도 같은 보고서를 반환했다. 두 proto 변경을 각각 독립 실행했다고 확대하지 않는다. 정적 그래프의 공유 문자열은 실제 메시지 전달·인과성·사용자 결과가 아니다.

Java/Dart/Flutter/Gradle/protoc는 컨테이너 PATH에서 발견되지 않았다. 컴파일·서비스·기기·사람 인수는 실행하지 않았다. 원본 수동 테스트의 임시 Dart 텍스트 fixture는 실제 Dart 실행이나 사용자 인수가 아니다. parser 결과를 재현한 영수증과 실제 제품 인수 증거를 분리한다.

## 정적 테스트 검토의 후속 작업

- [tests006](baldrix-tests-006/review.md): 24개 primary와 29개 supporting. bridge section 전체 삭제 및 최신 캐시의 검사 생략, retract 실패 후 flag 소비와 성공 반환, pytest에 전달되지 않는 수동 `_ok` 실패, 예외가 없어도 통과하는 heartbeat 검사와 실제 응답을 검사하지 않는 clean Stop 경로를 확인했다. 원본 실행 0이며 현재 Zeus 결함으로 단정하지 않는다.
- [tests007](baldrix-tests-007/review.md): 23개 primary와 40개 supporting. 반복 승격의 evidence 행 중복과 고유 근거 분모, 현재 phase 결과만 전달하는 milestone 선택, HEAD와 분리된 checklist pass 이월, 마지막 checklist만 사용하는 종결 판단을 정적으로 추적했다. 실제 다단계 재현·독립 승인·사용자 인수는 후속이다.
- [tests008](baldrix-tests-008/review.md): 26개 primary와 35개 supporting. mutation 복원 실패·timeout의 판정, pane 재병합 중복 가능성, 실제 설정을 상속하는 notification 시험, 구성된 Probe·모델 문자열과 실제 실행/자격 차이를 기록했다. 원본 실행 0이다. 보고서의 fake transport 제안은 실제 인수 방식으로 채택하지 않는다. 사용자 요구에 따라 실제 격리된 전송 대상과 수신 증거를 통해 검증해야 한다.

120개 supporting 기록은 새로운 primary 수에 더하지 않는다. Root supporting 16개 중 1개는 이번 전문 독해이며 15개는 직전 전문 독해 기록의 동일 바이트·범위·보고서 해시를 재검증한 재사용이다. 세 검토자의 supporting은 각 명시 범위에 한정되며 전이 의존 전체 완료가 아니다.

## 검증과 티켓 종료 기준

[정체성 검사](synthetic-tests-checkpoint-verification.json)는 primary 111개, supporting 120개, 산출물 65개와 실제 Claude 영수증 2개 및 원본 실행 영수증 1개의 정체성을 확인했다. 의미 정확성·라이선스·모델 자격·흡수 승인을 인증하는 검사가 아니다. [로컬 검증](synthetic-tests-local-validation.json)의 Zeus 660 passed/68 skipped도 원본 하네스 전체 인수가 아니다.

사용자가 확인한 종료 기준은 **해결 구현과 해당 개정의 인수 기준 검증 후 이슈 종료**다. 현재 Zeus에는 close/reopen 및 종료 상태 동기화가 없음을 [별도 감사](../ticket-lifecycle-review.md)에 기록했다. 기존 본문 sync 성공을 양쪽 종료 완료라고 부르지 않는다. 분석·검토만 마친 개선 이슈는 열어 두며 종료 계약 구현과 실제 복구 검증을 별도 추적한다.

전체 분석·실행 closure·채택·운영 전환은 미완료다. 기존 사용자 하네스와 운영 컨테이너는 변경하지 않았다.
