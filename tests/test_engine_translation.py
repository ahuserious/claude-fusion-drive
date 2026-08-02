from __future__ import annotations

from types import SimpleNamespace

from claude_fusion_drive.config import load_config
from claude_fusion_drive.engine import (
    FusionDriveEngine,
    HybridProviderRegistry,
    translate_config,
)
from relentless_inception.execution import _remaining_budget
from relentless_inception.state import BudgetTracker
from relentless_inception.types import ModelResponse, Usage


def test_maximum_intelligence_translates_to_inherited_runtime() -> None:
    drive = load_config(include_user=False)
    legacy, profile_name = translate_config(drive, profile_name="maximum-intelligence")
    profile = legacy["profiles"][profile_name]
    assert profile["fusion"]["panel"] == [
        "grok45-panel",
        "gpt56sol-panel",
        "fable5-panel",
    ]
    assert profile["fusion"]["judge"] == "gpt56sol-judge"
    assert profile["fusion"]["synthesizer"] == "gpt56sol-fuser"
    assert profile["fusion"]["min_live_seats"] == 3
    assert legacy["seats"]["grok45-panel"]["reasoning_effort"] == "high"
    assert legacy["seats"]["gpt56sol-panel"]["reasoning_effort"] == "xhigh"
    assert legacy["seats"]["fable5-panel"]["model"] == "anthropic/claude-fable-5"
    assert profile["budgets"]["max_reasoning_tokens"] is None
    assert profile["budgets"]["max_wall_seconds"] is None


def test_gate_translation_uses_grok_reviewers_and_enabled_host_stages() -> None:
    drive = load_config(include_user=False)
    legacy, profile_name = translate_config(drive)
    gates = legacy["profiles"][profile_name]["gates"]
    assert gates["reviewers"] == ["grok45-gate-primary", "grok45-gate-secondary"]
    assert all(legacy["seats"][name]["model"] == "grok-4.5" for name in gates["reviewers"])
    assert legacy["seats"]["grok45-gate-primary"]["reasoning_effort"] == "high"
    assert "synthesis" not in gates["stages"]
    assert gates["stages"]["plan"]["enabled"] is True
    assert gates["stages"]["subagent_pre_execution"]["enabled"] is True


def test_unbounded_limits_are_explicit_in_handoff_budget_report() -> None:
    budgets = load_config(include_user=False)["profiles"]["maximum-intelligence"]["budgets"]
    remaining = _remaining_budget(
        budgets,
        {
            "calls": 2,
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 25,
            "tool_calls": 1,
            "wall_seconds": 90,
            "known_cost_usd": 0.5,
            "unknown_cost_calls": 0,
            "warnings": [],
            "provider_cost_usd": {},
        },
    )
    assert remaining["reasoning_tokens"] == {
        "limit": None,
        "consumed": 25,
        "remaining": None,
        "unbounded": True,
    }
    assert remaining["wall_seconds"] == {
        "limit": None,
        "consumed": 90.0,
        "remaining": None,
        "unbounded": True,
    }


def test_all_grok_profile_translates_two_panel_judge_fuser() -> None:
    drive = load_config(include_user=False)
    legacy, profile_name = translate_config(drive, profile_name="all-grok-4.5")
    fusion = legacy["profiles"][profile_name]["fusion"]
    assert fusion["panel"] == ["all-grok-panel-a", "all-grok-panel-b"]
    assert fusion["judge"] == "all-grok-judge"
    assert fusion["synthesizer"] == "all-grok-fuser"
    assert all(
        legacy["seats"][name]["model"] == "grok-4.5"
        for name in fusion["panel"] + [fusion["judge"], fusion["synthesizer"]]
    )


def test_subscription_profile_translates_oauth_roles_and_unknown_cost_reporting() -> None:
    drive = load_config(include_user=False)
    legacy, profile_name = translate_config(
        drive,
        profile_name="subscription-oauth",
    )
    profile = legacy["profiles"][profile_name]
    fusion = profile["fusion"]
    assert fusion["panel"] == [
        "grok45-oauth-panel",
        "grok45-oauth-panel-b",
        "fable5-oauth-panel",
    ]
    assert fusion["judge"] == "grok45-oauth-judge"
    assert fusion["synthesizer"] == "fable5-oauth-fuser"
    assert profile["gates"]["reviewers"] == [
        "grok45-oauth-gate-primary",
        "grok45-oauth-gate-secondary",
    ]
    assert profile["gates"]["max_concurrency"] == 1
    assert profile["budgets"]["unknown_cost_policy"] == "report_unknown"
    assert legacy["seats"]["grok45-oauth-judge"]["provider"] == "grok_oauth"
    assert legacy["seats"]["fable5-oauth-fuser"]["provider"] == "claude_oauth"


