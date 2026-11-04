"""Cross-platform local startup. Setup is explicit and never starts a cloud service."""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "backend" / ".venv"
PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def command(args, cwd=ROOT):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser(description="Start OptiModel Studio on http://127.0.0.1:8000")
    parser.add_argument(
        "--setup", action="store_true", help="Install isolated Python/npm dependencies and build the UI first"
    )
    parser.add_argument("--check", action="store_true", help="Check prerequisites without starting a server")
    parser.add_argument("--dev", action="store_true", help="Reload the Python backend when source changes")
    parser.add_argument("--port", type=int, default=8000, help="Loopback port (default 8000)")
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise RuntimeError("Python 3.12 or later is required. Install Python, then retry.")
    if args.setup:
        npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not npm:
            raise RuntimeError("Install Node.js 22.12+ (including npm), then retry --setup.")
        if not PYTHON.exists():
            command([sys.executable, "-m", "venv", VENV])
        command([PYTHON, "-m", "pip", "install", "-r", "backend/requirements.txt"])
        command([npm, "ci"], ROOT / "frontend")
        command([npm, "run", "build"], ROOT / "frontend")
    if not PYTHON.exists():
        raise RuntimeError("Missing local virtual environment. Run: python run.py --setup")
    command([PYTHON, "-c", "import fastapi, uvicorn, ortools, lxml, reportlab, networkx, dotenv"])
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        raise RuntimeError("Missing built UI. Run: python run.py --setup")
    if args.check:
        print("Local Python dependencies and built frontend are ready. No AI key is required.")
        return
    if not 1024 <= args.port <= 65535:
        raise RuntimeError("Use a port between 1024 and 65535.")
    print(f"OptiModel Studio: http://127.0.0.1:{args.port}  |  Ctrl+C stops the local server.", flush=True)
    command(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.port),
            *(["--reload"] if args.dev else []),
        ]
    )


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
