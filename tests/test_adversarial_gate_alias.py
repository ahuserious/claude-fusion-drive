"""`adversarial_gate` must run against the Fusion Drive config, not the legacy one.

It used to delegate straight to the vendored legacy server, whose config universe
has no drive gate sets and no OAuth seats and reports drive profile names as
"unknown profile". It now routes through FusionDriveEngine.approval_gate, so it
shares the drive gate sets, the hybrid registry, and the fixed verdict unwrap --
while still returning the inherited top-level payload, because the benchmark
contract reads `run_id` and `gate.passed` at the top level.

It records no lifecycle receipt: no workflow_id is passed, so record_gate is
never reached. `approval_gate` remains the recorded form.
"""

from __future__ import annotations

import pytest

# Every claude_fusion_drive / mcp_server import here is deliberately deferred
# into the functions below, for two separate reasons.
#
# 1. CI runs `unittest discover`, which does not load conftest.py and so never
#    puts the plugin root on sys.path; a module-level import would add a third
#    collection error to the two already there.
# 2. mcp_server and claude_fusion_drive.engine both pull `relentless_inception`
#    into sys.modules, and bench/validate_evidence.py refuses to load when that
#    module is already cached. This file sorts before tests/test_bench_assets.py,
#    so a module-level import here breaks bench collection under pytest.
# into the functions below. Both pull `relentless_inception` into sys.modules,
# and bench/validate_evidence.py refuses to load if that module is already
# cached when it is imported. This file sorts before tests/test_bench_assets.py,
# so a module-level import here breaks bench collection. Keeping them lazy makes
# that independent of filename ordering.


@pytest.fixture
def drive_gate(isolated_runtime, monkeypatch, tmp_path):
    """Patch the orchestrator at CLASS level and isolate the engine run store.

    call_tool builds its own FusionDriveEngine(), so an instance-level patch would
    not reach it and the call would make live provider requests. RELENTLESS_INCEPTION_DATA_DIR
    is set here because RELENTLESS_INCEPTION_HOME is a dead variable -- written in
    three places, read nowhere -- so without this the real orchestrator writes run
    directories into the developer's actual home.
    """

    from claude_fusion_drive.engine import FusionDriveEngine, translate_config
    from relentless_inception.orchestrator import FusionOrchestrator

    from tests.support import FakeProviderRegistry

    monkeypatch.setenv("RELENTLESS_INCEPTION_DATA_DIR", str(tmp_path / "engine"))
    registry = FakeProviderRegistry()

    def factory(self, profile_name: str | None = None):
        legacy, translated_profile = translate_config(self.config, profile_name=profile_name)
        return FusionOrchestrator(legacy, registry=registry), translated_profile

    monkeypatch.setattr(FusionDriveEngine, "_orchestrator", factory)
    return registry


def _call(**overrides):
    import mcp_server

    arguments = {
        "task": "Verify the fused plan",
        "artifact": "A bounded implementation plan with acceptance criteria.",
        "mechanical_evidence": "pytest: 370 passed",
    }
    arguments.update(overrides)
    return mcp_server.call_tool("adversarial_gate", arguments)


def test_alias_runs_the_drive_gate_reviewers(drive_gate) -> None:
    result = _call()
    assert result["verdict"] == "PASS"
    assert result["gate"]["passed"] is True

    reviewers = {
        str(entry.get("seat_name"))
        for entry in result["gate"].get("reviews", result["gate"].get("verdicts", []))
        if isinstance(entry, dict)
    }
    if reviewers:
        # Drive gate-set reviewers, not the legacy grok45_verifier pair.
        assert reviewers <= {"grok45-gate-primary", "grok45-gate-secondary"}


def test_alias_preserves_the_inherited_envelope(drive_gate) -> None:
    # bench/validate_evidence.py reads run_id and gate.passed at the TOP level of
    # this payload. Nothing else in the suite guards that seam.
    result = _call()
    assert "run_id" in result
    assert "artifacts_dir" in result
    assert result["gate"]["passed"] is True
    # ...and the drive-derived fields are additive, not replacements.
    assert result["verdict"] == "PASS"
    assert result["artifact_sha256"]
    assert result["profile"]
    assert result["engine"]


def test_alias_never_touches_the_legacy_server(drive_gate, monkeypatch) -> None:
    """Regression guard against a silent revert to legacy.call_tool."""

    import mcp_server

    def _fail(*_args, **_kwargs):
        raise AssertionError("adversarial_gate must not delegate to the legacy server")

    monkeypatch.setattr(mcp_server.legacy, "call_tool", _fail)
    assert _call()["verdict"] == "PASS"


def test_alias_records_no_lifecycle_receipt(drive_gate) -> None:
    assert "host_lifecycle" not in _call()


def test_alias_rejects_a_legacy_profile_name(drive_gate) -> None:
    from claude_fusion_drive.errors import ConfigurationError

    # Drive profiles are hyphenated; the legacy underscore spelling must fail
    # loudly rather than silently gating against a different config universe.
    with pytest.raises(ConfigurationError, match="Unknown Fusion Drive profile"):
        _call(profile="maximum_intelligence")

    assert _call(profile="maximum-intelligence")["profile"] == "maximum-intelligence"


def test_alias_is_still_declared_in_the_tool_surface() -> None:
    import mcp_server

    assert "adversarial_gate" in {tool["name"] for tool in mcp_server.TOOLS}
