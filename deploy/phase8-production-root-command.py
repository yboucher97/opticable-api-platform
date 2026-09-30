#!/usr/bin/env python3
"""Phase 8 health-only reconciliation hook; no checkout, restart or write path.

The production wrapper must independently collect `live` values. No adapter
is wired in this offline proposal, so invocation only prints the required plan.
"""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path


GATES_PATH = Path(__file__).with_name("phase8-static-release-gates.py")
spec = importlib.util.spec_from_file_location("phase8_static_release_gates", GATES_PATH)
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)


def verify_health_only(authority, campaign_result, live, now=None):
    """Reconcile exact post-promotion identity using fresh read-only facts."""
    now = datetime.now(timezone.utc) if now is None else now
    gates.validate_authority(authority, now)
    gates.fields(campaign_result, {"result", "release_id", "candidate",
                                   "completed_gates", "deployment_authorized",
                                   "main_promotion_authorized", "provider_actions_authorized"},
                 "campaign_result_fields")
    gates.require(campaign_result["result"] == "PASS" and
                  campaign_result["release_id"] == authority["release_id"] and
                  campaign_result["candidate"] == gates.CANDIDATE and
                  campaign_result["completed_gates"] == [
                      "prestage_identity", "baseline_recovery", "prepromotion_identity"] and
                  campaign_result["deployment_authorized"] is False and
                  campaign_result["main_promotion_authorized"] is False and
                  campaign_result["provider_actions_authorized"] is False,
                  "campaign_result_identity")
    gates.fields(live, {"observed_at", "repository", "branch", "remote_main",
                        "remote_branch", "production_sha", "production_status",
                        "diagnostic_sha256", "service_active", "local_health",
                        "public_health", "external_actions_disabled"}, "live_fields")
    observed = gates.timestamp(live["observed_at"], "live_time")
    gates.require(timedelta(0) <= now - observed <= timedelta(minutes=2), "stale_live_observation")
    gates.require(live["repository"] == gates.REPOSITORY and
                  live["branch"] == gates.BRANCH and
                  live["remote_main"] == live["remote_branch"] ==
                  live["production_sha"] == gates.CANDIDATE, "post_promotion_identity")
    gates.require(live["production_status"] ==
                  "?? ops/backup/optibrain-cloudflare-auth-diagnostic.sh" and
                  live["diagnostic_sha256"] == gates.DIAGNOSTIC_SHA256,
                  "production_integrity")
    for key in ("local_health", "public_health"):
        gates.fields(live[key], {"status", "version"}, key + "_fields")
        gates.require(live[key]["status"] == "ok" and
                      live[key]["version"] == "1.11.0", key + "_failed")
    gates.require(live["service_active"] is True and
                  live["external_actions_disabled"] is True, "operational_safety")
    return {"result": "PASS", "mode": "health_only_reconciliation",
            "sha": gates.CANDIDATE, "production_mutations": 0,
            "provider_actions_authorized": False}


if __name__ == "__main__":
    print(json.dumps({"mode": "offline_only", "health_only": True,
                      "production_mutations": 0, "provider_actions_authorized": False}))
