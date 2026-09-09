#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --frozen --project "$task_root" zeus-supervisor --repository "$task_root" "$@"
