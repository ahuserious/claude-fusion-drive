"""PRD-required tool surface: config history/rollback, gate/provider/cost reports, human-sim lifecycle."""

from __future__ import annotations

import json

import pytest

import mcp_server
from claude_fusion_drive.config import (
    approve_config,
    config_history,
    config_rollback_propose,
    load_config,
    propose_config,
)
from claude_fusion_drive.errors import ConfigurationError
from claude_fusion_drive.human_sim import (
    abort_campaign,
    campaign_plan,
    campaign_report,
    create_campaign,
    human_sim_questions,
    pause_campaign,
    record_campaign_iteration,
    resume_campaign,
)
from claude_fusion_drive.report import cost_estimate, gate_set_list, provider_list

QUESTIONNAIRE = human_sim_questions()["questions"]

PRD_REQUIRED_CONFIG_TOOLS = {
    "config_show",
    "config_get",
    "config_validate",
    "config_propose",
    "config_approve",
    "config_history",
    "config_rollback_propose",
    "workflow_report",
    "preset_list",
    "preset_resolve",
    "gate_set_list",
    "provider_list",
    "provider_models",
    "provider_test",
    "cost_estimate",
}

PRD_REQUIRED_HUMAN_SIM_TOOLS = {
    "human_sim_questions",
    "human_sim_create",
    "human_sim_plan",
    "human_sim_record",
    "human_sim_status",
    "human_sim_pause",
    "human_sim_resume",
    "human_sim_abort",
    "human_sim_goal_record",
    "human_sim_report",
}


def _preferences() -> dict:
    return {item["key"]: f"configured {item['key']}" for item in QUESTIONNAIRE}


def _campaign() -> dict:
    return create_campaign(
        preferences=_preferences(),
        acceptance_criteria=["no console errors"],
        scenarios=[{"scenario_id": "desktop", "objective": "Complete primary journey"}],
    )


def test_all_prd_required_tools_are_registered() -> None:
    registered = {tool["name"] for tool in mcp_server.TOOLS}
    assert PRD_REQUIRED_CONFIG_TOOLS.issubset(registered)
    assert PRD_REQUIRED_HUMAN_SIM_TOOLS.issubset(registered)


def test_gate_set_list_exposes_all_eight_canonical_stages() -> None:
    listing = gate_set_list()
    assert listing["count"] >= 3
    canonical = {
        "synthesis",
        "plan",
        "pre_execution",
        "subagent_pre_execution",
        "subagent_post_execution",
        "post_execution",
        "final",
        "summarize",
    }
    for gate_set in listing["gate_sets"]:
        assert canonical.issubset(set(gate_set["stages"]))
        for reviewer in gate_set["reviewers"]:
            assert reviewer["model"] == "grok-4.5"
            assert reviewer["requested_reasoning"] == "xhigh"
            assert reviewer["effective_reasoning"] == "high"


def test_provider_list_redacts_credentials_and_disables_openrouter_by_default() -> None:
    listing = provider_list()
    providers = {row["name"]: row for row in listing["providers"]}
    assert providers["xai_api"]["enabled"] is True
    assert providers["openrouter_api"]["enabled"] is False
    assert providers["openrouter_fusion_api"]["enabled"] is False
    assert providers["xai_api"]["api_key_env"] == "XAI_API_KEY"
    serialized = json.dumps(listing)
    assert "sk-" not in serialized
    assert "Bearer" not in serialized


def test_cost_estimate_prices_metered_grok_and_reports_unknown_subscription() -> None:
    estimate = cost_estimate()
    assert estimate["profile"] == "xai-claude-oauth"
    rows = {row["seat"]: row for row in estimate["seats"]}
    grok_row = rows["all-grok-panel-a"]
    assert grok_row["known_pricing"] is True
    assert grok_row["max_cost_usd"] > 0
    claude_row = rows["fable5-oauth-panel"]
    assert claude_row["known_pricing"] is False
    assert claude_row["max_cost_usd"] is None
    assert "claude-fable-5" in estimate["unknown_cost_models"]
    assert estimate["known_metered_max_cost_usd"] > 0
    assert estimate["assumptions"]["unknown_cost_policy"] == "report_unknown"


def test_cost_estimate_rejects_unknown_profile() -> None:
    with pytest.raises(ConfigurationError, match="Unknown Fusion Drive profile"):
        cost_estimate(profile_name="does-not-exist")


