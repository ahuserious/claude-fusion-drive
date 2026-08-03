"""The `reporting` block must actually gate response size.

Every flag here shipped in the default config from the start but was read by no
code, so a caller had no way to stop a single tool result from consuming more
context than the conversation it was reported into.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_fusion_drive.config import load_config, reporting_flags
from claude_fusion_drive.report import workflow_report

import mcp_server


def _config_with_reporting(**overrides: object) -> dict:
    config = load_config(include_user=False)
    config["reporting"] = {**config["reporting"], **overrides}
    return config


def test_reporting_flags_fall_back_to_defaults_when_block_is_missing() -> None:
    config = load_config(include_user=False)
    config.pop("reporting", None)
    flags = reporting_flags(config)
    assert flags["return_full_redacted_config_after_planning"] is True
    assert flags["max_inline_response_chars"] == 24000


def test_workflow_report_keeps_full_config_by_default() -> None:
    report = workflow_report(load_config(include_user=False))
    assert "config" in report
    assert "mermaid" in report
    assert "reasoning" in report


def test_workflow_report_drops_the_redacted_config_when_switched_off() -> None:
    config = _config_with_reporting(return_full_redacted_config_after_planning=False)
    report = workflow_report(config)
    assert "config" not in report
    # The exact-hash approval flow depends on these, so they must survive.
    assert report["config_hash"]
    assert report["validation"] == {"ok": True, "errors": []}


def test_workflow_report_drops_mermaid_and_reasoning_when_switched_off() -> None:
    config = _config_with_reporting(
        return_mermaid_after_planning=False,
        return_reasoning_normalization=False,
    )
    report = workflow_report(config)
    assert "mermaid" not in report
    assert "reasoning" not in report
    assert report["gates"]


def test_config_proposal_attaches_the_report_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "reporting_flags", lambda *a, **k: {"return_updated_report_for_config_proposals": True})
    payload = mcp_server._with_workflow_report({"candidate": load_config(include_user=False)}, "candidate")
    assert "workflow_report" in payload


def test_config_proposal_omits_the_report_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "reporting_flags", lambda *a, **k: {"return_updated_report_for_config_proposals": False})
    payload = mcp_server._with_workflow_report({"candidate": load_config(include_user=False)}, "candidate")
    assert "workflow_report" not in payload


def test_small_responses_are_returned_inline_unchanged() -> None:
    text = mcp_server._render_json({"ok": True, "value": 1})
    assert json.loads(text) == {"ok": True, "value": 1}


def test_oversized_responses_spill_to_disk_as_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "reporting_flags", lambda *a, **k: {"max_inline_response_chars": 500})
    payload = {"synthesis": "x" * 4000, "panel": ["y" * 2000]}

    envelope = json.loads(mcp_server._render_json(payload))

    assert envelope["response_spilled"] is True
    assert envelope["response_chars"] > 500
    # The caller has to be able to tell which section is worth reading back.
    assert set(envelope["section_chars"]) == {"synthesis", "panel"}
    spilled = Path(envelope["full_response_path"])
    assert json.loads(spilled.read_text(encoding="utf-8")) == payload


def test_spilling_is_disabled_by_a_non_positive_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "reporting_flags", lambda *a, **k: {"max_inline_response_chars": 0})
    payload = {"synthesis": "x" * 4000}
    assert json.loads(mcp_server._render_json(payload)) == payload


def test_a_failed_spill_still_returns_the_full_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_server, "reporting_flags", lambda *a, **k: {"max_inline_response_chars": 10})

    def explode(_text: str) -> Path:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(mcp_server, "_spill_response", explode)
    payload = {"synthesis": "x" * 400}
    assert json.loads(mcp_server._render_json(payload)) == payload


def test_dotted_path_proposals_are_rejected_instead_of_silently_landing() -> None:
    from claude_fusion_drive.config import propose_config
    from claude_fusion_drive.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="looks like a dotted path"):
        propose_config({"reporting.return_mermaid_after_planning": False})


def test_unknown_config_sections_are_rejected() -> None:
    from claude_fusion_drive.config import propose_config
    from claude_fusion_drive.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="not a Claude Fusion Drive configuration section"):
        propose_config({"reprting": {"theme": "dark"}})


def test_valid_nested_proposals_still_pass() -> None:
    from claude_fusion_drive.config import propose_config

    proposal = propose_config({"reporting": {"return_mermaid_after_planning": False}})
    assert proposal["requires_final_approval"] is True
