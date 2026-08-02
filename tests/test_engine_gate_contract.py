"""Contract tests: FusionDriveEngine against the real FusionOrchestrator.

The 0.1.0 production incident (every approval gate auto-recorded FAIL) lived in
the engine-orchestrator seam: the engine read the verdict off the orchestrator's
wrapper dict instead of the nested gate result, and the engine tests faked the
orchestrator with the wrong return shape. These tests run the real orchestrator
with the deterministic provider double so the seam stays pinned.
"""

from __future__ import annotations

from claude_fusion_drive.config import load_config
from claude_fusion_drive.engine import FusionDriveEngine, _gate_verdict, translate_config
from claude_fusion_drive.lifecycle import initialize_lifecycle
from relentless_inception.orchestrator import FusionOrchestrator

from tests.support import FakeProviderRegistry


def _real_orchestrator_factory(engine: FusionDriveEngine, registry: FakeProviderRegistry):
    def factory(profile_name: str | None = None):
        legacy, translated_profile = translate_config(engine.config, profile_name=profile_name)
        return FusionOrchestrator(legacy, registry=registry), translated_profile

    return factory


def test_approval_gate_pass_through_real_orchestrator(isolated_runtime, monkeypatch) -> None:
    engine = FusionDriveEngine(load_config(include_user=False))
    registry = FakeProviderRegistry()
    monkeypatch.setattr(engine, "_orchestrator", _real_orchestrator_factory(engine, registry))

    state = initialize_lifecycle(
        "workflow-contract",
        run_id="run-contract",
        plan_sha256="a" * 64,
        config_sha256="b" * 64,
    )
    result = engine.approval_gate(
        "Verify the fused plan",
        "candidate artifact",
        stage="plan",
        workflow_id="workflow-contract",
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )

    assert result["verdict"] == "PASS"
    assert result["gate"]["gate"]["passed"] is True
    assert result["gate"]["gate"]["pass_count"] == 2
    assert "run_id" in result["gate"]
    assert result["host_lifecycle"]["state"] == "awaiting_user_confirmation"
    assert result["host_lifecycle"]["gates"]["plan"]["verdict"] == "PASS"


def test_approval_gate_schema_failure_fails_closed_through_real_orchestrator(
    isolated_runtime, monkeypatch
) -> None:
    engine = FusionDriveEngine(load_config(include_user=False))
    registry = FakeProviderRegistry(invalid_verdict_seats={"grok45-gate-secondary"})
    monkeypatch.setattr(engine, "_orchestrator", _real_orchestrator_factory(engine, registry))

    result = engine.approval_gate("Verify the fused plan", "candidate artifact", stage="plan")

    assert result["verdict"] == "FAIL"
    assert result["gate"]["gate"]["passed"] is False
    assert result["gate"]["gate"]["schema_blocked"] is True


def test_gate_verdict_derivation() -> None:
    needs_work = {
        "passed": False,
        "negative_verdicts": [
            {"seat_name": "grok45-gate-primary", "verdict": {"verdict": "NEEDS_WORK"}},
            {"seat_name": "grok45-gate-secondary", "verdict": {"verdict": "NEEDS_WORK"}},
        ],
        "mechanical_blocked": False,
        "schema_blocked": False,
        "blind_spot_blocked": False,
    }
    assert _gate_verdict(needs_work) == "NEEDS_WORK"

    one_hard_fail = {
        **needs_work,
        "negative_verdicts": [
            {"seat_name": "grok45-gate-primary", "verdict": {"verdict": "FAIL"}},
            {"seat_name": "grok45-gate-secondary", "verdict": {"verdict": "NEEDS_WORK"}},
        ],
    }
    assert _gate_verdict(one_hard_fail) == "FAIL"

    mechanical_block = {**needs_work, "mechanical_blocked": True}
    assert _gate_verdict(mechanical_block) == "FAIL"

    assert _gate_verdict({"passed": True}) == "PASS"
