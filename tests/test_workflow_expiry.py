"""Abandoned workflows must be discoverable and closable.

Before this, lifecycle.py had no expiry, staleness or abort path at all, so a
workflow abandoned at `awaiting_plan_gate` sat there forever with no way to find
it (the MCP surface had no listing tool) and no way to close it.

Staleness is a read-time view and abort is a persisted compare-and-swap
transition. That asymmetry is load-bearing: `lifecycle_status` is how a caller
obtains `expected_lifecycle_sha256`, so a read that wrote would invalidate its
own output.
"""

from __future__ import annotations

import json

import pytest

from claude_fusion_drive.errors import LifecycleError
from claude_fusion_drive.lifecycle import (
    WORKFLOW_EXPIRY_SECONDS,
    abort_workflow,
    confirm_plan,
    initialize_lifecycle,
    lifecycle_path,
    lifecycle_summary,
    list_workflows,
    load_lifecycle,
    record_gate,
)
from claude_fusion_drive.util import canonical_hash

import mcp_server


def _initialize(workflow_id: str = "workflow-expiry") -> dict:
    return initialize_lifecycle(
        workflow_id,
        run_id=f"run-{workflow_id}",
        plan_sha256="a" * 64,
        config_sha256="b" * 64,
    )


def _gate(workflow_id: str, state: dict, stage: str) -> dict:
    return record_gate(
        workflow_id,
        stage=stage,
        verdict="PASS",
        artifact_sha256="c" * 64,
        evidence=[f"{stage}-evidence"],
        reviewer_models=["grok-4.5", "grok-4.5"],
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )


def _age_on_disk(workflow_id: str, seconds: float) -> dict:
    """Rewrite updated_at to `seconds` ago and repair the hash, as the suite does elsewhere.

    Ageing the file rather than patching the clock keeps the test hermetic and
    free of sleeps.
    """

    from datetime import datetime, timedelta, timezone

    path = lifecycle_path(workflow_id)
    state = json.loads(path.read_text())
    state["updated_at"] = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    hash_input = dict(state)
    hash_input.pop("lifecycle_sha256")
    state["lifecycle_sha256"] = canonical_hash(hash_input)
    path.write_text(json.dumps(state))
    return state


def test_abort_is_terminal_and_preserves_the_hash_chain(isolated_runtime) -> None:
    state = _initialize()
    events_before = json.loads(json.dumps(state["events"]))

    aborted = abort_workflow(
        "workflow-expiry",
        reason="Superseded by a re-planned run",
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )

    assert aborted["state"] == "aborted"
    assert aborted["abort"]["state_before"] == "awaiting_plan_gate"
    assert aborted["abort"]["reason"] == "Superseded by a re-planned run"
    # Nothing is rewritten or removed: the prior chain is byte-identical and the
    # abort is appended after it.
    assert aborted["events"][: len(events_before)] == events_before
    assert aborted["events"][-1]["event_type"] == "workflow_aborted"
    assert lifecycle_path("workflow-expiry").exists()
    assert load_lifecycle("workflow-expiry")["state"] == "aborted"


def test_abort_requires_a_reason_and_the_current_lifecycle_hash(isolated_runtime) -> None:
    state = _initialize()
    with pytest.raises(LifecycleError, match="explicit reason"):
        abort_workflow(
            "workflow-expiry", reason="   ", expected_lifecycle_sha256=state["lifecycle_sha256"]
        )
    with pytest.raises(LifecycleError, match="Stale lifecycle receipt"):
        abort_workflow("workflow-expiry", reason="cleanup", expected_lifecycle_sha256="f" * 64)


def test_aborted_workflow_rejects_further_gates(isolated_runtime) -> None:
    state = _initialize()
    state = abort_workflow(
        "workflow-expiry", reason="cleanup", expected_lifecycle_sha256=state["lifecycle_sha256"]
    )

    with pytest.raises(LifecycleError, match="aborted"):
        _gate("workflow-expiry", state, "plan")
    # The one that matters: subagent stages are non-transition gates, so they
    # bypass the usual illegal-transition rejection and need the explicit guard.
    with pytest.raises(LifecycleError, match="aborted"):
        _gate("workflow-expiry", state, "subagent_pre_execution")


def test_abort_rejects_an_already_terminal_workflow(isolated_runtime) -> None:
    state = _initialize()
    state = abort_workflow(
        "workflow-expiry", reason="cleanup", expected_lifecycle_sha256=state["lifecycle_sha256"]
    )
    with pytest.raises(LifecycleError, match="already aborted"):
        abort_workflow(
            "workflow-expiry", reason="again", expected_lifecycle_sha256=state["lifecycle_sha256"]
        )