def test_subscription_unknown_costs_are_counted_without_blocking_later_calls() -> None:
    legacy, profile_name = translate_config(
        load_config(include_user=False),
        profile_name="subscription-oauth",
    )
    tracker = BudgetTracker(legacy["profiles"][profile_name]["budgets"])
    for seat_name, provider_name in (
        ("grok45-oauth-panel", "grok_oauth"),
        ("fable5-oauth-panel", "claude_oauth"),
    ):
        tracker.reserve_attempt("panel", seat_name)
        tracker.record(
            "panel",
            seat_name,
            ModelResponse(
                text="complete",
                provider=provider_name,
                requested_model="requested",
                actual_model="actual",
                usage=Usage(
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=None,
                ),
            ),
        )
    snapshot = tracker.snapshot()
    assert snapshot["unknown_cost_calls"] == 2
    assert snapshot["known_cost_usd"] == 0.0
    assert snapshot["stop_reason"] is None
    assert all(entry["usage"]["cost_usd"] is None for entry in snapshot["entries"])
    assert len(snapshot["warnings"]) == 2


def test_xai_claude_profile_translates_without_openrouter_routes() -> None:
    drive = load_config(include_user=False)
    legacy, profile_name = translate_config(
        drive,
        profile_name="xai-claude-oauth",
    )
    profile = legacy["profiles"][profile_name]
    fusion = profile["fusion"]
    assert fusion["panel"] == [
        "all-grok-panel-a",
        "all-grok-panel-b",
        "fable5-oauth-panel",
    ]
    assert fusion["judge"] == "all-grok-judge"
    assert fusion["synthesizer"] == "fable5-oauth-fuser"
    assert profile["gates"]["reviewers"] == [
        "grok45-gate-primary",
        "grok45-gate-secondary",
    ]
    assert profile["gates"]["max_concurrency"] == 1
    selected_seats = [
        *fusion["panel"],
        fusion["judge"],
        fusion["synthesizer"],
        *profile["gates"]["reviewers"],
    ]
    assert {
        legacy["seats"][seat_name]["provider"]
        for seat_name in selected_seats
    } == {"xai_api", "claude_oauth"}
    assert all(
        legacy["seats"][seat_name]["allow_model_fallbacks"] is False
        and legacy["seats"][seat_name]["fallback_models"] == []
        and legacy["seats"][seat_name]["fallback_seats"] == []
        for seat_name in selected_seats
    )
    assert legacy["seats"]["all-grok-panel-a"]["pricing"]["input_per_million_usd"] == 2.0


def test_xai_claude_profile_tracks_known_xai_and_unknown_claude_costs() -> None:
    legacy, profile_name = translate_config(
        load_config(include_user=False),
        profile_name="xai-claude-oauth",
    )
    tracker = BudgetTracker(legacy["profiles"][profile_name]["budgets"])
    for seat_name, provider_name, cost_usd in (
        ("all-grok-panel-a", "xai_api", 0.125),
        ("fable5-oauth-panel", "claude_oauth", None),
    ):
        tracker.reserve_attempt("panel", seat_name)
        tracker.record(
            "panel",
            seat_name,
            ModelResponse(
                text="complete",
                provider=provider_name,
                requested_model="requested",
                actual_model="actual",
                usage=Usage(
                    input_tokens=10,
                    output_tokens=2,
                    cost_usd=cost_usd,
                ),
            ),
        )
    snapshot = tracker.snapshot()
    assert snapshot["known_cost_usd"] == 0.125
    assert snapshot["provider_cost_usd"] == {"xai_api": 0.125}
    assert snapshot["unknown_cost_calls"] == 1
    assert snapshot["stop_reason"] is None


def test_hybrid_registry_forwards_oauth_attempt_and_failure_callbacks(
    monkeypatch,
) -> None:
    drive = load_config(include_user=False)
    legacy, _ = translate_config(drive, profile_name="xai-claude-oauth")
    registry = HybridProviderRegistry(legacy, drive)
    captured = {}
    before_attempt = lambda: None
    on_failure = lambda response: None

    def fake_complete(seat_name, **kwargs):
        captured["seat_name"] = seat_name
        captured.update(kwargs)
        return ModelResponse(
            text="complete",
            provider="claude_oauth",
            requested_model="claude-fable-5",
            actual_model="claude-fable-5",
            usage=Usage(cost_usd=None),
        )

    monkeypatch.setattr(registry.oauth_adapter, "complete", fake_complete)
    registry.complete(
        "fable5-oauth-panel",
        system="system",
        prompt="task",
        before_attempt=before_attempt,
        on_semantic_failure_response=on_failure,
    )
    assert captured["before_attempt"] is before_attempt
    assert captured["on_semantic_failure_response"] is on_failure


