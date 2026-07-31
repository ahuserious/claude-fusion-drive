from __future__ import annotations

import json

import pytest

from claude_fusion_drive.errors import LifecycleError
from claude_fusion_drive.lifecycle import (
    confirm_plan,
    finish_execution,
    initialize_lifecycle,
    lifecycle_path,
    lifecycle_summary,
    load_lifecycle,
    record_claude_goal,
    record_gate,
    start_execution,
)
from claude_fusion_drive.util import canonical_hash


def _initialize() -> dict:
    return initialize_lifecycle(
        "workflow-001",
        run_id="run-001",
        plan_sha256="a" * 64,
        config_sha256="b" * 64,
        synthesis_gate_receipt={
            "stage": "synthesis",
            "verdict": "PASS",
            "artifact_sha256": "a" * 64,
        },
    )


def _gate(state: dict, stage: str, verdict: str = "PASS") -> dict:
    return record_gate(
        "workflow-001",
        stage=stage,
        verdict=verdict,
        artifact_sha256="c" * 64,
        evidence=[f"{stage}-evidence"],
        reviewer_models=["grok-4.5", "grok-4.5"],
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )


def test_full_plan_goal_execution_gate_lifecycle(isolated_runtime) -> None:
    state = _initialize()
    assert state["state"] == "awaiting_plan_gate"
    state = _gate(state, "plan")
    assert state["state"] == "awaiting_user_confirmation"
    state = confirm_plan(
        "workflow-001",
        confirmed=True,
        user_message_sha256="d" * 64,
        expected_plan_sha256="a" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert state["state"] == "awaiting_claude_goal"
    state = record_claude_goal(
        "workflow-001",
        goal_thread_id="thread-001",
        objective_sha256="e" * 64,
        host_tool="create_goal",
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert state["state"] == "awaiting_pre_execution_gate"
    state = _gate(state, "pre_execution")
    assert state["state"] == "ready_for_execution"
    state = start_execution(
        "workflow-001",
        execution_scope_sha256="f" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert state["state"] == "executing"
    state = finish_execution(
        "workflow-001",
        result_sha256="1" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert state["state"] == "awaiting_post_execution"
    state = _gate(state, "post_execution")
    state = _gate(state, "final")
    state = _gate(state, "summarize")
    assert state["state"] == "complete"
    assert lifecycle_summary("workflow-001")["next_action"] == "Workflow is complete."


def test_goal_cannot_be_recorded_before_confirmation(isolated_runtime) -> None:
    state = _initialize()
    with pytest.raises(LifecycleError, match="cannot be recorded"):
        record_claude_goal(
            "workflow-001",
            goal_thread_id="thread-001",
            objective_sha256="e" * 64,
            host_tool="create_goal",
            expected_lifecycle_sha256=state["lifecycle_sha256"],
        )


def test_confirmation_requires_exact_plan_hash(isolated_runtime) -> None:
    state = _gate(_initialize(), "plan")
    with pytest.raises(LifecycleError, match="plan hash"):
        confirm_plan(
            "workflow-001",
            confirmed=True,
            user_message_sha256="d" * 64,
            expected_plan_sha256="9" * 64,
            expected_lifecycle_sha256=state["lifecycle_sha256"],
        )
    with pytest.raises(LifecycleError, match="confirmed=true"):
        confirm_plan(
            "workflow-001",
            confirmed=False,
            user_message_sha256="d" * 64,
            expected_plan_sha256="a" * 64,
            expected_lifecycle_sha256=state["lifecycle_sha256"],
        )


def test_goal_receipt_requires_host_create_goal_tool(isolated_runtime) -> None:
    state = _gate(_initialize(), "plan")
    state = confirm_plan(
        "workflow-001",
        confirmed=True,
        user_message_sha256="d" * 64,
        expected_plan_sha256="a" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    with pytest.raises(LifecycleError, match="create_goal"):
        record_claude_goal(
            "workflow-001",
            goal_thread_id="thread-001",
            objective_sha256="e" * 64,
            host_tool="shell",
            expected_lifecycle_sha256=state["lifecycle_sha256"],
        )


def test_new_lifecycle_binds_codex_create_thread_receipt(isolated_runtime) -> None:
    state = initialize_lifecycle(
        "workflow-thread-tool",
        run_id="run-thread-tool",
        plan_sha256="a" * 64,
        config_sha256="b" * 64,
        profile_name="subscription-oauth",
        engine_name="subscription_oauth",
        host_goal_creation_tool="claude_code.TaskCreate",
    )
    state = record_gate(
        "workflow-thread-tool",
        stage="plan",
        verdict="PASS",
        artifact_sha256="c" * 64,
        evidence=["workflow report"],
        reviewer_models=["grok-4.5", "grok-4.5"],
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    state = confirm_plan(
        "workflow-thread-tool",
        confirmed=True,
        user_message_sha256="d" * 64,
        expected_plan_sha256="a" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    with pytest.raises(LifecycleError, match="claude_code.TaskCreate"):
        record_claude_goal(
            "workflow-thread-tool",
            goal_thread_id="thread-wrong-tool",
            objective_sha256="e" * 64,
            host_tool="create_goal",
            expected_lifecycle_sha256=state["lifecycle_sha256"],
        )
    state = record_claude_goal(
        "workflow-thread-tool",
        goal_thread_id="thread-created",
        objective_sha256="e" * 64,
        host_tool="claude_code.TaskCreate",
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert state["claude_goal"]["thread_id"] == "thread-created"
    assert state["claude_goal"]["host_tool"] == "claude_code.TaskCreate"
    assert state["state"] == "awaiting_pre_execution_gate"


def test_legacy_lifecycle_without_bound_tool_still_accepts_create_goal(
    isolated_runtime,
) -> None:
    state = _gate(_initialize(), "plan")
    state = confirm_plan(
        "workflow-001",
        confirmed=True,
        user_message_sha256="d" * 64,
        expected_plan_sha256="a" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    path = lifecycle_path("workflow-001")
    legacy_state = json.loads(path.read_text())
    legacy_state.pop("host_goal_creation_tool")
    hash_input = dict(legacy_state)
    hash_input.pop("lifecycle_sha256")
    legacy_state["lifecycle_sha256"] = canonical_hash(hash_input)
    path.write_text(json.dumps(legacy_state))
    state = record_claude_goal(
        "workflow-001",
        goal_thread_id="legacy-thread",
        objective_sha256="e" * 64,
        host_tool="create_goal",
        expected_lifecycle_sha256=legacy_state["lifecycle_sha256"],
    )
    assert state["claude_goal"]["host_tool"] == "create_goal"
    assert lifecycle_summary("workflow-001")["host_goal_creation_tool"] == "create_goal"


def test_compare_and_swap_rejects_stale_receipt(isolated_runtime) -> None:
    state = _initialize()
    stale_hash = state["lifecycle_sha256"]
    _gate(state, "plan")
    with pytest.raises(LifecycleError, match="Stale lifecycle receipt"):
        record_gate(
            "workflow-001",
            stage="plan",
            verdict="PASS",
            artifact_sha256="c" * 64,
            evidence=[],
            reviewer_models=["grok-4.5"],
            expected_lifecycle_sha256=stale_hash,
        )


def test_subagent_gates_do_not_skip_main_state(isolated_runtime) -> None:
    state = _initialize()
    state = _gate(state, "subagent_pre_execution")
    assert state["state"] == "awaiting_plan_gate"
    state = _gate(state, "subagent_post_execution")
    assert state["state"] == "awaiting_plan_gate"


def test_failed_gate_does_not_advance(isolated_runtime) -> None:
    state = _gate(_initialize(), "plan", verdict="NEEDS_WORK")
    assert state["state"] == "awaiting_plan_gate"
    assert state["gates"]["plan"]["verdict"] == "NEEDS_WORK"
    state = _gate(state, "plan", verdict="PASS")
    assert state["state"] == "awaiting_user_confirmation"


def test_lifecycle_hash_chain_detects_tampering(isolated_runtime) -> None:
    _initialize()
    path = lifecycle_path("workflow-001")
    value = json.loads(path.read_text())
    value["events"][0]["payload"]["run_id"] = "tampered"
    path.write_text(json.dumps(value))
    with pytest.raises(LifecycleError, match="hash"):
        load_lifecycle("workflow-001")


def test_initialization_is_idempotent_for_same_immutable_inputs(isolated_runtime) -> None:
    first = _initialize()
    second = _initialize()
    assert first == second
    assert len(second["events"]) == 1