def test_a_fresh_workflow_is_not_stale(isolated_runtime) -> None:
    _initialize()
    staleness = lifecycle_summary("workflow-expiry")["staleness"]
    assert staleness["stale"] is False
    assert staleness["expiry_seconds"] == WORKFLOW_EXPIRY_SECONDS
    assert lifecycle_summary("workflow-expiry")["abort"] is None


def test_lifecycle_status_reports_staleness_past_the_expiry(isolated_runtime) -> None:
    _initialize()
    _age_on_disk("workflow-expiry", WORKFLOW_EXPIRY_SECONDS + 1)
    staleness = lifecycle_summary("workflow-expiry")["staleness"]
    assert staleness["stale"] is True
    assert staleness["age_seconds"] > WORKFLOW_EXPIRY_SECONDS


def test_terminal_workflows_are_never_reported_stale(isolated_runtime) -> None:
    state = _initialize("workflow-terminal")
    abort_workflow(
        "workflow-terminal", reason="cleanup", expected_lifecycle_sha256=state["lifecycle_sha256"]
    )
    _age_on_disk("workflow-terminal", WORKFLOW_EXPIRY_SECONDS * 3)
    # Nothing is waiting on a closed workflow, so age alone must not flag it.
    assert lifecycle_summary("workflow-terminal")["staleness"]["stale"] is False


@pytest.mark.parametrize(
    "updated_at,expected_stale",
    [
        ("not-a-timestamp", None),
        ("2020-01-01T00:00:00", True),
        ("2020-01-01T00:00:00Z", True),
    ],
)
def test_staleness_degrades_safely_on_odd_timestamps(
    isolated_runtime, updated_at: str, expected_stale: object
) -> None:
    _initialize()
    path = lifecycle_path("workflow-expiry")
    state = json.loads(path.read_text())
    state["updated_at"] = updated_at
    hash_input = dict(state)
    hash_input.pop("lifecycle_sha256")
    state["lifecycle_sha256"] = canonical_hash(hash_input)
    path.write_text(json.dumps(state))

    staleness = lifecycle_summary("workflow-expiry")["staleness"]
    assert staleness["stale"] is expected_stale
    if expected_stale is None:
        assert staleness["age_seconds"] is None


def test_workflow_list_surfaces_stale_workflows_oldest_first(isolated_runtime) -> None:
    _initialize("workflow-fresh")
    _initialize("workflow-old")
    _age_on_disk("workflow-old", WORKFLOW_EXPIRY_SECONDS + 60)

    # A corrupt file must be skipped, not raised on: finding broken workflows is
    # the entire point of this call.
    junk = isolated_runtime / "workflows" / "workflow-junk"
    junk.mkdir(parents=True, exist_ok=True)
    (junk / "host-lifecycle.json").write_text("{ not json")

    listing = list_workflows()
    ids = [entry["workflow_id"] for entry in listing["workflows"]]
    assert ids == ["workflow-old", "workflow-fresh"]
    assert listing["count"] == 2
    assert listing["workflows"][0]["stale"] is True
    assert listing["workflows"][1]["stale"] is False


def test_workflow_abort_and_list_dispatch_through_mcp_call_tool(isolated_runtime) -> None:
    state = _initialize()

    listed = mcp_server.call_tool("workflow_list", {})
    assert listed["workflows"][0]["workflow_id"] == "workflow-expiry"

    aborted = mcp_server.call_tool(
        "workflow_abort",
        {
            "workflow_id": "workflow-expiry",
            "reason": "abandoned",
            "expected_lifecycle_sha256": state["lifecycle_sha256"],
        },
    )
    assert aborted["state"] == "aborted"


def test_both_workflow_tools_are_declared_in_the_mcp_surface() -> None:
    declared = {tool["name"] for tool in mcp_server.TOOLS}
    assert {"workflow_list", "workflow_abort"} <= declared


def test_confirm_plan_still_works_so_the_abort_guard_is_not_overbroad(isolated_runtime) -> None:
    state = _initialize()
    state = _gate("workflow-expiry", state, "plan")
    state = confirm_plan(
        "workflow-expiry",
        confirmed=True,
        user_message_sha256="d" * 64,
        expected_plan_sha256="a" * 64,
        expected_lifecycle_sha256=state["lifecycle_sha256"],
    )
    assert state["state"] == "awaiting_claude_goal"
