# Context conventions — index

**Purpose.** One readable map of the durable guidance Zeus keeps, who owns each piece and how (or
whether) it ever reaches a run. **Owner:** this repository's maintainers, through ordinary review.
**When to read:** before writing or moving a guidance document, or when you need to know what a
given layer can actually decide.

This tree is documentation. Nothing here starts a loader, registers a router or activates a
release, and linking a document from here does not cause anything to read it. The authoritative
definitions stay where they already live: `docs/contracts.md` for invariants,
`src/codex_harness/domain/policy.py` for runtime limits, and the packaged resources for what is
delivered to a provider.

- [AUTHORING.md](AUTHORING.md) — how one durable guidance unit is written: one canonical owner per
  rule, predictable sections, and the metadata a packaged document needs.
- [DELIVERY.md](DELIVERY.md) — what the running system actually loads, what a human or a task must
  hand over deliberately, and what is reference-only.

## Layers

The layers are an organizing vocabulary for readers. They are not a new instruction-priority
mechanism, and a document does not gain authority by sitting in a particular folder.

| Layer | Content | Owner | How it reaches a run |
|---|---|---|---|
| L0 | Platform and user constraints: the host's directory layout, the authorized allowances, what the user asked for | the user and `AGENTS.md` | Written into the assignment or the repository; never auto-loaded from here |
| L1 | The packaged common worker profile (`worker-profile-v1.md`) | `adapters/worker_profile.py` and its manifest (INV-WORKER-PROFILE-001) | Verified by digest, then delivered as `--append-system-prompt` when `runtime.worker_profile` selects it |
| L2 | The role/task assignment, the per-run host project section and the Git-pinned project skills under `.harness/skills/` | the dispatching lead, `adapters/project_evidence.py`, `adapters/project_skills.py` and `adapters/skill_routing.py` | Composed per run by the existing selectors, inside their own separate budgets |
| L3 | Focused procedures and experience references in `docs/` | whoever owns the subject | Read on purpose, by a person or because a task names the path |
| L4 | Raw evidence in the artifact store on `D:` | the artifact store (INV-ARTIFACT-001) | Addressed by hash or run identifier through the bounded artifact reader |

A higher number is not a weaker rule and a lower number is not a licence. Platform instructions
and the user's current instructions keep their existing authority; this map cannot override them.
The profile and assignment operate within that authority, while L3 and L4 are consulted material.
For conflicting project definitions, trace the canonical owner named in `docs/contracts.md` and
correct the stale duplicate. A project contract is not permission to disregard a user instruction.

## Boundaries

- No layer instructs anyone to read this tree as a whole. This convention adds no automatic loader.
- A reference is not authority: a document that only links a rule cannot change it.
- Plans, drafts and proposals are candidates. Verified knowledge is promoted through the existing
  reviewed promotion path and lives in PostgreSQL, not in a Markdown file that claims it.
- Selected and omitted context is reported where the existing selectors already report it; this
  convention adds no new metric and claims no measured improvement in adherence or token use.
