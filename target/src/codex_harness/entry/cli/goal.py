"""The `zeus goal` argument parser (M7 cli.py).

Layer: entry
Owns: add_parser (the argument shape of `zeus goal`), run (its body: M7 goal_command) and _json_file
Does not own: dispatch (entry.cli main) and composition (composition)
Entry points: add_parser, run
Contracts: none

Moved from M7 cli.py:382-388 (SOURCE e38aa722) by named rules (A/evidence/rebuild/s10/unit-p/transcribe.py); the parser statements are M7's verbatim. `run` is M7 `goal_command` (SOURCE cli.py:402-408) and `_json_file` is cli.py:392-399 verbatim; `report` builds the service (S10 unit C2a).
"""

from pathlib import Path


def add_parser(commands) -> None:
    goal = commands.add_parser("goal", help="Goal manifest progress: read-only report and same-definition compare")
    goal_commands = goal.add_subparsers(dest="goal_command", required=True)
    report = goal_commands.add_parser("report", help="Observe criterion closure state; no completion authority")
    report.add_argument("manifest", type=Path)
    compare = goal_commands.add_parser("compare", help="Gained/regressed criteria between two reports of one definition")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)


def _json_file(path):
    import json

    from codex_harness.kernel.errors import ContractError, require
    try:
        require(path.stat().st_size <= 1024 * 1024, "Goal file exceeds budget")
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError("Goal file unavailable") from exc
    except json.JSONDecodeError as exc:
        raise ContractError("Goal file is not valid JSON") from exc


def run(args) -> None:
    # INV-GOAL-PROGRESS-001: store read only; no executor, observer, bus or provider is built. `goal compare` is store-free:
    # M7 tried it before `build()` (SOURCE cli.py:709-711), so `build()` runs only for `report`.
    from codex_harness.entry.cli.output import emit
    from codex_harness.intake.application.goal_progress import GoalProgress, compare_reports
    if args.goal_command == "report":
        from codex_harness.composition import build
        service = build()
        emit(GoalProgress(service.store).report(_json_file(args.manifest)))
    else:
        emit(compare_reports(_json_file(args.before), _json_file(args.after)))
