All 22 primary bodies read in full from `.runtime/absorption/sources/baldrix/pinned/`. No file was truncated, sampled, or partially read; no Codex/agent report, `files.json`, or prior reviewer output was opened. Consumer tracing was limited to Read/Glob/Grep on pinned host scripts. Nothing was executed, imported, installed, or written.

# Independent static review — 22 Flutter skill/experience documents

## 0. Read ledger and method limits

| Group | Files | Read state |
|---|---|---|
| `skills/flutter/3.x/` | 8 | full, complete |
| `skills/flutter/outpos-agent/` | 5 | full, complete |
| `skills/flutter/outpos/` | 9 | full, complete |

Bounded consumer/config tracing (read as evidence, not as review input): `scripts/validators/private_content_leak.py`, `scripts/validators/skill_frontmatter.py` (partial: lines 30–209, sufficient for the rules cited), `scripts/validators/git_flow.py` (grep only), `scripts/lib/git_flow_override.py` (grep only), `scripts/handlers/prompt/skill_match.py` (grep only — I did **not** read its scoring body).

**What I cannot know from this evidence.** No execution, no matcher run, no repo access. The three code repositories these documents describe (`outpos-client-agent-review`, `outpos-client-wating`, `study-outpos-agent-docs`) are **not** in the pinned set, so every line-number claim inside the outpos/outpos-agent skills is an unverified documentation claim. Vendor materials (KOVAN "VPOS NEW APP 연동 인터페이스 v1.13", EasyPOS PDF, `VposCallTest/`, `paygate-adb-commands.md`) were not acquired and **remain unreviewed**. Presence of frontmatter, tool names, or validator files does **not** establish that the host actually registers or gates these skills; I observed static consistency only.

---

## 1. Findings ordered by consequence

### S1 — Fixed database encryption key literal published in two in-scope files (highest)

`outpos/README.md:50` and `outpos/drift-lc-table-pattern.md:190-197` both publish a hardcoded SQLCipher `PRAGMA key` value in plaintext, described as the common key for **all** `outpos-*` projects. I am not reproducing the value.

Risk, stated without the literal: a single static key shared across every deployment of the product family reduces at-rest DB encryption to obfuscation; possession of any one build or of these skill files yields every store's local database, which per `drift-mt-lc-pattern.md:144-166` holds order/payment transactions (`pm_*`), VAN/terminal info (`lc_client_info`), and logs. Because the value now lives in skill documentation, it propagates into every context window, absorption artifact, and downstream review that loads these files — a much wider blast radius than source code.

The host's own leak validator does not and cannot catch this: `private_content_leak.py:103-108` skips `flutter/outpos` and `flutter/outpos-agent` entirely, and its token list (`:58-66`) contains only company/project **names** — no credential or secret pattern at all. So there is no static gate anywhere in the pinned scripts for secrets in skill trees.

Useful defenses: (a) treat the key as compromised and note that rotation is not a one-line change — it requires a re-encrypt migration path that none of the 22 documents describes; (b) in any zeus-side artifact, replace with a placeholder plus a pointer to a secret store, never the value; (c) add a secrets dimension to `private_content_leak.py` that scans **all** trees including the private ones, since the private-subtree exemption was designed for company names, not credentials. Note the doctrinal inconsistency: `easypos-integration.md:238-254` forbids plaintext hardcoded identifiers and developer backdoors, and its sibling ships a hardcoded master key.

### S2 — One validator-detectable private leak in the shared tree, plus systematic under-inclusion

`3.x/flutter-native.md:261` contains the uppercase token `OUTPOS` on a line with no pointer-OK marker. `private_content_leak.py:96` lists `flutter/3.x` as a scanned shared subtree and `:59` matches `\bOUTPOS\b`; `:127-128,139` exempts only lines carrying cross-link markers. Static prediction: `[FAIL]`. Whether the host currently fails is **unknown** — I did not run it.

More significant than the token: the same "shared" file carries company-private material the token list does not cover — a real repository URL (`:166-169`), the production channel name `app.paygate/payment` (`:30,86,102`), thirteen VAN provider codes (`:152-160`), and a 29-field payment response contract (`:131-150`). By the project's own taxonomy this belongs in `flutter/outpos*`. `paygate`, `kovan`, `koces`, and the org name are absent from `PRIVATE_TOKENS`, so the validator reports clean on the bulk of the exposure while flagging one Korean-language sentence. The gate measures the wrong surface.

### S3 — Three co-loadable skills give three different, unreconciled prescriptions

This is the most consequential structural problem for absorption:

- `3.x/dart-flutter-app.md:15,55-61` mandates Riverpod codegen, labels Provider "레거시", and bans GetX.
- `3.x/app-architecture-and-state.md:24-25,135-155` teaches `provider` + `ChangeNotifier` + `MultiProvider` as a primary implementation path.
- `outpos/state-management-pattern.md:239-242` mandates Riverpod 3 `Notifier` and treats `StateNotifier` as legacy-only.

