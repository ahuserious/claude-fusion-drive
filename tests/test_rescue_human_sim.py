from __future__ import annotations

import pytest

from claude_fusion_drive.errors import ConfigurationError
from claude_fusion_drive.human_sim import (
    QUESTIONNAIRE,
    campaign_status,
    create_campaign,
    human_sim_questions,
    record_campaign_goal,
    record_campaign_iteration,
)
from claude_fusion_drive.rescue import (
    create_rescue_packet,
    record_rescue_attempt,
    resume_rescue,
)


def _rescue_packet() -> dict:
    return create_rescue_packet(
        problem="The implementation repeatedly fails its deterministic report check.",
        acceptance_criteria=["Equal input produces equal bytes", "All tests pass"],
        work_units=[
            {"unit_id": "diagnose", "objective": "Find the nondeterministic input"},
            {
                "unit_id": "repair",
                "objective": "Remove nondeterminism",
                "dependencies": ["diagnose"],
            },
        ],
        constraints=["Do not discard failed evidence"],
        evidence_bar=["Two equal-input byte comparisons"],
    )


def _preferences() -> dict:
    return {item["key"]: f"configured {item['key']}" for item in QUESTIONNAIRE}


def test_rescue_packet_is_content_addressed_and_idempotent(isolated_runtime) -> None:
    first = _rescue_packet()
    second = _rescue_packet()
    assert first["packet_id"] == second["packet_id"]
    assert first["packet_sha256"] == second["packet_sha256"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    assert first["strategy"]["preserve_failed_attempts"] is True


def test_rescue_records_checkpoint_and_resumes_from_it(isolated_runtime) -> None:
    packet = _rescue_packet()
    packet = record_rescue_attempt(
        packet["packet_id"],
        unit_id="diagnose",
        outcome="passed",
        evidence=["timestamp was injected"],
        checkpoint={"commit": "abc", "finding": "remove current time"},
        expected_manifest_sha256=packet["manifest_sha256"],
    )
    resumed = resume_rescue(packet["packet_id"])
    repair = next(item for item in resumed["pending_units"] if item["unit_id"] == "repair")
    assert repair["resume_checkpoint"] is None
    diagnosed = next(item for item in packet["work_units"] if item["unit_id"] == "diagnose")
    assert diagnosed["last_proven_checkpoint"]["finding"] == "remove current time"


def test_rescue_stale_receipt_is_rejected(isolated_runtime) -> None:
    packet = _rescue_packet()
    stale = packet["manifest_sha256"]
    record_rescue_attempt(
        packet["packet_id"],
        unit_id="diagnose",
        outcome="failed",
        failure_fingerprint="same",
        expected_manifest_sha256=stale,
    )
    with pytest.raises(ConfigurationError, match="Stale rescue manifest"):
        record_rescue_attempt(
            packet["packet_id"],
            unit_id="diagnose",
            outcome="failed",
            failure_fingerprint="same",
            expected_manifest_sha256=stale,
        )


def test_rescue_repeated_failure_hands_off(isolated_runtime) -> None:
    packet = _rescue_packet()
    for _ in range(3):
        packet = record_rescue_attempt(
            packet["packet_id"],
            unit_id="diagnose",
            outcome="failed",
            evidence=["same trace"],
            failure_fingerprint="repeat-001",
            diagnosis="Fresh diagnosis still reaches the same failure.",
            expected_manifest_sha256=packet["manifest_sha256"],
        )
    assert packet["status"] == "human_handoff"
    assert packet["handoff"]["reason"] == "same_failure_fingerprint"
    assert resume_rescue(packet["packet_id"])["human_handoff"]["fingerprint"] == "repeat-001"


def test_human_sim_questionnaire_covers_required_dimensions() -> None:
    result = human_sim_questions()
    keys = {item["key"] for item in result["questions"]}
    assert keys == {
        "platform_runtime",
        "ui_ux",
        "viewports",
        "personas",
        "accessibility",
        "logs",
        "performance",
        "privacy_security",
        "data_integrity",
        "external_writes",
    }
    assert "manifest-driven" in result["goal_note"]


def test_campaign_returns_missing_questions_before_creation(isolated_runtime) -> None:
    result = create_campaign(
        preferences={"ui_ux": "polished"},
        acceptance_criteria=["pass"],
        scenarios=[{"objective": "test"}],
    )
    assert result["created"] is False
    assert "performance" in result["missing_preferences"]


def test_extra_goal_requires_explicit_confirmation(isolated_runtime) -> None:
    with pytest.raises(ConfigurationError, match="explicit"):
        create_campaign(
            preferences=_preferences(),
            acceptance_criteria=["pass"],
            scenarios=[{"objective": "test"}],
            request_extra_goal=True,
            confirmed_extra_goal=False,
        )


def test_campaign_goal_receipt_and_completion(isolated_runtime) -> None:
    campaign = create_campaign(
        preferences=_preferences(),
        acceptance_criteria=["no console errors", "performance passes"],
        scenarios=[{"scenario_id": "desktop", "objective": "Complete primary journey"}],
        request_extra_goal=True,
        confirmed_extra_goal=True,
    )
    campaign = record_campaign_goal(
        campaign["campaign_id"],
        goal_thread_id="thread-human-sim",
        expected_manifest_sha256=campaign["manifest_sha256"],
    )
    assert campaign["extra_goal"]["host_action_required"] is False
    campaign = record_campaign_iteration(
        campaign["campaign_id"],
        scenario_id="desktop",
        passed=True,
        evidence=["screenshot hash", "log capture", "performance trace"],
        errors=[],
        performance_pass=True,
        criteria_evidenced=True,
        stalled_subagents=[],
        expected_manifest_sha256=campaign["manifest_sha256"],
    )
    assert campaign["status"] == "complete"
    assert campaign_status(campaign["campaign_id"])["next_action"].startswith("Stop")


def test_campaign_repeated_failure_hands_off(isolated_runtime) -> None:
    campaign = create_campaign(
        preferences=_preferences(),
        acceptance_criteria=["pass"],
        scenarios=[{"scenario_id": "mobile", "objective": "Complete mobile journey"}],
    )
    for _ in range(3):
        campaign = record_campaign_iteration(
            campaign["campaign_id"],
            scenario_id="mobile",
            passed=False,
            evidence=["trace"],
            errors=[
                {
                    "fingerprint": "layout-loop",
                    "message": "button remains outside viewport",
                    "source": "visual",
                }
            ],
            expected_manifest_sha256=campaign["manifest_sha256"],
        )
    assert campaign["status"] == "human_handoff"
    assert campaign["handoff"]["fingerprint"] == "layout-loop"