def test_openrouter_profile_enables_native_fusion_with_canonical_fallback() -> None:
    drive = load_config(include_user=False)
    legacy, profile_name = translate_config(drive, profile_name="openrouter-fusion")
    fusion = legacy["profiles"][profile_name]["fusion"]
    assert legacy["providers"]["openrouter_fusion_api"]["enabled"] is True
    assert fusion["native_openrouter_fusion"]["enabled"] is True
    assert fusion["native_fusion_seat"] == "openrouter-fusion-seat"
    assert fusion["panel"] == ["grok45-panel", "gpt56sol-panel", "fable5-panel"]
    assert legacy["seats"]["openrouter-fusion-seat"]["fusion"]["reasoning"]["effort"] == "xhigh"


def test_fuse_returns_plan_report_and_stops_at_plan_gate(
    isolated_runtime, monkeypatch
) -> None:
    class FakeResult:
        def to_dict(self):
            return {
                "run_id": "run-fake-001",
                "task_hash": "1" * 64,
                "config_hash": "2" * 64,
                "status": "completed",
                "synthesis": "A fully fused plan",
                "gate": {"passed": True, "verdict": "PASS"},
                "panel": [],
                "judge": {},
                "ledger": {"known_cost_usd": 1.25},
                "artifacts_dir": "/tmp/fake",
                "execution_handoff": {},
            }

    class FakeOrchestrator:
        def fuse(self, *args, **kwargs):
            return FakeResult()

    engine = FusionDriveEngine(load_config(include_user=False))
    monkeypatch.setattr(engine, "_orchestrator", lambda profile_name=None: (FakeOrchestrator(), "fusion_drive"))
    result = engine.fuse("Create a plan")
    assert result["synthesis"] == "A fully fused plan"
    assert result["host_lifecycle"]["state"] == "awaiting_plan_gate"
    assert result["host_lifecycle"]["host_goal_creation_tool"] == "claude_code.TaskCreate"
    assert "Mermaid" in result["next_action"]
    assert result["workflow_report"]["config"]["profiles"]["maximum-intelligence"]


def test_approval_gate_records_lifecycle_receipt(isolated_runtime, monkeypatch) -> None:
    class FakeOrchestrator:
        def adversarial_gate(self, *args, **kwargs):
            # Mirrors the real FusionOrchestrator.adversarial_gate wrapper shape:
            # pass/fail lives on the nested "gate" dict, never at the top level.
            return {
                "run_id": "run-gate",
                "artifacts_dir": "/tmp/fake-gate",
                "gate": {
                    "enabled": True,
                    "passed": True,
                    "pass_count": 2,
                    "required_passes": 2,
                    "fail_closed": True,
                    "mechanical_failures": [],
                    "mechanical_blocked": False,
                    "schema_failures": [],
                    "schema_blocked": False,
                    "negative_verdicts": [],
                    "negative_verdict_blocked": False,
                    "unresolved_blind_spots": [],
                    "blind_spot_blocked": False,
                    "deterministic_blockers": [],
                    "reviewers": [],
                },
                "ledger": {"known_cost_usd": 0.1},
            }

    engine = FusionDriveEngine(load_config(include_user=False))
    monkeypatch.setattr(engine, "_orchestrator", lambda profile_name=None: (FakeOrchestrator(), "fusion_drive"))
    fused = engine.fuse

    from claude_fusion_drive.lifecycle import initialize_lifecycle

    state = initialize_lifecycle(
        "workflow-gate",
        run_id="run-gate",
        plan_sha256="a" * 64,
        config_sha256="b" * 64,
    )
    result = engine.approval_gate(
        "task",
        "artifact",
        stage="plan",
        workflow_id="workflow-gate",
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert result["verdict"] == "PASS"
    assert result["host_lifecycle"]["state"] == "awaiting_user_confirmation"
    assert result["host_lifecycle"]["gates"]["plan"]["reviewer_models"] == [
        "grok-4.5",
        "grok-4.5",
    ]
