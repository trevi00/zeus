---
name: codetutor-real-acceptance
description: Acceptance evidence contract for Code Tutor learning scenarios; stable IDs, independent expected outcomes, real service and data paths, bounded timeouts, unknown results and human approval.
keywords: [codetutor, learning, submission, acceptance, e2e, scenario, evidence, oracle]
min_score: 3
---
Give every requirement and scenario a stable ID and write the expected outcome before running anything; an observed log line is never promoted to an expectation.

Core-flow evidence (signup or login, choose problem, submit, result, history) runs against the real service, real database and a real browser. Runs using page.route, MSW, mocked fetch or an emulator are synthetic tests: count them in a separate denominator, never as product evidence.

Each run records build identity, backend revision, data seed digest and reset receipt, and uses bounded timeouts. A timeout, network loss or unknown submission state is reported as unknown, never as success, and is never resolved by blind resubmission; reconcile the known submission ID first.

Redact tokens, passwords and personal data from receipts. Keep general, development and operations logs apart. A scenario is accepted only by a recorded human decision, not by a green run.
