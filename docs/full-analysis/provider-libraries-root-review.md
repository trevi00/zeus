# 모델 호출·라이브러리·통합 시험 묶음의 root 검토

provider 5개는 root와 실제 Claude의 독립 검토·토론으로 대조했다. 별도 정적 검토 세 영역은 lib001 25개, lib003 10개, harness integration001 10개다. root가 각 최종 review와 lib001의 파일별 판단·중간 기록·후속 정정을 모두 읽었다. lib001 파일별 보고의 최초 출력은 중간이 잘렸으므로 1–210행을 추가로 읽어 누락을 닫았다. primary 50개와 직접 supporting 66개, 선행 primary 참조 4개를 원문 SHA/Git blob/바이트·읽기 구간과 대조했다. 이 검사는 의미적 정확성을 자동으로 증명하지 않는다.

이번 고유 primary 증가는 48개다. ac_tree와 axis_scores_log는 앞선 완료 권위 primary와 중복한다. 나머지 선행 전문 재사용 중 autopilot_state와 agent_depth는 과거 supporting이므로 이번 primary 원장 편입과 새 독해 수를 구분한다. 전체 coverage는 857/2736에 검토 기록, 1879 unreviewed다. 전문을 읽었더라도 transitive closure·실행·license·자격·채택은 여전히 미완료인 상태를 포함한다.

## root의 연결 판단

provider의 요청/default 모델 라벨과 None usage는 모델 자격·실측 비용이 아니다. 앙상블이 성공 JSON을 받았다는 사실도 객관 completeness를 대신하지 않는다. lib003의 성공 경로와 provider의 입력·오류·deadline 계약을 함께 해결해야 한다. 완료 근거 권위는 FA-018, 호출·예산·모델 실적은 신규 FA-019로 나누어 추적한다. 같은 원본 문자열이나 호스트에 실행기가 있다는 사실만으로 Astra→Sol→Terra의 자격을 부여할 수 없다.

lib001의 alert 성공은 webhook 반환 tuple을 확인하지 않고, brain push의 완료 ack는 원격 push보다 먼저 기록될 수 있다. event_store의 module-level append를 가져오려는 outcome caller와 실제 클래스 메서드의 불일치도 정적 검토에서 연결됐다. 이것들은 관측 발행, 로컬 저장, 원격 전달, 완료 수용을 별도 상태로 남겨야 하는 이유다. 모든 이벤트가 실제로 유실됐거나 사용자의 현재 원격 데이터가 손상됐다는 주장으로 확대하지 않는다.

통합 테스트라는 이름이 환경 격리나 사람 인수를 보장하지 않는다. integration001에서는 상속 GUARDIAN_HOME을 유지한 채 키를 생성/대체할 수 있는 경로와, 격리 STATE_DIR과 다른 var/ontology 경로에 쓰는 경로를 읽었다. 실제 운영 키나 원장을 읽거나 변경해 재현하지 않았다. 원본 시험을 실행하기 전 각 쓰기 대상·환경·외부 호출을 별도로 한정해야 한다.

상수 True를 검사에 포함하거나 예상 수정 바이트 대신 DIRTY 부재만 확인하는 오라클, `A and B or A` 형태의 무효한 짝 검사는 사람 시나리오를 검사했다는 증거가 아니다. 기존 조기 종료 marker·suite 발견0 방어·driver deferred 방어는 현재 존재하므로 이전 결함을 재발견한 것처럼 쓰지 않는다. partial/skip/unknown은 사전 명세의 전체 scenario ID 집합과 대조해야 한다.

6W 키워드 점수는 명세 논의를 돕는 신호이며 인간의 핵심 시나리오가 구체화됐다는 승인으로 채택하지 않는다. mockup 파일 존재, 단계 marker, 역할 카드, fixture 승인 및 합성 model command는 사용자 8단계 SDD의 제품 인수와 구분한다. 실제 사용자 VIEW·인터랙션·기능·환경·배포 및 CS 폐회로가 필요하다.

## 증거와 제한

원본 실행은 provider 폴더의 Ollama wrapper와 negative component 프로그램 두 건뿐이다. 8 assertions PASS는 CLI-absent immutable Alpine의 조건에 귀속되며 fake CLI/SDK와 실제 모델 호출은 없다. 실제 Claude는 리뷰를 수행한 별도 프로세스이며 원본 adapter가 그 모델을 호출했다고 계산하지 않는다. 세 병렬 영역은 source 실행/import/probe/test 0이다.

lib001 기록기의 초기 regex 누락 실패와 수정 성공은 metadata 작업의 역사다. 실행 당시 프로그램을 .executed.txt에 보존했고 열람용 .py의 lint 변수명만 고쳤다. 손상된 설명 문단도 UTF-8로 정정했다. 해당 실패를 upstream 시험 결과로 합산하지 않는다.

현재 Zeus 로컬 pytest는 660 passed/68 skipped다. ruff는 작성 중 기록기의 E741 4개를 발견했고 수정 후 전체 통과했다. 이는 같은 묶음의 검토 도구/Zeus 회귀 검사이며 원본 provider 플랫폼 인수와 다른 범위다. 1bce57b의 GitHub 다섯 작업 SUCCESS 영수증을 보존했다. 다음 커밋의 CI 상태는 그 커밋에서 별도로 확인한다.

전체 source·로컬 추가 경험 자산의 미검토, 각 subsystem의 실행·전이·license, 실제 Claude의 미검토 영역, 합의한 Zeus 구현·Windows/Linux/WSL 실동작·시범 운영은 남아 있다. 기존 live 하네스나 컨테이너를 제거하거나 Zeus 운영 서비스를 활성화하지 않았다.
