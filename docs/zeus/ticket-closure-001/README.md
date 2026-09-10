# Verified code-issue closure — 2026-09-11

Closed **#2–#9 (8 issues)** through the local lifecycle and GitHub projection. Local and remote states, signatures and comment bodies were read back and verified. **25 issues remain OPEN**; their concrete remaining criteria were posted and recorded locally as external observations.

The previous blanket explanation that all 33 issues lacked implementation/operational evidence was inaccurate. Eight bounded code-defect tickets had sufficient source review, independent Claude/Codex agreement and regression evidence. Their criteria and revisions were not weakened. Issue #10 and the broader acceptance topics were not silently reduced to merged PR scope.

## Provisioning and verification

PR #68 provisions an automation-only public signing policy. The private key remains outside Git in an ACL-restricted local operator directory. The immutable policy commit is configured in the Windows user environment and pinned by the first signed closure in PostgreSQL. No human identity, physical presence or deployment approval is claimed; the proof explicitly says configured_key_authority_only. Policy scope text is descriptive rather than an enforced issue allowlist. This batch signed only #2–#9.

Fresh local targets: **389 passed, 7 skipped**, with isolated real PostgreSQL enabled, including lifecycle, stale execution, process concurrency, outbox, SDD and skill routing tests. Skips were explicit disposable Docker and POSIX fixtures, not counted as passes. PR #68 Windows/Ubuntu/integration CI **10/10 SUCCESS**; remote integration enables the disposable Docker checks. No product source code changed for provisioning.

Each closure packet binds the unchanged ticket revision/content hash, all three original acceptance criteria, immutable evidence artifacts, merged solution commit, signing policy and lifecycle sequence. Evidence timestamps describe the current audit and fresh tests; older independent test receipts keep their original provenance. Signatures were produced and verified by real OpenSSH. Canonical packets, signatures, verification proofs and PG/GitHub readbacks are retained here. Source reviews and fixture results are not represented as actual model, human, device or host acceptance.

## Remaining issues

