# Code Tutor 프로젝트 지침·시나리오 팩

2026-09-17. PR119 선정(`docs/zeus/operations/java-typescript-decision-001/DECISION.md`)의
후속으로, 선정된 원칙을 **프로젝트 로컬** 팩으로 만든 것이다. 원문 재배포가 아니라
독립적으로 다시 쓴 원칙이며, 앱 코드·런타임 변경, 배포, 모델 준수 주장, 사람·기기
인수는 포함하지 않는다.

## 범위와 SSOT

- 기준 저장소: `trevi00/code-tutor-ai` revision
  `0d48f06dd8860a9e9f731e7af434824779eaadd8` (읽기 전용). 검사한 파일과 선정 원칙의
  해시는 `docs/zeus/operations/code-tutor-scenario-pack-001/SOURCE.json`에 있다.
  전체 프로젝트를 검토했다는 뜻은 아니다.
- 관찰된 선언: React 19, TypeScript 5.9, Vite, Lucide, React Query, Zustand; 백엔드
  FastAPI/PostgreSQL/Redis. 선언은 설치 환경 영수증이 아니다.
- 정의의 SSOT는 Git이다. Zeus는 `adapters/project_skills.py`가 커밋된 revision의
  `.harness/tech-stack.yaml`과 `.harness/skills/`만 읽고, `adapters/skill_routing.py`가
  점수·예산·경로 identity를 정한다. SDD는 기존 `validate_spec`/`gate_report`/
  `render_review`가 스키마·8단계·검토 전용 보고서를 소유한다. 이 팩은 새 로더나
  설치 CLI를 만들지 않는다.

## 파일과 설치 경로 맵

이 디렉터리는 배포용 사본이며 활성 프로젝트 루트가 아니다. 설치 맵은 아래와 같고,
`tests/test_code_tutor_pack.py`의 실제 Git 테스트가 같은 맵을 사용한다.

| 팩 파일 | 설치 위치(새 프로젝트 루트 기준) |
|---|---|
| `profile.yaml` | `.harness/tech-stack.yaml` |
| `skills/typescript/react/experience-contract.md` | `.harness/skills/typescript/react/experience-contract.md` |
| `skills/typescript/5.x/runtime-contract.md` | `.harness/skills/typescript/5.x/runtime-contract.md` |
| `skills/common/real-acceptance.md` | `.harness/skills/_common/real-acceptance.md` |
| `sdd/learning-loop.spec.json` | 복사하지 않고 `zeus sdd inspect/view`로 검토 |

프로필은 React 19(프레임워크 버전)와 TypeScript 5.9(언어 버전)를 별도 stack으로
두고, Python/FastAPI는 버전을 측정하지 않았으므로 버전 없이 선언한다.
`project_id`는 선택 항목이며 프로젝트마다 다르게 두는 것이 맞다.

## 온보딩 (덮어쓰기 금지)

아래 절차는 문서화만 했고 이 저장소에서 실행하지 않았다. PowerShell과 bash의 등가는
문서상 대응이며 실행으로 확인한 것이 아니다.

1. **대상 확인.** 새 프로젝트 루트에 `.harness/`가 이미 있으면 복사하지 말고, 기존
   프로필과 이 팩의 `profile.yaml`을 diff로 검토해 필요한 stack만 옮긴다. 사용자가
   작성한 권위 파일을 맹목적으로 교체하지 않는다.
2. **복사.** 대상 파일이 없을 때만 복사한다.

   PowerShell:

   ```powershell
   $pack = 'D:\path\to\zeus\examples\code-tutor-ai'
   $root = 'D:\path\to\new-project'
   if (Test-Path "$root\.harness") { throw 'Existing .harness: review the diff instead of copying' }
   New-Item -ItemType Directory -Force "$root\.harness\skills\typescript\react","$root\.harness\skills\typescript\5.x","$root\.harness\skills\_common" | Out-Null
   Copy-Item "$pack\profile.yaml" "$root\.harness\tech-stack.yaml"
   Copy-Item "$pack\skills\typescript\react\experience-contract.md" "$root\.harness\skills\typescript\react\experience-contract.md"
   Copy-Item "$pack\skills\typescript\5.x\runtime-contract.md" "$root\.harness\skills\typescript\5.x\runtime-contract.md"
   Copy-Item "$pack\skills\common\real-acceptance.md" "$root\.harness\skills\_common\real-acceptance.md"
   ```

   bash:

   ```bash
   pack=/path/to/zeus/examples/code-tutor-ai
   root=/path/to/new-project
   [ -e "$root/.harness" ] && { echo 'Existing .harness: review the diff instead of copying'; exit 1; }
   mkdir -p "$root/.harness/skills/typescript/react" "$root/.harness/skills/typescript/5.x" "$root/.harness/skills/_common"
   cp -n "$pack/profile.yaml" "$root/.harness/tech-stack.yaml"
   cp -n "$pack/skills/typescript/react/experience-contract.md" "$root/.harness/skills/typescript/react/experience-contract.md"
   cp -n "$pack/skills/typescript/5.x/runtime-contract.md" "$root/.harness/skills/typescript/5.x/runtime-contract.md"
   cp -n "$pack/skills/common/real-acceptance.md" "$root/.harness/skills/_common/real-acceptance.md"
   ```

