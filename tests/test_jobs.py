from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_fusion_drive import jobs
from claude_fusion_drive.config import load_config
from claude_fusion_drive.errors import ConfigurationError, ExternalActionRequired


def _patch_detached_worker(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def fake_popen(command, **kwargs):
        calls.append({"command": command, "kwargs": kwargs})
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(jobs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(jobs, "_pid_is_alive", lambda _pid, _started_at=None: True)
    # Stub the OS start-time probe too, so `calls` stays a count of worker
    # dispatches rather than also catching the probe's own `ps` invocation.
    monkeypatch.setattr(jobs, "_process_started_at", lambda _pid: "Sat Aug  2 20:00:00 2026")
    return calls


def _start_fuse(monkeypatch: pytest.MonkeyPatch, *, key: str = "stable-fuse-key") -> dict:
    _patch_detached_worker(monkeypatch)
    return jobs.start_fuse_job(
        task="Build a verified plan",
        context="No workspace mutation",
        mechanical_evidence="offline fixture",
        profile_name="subscription-oauth",
        idempotency_key=key,
        confirmed_external_costs=True,
    )


def test_async_start_requires_explicit_external_cost_confirmation(
    isolated_runtime,
) -> None:
    with pytest.raises(ExternalActionRequired, match="requires confirmation"):
        jobs.start_fuse_job(
            task="Plan",
            idempotency_key="unconfirmed-fuse",
            confirmed_external_costs=False,
        )
    with pytest.raises(ExternalActionRequired, match="requires confirmation"):
        jobs.start_approval_gate_job(
            task="Review",
            artifact="Plan",
            stage="plan",
            idempotency_key="unconfirmed-gate",
            confirmed_external_costs=False,
        )


def test_approval_start_rejects_unknown_stage_before_worker_dispatch(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_detached_worker(monkeypatch)
    with pytest.raises(ConfigurationError, match="Unknown approval stage"):
        jobs.start_approval_gate_job(
            task="Review",
            artifact="Plan",
            stage="not-a-stage",
            profile_name="subscription-oauth",
            idempotency_key="invalid-stage",
            confirmed_external_costs=True,
        )
    assert calls == []


def test_fuse_start_returns_immediately_and_replays_idempotently(
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_detached_worker(monkeypatch)
    first = jobs.start_fuse_job(
        task="Build a verified plan",
        context="No workspace mutation",
        mechanical_evidence="offline fixture",
        profile_name="subscription-oauth",
        idempotency_key="durable-fuse",
        confirmed_external_costs=True,
    )
    assert first["status"] == "queued"
    assert first["reused"] is False
    assert first["run_id"] == first["job_id"]
    assert first["request_sha256"]
    assert first["config_sha256"]
    assert first["worker_pid"] == 4242
    assert first["worker_state"] == "spawned"
    assert first["automatic_redispatch"] is False
    assert len(calls) == 1
    assert calls[0]["command"][1:3] == ["-m", "claude_fusion_drive.jobs"]
    assert calls[0]["kwargs"]["start_new_session"] is True
    assert calls[0]["kwargs"]["stdin"] == jobs.subprocess.DEVNULL
    assert calls[0]["kwargs"]["stdout"] == jobs.subprocess.DEVNULL
    assert calls[0]["kwargs"]["stderr"] == jobs.subprocess.DEVNULL

    job_directory = isolated_runtime / "jobs" / first["job_id"]
    assert job_directory.stat().st_mode & 0o777 == 0o700
    assert (job_directory / "job.json").stat().st_mode & 0o777 == 0o600
    assert (job_directory / "request.json").stat().st_mode & 0o777 == 0o600

    replay = jobs.start_fuse_job(
        task="Build a verified plan",
        context="No workspace mutation",
        mechanical_evidence="offline fixture",
        profile_name="subscription-oauth",
        idempotency_key="durable-fuse",
        confirmed_external_costs=True,
    )
    assert replay["job_id"] == first["job_id"]
    assert replay["reused"] is True
    assert len(calls) == 1
    assert jobs.job_status(first["job_id"])["status"] == "queued"


def test_conflicting_idempotency_key_is_rejected_without_redispatch(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_detached_worker(monkeypatch)
    jobs.start_fuse_job(
        task="First immutable request",
        profile_name="subscription-oauth",
        idempotency_key="conflicting-fuse",
        confirmed_external_costs=True,
    )
    with pytest.raises(ConfigurationError, match="different request or configuration"):
        jobs.start_fuse_job(
            task="Different request",
            profile_name="subscription-oauth",
            idempotency_key="conflicting-fuse",
            confirmed_external_costs=True,
        )
    assert len(calls) == 1


def test_worker_completion_and_result_hash_validation(
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _start_fuse(monkeypatch, key="completed-fuse")
    invocations: list[dict] = []

    class FakeEngine:
        def fuse(self, task, **kwargs):
            invocations.append({"task": task, **kwargs})
            return {
                "workflow_id": "offline-workflow",
                "profile": kwargs["profile_name"],
                "synthesis": "verified plan",
            }

    manifest = jobs.run_job(
        started["job_id"],
        engine_factory=lambda: FakeEngine(),
    )
    assert manifest["status"] == "completed"
    assert manifest["worker_state"] == "completed"
    assert invocations == [
        {
            "task": "Build a verified plan",
            "context": "No workspace mutation",
            "mechanical_evidence": "offline fixture",
            "profile_name": "subscription-oauth",
            "resume_run_id": started["job_id"],
        }
    ]
    persisted = jobs.job_result(started["job_id"])
    assert persisted["result"]["synthesis"] == "verified plan"
    assert persisted["job"]["result_sha256"] == manifest["result_sha256"]
    result_path = isolated_runtime / "jobs" / started["job_id"] / "result.json"
    assert result_path.stat().st_mode & 0o777 == 0o600

    tampered = json.loads(result_path.read_text())
    tampered["synthesis"] = "tampered"
    result_path.write_text(json.dumps(tampered))
    with pytest.raises(ConfigurationError, match="result hash mismatch"):
        jobs.job_result(started["job_id"])


def test_job_wait_collapses_polling_and_returns_verified_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statuses = iter(
        [
            {"job_id": "job-test", "status": "queued"},
            {"job_id": "job-test", "status": "running"},
            {"job_id": "job-test", "status": "completed"},
        ]
    )
    monkeypatch.setattr(jobs, "job_status", lambda _job_id: next(statuses))
    monkeypatch.setattr(
        jobs,
        "job_result",
        lambda _job_id: {
            "job": {"job_id": "job-test", "status": "completed"},
            "result": {"synthesis": "verified"},
        },
    )
    monkeypatch.setattr(jobs.time, "sleep", lambda _seconds: None)

    result = jobs.job_wait(
        "job-test",
        timeout_seconds=5,
        poll_interval_seconds=0.1,
    )

    assert result["wait_timed_out"] is False
    assert result["result"]["synthesis"] == "verified"


def test_job_wait_returns_a_nonterminal_receipt_when_window_elapses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jobs,
        "job_status",
        lambda _job_id: {"job_id": "job-test", "status": "running"},
    )

    result = jobs.job_wait("job-test", timeout_seconds=0)

    assert result == {
        "job": {"job_id": "job-test", "status": "running"},
        "result": None,
        "wait_timed_out": True,
    }


@pytest.mark.parametrize("terminal_status", ["failed", "aborted"])
def test_job_wait_returns_terminal_failure_without_requesting_a_result(
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: str,
) -> None:
    terminal_job = {"job_id": "job-test", "status": terminal_status}
    monkeypatch.setattr(jobs, "job_status", lambda _job_id: terminal_job)

    def forbidden_job_result(_job_id: str) -> dict:
        raise AssertionError("a failed or aborted job has no result to retrieve")

    monkeypatch.setattr(jobs, "job_result", forbidden_job_result)

    result = jobs.job_wait("job-test", timeout_seconds=1)

    assert result == {
        "job": terminal_job,
        "result": None,
        "wait_timed_out": False,
    }


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        ("timeout_seconds", -0.1, "timeout_seconds must be between 0 and 300"),
        ("timeout_seconds", 301, "timeout_seconds must be between 0 and 300"),
        ("timeout_seconds", True, "timeout_seconds must be between 0 and 300"),
        (
            "poll_interval_seconds",
            0.09,
            "poll_interval_seconds must be between 0.1 and 10",
        ),
        (
            "poll_interval_seconds",
            10.1,
            "poll_interval_seconds must be between 0.1 and 10",
        ),
        (
            "poll_interval_seconds",
            False,
            "poll_interval_seconds must be between 0.1 and 10",
        ),
    ],
)
def test_job_wait_rejects_invalid_bounds(
    keyword: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(ConfigurationError, match=message):
        jobs.job_wait("job-test", **{keyword: value})


def test_approval_gate_worker_preserves_stage_and_resume_run_id(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_detached_worker(monkeypatch)
    started = jobs.start_approval_gate_job(
        task="Review the exact plan",
        artifact="Exact plan bytes",
        stage="plan",
        mechanical_evidence="requirements trace",
        profile_name="subscription-oauth",
        idempotency_key="approval-plan",
        confirmed_external_costs=True,
    )
    invocations: list[dict] = []

    class FakeEngine:
        def approval_gate(self, task, artifact, **kwargs):
            invocations.append(
                {"task": task, "artifact": artifact, **kwargs}
            )
            return {"verdict": "PASS", "reviews": [{}, {}]}

    manifest = jobs.run_job(
        started["job_id"],
        engine_factory=lambda: FakeEngine(),
    )
    assert manifest["status"] == "completed"
    assert invocations[0]["stage"] == "plan"
    assert invocations[0]["profile_name"] == "subscription-oauth"
    assert invocations[0]["resume_run_id"] == started["job_id"]
    assert jobs.job_result(started["job_id"])["result"]["verdict"] == "PASS"


def test_config_hash_drift_fails_before_engine_dispatch(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _start_fuse(monkeypatch, key="config-drift")
    changed_config = load_config()
    changed_config["providers"]["grok_oauth"]["command"] = "/changed/grok"
    monkeypatch.setattr(jobs, "load_config", lambda: changed_config)
    engine_created = False

    def forbidden_engine():
        nonlocal engine_created
        engine_created = True
        raise AssertionError("engine must not be created after config drift")

    manifest = jobs.run_job(
        started["job_id"],
        engine_factory=forbidden_engine,
    )
    assert manifest["status"] == "failed"
    assert engine_created is False
    assert "Configuration changed after job creation" in manifest["error"]["message"]


def test_abort_writes_recoverable_kill_switch_without_dispatch(
    isolated_runtime: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _start_fuse(monkeypatch, key="abort-fuse")
    receipt = jobs.job_abort(started["job_id"])
    assert receipt["status"] == "abort_requested"
    assert receipt["worker_state"] == "abort_requested"
    assert receipt["abort_requested"] is True
    assert (
        isolated_runtime
        / "engine"
        / "runs"
        / started["job_id"]
        / "KILL"
    ).is_file()

    def forbidden_engine():
        raise AssertionError("aborted job must not dispatch")

    manifest = jobs.run_job(
        started["job_id"],
        engine_factory=forbidden_engine,
    )
    assert manifest["status"] == "aborted"
    assert manifest["worker_state"] == "aborted"


def test_orphaned_worker_fails_closed_and_is_never_redispatched(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_detached_worker(monkeypatch)
    started = jobs.start_fuse_job(
        task="Preserve ambiguous work",
        profile_name="subscription-oauth",
        idempotency_key="orphaned-fuse",
        confirmed_external_costs=True,
    )
    monkeypatch.setattr(jobs, "_pid_is_alive", lambda _pid, _started_at=None: False)
    status = jobs.job_status(started["job_id"])
    assert status["status"] == "failed"
    assert status["worker_state"] == "exited_without_receipt"
    assert status["error"]["type"] == "WorkerExitedWithoutReceipt"
    assert status["automatic_redispatch"] is False

    replay = jobs.start_fuse_job(
        task="Preserve ambiguous work",
        profile_name="subscription-oauth",
        idempotency_key="orphaned-fuse",
        confirmed_external_costs=True,
    )
    assert replay["status"] == "failed"
    assert replay["reused"] is True
    assert len(calls) == 1


def test_worker_failure_receipt_is_sanitized(
    isolated_runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = _start_fuse(monkeypatch, key="sanitized-failure")

    class FailingEngine:
        def fuse(self, *args, **kwargs):
            raise RuntimeError(
                "user@example.com bearer-abcdefghijklmnop provider failed"
            )

    manifest = jobs.run_job(
        started["job_id"],
        engine_factory=lambda: FailingEngine(),
    )
    assert manifest["status"] == "failed"
    assert manifest["error"]["type"] == "RuntimeError"
    assert "<redacted-email>" in manifest["error"]["message"]
    assert "<redacted-token>" in manifest["error"]["message"]
    assert "user@example.com" not in manifest["error"]["message"]
    assert "abcdefghijklmnop" not in manifest["error"]["message"]
