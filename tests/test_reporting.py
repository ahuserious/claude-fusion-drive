from __future__ import annotations

from claude_fusion_drive.config import load_config
from claude_fusion_drive.report import gate_inventory, workflow_mermaid, workflow_report


def test_planning_report_contains_graph_and_full_config() -> None:
    config = load_config(include_user=False)
    report = workflow_report(config)
    assert report["validation"] == {"ok": True, "errors": []}
    assert report["config"]["engines"]["in_harness"]["panel"] == [
        "grok45-panel",
        "gpt56sol-panel",
        "fable5-panel",
    ]
    assert "flowchart TD" in report["mermaid"]
    assert "User confirms exact plan?" in report["mermaid"]
    assert "Claude host claude_code.TaskCreate" in report["mermaid"]
    assert "claude-fable-5 max driver" in report["mermaid"]


def test_mermaid_discloses_xai_reasoning_mapping() -> None:
    graph = workflow_mermaid(load_config(include_user=False))
    assert "requested xhigh / effective high" in graph
    assert "Fable 5" not in graph  # Seat/model identifiers are used, not a fabricated display name.
    assert "claude-fable-5" in graph


def test_openrouter_profile_graph_is_server_managed() -> None:
    graph = workflow_mermaid(load_config(include_user=False), profile_name="openrouter-fusion")
    assert "OpenRouter server-side panel and judge" in graph
    assert "separately configured" in graph


def test_gate_report_has_reviewers_and_evidence() -> None:
    rows = gate_inventory(load_config(include_user=False))
    assert len(rows) == 8
    assert all(row["requested_reasoning"] == "xhigh" for row in rows)
    assert all(row["effective_reasoning"] == "high" for row in rows)
    assert next(row for row in rows if row["stage"] == "plan")["required_evidence"] == [
        "requirements_trace",
        "risk_analysis",
        "workflow_report",
    ]


def test_subscription_report_uses_oauth_graph_and_serialized_reviewers() -> None:
    config = load_config(include_user=False)
    report = workflow_report(config, profile_name="subscription-oauth")
    assert report["profile"] == "subscription-oauth"
    assert "Fusion engine: subscription_oauth" in report["mermaid"]
    assert "grok45-oauth-panel" in report["mermaid"]
    assert "grok45-oauth-panel-b" in report["mermaid"]
    assert "fable5-oauth-panel" in report["mermaid"]
    assert "Judge: grok-4.5" in report["mermaid"]
    assert "Fuser: claude-fable-5" in report["mermaid"]
    assert all(
        row["reviewers"]
        == ["grok45-oauth-gate-primary", "grok45-oauth-gate-secondary"]
        for row in report["gates"]
    )


def test_xai_claude_report_uses_mixed_graph_and_direct_serialized_reviewers() -> None:
    config = load_config(include_user=False)
    report = workflow_report(config, profile_name="xai-claude-oauth")
    assert report["profile"] == "xai-claude-oauth"
    assert "Fusion engine: xai_claude_oauth" in report["mermaid"]
    assert "all-grok-panel-a" in report["mermaid"]
    assert "all-grok-panel-b" in report["mermaid"]
    assert "fable5-oauth-panel" in report["mermaid"]
    assert "Judge: grok-4.5" in report["mermaid"]
    assert "Fuser: claude-fable-5" in report["mermaid"]
    assert "requested xhigh / effective high" in report["mermaid"]
    assert all(
        row["reviewers"]
        == ["grok45-gate-primary", "grok45-gate-secondary"]
        for row in report["gates"]
    )
