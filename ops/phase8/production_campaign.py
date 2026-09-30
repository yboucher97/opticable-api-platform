#!/usr/bin/env python3
"""Offline Phase 8 campaign gates. No production backend or execute mode exists.

A backend supplies fresh observations from independent sources. This module
orders and validates them; it never invokes a provider, Git push, or deploy.
"""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path


GATES_PATH = Path(__file__).resolve().parents[2] / "deploy/phase8-static-release-gates.py"
spec = importlib.util.spec_from_file_location("phase8_static_release_gates", GATES_PATH)
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)

STAGES = (
    "prestage_identity",
    "baseline_recovery",
    "prepromotion_identity",
)
PRESTAGE = frozenset(STAGES[:2])


def run_campaign(authority, backend, now=None):
    """Validate ordered snapshots; stop before requesting another on failure.

    `backend.observe(stage)` must collect fresh read-only facts. The caller is
    responsible for independently sourcing and protecting those observations.
    This runner intentionally has no production backend or mutation callback.
    """
    now = datetime.now(timezone.utc) if now is None else now
    gates.validate_authority(authority, now)
    completed = []
    previous = None
    baseline_generation = None
    for stage in STAGES:
        packet = backend.observe(stage)
        expected = "prestage" if stage in PRESTAGE else "prepromotion"
        gates.require(type(packet) is dict and packet.get("stage") == expected,
                      stage + "_snapshot_stage")
        result = gates.validate_packet(authority, packet, now)
        observed = gates.timestamp(packet["observed_at"], "observation_time")
        gates.require(previous is None or observed > previous, "observation_not_newer")
        previous = observed
        if baseline_generation is None:
            baseline_generation = packet["baseline_backup"]["generation"]
        else:
            gates.require(packet["baseline_backup"]["generation"] == baseline_generation,
                          "baseline_recovery_changed")
        if stage == "baseline_recovery":
            gates.require(packet["baseline_backup"]["restore_result"] == "PASS" and
                          packet["baseline_backup"]["offhost_status"] == "download_hash_verified",
                          "baseline_recovery_incomplete")
        gates.require(result["candidate"] == gates.CANDIDATE and
                      result["release_id"] == authority["release_id"], "campaign_identity")
        completed.append(stage)
    return {"result": "PASS", "release_id": authority["release_id"],
            "candidate": gates.CANDIDATE, "completed_gates": completed,
            "deployment_authorized": False, "main_promotion_authorized": False,
            "provider_actions_authorized": False}


if __name__ == "__main__":
    import json
    print(json.dumps({"mode": "offline_only", "stages": STAGES,
                      "candidate": gates.CANDIDATE, "deployment_authorized": False,
                      "main_promotion_authorized": False,
                      "provider_actions_authorized": False}))