Two incompatible `Result` designs also coexist: `dart-flutter-app.md:203-218` versus `outpos/di-and-result-pattern.md:157-179`. All of these match on overlapping keywords (`flutter`, `riverpod`, `state`, `result`), and **no frontmatter field expresses precedence, exclusivity, or mutual conflict**. A consumer that co-loads them receives contradictory canon with no arbitration rule. Before transfer, an explicit precedence or exclusivity field is required; this is a gap in the skill schema, not merely in these files.

### S4 — Git definitions contradict each other and one contradicts the enforcing validator

`git_flow.py:55` fixes `COMPANY_COMMIT_PREFIXES = ("[f/d]","[f/r]","[f/m]","[fix]","[etc]")`, activated by `git_flow_override.py:96-103` on `override: company`.

- `outpos/workflow-rules.md:20-22,124` recommends `[refactor]` and uses it in a worked example at `:221`. `[refactor]` is **not** in the validator set and **not** in `git-flow-company.md:26-33`. Commits following `workflow-rules.md` would be rejected by the company gate.
- `[f/m]` is defined twice, differently: "기능 변경" (`git-flow-company.md:31`) versus "feature/menu, 사용자 visible 기능" (`workflow-rules.md:19,120`).
- Branch models diverge: `git-flow-company.md:20-23` defines `feature/<name>`, `release-<version>`, `hotfix-<version>`; `workflow-rules.md:112-114` defines `feature/{이름}_backend` and personal-name branches, with no release or hotfix branch at all.

Adaptation decision: make `git-flow-company.md` canonical for Git definitions — it carries complete frontmatter, matches the validator set exactly, and is activation-gated by a real parser. Demote the Git sections of `workflow-rules.md:105-226` to non-normative, or reconcile `[refactor]` by adding it to the validator, not by leaving both documents live.

### S5 — Personal account identifiers

`outpos/workflow-rules.md:158-169` names two real GitHub accounts and the organization, tied to push permissions. Outside the leak validator's token set. Transfer the account-switch *procedure* abstractly; strip the identifiers.

### S6 — Insert-only legacy rule versus the operations its siblings require

`workflow-rules.md:5-8,46-101` forbids modifying existing lines. Sibling skills mandate exactly that: `drift-lc-table-pattern.md:10` requires editing `database.dart` in three places, `:168` requires a `schemaVersion` bump, and `di-and-result-pattern.md:56-70` requires appending to a shared DI class. The documents resolve this with a human "사전 승인" exception (`workflow-rules.md:8,77`; `drift-lc-table-pattern.md:186`). Under an 8-stage SDD regime that gate must become an explicit stage artifact with a recorded approver, not an implicit assumption carried in prose. Secondary, unbounded consequence: insert-only plus lazy-getter DI makes `ApplicationContext` grow monotonically forever; no document bounds this.

### S7 — Acceptance posture is incompatible with no-mock human-scenario acceptance

The documents do not merely permit mocks; they require them, and they record the absence of the real-execution paths that no-mock acceptance would need:

- `testing-matrix.md:23-31,109-137,224-225` mandates fake repositories in widget tests and warns against real services.
- `background-service-pattern.md:249-255` states the factory singleton has **no reset API**, so unit tests must substitute Mock/Fake.
- `drift-mt-lc-pattern.md:227-231` states a single `Database` singleton with **no in-memory path in current code**; `:252-258` states migration-version fixtures are **"현재 미존재"**.
- `paygate-kovan.md:230` states the payment project has **no tests at all**.
- `easypos-integration.md:283-289` requires human coordination before any real POS test.

Conclusion for the acceptance doctrine: these 22 files supply conventions plus candid admissions of missing verification. They supply **no runnable no-mock acceptance path**. This must be recorded as unverified/unknown, not as satisfied. The honest positive: the admissions are specific enough to be turned into a work list.

### S8 — PG runtime: non-contributing

No file touches PostgreSQL. Persistence is Drift/SQLite + SQLCipher (`drift-mt-lc-pattern.md`, `drift-lc-table-pattern.md`) or platform secure storage (`dart-flutter-app.md:250-262`). Transfer decision: client-side persistence only, no PG surface. One transferable caution if any of this ever informs server design — `drift-mt-lc-pattern.md:105-110` records that `stepByStep` migration steps are **not** wrapped in transactions, so partial failure leaves an inconsistent schema. That property is unacceptable under a PG-migration doctrine; do not carry the pattern across.

### S9 — External and version claims without acquired evidence

