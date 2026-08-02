from __future__ import annotations

import json
from pathlib import Path

import mcp_server

from claude_fusion_drive import __version__


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "claude-fusion-drive"


def test_plugin_manifest_and_mcp_identity() -> None:
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    mcp = json.loads((PLUGIN / ".mcp.json").read_text())
    assert manifest["name"] == "claude-fusion-drive"
    assert manifest["version"] == __version__
    assert manifest["skills"] == "./skills/"
    assert set(mcp["mcpServers"]) == {"claude-fusion-drive"}
    assert mcp_server.SERVER_INFO == {"name": "claude-fusion-drive", "version": __version__}


def test_six_required_skills_exist() -> None:
    expected = {
        "claude-fusion-drive",
        "claude-fusion-drive-config",
        "claude-fusion-drive-review",
        "claude-fusion-drive-rescue",
        "human-sim-users",
        "auto-eval",
    }
    actual = {
        path.parent.name
        for path in (PLUGIN / "skills").glob("*/SKILL.md")
    }
    assert actual == expected
    for name in expected:
        text = (PLUGIN / "skills" / name / "SKILL.md").read_text()
        assert text.startswith("---\nname:")
        assert "description:" in text.split("---", 2)[1]


def test_mcp_exposes_complete_control_plane() -> None:
    names = {tool["name"] for tool in mcp_server.TOOLS}
    required = {
        "config_propose",
        "config_approve",
        "workflow_report",
        "capability_probe",
        "preset_resolve",
        "fuse",
        "fuse_start",
        "approval_gate",
        "approval_gate_start",
        "job_status",
        "job_result",
        "job_abort",
        "subagent_fuse",
        "oauth_status",
        "batch_plan",
        "batch_prepare",
        "batch_submit",
        "plan_confirm",
        "goal_record",
        "execution_start",
        "execution_finish",
        "rescue_create",
        "rescue_resume",
        "human_sim_questions",
        "human_sim_create",
        "auto_eval",
        "auto_eval_run",
    }
    assert required <= names
    assert len(names) == len(mcp_server.TOOLS)


def test_mcp_initialize_and_tool_list_protocol() -> None:
    initialized = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert initialized["result"]["serverInfo"]["name"] == "claude-fusion-drive"
    listed = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(listed["result"]["tools"]) == len(mcp_server.TOOLS)


def test_offline_doctor_is_valid(isolated_runtime, monkeypatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-only-placeholder")
    result = mcp_server.call_tool("doctor", {"host_mcp_tools": []})
    assert result["ok"] is True
    assert result["config"] == {"ok": True, "errors": []}
    assert result["capabilities"]["credential_policy"].startswith("This probe does not read")


def test_subscription_doctor_checks_binaries_and_create_thread(
    isolated_runtime,
    monkeypatch,
) -> None:
    available = {
        "claude": "/resolved/claude",
        "grok": "/resolved/grok",
    }
    monkeypatch.setattr(
        "claude_fusion_drive.capabilities.shutil.which",
        lambda command: available.get(command),
    )
    result = mcp_server.call_tool(
        "doctor",
        {
            "profile": "subscription-oauth",
            "host_mcp_tools": ["claude_code.TaskCreate"],
        },
    )
    assert result["ok"] is True
    assert result["version"] == "0.1.2"
    assert result["capabilities"]["selected_profile"] == "subscription-oauth"
    assert result["capabilities"]["providers"]["claude_oauth"]["binary_available"] == "/resolved/claude"
    assert result["capabilities"]["providers"]["grok_oauth"]["binary_available"] == "/resolved/grok"
    assert result["capabilities"]["host_goal"]["available"] is True


def test_hybrid_doctor_requires_xai_env_and_has_no_openrouter_dependency(
    isolated_runtime,
    monkeypatch,
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "test-only-placeholder")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        "claude_fusion_drive.capabilities.shutil.which",
        lambda command: "/resolved/claude" if command == "claude" else None,
    )
    result = mcp_server.call_tool(
        "doctor",
        {
            "profile": "xai-claude-oauth",
            "host_mcp_tools": ["claude_code.TaskCreate"],
        },
    )
    assert result["ok"] is True
    assert result["version"] == "0.1.2"
    capabilities = result["capabilities"]
    assert capabilities["required_providers"] == ["claude_oauth", "xai_api"]
    assert capabilities["providers"]["claude_oauth"]["binary_available"] == "/resolved/claude"
    assert capabilities["providers"]["xai_api"]["api_key_env_present"] is True
    assert capabilities["providers"]["xai_api"]["auth_value_accessed"] is False
    assert capabilities["providers"]["openrouter_api"]["required_for_profile"] is False
    assert capabilities["host_goal"]["available"] is True


def test_requirement_matrix_and_upstream_attribution_exist() -> None:
    matrix = (ROOT / "docs" / "REQUIREMENT_MATRIX.md").read_text()
    upstream = (ROOT / "docs" / "UPSTREAM.md").read_text()
    for requirement_id in (
        "CFG-01",
        "PLAN-01",
        "GOAL-01",
        "GATE-01",
        "SUB-01",
        "AUTH-01",
        "BAT-01",
        "RES-01",
        "SIM-01",
        "EVAL-01",
        "PKG-01",
    ):
        assert requirement_id in matrix
    assert "Relentless Inception 0.1.4" in upstream
    assert "0cb3dec" in upstream
