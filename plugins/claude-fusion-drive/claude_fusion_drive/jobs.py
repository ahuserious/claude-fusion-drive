"""Durable non-blocking Fusion Drive jobs.

The MCP request starts a detached worker and returns immediately. Each job is
bound to an immutable request and configuration hash so a repeated
idempotency key cannot silently dispatch duplicate provider work.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import __version__
from .config import load_config, runtime_dir, validate_config
from .engine import FusionDriveEngine
from .errors import ConfigurationError, ExternalActionRequired
from .util import (
    atomic_write_json,
    canonical_hash,
    exclusive_lock,
    json_copy,
    now_utc,
    read_json,
    validate_identifier,
)


TERMINAL_STATUSES = {"completed", "failed", "aborted"}
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
TOKEN_PATTERN = re.compile(
    r"\b(?:sk|xai|oauth|bearer)[-_A-Za-z0-9.]{12,}\b",
    re.IGNORECASE,
)


def _safe_error(value: str, limit: int = 500) -> str:
    redacted = EMAIL_PATTERN.sub("<redacted-email>", value)
    redacted = TOKEN_PATTERN.sub("<redacted-token>", redacted)
    return redacted.strip()[:limit]


def _jobs_root() -> Path:
    root = runtime_dir() / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def _job_directory(job_id: str) -> Path:
    path = _jobs_root() / validate_identifier(job_id, "job_id")
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _manifest_path(job_id: str) -> Path:
    return _job_directory(job_id) / "job.json"


def _request_path(job_id: str) -> Path:
    return _job_directory(job_id) / "request.json"


def _result_path(job_id: str) -> Path:
    return _job_directory(job_id) / "result.json"


def _lock_path(job_id: str) -> Path:
    return _job_directory(job_id) / ".job.lock"


def _manifest_hash(manifest: Mapping[str, Any]) -> str:
    value = json_copy(dict(manifest))
    value.pop("manifest_sha256", None)
    return canonical_hash(value)


def _load_manifest(job_id: str) -> dict[str, Any]:
    path = _manifest_path(job_id)
    if not path.exists():
        raise ConfigurationError(f"Unknown Fusion Drive job: {job_id}")
    manifest = read_json(path)
    if manifest.get("manifest_sha256") != _manifest_hash(manifest):
        raise ConfigurationError("Fusion Drive job manifest hash mismatch")
    return manifest


def _save_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["updated_at"] = now_utc()
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    atomic_write_json(_manifest_path(str(manifest["job_id"])), manifest)
    return json_copy(manifest)


def _public_manifest(manifest: Mapping[str, Any], *, reused: bool | None = None) -> dict[str, Any]:
    result = {
        key: json_copy(manifest.get(key))
        for key in (
            "schema_version",
            "job_id",
            "run_id",
            "operation",
            "profile",
            "status",
            "abort_requested",
            "request_sha256",
            "config_sha256",
            "plugin_version",
            "worker_pid",
            "worker_state",
            "created_at",
            "started_at",
            "finished_at",
            "updated_at",
            "result_sha256",
            "error",
        )
    }
    result["recoverable"] = True
    result["automatic_redispatch"] = False
    if reused is not None:
        result["reused"] = reused
    return result


def _job_id(operation: str, idempotency_key: str) -> str:
    validate_identifier(idempotency_key, "idempotency_key")
    return "job-" + canonical_hash(
        {"operation": operation, "idempotency_key": idempotency_key}
    )[:24]


def _worker_command(job_id: str) -> tuple[list[str], dict[str, str], Path]:
    plugin_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(plugin_root)
        if not existing_python_path
        else str(plugin_root) + os.pathsep + existing_python_path
    )
    command = [
        sys.executable,
        "-m",
        "claude_fusion_drive.jobs",
        "--worker",
        job_id,
    ]
    return command, environment, plugin_root


def _start_job(
    operation: str,
    *,
    idempotency_key: str,
    profile_name: str,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    config = load_config()
    errors = validate_config(config)
    if errors:
        raise ConfigurationError(
            "Cannot start a job with invalid configuration:\n- "
            + "\n- ".join(errors)
        )
    if profile_name not in config["profiles"]:
        raise ConfigurationError(f"Unknown Fusion Drive profile: {profile_name}")

    job_id = _job_id(operation, idempotency_key)
    request = {
        "schema_version": 1,
        "job_id": job_id,
        "operation": operation,
        "profile": profile_name,
        "arguments": json_copy(dict(arguments)),
    }
    request_sha256 = canonical_hash(request)
    config_sha256 = canonical_hash(config)

    with exclusive_lock(_lock_path(job_id)):
        manifest_path = _manifest_path(job_id)
        if manifest_path.exists():
            manifest = _load_manifest(job_id)
            if (
                manifest.get("request_sha256") != request_sha256
                or manifest.get("config_sha256") != config_sha256
            ):
                raise ConfigurationError(
                    "Idempotency key already belongs to a different request or configuration"
                )
            return _public_manifest(manifest, reused=True)

        atomic_write_json(_request_path(job_id), request)
        created_at = now_utc()
        manifest = {
            "schema_version": 1,
            "job_id": job_id,
            "run_id": job_id,
            "operation": operation,
            "profile": profile_name,
            "status": "queued",
            "abort_requested": False,
            "request_sha256": request_sha256,
            "config_sha256": config_sha256,
            "plugin_version": __version__,
            "worker_pid": None,
            "worker_state": "launching",
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "updated_at": created_at,
            "result_sha256": None,
            "error": None,
        }
        _save_manifest(manifest)
        command, environment, plugin_root = _worker_command(job_id)
        try:
            worker = subprocess.Popen(
                command,
                cwd=plugin_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        except OSError as exc:
            manifest["status"] = "failed"
            manifest["worker_state"] = "launch_failed"
            manifest["finished_at"] = now_utc()
            manifest["error"] = {
                "type": type(exc).__name__,
                "message": _safe_error(str(exc)),
            }
            return _public_manifest(_save_manifest(manifest), reused=False)
        manifest["worker_pid"] = worker.pid
        manifest["worker_state"] = "spawned"
        return _public_manifest(_save_manifest(manifest), reused=False)


def start_fuse_job(
    *,
    task: str,
    idempotency_key: str,
    confirmed_external_costs: bool,
    context: str = "",
    mechanical_evidence: str = "",
    profile_name: str | None = None,
) -> dict[str, Any]:
    if not confirmed_external_costs:
        raise ExternalActionRequired(
            "Asynchronous fusion consumes provider or subscription usage and requires confirmation"
        )
    if not task.strip():
        raise ConfigurationError("Fusion task cannot be empty")
    config = load_config()
    selected_profile = profile_name or str(config["active_profile"])
    return _start_job(
        "fuse",
        idempotency_key=idempotency_key,
        profile_name=selected_profile,
        arguments={
            "task": task,
            "context": context,
            "mechanical_evidence": mechanical_evidence,
        },
    )


def start_approval_gate_job(
    *,
    task: str,
    artifact: str,
    stage: str,
    idempotency_key: str,
    confirmed_external_costs: bool,
    mechanical_evidence: str = "",
    profile_name: str | None = None,
    workflow_id: str | None = None,
    expected_lifecycle_sha256: str | None = None,
) -> dict[str, Any]:
    if not confirmed_external_costs:
        raise ExternalActionRequired(
            "Asynchronous approval review consumes provider or subscription usage and requires confirmation"
        )
    if not task.strip() or not artifact.strip():
        raise ConfigurationError("Approval task and artifact cannot be empty")
    if workflow_id and not expected_lifecycle_sha256:
        raise ConfigurationError(
            "expected_lifecycle_sha256 is required when recording a workflow gate"
        )
    config = load_config()
    selected_profile = profile_name or str(config["active_profile"])
    profile = config.get("profiles", {}).get(selected_profile)
    if not isinstance(profile, Mapping):
        raise ConfigurationError(
            f"Unknown Fusion Drive profile: {selected_profile}"
        )
    gate_set = config["gate_sets"][profile["gate_set"]]
    if stage not in gate_set["stages"]:
        raise ConfigurationError(
            f"Unknown approval stage for profile {selected_profile}: {stage}"
        )
    return _start_job(
        "approval_gate",
        idempotency_key=idempotency_key,
        profile_name=selected_profile,
        arguments={
            "task": task,
            "artifact": artifact,
            "stage": stage,
            "mechanical_evidence": mechanical_evidence,
            "workflow_id": workflow_id,
            "expected_lifecycle_sha256": expected_lifecycle_sha256,
        },
    )


def _pid_is_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def job_status(job_id: str) -> dict[str, Any]:
    validate_identifier(job_id, "job_id")
    with exclusive_lock(_lock_path(job_id)):
        manifest = _load_manifest(job_id)
        queued_without_worker = (
            manifest["status"] == "queued"
            and manifest.get("worker_pid") is None
        )
        exited_without_receipt = (
            manifest["status"] not in TERMINAL_STATUSES
            and manifest.get("worker_pid") is not None
            and not _pid_is_alive(manifest.get("worker_pid"))
        )
        if queued_without_worker or exited_without_receipt:
            manifest["status"] = (
                "aborted" if manifest.get("abort_requested") else "failed"
            )
            manifest["worker_state"] = (
                "aborted"
                if manifest["status"] == "aborted"
                else "exited_without_receipt"
            )
            manifest["finished_at"] = now_utc()
            if manifest["status"] == "failed":
                manifest["error"] = {
                    "type": "WorkerExitedWithoutReceipt",
                    "message": (
                        "The detached worker exited without a terminal receipt; "
                        "the job will not be redispatched automatically"
                    ),
                }
            manifest = _save_manifest(manifest)
        return _public_manifest(manifest)


def job_result(job_id: str) -> dict[str, Any]:
    manifest = _load_manifest(validate_identifier(job_id, "job_id"))
    if manifest["status"] != "completed":
        raise ConfigurationError(
            f"Fusion Drive job {job_id} is {manifest['status']}; no completed result is available"
        )
    result = read_json(_result_path(job_id))
    if canonical_hash(result) != manifest.get("result_sha256"):
        raise ConfigurationError("Fusion Drive job result hash mismatch")
    return {
        "job": _public_manifest(manifest),
        "result": result,
    }


def job_abort(job_id: str) -> dict[str, Any]:
    validate_identifier(job_id, "job_id")
    with exclusive_lock(_lock_path(job_id)):
        manifest = _load_manifest(job_id)
        if manifest["status"] in TERMINAL_STATUSES:
            return _public_manifest(manifest)
        manifest["abort_requested"] = True
        manifest["status"] = "abort_requested"
        manifest["worker_state"] = "abort_requested"
        run_directory = runtime_dir() / "engine" / "runs" / str(manifest["run_id"])
        run_directory.mkdir(parents=True, exist_ok=True)
        os.chmod(run_directory, 0o700)
        kill_path = run_directory / "KILL"
        kill_path.touch(exist_ok=True)
        os.chmod(kill_path, 0o600)
        return _public_manifest(_save_manifest(manifest))


def _read_request(job_id: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
    request = read_json(_request_path(job_id))
    if canonical_hash(request) != manifest.get("request_sha256"):
        raise ConfigurationError("Fusion Drive job request hash mismatch")
    return request


def _finish_job(
    job_id: str,
    *,
    status: str,
    result: Mapping[str, Any] | None = None,
    error: BaseException | None = None,
) -> dict[str, Any]:
    with exclusive_lock(_lock_path(job_id)):
        manifest = _load_manifest(job_id)
        if result is not None:
            atomic_write_json(_result_path(job_id), result)
            manifest["result_sha256"] = canonical_hash(result)
        manifest["status"] = status
        manifest["worker_state"] = status
        manifest["finished_at"] = now_utc()
        if error is not None:
            manifest["error"] = {
                "type": type(error).__name__,
                "message": _safe_error(str(error)),
            }
        return _save_manifest(manifest)


def run_job(
    job_id: str,
    *,
    engine_factory: Callable[[], FusionDriveEngine] = FusionDriveEngine,
) -> dict[str, Any]:
    validate_identifier(job_id, "job_id")
    try:
        with exclusive_lock(_lock_path(job_id)):
            manifest = _load_manifest(job_id)
            if manifest["status"] in TERMINAL_STATUSES:
                return manifest
            if manifest.get("abort_requested"):
                manifest["status"] = "aborted"
                manifest["worker_state"] = "aborted"
                manifest["finished_at"] = now_utc()
                return _save_manifest(manifest)
            config = load_config()
            if canonical_hash(config) != manifest.get("config_sha256"):
                raise ConfigurationError(
                    "Configuration changed after job creation; provider work was not dispatched"
                )
            request = _read_request(job_id, manifest)
            manifest["status"] = "running"
            manifest["worker_state"] = "running"
            manifest["started_at"] = now_utc()
            manifest["worker_pid"] = os.getpid()
            _save_manifest(manifest)

        arguments = request["arguments"]
        engine = engine_factory()
        if request["operation"] == "fuse":
            result = engine.fuse(
                str(arguments["task"]),
                context=str(arguments.get("context", "")),
                mechanical_evidence=str(
                    arguments.get("mechanical_evidence", "")
                ),
                profile_name=str(request["profile"]),
                resume_run_id=job_id,
            )
        elif request["operation"] == "approval_gate":
            result = engine.approval_gate(
                str(arguments["task"]),
                str(arguments["artifact"]),
                stage=str(arguments["stage"]),
                mechanical_evidence=str(
                    arguments.get("mechanical_evidence", "")
                ),
                profile_name=str(request["profile"]),
                workflow_id=arguments.get("workflow_id"),
                expected_lifecycle_sha256=arguments.get(
                    "expected_lifecycle_sha256"
                ),
                resume_run_id=job_id,
            )
        else:
            raise ConfigurationError(
                f"Unsupported asynchronous operation: {request['operation']}"
            )
        return _finish_job(job_id, status="completed", result=result)
    except BaseException as exc:
        try:
            manifest = _load_manifest(job_id)
            status = "aborted" if manifest.get("abort_requested") else "failed"
            return _finish_job(job_id, status=status, error=exc)
        except BaseException:
            raise exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-fusion-drive-job")
    parser.add_argument("--worker", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    manifest = run_job(str(arguments.worker))
    return 0 if manifest.get("status") in {"completed", "aborted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
