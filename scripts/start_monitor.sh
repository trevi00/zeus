#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --frozen --project "$task_root" zeus-monitor --repository "$task_root" "$@"