| Issue | Remaining work or evidence |
|---|---|
| [#1](https://github.com/trevi00/zeus/issues/1) | 전체 reference와 미커밋 자산의 의미 분석·Zeus 흡수 범위가 아직 완료되지 않았습니다. |
| [#10](https://github.com/trevi00/zeus/issues/10) | 제한된 직접 source-read 탐지의 수용과 이슈 전체의 실제 행동 검증 분모를 대조해야 합니다. 탐지 0건은 E2E 완료가 아닙니다. |
| [#11](https://github.com/trevi00/zeus/issues/11) | Git 추적 밖 자산과 기존 미커밋 full-analysis 자료의 전체 의미 분석이 남아 있습니다. |
| [#12](https://github.com/trevi00/zeus/issues/12) | 실제 배포 템플릿의 producer→validator→reader 및 Windows/Linux/WSL 기준별 종료 증거를 완성해야 합니다. |
| [#13](https://github.com/trevi00/zeus/issues/13) | 동일 시나리오·환경·guardrail에서 Astra→Sol→Terra 자격 이전과 퇴행 시 회수 실측이 남아 있습니다. |
| [#14](https://github.com/trevi00/zeus/issues/14) | 현재 후보에 결속한 필수 게이트의 실제 결과·사람 승인 범위 및 동시 재개·복구 검증이 남아 있습니다. |
| [#15](https://github.com/trevi00/zeus/issues/15) | 승인된 스펙에서 실제 앱·기기·격리 backend까지 연결한 E2E와 금전 흐름 인수가 남아 있습니다. |
| [#16](https://github.com/trevi00/zeus/issues/16) | Windows/Linux/WSL의 다중 파일 crash/lost-ack 복구와 실제 사용자 인수·독립 승인 증거를 완성해야 합니다. |
| [#17](https://github.com/trevi00/zeus/issues/17) | 실제 append/DB commit/ack/원문 정리 중단·재개 및 환경별 수집 복구·QA 인수 증거가 남아 있습니다. |
| [#18](https://github.com/trevi00/zeus/issues/18) | 현재 PC의 실제 절전·재부팅, WSL/Docker 중단 복구 및 격리 VM 시계 변경 증거가 남아 있습니다. 이번 작업에서 재부팅하지 않았습니다. |
| [#19](https://github.com/trevi00/zeus/issues/19) | 코드 결함은 #50/#67에서 해결했습니다. 현재 기준에 적힌 실제 평가·사람 시나리오 및 Windows/Linux/WSL 저장 실패·재개 증거는 별도로 충족해야 합니다. |
| [#20](https://github.com/trevi00/zeus/issues/20) | 실제 모델 호출 사용량과 같은 사용자 시나리오에서의 Astra→Sol→Terra 자격 이전 실측이 남아 있습니다. |
| [#21](https://github.com/trevi00/zeus/issues/21) | 실제 PG·프로세스·시계·권한 환경의 재시험/동시성 및 기준별 인수 증거를 완성해야 합니다. |
| [#22](https://github.com/trevi00/zeus/issues/22) | 실제 설정 적용·동시 소비·중단·되돌리기 및 제품 시나리오 검증이 남아 있습니다. |
| [#23](https://github.com/trevi00/zeus/issues/23) | 코드 검증과 별개로 Windows/Linux/WSL의 경로·프로세스 트리·PG 재시작·stale authority 종료 증거를 완성해야 합니다. |
| [#24](https://github.com/trevi00/zeus/issues/24) | 코드 결함은 #55/#67에서 해결했습니다. 현재 기준의 환경별 실제 실행·저장·알림 누락·재개와 제품 인수 증거는 별도입니다. |
| [#25](https://github.com/trevi00/zeus/issues/25) | 동일 source/environment의 실행과 사람이 검토한 실제 제품 시나리오 증거가 남아 있습니다. |
| [#26](https://github.com/trevi00/zeus/issues/26) | 실제 Docker 거부·정리 경로는 검증됐습니다. 실제 renderer/build 산출물과 사람이 검토한 핵심 SDD 시나리오 인수는 남아 있습니다. |
| [#27](https://github.com/trevi00/zeus/issues/27) | 실제 제품의 핵심 SDD 시나리오 인수와 모델 자격 이전 증거가 남아 있습니다. |
| [#28](https://github.com/trevi00/zeus/issues/28) | 실제 서비스·기기에서 사람의 핵심 사용자·실패·금전 시나리오를 검증하는 기준이 남아 있습니다. |
| [#29](https://github.com/trevi00/zeus/issues/29) | 실제 peer·저장·사용자 결과로 핵심 오류/금전 시나리오를 검증하는 기준이 남아 있습니다. |
| [#30](https://github.com/trevi00/zeus/issues/30) | 신뢰 정책 부재는 이번에 해결했습니다. 검증된 코드 이슈의 실제 종료는 완료하지만, 별도 시험 이슈의 reopen·재시도·충돌·ACK 유실 등 전체 프로토콜 인수는 아직 완료하지 않았습니다. |
| [#31](https://github.com/trevi00/zeus/issues/31) | 실제 PG export/import·배포 환경 실패 복구와 사람 핵심 시나리오 인수가 남아 있습니다. |
| [#32](https://github.com/trevi00/zeus/issues/32) | 현재 8단계 SDD의 실제 DB·API·사용자 시나리오 결과와 migration 승인 증거를 연결해야 합니다. |
| [#33](https://github.com/trevi00/zeus/issues/33) | 실제 처리 환경과 필요한 사람의 안내·동의 검토 및 제품 인수 증거가 남아 있습니다. |

The trust-policy configuration blocker is resolved. #30 remains open for the full real GitHub/PG reopen, retry, conflict and failure-path acceptance contract, not because the policy is absent. The real closures above completed verified work; they were not test closures of unresolved issues. No reboot or host interruption was performed.

The automation key has a 90-day validity period. Authenticated trust rotation remains separate work; immutable pinning was not disabled. Existing uncommitted reference-analysis material was preserved.
