# Utilities cost breakdown from landlord dashboard doesn't include all types and it seems a bit crowded (it's always for all properites and a bit small idk)... same goes for Business performance... try to improve these two views
# View History from properties doesn't do anything in the popup


# For tenants side make sure you display the type of expense when they are displayed for paying(the type and the subtype if its like utility... so they don't see only descriptions
# and on the tenant side in maintenace and transaction history tab if they don't have any data to display for that period make a button to suggest to switch to all years all months near this text "No active maintenance requests for selected period."
# And display something in their dashboard or some view where it would draw their attention if they are due to pay rent or bills (this should be color coded if the payment is super late red.... if its mid something yellow and if its paid all green
# Also they should be able to edit the maintance requests or remove them or make them obsolete idk but now on the tenant side once you write it is good as done... can't be changed or anything
# Also the landlord should be able to change the desctiption or title... add comments which the tenant should see (add some examples like this in data)
# make team members editable
# make login work
# make pagination and api pagination
# different rent for different periods


# While at it make sure you cover the bills if the tenant has the correct credit to cover their expenses and then cover the rent (the rent has to be due just to the current month, if the contract still has a lot more months we expect payment but not for the whole period just till the current day/ current rent).
# If the balance is enough to cover the rent fully, mark it as Paid.
# If there is a surplus, keep it as CarryoverCredit for the next period.
# Technical Specs:
# Ensure the logic handles Decimal types for financial accuracy (no floating point errors).
# Create a function allocate_tenant_funds(tenant_id) that returns a summary of what was paid and what remains pending.
# Provide the React frontend logic (or API response structure) to display to the tenant exactly which bills were "matched" by their payments.
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
