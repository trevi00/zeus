"""The declarative hook evaluator of the recurrence -> hook lifecycle (INV-RECURRENCE-001).

Layer: domain
Context: research
Owns: hook_apply (M7 `domain/model.py`, moved ahead in S4 unchanged: the host NativeHooks candidate validates
    through it; other contexts receive it injected, §2.4)
Does not own: the hook lifecycle (proposal, review, canary, activation: research application, S8)
Entry points: hook_apply
Contracts: INV-RECURRENCE-001
"""

from __future__ import annotations

from codex_harness.kernel.errors import require


def hook_apply(spec: dict, argv: list[str], platform: str) -> list[str]:
    """Declarative hook evaluator; only exact executable matching, never shell text."""
    if spec.get("kind") == "native_hook":
        require(spec.get("event") in {"PreToolUse", "PostToolUse", "Stop", "SessionStart"}, "Unsupported hook event")
        require(isinstance(spec.get("matcher"), str), "Hook matcher required")
        require(isinstance(spec.get("script_path"), str) and bool(spec["script_path"])
                and not spec["script_path"].startswith(("/", "\\"))
                and ".." not in spec["script_path"].replace("\\", "/").split("/")
                and ":" not in spec["script_path"], "Hook script must be repository relative")
        require(isinstance(spec.get("script_sha256"), str) and len(spec["script_sha256"]) == 64,
                "Hook script content hash required")
        return list(argv)
    require(spec.get("kind") == "executable_alias", "Unsupported hook kind")
    require(all(isinstance(spec.get(k), str) and spec[k] for k in ("match", "replacement", "platform")),
            "Invalid executable alias")
    if argv and platform == spec["platform"] and argv[0] == spec["match"]:
        return [spec["replacement"], *argv[1:]]
    return list(argv)
