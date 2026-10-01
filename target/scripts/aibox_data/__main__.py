"""`uv run python scripts/aibox_data <command>` (or `python -m aibox_data` with scripts/ on the path)."""
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from aibox_data.cli import main
else:
    from .cli import main

sys.exit(main())
