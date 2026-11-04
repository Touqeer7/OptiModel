"""Isolated localhost server for browser tests; never points at user projects."""

import sys
import tempfile
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.main import create_app  # noqa: E402

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="optimodel-e2e-") as directory:
        uvicorn.run(create_app(Path(directory)), host="127.0.0.1", port=8017, log_level="warning")