def test_config_history_lists_proposals_and_rollback_restores_prior_state(isolated_runtime) -> None:
    assert config_history()["count"] == 0

    first = propose_config({"reporting": {"theme": "warm_signal_dark"}}, rationale="first change")
    approve_config(first["proposal_hash"], confirmed=True)
    assert load_config()["reporting"]["theme"] == "warm_signal_dark"

    second = propose_config({"reporting": {"theme": "warm_signal_light"}}, rationale="second change")
    approve_config(second["proposal_hash"], confirmed=True)
    assert load_config()["reporting"]["theme"] == "warm_signal_light"

    history = config_history()
    assert history["count"] == 2
    statuses = {entry["proposal_hash"]: entry["status"] for entry in history["proposals"]}
    assert statuses[first["proposal_hash"]] == "approved"
    assert statuses[second["proposal_hash"]] == "approved"

    rollback = config_rollback_propose(first["proposal_hash"])
    assert rollback["rollback_of"] == first["proposal_hash"]
    assert rollback["requires_final_approval"] is True
    # Not applied until approved.
    assert load_config()["reporting"]["theme"] == "warm_signal_light"
    approve_config(rollback["proposal_hash"], confirmed=True)
    assert load_config()["reporting"]["theme"] == "warm_signal_dark"


def test_config_rollback_rejects_unapproved_target(isolated_runtime) -> None:
    pending = propose_config({"reporting": {"theme": "warm_signal_dark"}}, rationale="never approved")
    with pytest.raises(ConfigurationError, match="previously approved"):
        config_rollback_propose(pending["proposal_hash"])


def test_human_sim_pause_blocks_recording_until_resume(isolated_runtime) -> None:
    campaign = _campaign()
    campaign_id = campaign["campaign_id"]

    paused = pause_campaign(
        campaign_id,
        expected_manifest_sha256=campaign["manifest_sha256"],
        reason="operator break",
    )
    assert paused["status"] == "paused"

    with pytest.raises(ConfigurationError, match="paused"):
        record_campaign_iteration(
            campaign_id,
            scenario_id="desktop",
            passed=True,
            evidence=["screenshot"],
            expected_manifest_sha256=paused["manifest_sha256"],
        )

    resumed = resume_campaign(
        campaign_id,
        expected_manifest_sha256=paused["manifest_sha256"],
    )
    assert resumed["status"] == "active"
    recorded = record_campaign_iteration(
        campaign_id,
        scenario_id="desktop",
        passed=True,
        evidence=["screenshot"],
        expected_manifest_sha256=resumed["manifest_sha256"],
    )
    assert recorded["scenarios"][0]["status"] == "passed"


def test_human_sim_abort_is_terminal_and_requires_reason(isolated_runtime) -> None:
    campaign = _campaign()
    campaign_id = campaign["campaign_id"]

    with pytest.raises(ConfigurationError, match="explicit reason"):
        abort_campaign(
            campaign_id,
            expected_manifest_sha256=campaign["manifest_sha256"],
            reason="  ",
        )

    aborted = abort_campaign(
        campaign_id,
        expected_manifest_sha256=campaign["manifest_sha256"],
        reason="scope withdrawn",
    )
    assert aborted["status"] == "aborted"
    with pytest.raises(ConfigurationError, match="Cannot move campaign"):
        resume_campaign(
            campaign_id,
            expected_manifest_sha256=aborted["manifest_sha256"],
        )


def test_human_sim_plan_and_report_survive_reload(isolated_runtime) -> None:
    campaign = _campaign()
    campaign_id = campaign["campaign_id"]
    record_campaign_iteration(
        campaign_id,
        scenario_id="desktop",
        passed=False,
        evidence=["console dump"],
        errors=[{"message": "boom", "source": "console"}],
        expected_manifest_sha256=campaign["manifest_sha256"],
    )

    plan = campaign_plan(campaign_id)
    assert plan["scenarios"][0]["scenario_id"] == "desktop"
    assert plan["scenarios"][0]["iteration_count"] == 1
    assert "iterations" not in plan["scenarios"][0]

    report = campaign_report(campaign_id)
    assert report["total_iterations"] == 1
    assert report["scenarios"][0]["last_passed"] is False
    assert report["scenarios"][0]["open_error_count"] == 1
    assert report["open_errors"]

    # Stale-hash writes are rejected after reload.
    with pytest.raises(ConfigurationError, match="Stale"):
        pause_campaign(
            campaign_id,
            expected_manifest_sha256=campaign["manifest_sha256"],
            reason="stale writer",
        )


def test_new_tools_dispatch_through_mcp_call_tool(isolated_runtime) -> None:
    assert mcp_server.call_tool("gate_set_list", {})["count"] >= 3
    assert mcp_server.call_tool("provider_list", {})["count"] >= 5
    assert mcp_server.call_tool("cost_estimate", {})["profile"] == "xai-claude-oauth"
    assert mcp_server.call_tool("config_history", {})["count"] == 0