3. **커밋.** 소비 전에 반드시 커밋한다. `project_context`는 정확한 Git revision만
   읽으므로 커밋되지 않은 프로필·스킬 편집은 반영되지 않는다(테스트로 확인).
4. **확인.** 목표 문구에 `codetutor learning submission`이 포함되면 세 스킬 본문이
   모두 full tier로 선택된다. 선택 manifest에 revision과 content_ref가 남는다.

## SDD 초안 검토

```powershell
python -m zeus sdd inspect examples/code-tutor-ai/sdd/learning-loop.spec.json
python -m zeus sdd view examples/code-tutor-ai/sdd/learning-loop.spec.json --output D:\workspaces\zeus\scratch\code-tutor-review.html
```

`inspect`는 스키마 검증과 8단계 보고서를, `view`는 검토용 HTML을 만든다. 둘 다
검토 전용이며 어떤 단계도 통과시키지 않는다. 시나리오는 정확히 다섯 개다:
`SCN.ct.learning-loop`, `SCN.ct.wrong-answer`, `SCN.ct.ownership`,
`SCN.ct.interruption`, `SCN.ct.ui-states`. 사용자는 happy flow의 의도를 선택했고,
세부 GWT와 실제 실행의 사람 인수는 아직 없다.

### 8단계 완료 체크리스트

| 단계 | 현재 | 남은 일 |
|---|---|---|
| 1 스펙 논의 | 구조 검증만 됨 | 사람이 다섯 GWT의 기대값을 검토·승인 |
| 2 디자인 분석 | 토큰·스토리는 제안 | 실제 stories(loading/empty/error/success/pending) 작성 |
| 3 코드 작성 | 앱 미변경 | 후보 빌드와 build_hash 기록 |
| 4 자체 검증 | 미실행 | 격리 데이터셋·초기화 영수증·실제 브라우저 실행 |
| 5 알파 배포 | target unconfigured | alpha URL/빌드 확정 |
| 6 QA 및 증적 | 미실행 | 오라클 검토와 인증된 사람 승인 |
| 7 라이브 배포 | 없음 | 점진 배포·롤백 영수증 |
| 8 CS 대응 | 없음 | 모니터링·피드백 연결 |

### mock 대 real 분모

기준 저장소의 `frontend/e2e/problem-solve.spec.ts`는 run/submit을 구동하고 결과
문자열을 로그로 남기지만 통과 수·상태·이력 단언이 없다. page.route/MSW/emulator를
쓰는 실행은 합성 테스트로 별도 분모에 두고, 핵심 흐름 증적은 실제 서비스→DB→브라우저
경로에서만 센다. 이 팩에는 초록색으로 보이는 실행 가능한 E2E 골격을 넣지 않았다.

### 남은 것

- 사람 인수: 없음. `gate_report`의 human_accepted는 0이다.
- 기기: Samsung phone/tablet 프로필은 필수로 남기되 실기기 실행은 보류다.
- bindings: 모든 시나리오가 빈 배열이다. 셀렉터를 측정하지 않았으므로 replay를
  만들지 않는다(`export-replay`는 거부된다).
- target: kind `unconfigured`, build_hash·alpha_url null. 배포 주소나 자격 증명은
  만들지 않는다.

## 출처와 롤백

- 출처: SOURCE.json의 `selected_principles`(UI, TS-CONTRACT, WEB-AUTH, UI-TEST)를
  Code Tutor에 맞게 다시 썼다. Next.js 원칙은 프레임워크 중립 적용이며 마이그레이션이
  아니다. `moduleResolution: node20` 레시피는 채택하지 않았다.
- 롤백: 이 팩이 대상 프로젝트에 커밋한 파일(위 맵의 네 파일)만 되돌린다. 사용자가
  이미 작성한 `.harness` 내용은 건드리지 않는다.
- 기존 프로필이 있는 프로젝트로 옮길 때는 diff를 검토해 stack을 병합하고, 병합
  결과를 새 커밋으로 남긴다.