- `ci-hotfix-canon.md:112,127` pins `flutter-version: '3.41.7'` and `:15` attributes the catalog to an internal "dual-order Stage 17 + I-5 + V-3" history. I cannot verify the version's existence or currency, and the internal history is not reconstructible from the pinned set. Both are claims.
- `dart-flutter-app.md:33,42,56,110,152` repeatedly asserts "2026 표준" and "공식 추천" for Riverpod/dio/retrofit/freezed, and `:15` bans GetX outright, with no citation. `:266-284` pins version ranges. These are opinions presented as external standards.
- `paygate-kovan.md:233-242` asserts "KOVAN 공식 정보 (2026-04 실기기 검증 기준)", a vendor PDF v1.13 dated 2025-09-26, and a vendor sample project. The real-device verification is claimed execution evidence I did not observe; the PDF and sample are **unreviewed**. `:245` points to an absolute local path outside any repository — unreviewable and non-portable.
- Version-staleness signals to check rather than assert: `add-to-app-and-host-integration.md:146` uses `@UIApplicationMain` (modern templates use `@main`); `add-to-app:30,210,216`, `state-restoration.md:211`, `testing-matrix.md:233` each cite "docs 명시" without a version anchor.

### S10 — Security design issues in the integration skills

- `easypos-integration.md:318` advises **omitting authentication** on a new HTTP event route added to the live shelf server (`:316`), justified by a LAN assumption, with "check firewall rules" as the only mitigation. The exposed surface accepts POS order and payment events. Recommend requiring a shared-secret or token check before adoption regardless of network placement.
- `paygate-kovan.md:247-286` describes a self-updating APK client: `REQUEST_INSTALL_PACKAGES`, `DownloadManager`, install intent — with integrity verification **conditional** ("SHA256 검증 (서버 해시 제공 시)", `:257`) and `VersionApi` currently a mock stub returning UpToDate (`:256`). An auto-installer with optional integrity checking and no stated signature pinning or transport requirement is a supply-chain risk. Must-harden before adoption: mandatory hash **and** signature verification, enforced HTTPS, and failure-closed behavior.
- Genuinely good, worth keeping: the anti-hardcoding and anti-backdoor guidance at `easypos-integration.md:238-263` (runtime injection of store/brand codes, `kDebugMode` gating, PR review for `TEMP:`/`TODO: 개발용`), and the correct refutation at `:307-313` of a "raw TCP" misreading of the vendor spec — though that conclusion rests on a PDF I did not read.
- `paygate-kovan.md:240` carries a vendor test-TID pattern; low risk as a masked pattern, but keep it out of shared trees.

### S11 — Internal contradictions and defects in the prescriptive snippets

These matter because the snippets are templates meant to be copied.

- **Arithmetic**: `drift-mt-lc-pattern.md:25` states "총 83개 테이블: 54 MT + 19 PM + 7 LC + 4 EXT". The addends sum to 84. `outpos-agent/README.md:56` repeats the same counts. One of the two numbers is wrong and neither is checkable without the repo.
- **Self-admitted drift**: `drift-mt-lc-pattern.md:201-206` records that the code comment says 17 while the real `schemaVersion` is 18, then hardcodes 18 into the skill with no freshness marker. Any subsequent bump silently staleness the document.
- **`di-and-result-pattern.md:157-179,218-248`**: as written the snippets would not compile — `Success.voidSuccess()` performs an unchecked `'success' as S` in a `const` constructor; `Success`/`Failure` drop the parent's `E extends ErrorType` bound; and the shown three-argument `ErrorType` constructor (`:223`) is incompatible with the two-argument enum constructors that claim to implement it (`:238-248`). Prescriptive templates should compile.
- **`app-architecture-and-state.md:86-104,166-179`**: `submit()` calls `notifyListeners()` in `finally` with no cancellation and no disposal guard — precisely the "setState on disposed" failure the same file warns about at `:258-259` and demands at `:242`. Example contradicts its own quality gate.
- **`state-restoration.md:30-32` vs `:181-191`**: prose says `shouldSaveApplicationState`, code says `shouldSaveSecureApplicationState`. Same file, same fact.
- **`paygate-kovan.md:99` vs `:234`**: the KOVAN package name is "TODO (확인 필요)" in the table and a concrete value twelve lines later — a partially-updated document; a reader following the table stalls.
- **`drift-lc-table-pattern.md:61,81`**: `integer().autoIncrement().nullable()()` is self-described as non-standard for Drift. Autoincrement implies a non-null primary key; this deviation interacts with migrations. Verify against the actual Drift version before propagating.
- **`socket-action-pattern.md`**: three interacting defects are documented as known-and-unfixed — millisecond-granularity `requestId` collisions (`:84-85,177-182`), `_pendingRequests` never cleared on disconnect so awaiting callers hang forever (`:201-207`, echoed at `background-service-pattern.md:107-111`), and a 1-second send timeout (`:193-199`). Adopt only with all three corrections baked into the template; otherwise the skill teaches a known-leaky design as canon.
- **`background-service-pattern.md:281-286`**: heartbeat log suppression by substring `contains` — documented false-negative on payloads that incidentally contain the marker. `:273-279`: all eight services share the main isolate.

