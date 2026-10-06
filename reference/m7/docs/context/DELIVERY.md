# What is actually delivered, and what is only referenced

**Purpose.** Separate the context the running system composes by itself from the material a person
or a task must hand over deliberately. **Owner:** the adapters named below. **When to read:**
before claiming that a document "will be loaded", and when deciding where to put guidance so that
it reaches its reader.

## Delivered by existing code

- **The common worker profile.** `runtime.worker_profile` selects it; `load_profile` verifies the
  packaged document and hook against the manifest digests, refuses an unknown name, a mismatch, a
  document over 15000 normalized characters or a rule that widens anything but Bash, and the
  document then travels as the `--append-system-prompt` value (INV-WORKER-PROFILE-001). Delivery is
  recorded as identifiers and digests; whether the model followed the document is not judged by
  delivery, and hook receipts only show that the hook ran.
- **The per-run host project section.** When a host project-evidence profile applies to the
  checkout, `project_evidence.worker_delivery` derives the exact check commands and their exact
  Bash allow rules from the profile and the resolved checkout, and appends its
  `## Host project checks (this run)` section after the profile in the same system prompt
  (INV-PROJECT-EVIDENCE-001). It is derived from the host, never from model output.
- **Git-pinned project skills.** `project_skills.project_context` reads `.harness/tech-stack.yaml`
  and the files under `.harness/skills/` at a pinned revision, selects them for the project
  profile, lets `skill_routing` route them against the objective, and returns context items plus a
  manifest artifact naming every selected skill, its content reference and the files from which an
  omitted body can be read. A checkout with no project profile, no skills and no supported
  pipeline configuration (`.harness/stages.yaml` or `.claude/stages.yaml`) is reported as
  `not_configured` and nothing is delivered.
- **The assignment itself.** The six-W message and the task contract are the run's scope
  (INV-MESSAGE-001, INV-CONTEXT-001); required role, goal, acceptance, policy and provenance are
  never silently truncated, and composition budgets are counted in UTF-8 bytes, which is a
  conservative stand-in for tokens, not a token measurement.

Those budgets are independent of each other. The 15000-character profile ceiling bounds one
packaged document; it does not enlarge the context-composition budget, the skill-admission budget
or any research limit.

## Handed over deliberately

- A task that needs a procedure names its exact path, so the worker opens that one file.
- Evidence is passed as an artifact reference and read with the bounded artifact reader under one
  explicit store root (INV-ARTIFACT-001), rather than pasted.
- A lesson becomes standing guidance only through the existing reviewed promotion path; writing it
  into a document does not promote it.

## Reference-only

This convention tree is reference material for people and tasks that need it. These conventions
add no runtime traversal, link expansion or recursive loading, and a folder name selects no role.
Existing source inspection may read documentation as data; that is not automatic instruction
delivery. To require guidance in a run, use its existing delivery owner or name the document in
the assignment. Writing a new loading mechanism in prose does not implement one.

## Verifying a claim about delivery

`tests/test_worker_profile.py` exercises profile verification, delivery and receipts against the
protocol child fixture; `tests/test_project_delivery.py` covers the host project section beside the
profile; `tests/test_worker_profile_metadata.py` covers the packaging metadata command. Those are
fixture transports: they prove what the adapters send, not what a model did with it. A real
provider observation is recorded separately as an operation canary.
