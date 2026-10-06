"""Conservative model selection for harness-owned execution stages."""

from dataclasses import asdict, dataclass

from codex_harness.domain.model import require

ROUTING_POLICY = "model-routing.v2-unqualified-astra"
DESIGN_MODEL = "gpt-6-astra"
SIMPLE_IMPLEMENTATION_MODEL = "gpt-5.6-terra"
IMPORTANT_IMPLEMENTATION_MODEL = "gpt-5.6-sol"


@dataclass(frozen=True)
class ModelSelection:
    policy: str
    workload: str
    importance: str
    requested_model: str

    def receipt(self) -> dict:
        return asdict(self)


def select_model(workload: str, importance: str | None = None) -> ModelSelection:
    """Keep unqualified tasks on Astra until versioned transfer gates exist."""
    require(isinstance(workload, str)
            and workload in {"design", "implementation", "final_validation"},
            "Unknown model-routing workload")
    if workload != "implementation":
        require(importance is None or importance == "not_applicable",
                "Importance applies only to implementation work")
        return ModelSelection(ROUTING_POLICY, workload, "not_applicable", DESIGN_MODEL)

    classification = "unknown" if importance is None else importance
    require(isinstance(classification, str)
            and classification in {"simple", "important", "unknown"},
            "Unknown implementation importance")
    # INV-MODEL-001: difficulty and narrow pilot receipts are not transfer authority.
    return ModelSelection(ROUTING_POLICY, workload, classification, DESIGN_MODEL)
