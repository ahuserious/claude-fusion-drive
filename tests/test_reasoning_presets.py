from __future__ import annotations

from claude_fusion_drive.config import load_config
from claude_fusion_drive.presets import list_presets, resolve_preset
from claude_fusion_drive.reasoning import normalize_reasoning, seat_reasoning_report


def test_xai_xhigh_intent_is_normalized_truthfully() -> None:
    config = load_config(include_user=False)
    result = normalize_reasoning(config["providers"]["xai_api"], "grok-4.5", "xhigh")
    assert result == {
        "requested": "xhigh",
        "effective": "high",
        "normalization": "provider_ceiling",
        "detail": "Grok 4.5 exposes low, medium, and high; xhigh intent is sent as high.",
    }


def test_openrouter_keeps_xhigh_and_claude_cli_maps_to_max() -> None:
    config = load_config(include_user=False)
    openrouter = normalize_reasoning(
        config["providers"]["openrouter_api"], "openai/gpt-5.6-sol", "xhigh"
    )
    claude = normalize_reasoning(
        config["providers"]["claude_oauth"], "claude-fable-5", "xhigh"
    )
    assert openrouter["effective"] == "xhigh"
    assert claude["effective"] == "max"
    assert claude["normalization"] == "provider_equivalent"


def test_reasoning_report_discloses_requested_and_effective() -> None:
    rows = {row["seat"]: row for row in seat_reasoning_report(load_config(include_user=False))}
    assert rows["grok45-panel"]["requested"] == "xhigh"
    assert rows["grok45-panel"]["effective"] == "high"
    assert rows["gpt56sol-panel"]["effective"] == "xhigh"
    assert rows["fable5-oauth-panel"]["effective"] == "max"


def test_hybrid_profile_reasoning_keeps_requested_and_effective_levels_distinct() -> None:
    config = load_config(include_user=False)
    rows = {row["seat"]: row for row in seat_reasoning_report(config)}
    for seat_name in (
        "all-grok-panel-a",
        "all-grok-panel-b",
        "all-grok-judge",
        "grok45-gate-primary",
        "grok45-gate-secondary",
    ):
        assert rows[seat_name]["requested"] == "xhigh"
        assert rows[seat_name]["effective"] == "high"
    for seat_name in ("fable5-oauth-panel", "fable5-oauth-fuser"):
        assert rows[seat_name]["requested"] == "xhigh"
        assert rows[seat_name]["effective"] == "max"


def test_grok_fusion_drive_preset() -> None:
    preset = resolve_preset("grok-fusion-drive", load_config(include_user=False))
    assert preset["driver"] == {
        "owner": "claude_host",
        "model": "claude-fable-5",
        "reasoning": "max",
    }
    assert preset["worker_engine_name"] == "all_grok_4_5"
    assert len(preset["worker_engine"]["panel"]) == 2
    assert preset["gate_set_name"] == "approval-gates"
    assert preset["max_fusion_depth"] == 1
    assert preset["host_owned_driver"] is True
    assert len(preset["preset_sha256"]) == 64


def test_presets_resolve_deterministically() -> None:
    config = load_config(include_user=False)
    first = list_presets(config)
    second = list_presets(config)
    assert first == second
    assert set(first) == {"all-grok-4.5", "canonical-in-harness", "grok-fusion-drive", "mini-fuse"}
