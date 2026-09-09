"""Original provider unavailable paths in a real networkless image; no fake CLI/SDK."""
import json
import os
import shutil
from dataclasses import asdict

from lib.providers import AskRequest, get_provider, list_aliases


def outcome(fn):
    try:
        return {"value": fn()}
    except Exception as exc:
        return {"exception": type(exc).__name__, "message": str(exc)}


def main():
    available_tools = {name: shutil.which(name) for name in ("claude", "codex", "ollama")}
    assert all(path is None for path in available_tools.values())
    assert not os.environ.get("ANTHROPIC_API_KEY")
    result = {"kind": "original_provider_unavailable_observations", "mocking": False,
              "installed_cli": available_tools, "aliases": list_aliases()}
    result["providers"] = {}
    for name in ("anthropic", "openai", "ollama"):
        provider = get_provider(name)
        result["providers"][name] = {
            "instance_returned_without_backend": True,
            "is_available": provider.is_available(),
            "ask": outcome(lambda: provider.ask(AskRequest(prompt="fixture ping"))),
        }
    result["aliases_canonical"] = {name: get_provider(name).name for name in ("CLAUDE", "CODEX")}
    result["whitespace_alias"] = outcome(lambda: get_provider(" codex "))
    result["nonstring_alias"] = outcome(lambda: get_provider(None))
    result["invalid_request_constructs"] = asdict(AskRequest(prompt=None, model=123, max_tokens=-1, temperature="invalid", system=[]))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
