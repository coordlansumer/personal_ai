"""Make backend modules importable as top-level packages (matching the
container layout where /app/backend is the working directory)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))
