# Add residents association tax a utility type
# Utilities cost breakdown from landlord dashboard doesn't include all types and it seems a bit crowded (it's always for all properites and a bit small idk)... same goes for Business performance... try to improve these two views
# View History from properties doesn't do anything in the popup
# in tenants tab in the table view contract/lease period "2023-01-01 | 2024-01-01" is displayed weird when the page is smaller (the text wraps in rows but dates are split (they shouldn't, try making a small container with 2 rows"
# landlord settings page has white text on white background in all fields
import os
import subprocess
import threading
import sys
import shutil
from pathlib import Path


def _start_npm_dev(cwd: Path):
    npm = shutil.which("npm")
    if not npm:
        print("npm not found on PATH", file=sys.stderr)
        return None
    return subprocess.Popen([npm, "run", "dev"], cwd=str(cwd))


def main():
    root = Path(__file__).resolve().parent

    # Start API as a separate process so it runs independently from npm
    python = sys.executable
    print(os.getcwd())
    api_cmd = [
        python,
        "-m",
        "uvicorn",
        "api:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--reload",
    ]
    try:
        api_proc = subprocess.Popen(api_cmd, cwd=str(root))
    except Exception as e:
        print(f"Failed to start API process: {e}", file=sys.stderr)
        api_proc = None

    npm_proc = _start_npm_dev(root)

    try:
        # Wait for either process to exit; if one exits, shut down the other.
        while True:
            api_ret = api_proc.poll() if api_proc else None
            npm_ret = npm_proc.poll() if npm_proc else None
            if api_ret is not None:
                print(f"API process exited with {api_ret}")
                break
            if npm_ret is not None:
                print(f"npm process exited with {npm_ret}")
                break
            # small sleep to avoid busy loop
            threading.Event().wait(2)
    except KeyboardInterrupt:
        sys.exit(0)
    finally:
        if npm_proc and npm_proc.poll() is None:
            npm_proc.terminate()
        if api_proc and api_proc.poll() is None:
            api_proc.terminate()
        sys.exit(0)
