# Python 자식 프로세스 기계 채널 인코딩 계약

기존 FA-001 / GitHub [#2](https://github.com/trevi00/zeus/issues/2) / `ZEUS-ba0de9a2623e` 개정 1의 수정입니다.
Zeus가 띄우는 Python 자식(릴리스 후보의 incumbent·candidate pytest, 네이티브 훅 카나리아)은
Windows에서 콘솔 코드 페이지(cp949)를 따라 stdio를 인코딩했습니다. 부모 `run_process`는 UTF-8로만
디코딩하므로 cp949로 표현할 수 없는 문자(예: U+2014)는 자식이 `UnicodeEncodeError`로 종료 1이 되거나,
stdin 방향에서는 **종료 0인 채로 바이트가 깨진 채** 돌아왔습니다. 새 이슈나 분석 후보는 추가하지 않았습니다.

## 변경

- `adapters/commands.py`: `python_channel_environment(base=None)` — 주어진 환경 사본에
  `PYTHONIOENCODING=utf-8`만 결속합니다. `PYTHONUTF8`은 건드리지 않습니다. UTF-8 모드는 자식이
  다른 프로그램의 출력·파일명을 디코딩하는 방식까지 바꾸므로 이 계약의 범위가 아닙니다.
- `adapters/verification.py`: `verification_environment`가 허용목록으로 상속 `PYTHONIOENCODING`/
  `PYTHONUTF8`을 제거한 뒤 채널을 명시적으로 결속합니다. 릴리스 pytest(`deployment.py`)는 이 환경을
  그대로 받습니다.
- `adapters/hooks.py`: 훅 카나리아 자식(`sys.executable script`)에 같은 환경을 전달합니다.
  case 입력은 stdin, 출력은 stdout으로 양방향 UTF-8입니다.
- `docs/contracts.md`: `INV-ENCODING-001` 추가.

결속하지 않은 경로와 그 이유:

- 외부 프로그램(`docker`, `git`, `gh`, `codex`)과 `zeus run-command`의 임의 argv: Python이 아니거나
  Python인지 알 수 없는 자식입니다. 교차검토 합의는 "Python 기계 채널에 명시 계약"이지 모든 프로그램의
  인코딩을 무조건 바꾸는 조치가 아닙니다.
- `NativeHooks.configuration()`이 Codex에 넘기는 훅 명령과 `scripts/verify_runtime.py`의 훅: 자식을
  띄우고 출력을 디코딩하는 쪽이 Zeus의 `run_process`가 아니라 Codex 앱 서버입니다. 그 디코더의 계약은
  이번 프로브로 재지 않았으므로 증거 없이 결속하지 않습니다. 현재 훅 출력은 ASCII JSON입니다.
- `scripts/host_cycle.py`의 worker: stdout/stderr를 파일에 바이트 그대로 기록하며 디코딩하지 않습니다.
- 컨테이너 안의 Python(`source_execution.py`): Linux 로케일 계약이며 별도 측정하지 않았습니다.

## 재현과 검증

- `probe.py`: 실제 `run_process`·`verification_environment`를 거쳐 현재 인터페이스를 `-X utf8=0`
  자식으로 실행합니다. 원본 교차검토 프로브와 같은 리터럴 출력 형태와, 훅 카나리아와 같은 stdin 왕복
  형태를 각각 기록합니다. DB·릴리스·Codex·GitHub는 호출하지 않습니다.
- `baseline.json`: 수정 전 소스(`origin/main` `0c66a67`의 `commands.py`/`verification.py`/`hooks.py`)로
  같은 프로브를 실행한 영수증. 6개 실행 모두 실패 또는 손상 — 리터럴은 rc 1 `UnicodeEncodeError`,
  왕복은 rc 0이지만 stdout이 기대값과 다름(`verification_environment` 포함).
- `windows-probe.json`: 수정 후 영수증. `verification_environment`·`python_channel_environment`의
  4개 실행이 모두 rc 0, stdout이 `utf-8\n검증 — 완료\n`와 일치. 계약 없이 상속한 환경과 cp949
  명시 환경은 실패 대조군으로 그대로 실패합니다.
- `tests/test_python_channel.py`: 실제 자식 프로세스로 양방향 왕복 성공과, 결속 없는 같은 자식의
  `UnicodeEncodeError`/`UnicodeDecodeError` 실패 대조군. 환경 문자열 검사만으로 통과하지 않습니다.
- `tests/test_native_hooks.py::test_canary_channel_carries_non_locale_text_both_ways`: 실제 훅 스크립트를
  카나리아 경로로 실행해 cp949 밖 문자를 양방향 전달합니다.
- `tests/test_verification.py`: cp949 부모 환경에서도 릴리스 pytest 환경이 `utf-8`로 결속되고
  `PYTHONUTF8`이 상속되지 않음.
- 음성 대조: `hooks.py`/`verification.py`만 수정 전으로 되돌리면 위 신규 검사 4건이 실패함을 확인했습니다.
- Windows 전체 회귀: 아래 표. Linux 경로는 이 PR의 CI(ubuntu 매트릭스)로 확인하며 이 기록 시점에는 미실행입니다.

| 항목 | 결과 |
|---|---|
| 타깃 검사 (`test_python_channel`, `test_verification`, `test_native_hooks`) | 30 passed, 1 skipped |
| Windows 전체 `uv run pytest -q` (Python 3.12.14) | 917 passed, 305 skipped (155s) |
| `uv run ruff check .` | 통과 |

## 남은 범위

- Windows 콘솔 호스트에 직접 붙은 자식 출력(파이프가 아닌 경우)과 실제 릴리스 후보의 전체 거부→통과
  흐름은 이번 측정에 포함되지 않았습니다. 프로브는 파이프 채널만 잽니다.
- 이슈 종료는 Codex·Claude 독립 검토와 해당 개정 인수 기준 확인 뒤 [#30](https://github.com/trevi00/zeus/issues/30)
  범위의 종료 경로를 따릅니다. 이 기록은 구현·검증 증거이며 배포 승인이 아닙니다.
