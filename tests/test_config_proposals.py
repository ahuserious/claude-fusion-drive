from __future__ import annotations

import pytest

from claude_fusion_drive.config import (
    approve_config,
    load_config,
    propose_config,
    user_config_path,
)
from claude_fusion_drive.errors import ConfigurationError


def test_proposal_returns_full_candidate_and_is_idempotent(isolated_runtime) -> None:
    changes = {"active_profile": "all-grok-4.5"}
    first = propose_config(changes, rationale="Use the explicit all-Grok preset")
    second = propose_config(changes, rationale="Use the explicit all-Grok preset")
    assert first["proposal_hash"] == second["proposal_hash"]
    assert first["candidate"]["active_profile"] == "all-grok-4.5"
    assert first["requires_final_approval"] is True
    assert first["reasoning"]
    assert not user_config_path().exists()


def test_approval_requires_confirmation_and_exact_hash(isolated_runtime) -> None:
    proposal = propose_config({"active_profile": "all-grok-4.5"})
    with pytest.raises(ConfigurationError, match="confirmed=true"):
        approve_config(proposal["proposal_hash"], confirmed=False)
    applied = approve_config(proposal["proposal_hash"], confirmed=True)
    assert applied["approved"] is True
    assert load_config()["active_profile"] == "all-grok-4.5"
    assert user_config_path().exists()


def test_stale_proposal_is_rejected(isolated_runtime) -> None:
    first = propose_config({"active_profile": "all-grok-4.5"})
    second = propose_config(
        {"profiles": {"maximum-intelligence": {"execution": {"run_tests": False}}}}
    )
    approve_config(second["proposal_hash"], confirmed=True)
    with pytest.raises(ConfigurationError, match="changed after proposal"):
        approve_config(first["proposal_hash"], confirmed=True)


def test_plaintext_secret_is_rejected(isolated_runtime) -> None:
    with pytest.raises(ConfigurationError, match="may not store a credential"):
        propose_config({"providers": {"xai_api": {"api_key": "secret-value"}}})


def test_invalid_canonical_change_is_rejected(isolated_runtime) -> None:
    with pytest.raises(ConfigurationError, match="canonical order"):
        propose_config({"engines": {"in_harness": {"panel": ["grok45-panel"]}}})


def test_mcp_config_set_is_a_proposal_not_direct_write(isolated_runtime) -> None:
    import mcp_server

    result = mcp_server.call_tool(
        "config_set",
        {"path": "active_profile", "value": "all-grok-4.5", "rationale": "test"},
    )
    assert result["requires_final_approval"] is True
    assert "workflow_report" in result
    assert not user_config_path().exists()

