"""Create a local-only database credential; never print it or overwrite an existing one."""
from pathlib import Path

from codex_harness.adapters.configuration import initialize

if __name__ == "__main__":
    result = initialize(Path(__file__).resolve().parents[1])
    print("Created .env (local credential; gitignored)" if result["env_created"]
          else "Existing .env retained")
