"""PropFlow dev launcher — canonical entry point (task C6).

Starts the FastAPI backend and the Vite dev server together and ties their
lifetimes: when one exits, the other is torn down.

    cd PropFlow
    uv sync           # once, or after pyproject/uv.lock changes
    uv run python main.py     # or:  python main.py   (if the env is already active)

Ports:
  - API   : $PROPFLOW_API_PORT (default 8000)
  - Vite  : whatever `npm run dev` picks (see ../vite.config.ts)

Prod (systemd, static bundle, port 8100) is task D6's concern — kept out of here.

The frontend repo also has a gitignored root `main.py` shim that just does
`from PropFlow.main import main` so `python main.py` from the repo root still works.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path


def _start_npm_dev(cwd: Path) -> subprocess.Popen | None:
    npm = shutil.which("npm")
    if not npm:
        print("npm not found on PATH — skipping the Vite dev server", file=sys.stderr)
        return None
    return subprocess.Popen([npm, "run", "dev"], cwd=str(cwd))


def _start_fastapi(cwd: Path) -> subprocess.Popen | None:
    port = os.environ.get("PROPFLOW_API_PORT", "8000")
    # Prefer `uv run` so the API uses the locked env (task C6); fall back to the
    # current interpreter when uv isn't on PATH.
    uv = shutil.which("uv")
    base = [uv, "run", "--"] if uv else [sys.executable, "-m"]
    cmd = [*base, "uvicorn", "api:app", "--host", "0.0.0.0", "--port", port, "--reload"]
    try:
        return subprocess.Popen(cmd, cwd=str(cwd))
    except Exception as e:  # noqa: BLE001 - report and continue with npm only
        print(f"Failed to start the API process: {e}", file=sys.stderr)
        return None


def main() -> None:
    # Backend lives next to this file; the frontend (npm) is one level up.
    backend = Path(__file__).resolve().parent
    frontend = backend.parent

    processes: dict[str, subprocess.Popen | None] = {
        "api": _start_fastapi(backend),
        "npm": _start_npm_dev(frontend),
    }

    try:
        # When any child exits, stop waiting and let `finally` clean up the rest.
        while True:
            for name, proc in processes.items():
                if proc is not None and proc.poll() is not None:
                    print(f"{name} process exited with {proc.returncode}")
                    return
            threading.Event().wait(2)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in processes.values():
            if proc is not None and proc.poll() is None:
                proc.terminate()


if __name__ == "__main__":
    main()
