from __future__ import annotations

import hashlib
from pathlib import Path

from claude_fusion_drive.auto_eval import evaluate, generate_auto_eval
from claude_fusion_drive.config import load_config


def _evidence() -> dict:
    return {
        "run_id": "eval-run-001",
        "report_timestamp": "2026-07-30T00:00:00Z",
        "engine": "in_harness",
        "models": [
            {
                "seat": "grok45-panel",
                "model": "grok-4.5",
                "input_tokens": 1000,
                "output_tokens": 500,
                "reasoning_tokens": 600,
                "latency_seconds": 12.3456,
                "billed_cost_usd": 0.01234567,
                "honesty_observations": ["disclosed provider ceiling"],
            },
            {
                "seat": "gpt56sol-panel",
                "model": "openai/gpt-5.6-sol",
                "input_tokens": 800,
                "output_tokens": 400,
                "reasoning_tokens": 300,
                "latency_seconds": 8.5,
                "billed_cost_usd": 0.02,
            },
        ],
        "gates": {
            "synthesis": {"verdict": "PASS", "evidence": ["synthesis hash"]},
            "plan": {"verdict": "PASS", "score": 96, "evidence": ["requirements trace"]},
            "pre_execution": {"verdict": "PASS", "evidence": ["goal receipt"]},
            "subagent_pre_execution": {"verdict": "PASS", "evidence": ["preset hash"]},
            "subagent_post_execution": {"verdict": "NEEDS_WORK", "evidence": ["tool retry"]},
            "post_execution": {"verdict": "PASS", "evidence": ["pytest output"]},
            "final": {"verdict": "PASS", "evidence": ["ledger"]},
            "summarize": {"verdict": "PASS", "evidence": ["decisions"]},
        },
        "tool_calls": [
            {"tool": "fuse", "status": "ok"},
            {
                "tool": "gitnexus",
                "status": "failed",
                "error": "MCP capability unavailable",
                "category": "capability",
                "recoverable": True,
            },
        ],
        "claims": [
            {
                "claim": "Tests passed",
                "model": "gpt-5.6-sol",
                "verified": True,
                "evidence": "pytest output",
            },
            {
                "claim": "<script>alert('x')</script>",
                "model": "grok-4.5",
                "verified": False,
                "evidence": "contradicted by log",
            },
            {
                "claim": "Provider route exact",
                "model": "gpt-5.6-sol",
                "verified": None,
                "uncertainty_disclosed": True,
            },
        ],
        "failures": [
            {
                "category": "provider_timeout",
                "message": "One preserved attempt timed out",
                "severity": "warning",
            }
        ],
        "config_changes": [
            {
                "category": "configuration",
                "message": "Selected all-Grok subagent preset for verification.",
            }
        ],
        "ablations": [],
    }


def test_evaluation_has_every_requested_dimension() -> None:
    result = evaluate(_evidence(), load_config(include_user=False))
    assert result["spend"]["known_billed_cost_usd"] == 0.032346
    assert result["efficiency"]["grade"] in {"A", "B", "C", "D", "F"}
    assert result["tool_errors"][0]["tool"] == "gitnexus"
    assert result["claims"]["verified"] == 1
    assert result["claims"]["unknown"] == 1
    assert len(result["claims"]["unsupported"]) == 1
    assert result["honesty"]["basis"].startswith("Only supplied")
    assert "over_reasoning_flag" in result["reasoning"]
    assert "under_reasoning_flag" in result["reasoning"]
    assert result["config_changes"]
    assert result["failures"]


def test_contribution_is_unknown_without_pinned_ablation() -> None:
    result = evaluate(_evidence(), load_config(include_user=False))
    assert result["measured_contribution_count"] == 0
    assert all(item["status"] == "unknown" for item in result["intelligence_contribution"])
    assert all(item["delta_score"] is None for item in result["intelligence_contribution"])


def test_contribution_requires_all_pinning_conditions() -> None:
    evidence = _evidence()
    evidence["ablations"] = [
        {
            "model": "grok-4.5",
            "pinned": True,
            "same_task_hash": True,
            "same_config_except_model": True,
            "baseline_score": 95,
            "without_model_score": 82,
        },
        {
            "model": "openai/gpt-5.6-sol",
            "pinned": False,
            "same_task_hash": True,
            "same_config_except_model": True,
            "baseline_score": 95,
            "without_model_score": 60,
        },
    ]
    result = evaluate(evidence, load_config(include_user=False))
    by_model = {item["model"]: item for item in result["intelligence_contribution"]}
    assert by_model["grok-4.5"]["status"] == "measured"
    assert by_model["grok-4.5"]["delta_score"] == 13.0
    assert by_model["openai/gpt-5.6-sol"]["status"] == "unknown"


def test_html_is_byte_reproducible_and_standalone(
    isolated_runtime, tmp_path: Path
) -> None:
    first_path = tmp_path / "first.html"
    second_path = tmp_path / "second.html"
    first = generate_auto_eval(
        _evidence(),
        output_path=str(first_path),
        config=load_config(include_user=False),
    )
    second = generate_auto_eval(
        _evidence(),
        output_path=str(second_path),
        config=load_config(include_user=False),
    )
    first_bytes = first_path.read_bytes()
    second_bytes = second_path.read_bytes()
    assert first_bytes == second_bytes
    assert first["report_sha256"] == second["report_sha256"]
    assert first["report_sha256"] == hashlib.sha256(first_bytes).hexdigest()
    rendered = first_bytes.decode()
    assert "<svg" in rendered
    assert "<script" not in rendered.lower()
    assert "<link" not in rendered.lower()
    assert "src=" not in rendered.lower()
    assert "quantstats" in rendered.lower()  # The footer states that it is not used.
    assert "No JavaScript, external assets" in rendered