### S12 — Registration and matching: statically consistent, runtime unknown

Seven of the eight `3.x` files and `outpos/paygate-kovan.md` carry `keywords`/`intent`/`phase`/`min_score` but **lack `name` and `description`**. `skill_frontmatter.py:41` requires all three; `:49-51` limits FAIL severity to `mobile/`, so `flutter/**` yields WARN only. The concrete downstream effect is not cosmetic: `skill_match.py:528` renders `description` in the candidate list a consumer uses to decide whether to load a skill, so these files present an empty rationale at selection time.

The `outpos/` siblings without frontmatter are correctly exempt as content modules (`skill_frontmatter.py:94-107`, satisfied because `flutter/outpos/SKILL.md` exists). `outpos-agent/` has no `SKILL.md`, but its four content files each carry their own frontmatter and `README.md` is name-excluded (`:150-156`) — consistent. Note `outpos-agent/README.md:1-6,104,108-112` references absolute local directories that do not exist in this host; those pointers are unreviewable.

Per your constraint, I state plainly: none of this proves host registration or safety. I did not run the matcher.

---

## 2. Per-group adaptation decisions

| Group | Decision | Condition |
|---|---|---|
| `3.x/`: add-to-app, platform-channels-pigeon, state-restoration, testing-matrix | **Accept** — cleanest four; generic, no private content, decision-tree + gotcha + grep-pattern structure is sound | Add `name`/`description`; version-anchor the "docs 명시" claims; fix `state-restoration` prose/code mismatch |
| `3.x/app-architecture-and-state`, `dart-flutter-app` | **Accept with arbitration** | Resolve S3 precedence first; strip unsourced "2026 표준" assertions; fix the notify-after-dispose example |
| `3.x/ci-hotfix-canon` | **Accept as historical catalog** | Relabel the pinned toolchain version as unverified; the 13-item trap table is genuinely useful and mostly environment-invariant |
| `3.x/flutter-native` | **Relocate** to the private tree | Carries S2 company payment content; leaves a validator FAIL in a shared tree |
| `outpos/README`, `outpos/drift-lc-table-pattern` | **Quarantine** | S1 key literal; do not copy the value into any zeus artifact |
| `outpos/git-flow-company` | **Accept as canonical Git definition** | Per S4 |
| `outpos/workflow-rules` | **Accept, Git sections demoted** | Per S4/S5; strip account identifiers |
| `outpos/di-and-result-pattern`, `state-management-pattern`, `directory-and-naming` | **Accept as private convention** | Fix the non-compiling `Result`/`ErrorType` snippets before they are copied |
| `outpos/paygate-kovan`, `outpos-agent/easypos-integration` | **Pointer-only, do not adopt as-is** | S10 hardening (OTA integrity, event-endpoint auth) required first; vendor specs unreviewed |
| `outpos-agent/socket-action`, `background-service`, `drift-mt-lc`, `README` | **Accept as private convention with corrections** | S11 template fixes; all repo line-number claims flagged unverified |

---

## 3. Unresolved scope

1. **Astra/Sol/Terra qualification** — I found no definition of these designators anywhere in the material I read, and I will not infer one. The per-group table above is the transfer decision on the evidence available; mapping it onto Astra/Sol/Terra tiers is blocked pending your definitions. Everything not dependent on that mapping is complete.
2. **8-stage SDD conformance** — assessable only as the S6 tension (insert-only versus refactor stages, human approval gate needing a stage artifact). Whether these documents satisfy the eight stages cannot be judged without the stage definitions.
3. Three described repositories, all vendor documents, and the ADB cheat sheet — not acquired, unreviewed. Every line-number and behavioral claim about the live code is documentation only.
4. Whether the host currently executes `private_content_leak.py`, `skill_frontmatter.py`, or `git_flow.py` against this tree, and what they currently report — unknown by construction; no execution performed.
5. `skill_match.py` scoring semantics — grepped only; the effect of `min_score`/`patterns`/`requires` on actual selection is not established.
6. `_outpos/SKILL.md` and `_outpos/domains/SKILL.md`, referenced as parents by `outpos/SKILL.md:34-35`, exist in the pinned tree but are out of scope and unread — so the claimed parent-child skill hierarchy is unverified.
7. Whether the S1 key is still in use in any shipped build, and whether a re-encryption migration path exists — unknown and not determinable from documentation.

No closure, licensing, platform, model, human, or adoption approval is expressed or implied. These are my independent findings; delegated Codex reviews are independent, and discussion follows.