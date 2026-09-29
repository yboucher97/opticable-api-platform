#!/usr/bin/env python3
"""Schema-V2 restoration/restart/dedupe and approval proof on disposable copies."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/workflow-api"))
spec = importlib.util.spec_from_file_location("phase6_inherited_restore", ROOT / "ops/phase5/isolated_drill.py")
inherited = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inherited)


def ready(url, process):
    import httpx
    end = time.monotonic() + 30
    while time.monotonic() < end:
        inherited.base.check(process.poll() is None, "isolated_process_early_exit")
        try:
            response = httpx.get(url + "/health", timeout=2)
            if response.status_code == 200:
                inherited.base.check(response.json()["version"] == "1.11.0", "isolated_api_version")
                return response.json()
        except httpx.TransportError:
            pass
        time.sleep(.2)
    raise RuntimeError("isolated_readiness_timeout")


def run(source, workspace):
    inherited.ready = ready  # Private import; Phase5's historical version proof remains unchanged.
    result = inherited.run(source, workspace)
    # Approval crash/restart scenarios remain fake-only, socket/DNS blocked.
    import subprocess
    process = subprocess.run([sys.executable, "-I", str(ROOT / "ops/phase6/validate.py"),
                              "--suite", "approval"], capture_output=True, text=True, timeout=180)
    inherited.base.check(process.returncode == 0, "restored_approval_regression")
    summary = json.loads(process.stdout.splitlines()[-1])
    inherited.base.check(summary["passed"] and summary["blocked_network_attempts"] == 0, "approval_network_boundary")
    result.update(api_version="1.11.0", approval_regression=summary,
                  real_provider_writes=0, customer_sends=0, books_mutations=0, lead_conversions=0)
    (workspace / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.source_db, args.workspace)))
    except Exception as error:
        print(json.dumps({"result": "FAIL", "category": str(error) if isinstance(error, RuntimeError) else type(error).__name__}))
        raise SystemExit(1)
