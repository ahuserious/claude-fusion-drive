from __future__ import annotations

from pathlib import Path

from claude_fusion_drive.capabilities import advanced_workflow_plan, capability_probe
from claude_fusion_drive.config import load_config


def test_gitnexus_cli_and_mcp_are_reported_separately(monkeypatch, tmp_path: Path) -> None:
    config = load_config(include_user=False)
    repo_skill = tmp_path / "repo-merge" / "SKILL.md"
    gitnexus_skill = tmp_path / "gitnexus" / "SKILL.md"
    repo_skill.parent.mkdir()
    gitnexus_skill.parent.mkdir()
    repo_skill.write_text("repo")
    gitnexus_skill.write_text("gitnexus")
    config["integrations"]["repo_merge"]["skill_path"] = str(repo_skill)
    config["integrations"]["gitnexus"]["skill_path"] = str(gitnexus_skill)
    monkeypatch.setattr(
        "claude_fusion_drive.capabilities.shutil.which",
        lambda command: "/usr/local/bin/gitnexus" if command == "gitnexus" else None,
    )
    report = capability_probe(
        host_mcp_tools=["mcp__gitnexus__query", "mcp__other__tool"],
        config=config,
    )
    assert report["repo_merge"]["available"] is True
    assert report["gitnexus"]["cli_path"] == "/usr/local/bin/gitnexus"
    assert report["gitnexus"]["mcp_exposed_by_host"] is True
    assert report["gitnexus"]["auto_install"] is False
    assert report["credential_policy"].startswith("This probe does not read")


def test_capability_probe_does_not_claim_auth() -> None:
    report = capability_probe(config=load_config(include_user=False))
    assert all(provider["auth_checked"] is False for provider in report["providers"].values())
    assert all(
        provider["auth_value_accessed"] is False
        for provider in report["providers"].values()
    )
    assert all("authenticated" not in provider for provider in report["providers"].values())
    assert len(report["capability_sha256"]) == 64


def test_subscription_doctor_requirements_are_profile_and_host_tool_aware(
    monkeypatch,
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = load_config(include_user=False)
    config["providers"]["claude_oauth"]["command"] = "/opt/fusion/claude"
    config["providers"]["grok_oauth"]["command"] = "/opt/fusion/grok"
    available = {"/opt/fusion/claude", "/opt/fusion/grok"}
    monkeypatch.setattr(
        "claude_fusion_drive.capabilities.shutil.which",
        lambda command: command if command in available else None,
    )
    ready = capability_probe(
        host_mcp_tools=["claude_code.TaskCreate"],
        config=config,
        profile_name="subscription-oauth",
    )
    assert ready["selected_profile"] == "subscription-oauth"
    assert ready["required_providers"] == ["claude_oauth", "grok_oauth"]
    assert ready["providers"]["claude_oauth"]["binary_available"] == "/opt/fusion/claude"
    assert ready["providers"]["grok_oauth"]["binary_available"] == "/opt/fusion/grok"
    assert ready["host_goal"]["available"] is True
    assert ready["readiness"] == {"ok": True, "issues": []}
    assert all(
        provider["auth_checked"] is False
        for provider in ready["providers"].values()
    )

    missing_host = capability_probe(
        host_mcp_tools=["codex_app.list_projects"],
        config=config,
        profile_name="subscription-oauth",
    )
    assert missing_host["host_goal"]["available"] is False
    assert missing_host["readiness"]["ok"] is False
    assert "claude_code.TaskCreate" in missing_host["readiness"]["issues"][0]


def test_hybrid_doctor_requires_xai_reference_without_reading_auth_value(
    monkeypatch,
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    config = load_config(include_user=False)
    config["providers"]["claude_oauth"]["command"] = "/opt/fusion/claude"
    monkeypatch.setattr(
        "claude_fusion_drive.capabilities.shutil.which",
        lambda command: command if command == "/opt/fusion/claude" else None,
    )
    missing = capability_probe(
        host_mcp_tools=["claude_code.TaskCreate"],
        config=config,
        profile_name="xai-claude-oauth",
    )
    assert missing["required_providers"] == ["claude_oauth", "xai_api"]
    assert missing["providers"]["xai_api"]["api_key_env_present"] is False
    assert missing["providers"]["xai_api"]["auth_value_accessed"] is False
    assert missing["readiness"]["ok"] is False
    assert any("XAI_API_KEY" in issue for issue in missing["readiness"]["issues"])
    assert all("OPENROUTER_API_KEY" not in issue for issue in missing["readiness"]["issues"])

    monkeypatch.setenv("XAI_API_KEY", "opaque-test-placeholder")
    ready = capability_probe(
        host_mcp_tools=["claude_code.TaskCreate"],
        config=config,
        profile_name="xai-claude-oauth",
    )
    assert ready["providers"]["xai_api"]["api_key_env_present"] is True
    assert ready["providers"]["xai_api"]["auth_value_accessed"] is False
    assert ready["providers"]["claude_oauth"]["binary_available"] == "/opt/fusion/claude"
    assert ready["readiness"] == {"ok": True, "issues": []}


def test_advanced_multi_repo_plan_requires_approval() -> None:
    plan = advanced_workflow_plan(
        "Merge two related repositories without losing target-only work",
        repository_count=2,
        requires_merge=True,
        host_mcp_tools=["mcp__gitnexus__query"],
    )
    steps = {item["step"]: item for item in plan["steps"]}
    assert steps["gitnexus_context"]["enabled"] is True
    assert steps["repo_merge"]["approval_required"] is True
    assert steps["external_changes"]["approval_required"] is True
    assert len(plan["plan_sha256"]) == 64