def test_html_contains_all_tearsheet_sections_and_escapes_claims(
    isolated_runtime, tmp_path: Path
) -> None:
    path = tmp_path / "report.html"
    generate_auto_eval(
        _evidence(),
        output_path=str(path),
        config=load_config(include_user=False),
    )
    rendered = path.read_text()
    for heading in (
        "Proposed workflow",
        "Gate grades",
        "Spend by seat",
        "Efficiency",
        "Configuration changes",
        "Failures",
        "Tool-call errors",
        "Unsupported claims / hallucinations",
        "Model honesty",
        "Over / under reasoning",
        "Intelligence contribution",
        "Subscription usage",
        "Effective settings",
    ):
        assert heading in rendered
    assert "<script>alert" not in rendered
    assert "&lt;script&gt;alert" in rendered


def test_missing_subscription_cost_is_unknown_not_zero() -> None:
    evidence = _evidence()
    evidence["models"].append(
        {
            "seat": "fable5-oauth-panel",
            "model": "claude-fable-5",
            "subscription_usage_units": None,
        }
    )
    result = evaluate(evidence, load_config(include_user=False))
    subscription = result["spend"]["subscription_usage"][0]
    assert subscription["billed_cost_usd"] is None
    assert subscription["usage_units"] is None
    assert "fable5-oauth-panel" in result["spend"]["unknown_cost_models"]
    assert result["efficiency"]["pass_score_per_known_dollar"] is None


def test_subscription_profile_evaluation_excludes_api_profile_seats() -> None:
    evidence = _evidence()
    evidence["profile"] = "subscription-oauth"
    evidence["engine"] = "subscription_oauth"
    evidence["models"] = [
        {
            "seat": "grok45-oauth-panel",
            "model": "grok-4.5",
            "subscription_usage_units": None,
        },
        {
            "seat": "fable5-oauth-panel",
            "model": "claude-fable-5",
            "subscription_usage_units": None,
        },
    ]
    result = evaluate(evidence, load_config(include_user=False))
    seats = {row["seat"] for row in result["models"]}
    assert result["profile"] == "subscription-oauth"
    assert result["engine"] == "subscription_oauth"
    assert seats == {
        "grok45-oauth-panel",
        "grok45-oauth-panel-b",
        "fable5-oauth-panel",
        "grok45-oauth-judge",
        "fable5-oauth-fuser",
        "grok45-oauth-gate-primary",
        "grok45-oauth-gate-secondary",
    }
    assert "gpt56sol-panel" not in seats
    assert all(
        row["reviewers"]
        == ["grok45-oauth-gate-primary", "grok45-oauth-gate-secondary"]
        for row in result["gates"]
    )
    assert result["spend"]["known_billed_cost_usd"] == 0.0
    assert set(result["spend"]["unknown_cost_models"]) == seats
    assert result["settings"]["configured_active_profile"] == "xai-claude-oauth"
    assert result["settings"]["selected_profile"] == "subscription-oauth"


def test_xai_claude_profile_evaluation_separates_metered_and_subscription_costs() -> None:
    config = load_config(include_user=False)
    profile = config["profiles"]["xai-claude-oauth"]
    engine = config["engines"][profile["engine"]]
    selected_seats = [
        *engine["panel"],
        engine["judge"],
        engine["fuser"],
        *config["gate_sets"][profile["gate_set"]]["reviewers"],
    ]
    evidence = _evidence()
    evidence["profile"] = "xai-claude-oauth"
    evidence["engine"] = "xai_claude_oauth"
    evidence["models"] = [
        {
            "seat": seat_name,
            "model": config["seats"][seat_name]["model"],
            "billed_cost_usd": (
                0.01
                if config["seats"][seat_name]["provider"] == "xai_api"
                else None
            ),
            "subscription_usage_units": None,
        }
        for seat_name in selected_seats
    ]
    result = evaluate(evidence, config)
    rows = {row["seat"]: row for row in result["models"]}
    assert set(rows) == set(selected_seats)
    assert result["profile"] == "xai-claude-oauth"
    assert result["engine"] == "xai_claude_oauth"
    assert result["spend"]["known_billed_cost_usd"] == 0.05
    assert set(result["spend"]["unknown_cost_models"]) == {
        "fable5-oauth-panel",
        "fable5-oauth-fuser",
    }
    assert {
        row["seat"]
        for row in result["spend"]["subscription_usage"]
    } == {"fable5-oauth-panel", "fable5-oauth-fuser"}
    assert all(row["provider"] != "openrouter_api" for row in rows.values())
    assert result["settings"]["configured_active_profile"] == "xai-claude-oauth"
    assert result["settings"]["selected_profile"] == "xai-claude-oauth"


def test_openrouter_fusion_report_uses_server_engine(
    isolated_runtime, tmp_path: Path
) -> None:
    evidence = _evidence()
    evidence["engine"] = "openrouter_fusion"
    path = tmp_path / "openrouter.html"
    generate_auto_eval(
        evidence,
        output_path=str(path),
        config=load_config(include_user=False),
    )
    rendered = path.read_text()
    assert "openrouter fusion" in rendered.lower()
    assert "openrouter-fusion-seat" in rendered


def test_absent_timestamp_stays_absent_and_deterministic(
    isolated_runtime, tmp_path: Path
) -> None:
    evidence = _evidence()
    evidence.pop("report_timestamp")
    path = tmp_path / "no-time.html"
    generate_auto_eval(
        evidence,
        output_path=str(path),
        config=load_config(include_user=False),
    )
    assert "Timestamp: not supplied" in path.read_text()
