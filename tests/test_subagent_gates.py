"""All eight canonical gate stages must be reachable, and documented as such.

`subagent_pre_execution` shipped in all three gate sets but had fired zero times
in the runtime while the other seven stages had all fired. The code affordance
was never missing: `approval_gate` records any stage under compare-and-swap, and
`approval_gate_start` validates the stage against the active gate set. What was
missing was the host contract -- the skill only ever told the orchestrator to
review subagents *after* completion, so nothing ever asked for the pre gate.

So the fix is a documentation change, and these are the tests that stop config
presence, code reachability, and the documented contract from diverging again.
"""

from __future__ import annotations

from pathlib import Path

from claude_fusion_drive.config import CANONICAL_GATE_STAGES, load_config
from claude_fusion_drive.lifecycle import (
    MAIN_GATE_TRANSITIONS,
    NON_TRANSITION_GATES,
    initialize_lifecycle,
    load_lifecycle,
    record_gate,
)

SKILL = (
    Path(__file__).resolve().parents[1]
    / "plugins"
    / "claude-fusion-drive"
    / "skills"
    / "claude-fusion-drive"
    / "SKILL.md"
)


def _record(workflow_id: str, state: dict, stage: str) -> dict:
    return record_gate(
        workflow_id,
        stage=stage,
        verdict="PASS",
        artifact_sha256="c" * 64,
        evidence=[f"{stage}-evidence"],
        reviewer_models=["grok-4.5", "grok-4.5"],
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )


def test_canonical_stage_constant_matches_lifecycle_and_every_gate_set() -> None:
    lifecycle_stages = {stage for _, stage in MAIN_GATE_TRANSITIONS} | NON_TRANSITION_GATES
    assert lifecycle_stages == set(CANONICAL_GATE_STAGES)

    config = load_config(include_user=False)
    for name, gate_set in config["gate_sets"].items():
        assert set(CANONICAL_GATE_STAGES).issubset(set(gate_set["stages"])), name


def test_every_canonical_stage_can_be_recorded_on_one_workflow(isolated_runtime) -> None:
    """Drive a single workflow through all eight stages under real CAS.

    Records the receipts directly rather than through a provider so the test
    stays hermetic; the point is that no stage is unreachable, which is what the
    zero-count for subagent_pre_execution suggested.
    """

    from claude_fusion_drive.lifecycle import (
        confirm_plan,
        finish_execution,
        record_claude_goal,
        start_execution,
    )

    workflow_id = "workflow-all-stages"
    state = initialize_lifecycle(
        workflow_id,
        run_id="run-all-stages",
        plan_sha256="a" * 64,
        config_sha256="b" * 64,
        synthesis_gate_receipt={
            "stage": "synthesis",
            "verdict": "PASS",
            "artifact_sha256": "a" * 64,
        },
    )
    state = _record(workflow_id, state, "plan")
    state = confirm_plan(
        workflow_id,
        confirmed=True,
        user_message_sha256="d" * 64,
        expected_plan_sha256="a" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    state = record_claude_goal(
        workflow_id,
        goal_thread_id="thread-all-stages",
        objective_sha256="e" * 64,
        host_tool=state["host_goal_creation_tool"],
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    state = _record(workflow_id, state, "pre_execution")
    state = start_execution(
        workflow_id,
        execution_scope_sha256="f" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    # The two that motivated this file: both must be recordable mid-execution.
    state = _record(workflow_id, state, "subagent_pre_execution")
    state = _record(workflow_id, state, "subagent_post_execution")
    state = finish_execution(
        workflow_id,
        result_sha256="0" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    state = _record(workflow_id, state, "post_execution")
    state = _record(workflow_id, state, "final")
    state = _record(workflow_id, state, "summarize")

    assert state["state"] == "complete"
    assert set(load_lifecycle(workflow_id)["gates"]) == set(CANONICAL_GATE_STAGES)


def test_skill_execution_checklist_names_every_canonical_gate_stage() -> None:
    """The contract gap, pinned.

    Config presence and code reachability were both already fine; the orchestrator
    was simply never told to run the pre gate.
    """

    text = SKILL.read_text(encoding="utf-8")
    missing = sorted(stage for stage in CANONICAL_GATE_STAGES if stage not in text)
    assert not missing, f"SKILL.md never names these gate stages: {missing}"


def test_skill_requires_the_subagent_scope_gate_before_dispatch() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "before dispatch" in text or "Before\n   dispatching" in text or "Before dispatching" in text
    assert "subagent_pre_execution" in text
