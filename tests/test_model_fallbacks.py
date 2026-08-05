from __future__ import annotations

from claude_fusion_drive.config import load_config, validate_config
from claude_fusion_drive.fallback import (
    active_substitutions,
    is_substituted,
    model_fallbacks,
    resolve_model,
)


def test_default_map_redirects_fable_to_opus() -> None:
    config = load_config(include_user=False)
    assert model_fallbacks(config)["claude-fable-5"] == "claude-opus-5"
    assert resolve_model("claude-fable-5", config) == "claude-opus-5"
    assert is_substituted("claude-fable-5", config) is True


def test_provider_prefix_is_preserved() -> None:
    config = load_config(include_user=False)
    assert resolve_model("anthropic/claude-fable-5", config) == "anthropic/claude-opus-5"
    assert resolve_model("openrouter/anthropic/claude-fable-5", config) == (
        "openrouter/anthropic/claude-opus-5"
    )


def test_unmapped_models_pass_through_untouched() -> None:
    config = load_config(include_user=False)
    for model in ("grok-4.5", "gpt-5.6-sol", "claude-opus-5", "x-ai/grok-4.5"):
        assert resolve_model(model, config) == model
        assert is_substituted(model, config) is False


def test_empty_map_is_a_no_op() -> None:
    assert resolve_model("claude-fable-5", {}) == "claude-fable-5"
    assert active_substitutions({}) == []


def test_active_substitutions_only_reports_referenced_models() -> None:
    config = {
        "model_fallbacks": {"claude-fable-5": "claude-opus-5", "never-used": "other"},
        "seats": {"a": {"model": "claude-fable-5"}},
        "profiles": {},
        "subagent_presets": {},
    }
    assert active_substitutions(config) == [
        {"from": "claude-fable-5", "to": "claude-opus-5"}
    ]


def test_fable_pinned_rules_accept_the_fallback_target() -> None:
    # The two invariants that hard-pin Fable 5 must not reject a configuration
    # whose declared fallback has already replaced it.
    config = load_config(include_user=False)
    config["subagent_presets"]["grok-fusion-drive"]["driver"]["model"] = "claude-opus-5"
    config["profiles"]["xai-claude-oauth"]["execution"]["model"] = "claude-opus-5"
    assert validate_config(config) == []


def test_fable_pinned_rules_still_reject_an_undeclared_model() -> None:
    config = load_config(include_user=False)
    config["subagent_presets"]["grok-fusion-drive"]["driver"]["model"] = "grok-4.5"
    errors = validate_config(config)
    assert any("grok-fusion-drive driver" in error for error in errors)
