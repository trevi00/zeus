# Model routing

The later [progressive handoff procedure](progressive-model-handoff.md) supersedes
static difficulty-based assignment as the intended operating policy. This selector
alone is not qualification evidence; runtime promotion/fallback gates remain pending.

Deployment policy `model-routing.v2-unqualified-astra` keeps all unqualified execution
on Astra. Importance remains recorded, but cannot authorize downward transfer. The
qualification registry is still pending; the artifact pilot is not production eligibility.

The harness selects models from trusted workflow stage metadata before starting Codex. It does not
accept a model choice from model output.

| Workload | Importance | Requested model |
|---|---|---|
| Design, planning and research analysis | Not applicable | `gpt-6-astra` |
| Implementation | `simple` | `gpt-6-astra` (unqualified) |
| Implementation | `important` | `gpt-6-astra` (unqualified) |
| Implementation | Missing legacy classification (`unknown`) | `gpt-6-astra` (unqualified) |
| Independent or final validation | Not applicable | `gpt-6-astra` |

`harness improve` records an explicitly supplied `--importance simple|important` in the initial conductor assignment;
the downstream implementation reads that preserved origin. Automated source-adoption and recurrence
hook work is classified as important. Old assignments without importance are recorded as unknown and
use Astra; omitting the CLI option has the same conservative behavior. Rework assignments preserve the
original trusted classification. Unsupported classifications fail instead of falling through to the cheaper model.
Lead review forwards only the importance projection needed by conductor rework, avoiding
copies of the prior implementation payload in review feedback.

Deterministic scripts and runners remain the first choice for collection, inspection and mechanical
checks. Model routing applies only where a model judgment or implementation turn is required.

Each content-addressed execution artifact contains `model_selection`: policy version, workload,
importance and the requested model. This proves which model the harness requested, not which model
the provider actually served. Provider execution telemetry would be required to establish the latter.
The harness does not automatically fall back to a cheaper model when Astra design or validation fails.

Codex CLI 0.153.4's locally generated experimental app-server schemas expose `model` on
`thread/start`, `thread/resume` and `turn/start`; the executor supplies the selection to those calls.
This change does not alter a running production deployment.

Validation on 2026-09-08: Ruff passed; Windows suite with PostgreSQL/Redis integration
reported 528 passed and 7 skipped. Actual Docker AppServer file canaries passed for all
three requested models. The Terra canary also resumed its thread with Astra and verified
the file content. Final Python sources matched the tested image. Actual Claude CLI
supplied-source review accepted the routing change and the subsequent payload projection;
the reviewer did not execute tests. Immutable evidence and validation-driver sources:
`sha256:5ae8ca24d36e21f97515a85ecb0bf8762a04a3a525f5305f8af26f9687669395`.

An earlier Sol file-copy canary added a newline and failed exact-content comparison;
the failure is retained. Explicit byte-copy instructions passed with the same strict
comparison, as did the final image canaries. Token/cost savings have not been measured.
The queue fairness and inspection-classification issues documented in
[the autonomy observation](autonomy-observation-2026-09-08.md) remain unresolved.

## Provider responsibility routing

Which provider runs a role is separate from which Codex model is requested. Design-heavy read-only
roles MAY run on Claude through a proven read-only execution; detail, verification and
state-correctness roles stay on Codex (INV-CLAUDE-WORKER-001). The packaged policy permits these
read-only `design` pairs; none runs on Claude until the host enables it in `ZEUS_CLAUDE_ASSIGNMENTS`:

| Roles | Action | Responsibility |
|---|---|---|
| `lead:research`, `lead:improvement` | `dge_role` | council v2 research-lead proposal and improvement-lead alternative |
| `conductor` | `dge_role` | council v2 design arbitration |
| `lead:researcher`, `lead:proposer`, `lead:arbiter` | `dge_role` | v1 packet synthesis, proposal, design arbitration |
| `lead:frontdesk` | `frontdesk` | request framing |
| `lead:improvement` | `plan` | the improvement plan |

`lead:dba` and `lead:attacker` (`dge_role`), every review and decision phase, final validation,
diagnosis and the research workers stay on Codex. The writable `worker:implementation/implement`
pair is unchanged. The isolated (Docker) worker still refuses read-only runs, so an isolation-enabled
host cannot run these pairs yet.
