from __future__ import annotations

from claude_fusion_drive.config import load_config, load_schema, validate_config


def test_default_config_validates() -> None:
    config = load_config(include_user=False)
    assert validate_config(config) == []
    assert config["schema_version"] == 2
    assert load_schema()["properties"]["schema_version"]["const"] == 2
    assert "xai_claude_oauth" in load_schema()["properties"]["engines"]["required"]


def test_canonical_in_harness_models_and_reasoning() -> None:
    config = load_config(include_user=False)
    engine = config["engines"]["in_harness"]
    assert engine["panel"] == ["grok45-panel", "gpt56sol-panel", "fable5-panel"]
    assert engine["judge"] == "gpt56sol-judge"
    assert engine["fuser"] == "gpt56sol-fuser"
    expected_models = {
        "grok45-panel": "grok-4.5",
        "gpt56sol-panel": "openai/gpt-5.6-sol",
        "fable5-panel": "anthropic/claude-fable-5",
        "gpt56sol-judge": "openai/gpt-5.6-sol",
        "gpt56sol-fuser": "openai/gpt-5.6-sol",
    }
    for seat_name, model in expected_models.items():
        assert config["seats"][seat_name]["model"] == model
        assert config["seats"][seat_name]["reasoning"] == "xhigh"


def test_openrouter_and_in_harness_are_separate() -> None:
    config = load_config(include_user=False)
    in_harness = config["engines"]["in_harness"]
    openrouter = config["engines"]["openrouter_fusion"]
    assert openrouter is not in_harness
    assert openrouter["kind"] == "server_managed"
    assert openrouter["inherit_in_harness_settings"] is False
    assert openrouter["seat"] == "openrouter-fusion-seat"
    assert config["seats"]["openrouter-fusion-seat"]["model"] == "openrouter/fusion"
    assert config["seats"]["openrouter-fusion-seat"]["openrouter_fusion"]["reasoning"]["effort"] == "xhigh"


def test_aggregate_reasoning_and_wall_caps_are_unbounded() -> None:
    config = load_config(include_user=False)
    for profile in config["profiles"].values():
        assert profile["budgets"]["max_reasoning_tokens"] is None
        assert profile["budgets"]["max_wall_seconds"] is None
        assert profile["budgets"]["max_calls"] > 0
        assert profile["budgets"]["max_cost_usd"] > 0
    assert config["providers"]["xai_api"]["request_timeout_seconds"] > 0


def test_all_grok_shape_and_inherited_gate_set() -> None:
    config = load_config(include_user=False)
    engine = config["engines"]["all_grok_4_5"]
    assert len(engine["panel"]) == 2
    role_seats = engine["panel"] + [engine["judge"], engine["fuser"]]
    assert all(config["seats"][name]["model"] == "grok-4.5" for name in role_seats)
    assert config["profiles"]["all-grok-4.5"]["gate_set"] == "approval-gates"


def test_subscription_oauth_profile_has_exact_independent_topology() -> None:
    config = load_config(include_user=False)
    assert config["active_profile"] == "xai-claude-oauth"
    profile = config["profiles"]["subscription-oauth"]
    engine = config["engines"][profile["engine"]]
    gates = config["gate_sets"][profile["gate_set"]]
    assert profile["engine"] == "subscription_oauth"
    assert profile["gate_set"] == "oauth-approval-gates"
    assert profile["budgets"]["unknown_cost_policy"] == "report_unknown"
    assert engine["panel"] == [
        "grok45-oauth-panel",
        "grok45-oauth-panel-b",
        "fable5-oauth-panel",
    ]
    assert engine["judge"] == "grok45-oauth-judge"
    assert engine["fuser"] == "fable5-oauth-fuser"
    assert engine["min_live_seats"] == 3
    assert (
        config["seats"]["grok45-oauth-panel"]["persona"]
        != config["seats"]["grok45-oauth-panel-b"]["persona"]
    )
    assert gates["reviewers"] == [
        "grok45-oauth-gate-primary",
        "grok45-oauth-gate-secondary",
    ]
    assert gates["max_concurrency"] == 1
    assert all(
        config["seats"][seat_name]["provider"] == "grok_oauth"
        for seat_name in gates["reviewers"]
    )
    assert profile["execution"] == {
        "owner": "claude_host",
        "model": "claude-fable-5",
        "reasoning": "xhigh",
        "require_confirmed_plan": True,
        "require_claude_goal": True,
        "allow_recursive_claude_cli": False,
        "run_tests": True,
        "require_diff_review": True,
        "max_fix_cycles": 2,
    }
    assert config["lifecycle"]["host_goal_creation_tool"] == "claude_code.TaskCreate"


def test_xai_claude_oauth_profile_has_exact_hybrid_topology() -> None:
    config = load_config(include_user=False)
    profile = config["profiles"]["xai-claude-oauth"]
    engine = config["engines"][profile["engine"]]
    gates = config["gate_sets"][profile["gate_set"]]
    assert config["active_profile"] == "xai-claude-oauth"
    assert profile["engine"] == "xai_claude_oauth"
    assert profile["gate_set"] == "xai-serialized-approval-gates"
    assert profile["budgets"]["unknown_cost_policy"] == "report_unknown"
    assert engine["panel"] == [
        "all-grok-panel-a",
        "all-grok-panel-b",
        "fable5-oauth-panel",
    ]
    assert engine["judge"] == "all-grok-judge"
    assert engine["fuser"] == "fable5-oauth-fuser"
    assert engine["min_live_seats"] == 3
    assert engine["max_concurrency"] == 3
    selected_seats = [
        *engine["panel"],
        engine["judge"],
        engine["fuser"],
        *gates["reviewers"],
    ]
    assert {
        config["seats"][seat_name]["provider"]
        for seat_name in selected_seats
    } == {"xai_api", "claude_oauth"}
    assert all(
        config["seats"][seat_name]["provider"] != "openrouter_api"
        for seat_name in selected_seats
    )
    assert gates["reviewers"] == [
        "grok45-gate-primary",
        "grok45-gate-secondary",
    ]
    assert gates["max_concurrency"] == 1
    assert profile["execution"]["owner"] == "claude_host"
    assert profile["execution"]["model"] == "claude-fable-5"
    assert profile["execution"]["reasoning"] == "xhigh"
    assert profile["execution"]["require_confirmed_plan"] is True


def test_gate_inventory_uses_grok_and_has_all_stages() -> None:
    config = load_config(include_user=False)
    gates = config["gate_sets"]["approval-gates"]
    assert gates["requested_reasoning"] == "xhigh"
    assert gates["effective_reasoning"] == "high"
    assert gates["normalization"] == "provider_ceiling"
    assert {
        "synthesis",
        "plan",
        "pre_execution",
        "subagent_pre_execution",
        "subagent_post_execution",
        "post_execution",
        "final",
        "summarize",
    } == set(gates["stages"])
    assert all(config["seats"][name]["model"] == "grok-4.5" for name in gates["reviewers"])


def test_canonical_panel_mutation_fails_validation() -> None:
    config = load_config(include_user=False)
    config["engines"]["in_harness"]["panel"] = ["grok45-panel"]
    errors = validate_config(config)
    assert any("canonical order" in error for error in errors)
