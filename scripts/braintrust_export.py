#!/usr/bin/env python3
"""Export Claude Fusion Drive runtime evidence to Braintrust.

Reads the plugin state under ``~/.claude/claude-fusion-drive`` (or
``CLAUDE_FUSION_DRIVE_HOME``) and produces Braintrust project-log events:

- one event per durable job (fuse / approval_gate), scored on the engine's
  gate receipt (``gate.gate.passed``), with the recorded top-level verdict
  preserved in metadata so historical auto-FAIL records stay visible;
- one event per provider call from every engine run ledger (seat, model,
  tokens, cost, latency);
- one event per workflow lifecycle gate record (stage verdict as a score).

By default the events are written to a local JSONL file. With ``--upload``
they are posted to the Braintrust REST API (get-or-create project, then
``POST /v1/project_logs/{project_id}/insert``); this requires the
``BRAINTRUST_API_KEY`` environment variable. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_URL_DEFAULT = "https://api.braintrust.dev/v1"
UPLOAD_BATCH_SIZE = 100
TEXT_SNIPPET_CHARS = 2000


def state_root() -> Path:
    configured = os.environ.get("CLAUDE_FUSION_DRIVE_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".claude" / "claude-fusion-drive"


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def unix_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def snippet(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:TEXT_SNIPPET_CHARS]


def inner_gate(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    gate = result.get("gate")
    if not isinstance(gate, dict):
        return {}
    nested = gate.get("gate")
    return nested if isinstance(nested, dict) else gate


def job_events(root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for job_dir in sorted((root / "jobs").glob("job-*")):
        try:
            job = read_json(job_dir / "job.json")
            request = read_json(job_dir / "request.json")
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        result: dict[str, Any] = {}
        try:
            loaded = read_json(job_dir / "result.json")
            if isinstance(loaded, dict):
                result = loaded.get("result", loaded) if isinstance(loaded.get("result"), dict) else loaded
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        arguments = request.get("arguments") if isinstance(request.get("arguments"), dict) else {}
        gate = inner_gate(result)
        scores: dict[str, float] = {}
        if "passed" in gate:
            scores["gate_pass"] = 1.0 if gate.get("passed") else 0.0
            required = gate.get("required_passes")
            pass_count = gate.get("pass_count")
            if isinstance(required, int) and required > 0 and isinstance(pass_count, int):
                scores["reviewer_pass_rate"] = max(0.0, min(1.0, pass_count / required))
        metrics: dict[str, float] = {}
        start = unix_timestamp(job.get("started_at") or job.get("created_at"))
        end = unix_timestamp(job.get("finished_at") or job.get("updated_at"))
        if start is not None:
            metrics["start"] = start
        if end is not None:
            metrics["end"] = end
        ledger = load_ledger(root / "engine" / "runs" / str(job.get("job_id", "")))
        if ledger:
            for source_key, metric_key in (
                ("input_tokens", "prompt_tokens"),
                ("output_tokens", "completion_tokens"),
                ("total_tokens", "tokens"),
                ("known_cost_usd", "cost"),
            ):
                value = ledger.get(source_key)
                if isinstance(value, (int, float)):
                    metrics[metric_key] = float(value)
        events.append(
            {
                "id": str(job.get("job_id", job_dir.name)),
                "input": {
                    "operation": job.get("operation"),
                    "stage": arguments.get("stage"),
                    "task": snippet(arguments.get("task")),
                },
                "output": {
                    "recorded_verdict": result.get("verdict"),
                    "engine_gate_passed": gate.get("passed"),
                    "synthesis": snippet(result.get("synthesis")),
                },
                "scores": scores or None,
                "metadata": {
                    "kind": "job",
                    "operation": job.get("operation"),
                    "profile": job.get("profile"),
                    "engine": result.get("engine"),
                    "status": job.get("status"),
                    "error": job.get("error"),
                    "workflow_id": arguments.get("workflow_id"),
                    "run_id": job.get("run_id"),
                    "plugin_version": job.get("plugin_version"),
                    "deterministic_blockers": gate.get("deterministic_blockers"),
                },
                "metrics": metrics or None,
                "tags": ["fusion-drive", str(job.get("operation", "unknown"))],
            }
        )
    return events


def load_ledger(run_dir: Path) -> dict[str, Any]:
    try:
        ledger = read_json(run_dir / "ledger.json")
    except (FileNotFoundError, json.JSONDecodeError, NotADirectoryError):
        return {}
    return ledger if isinstance(ledger, dict) else {}


def seat_call_events(root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    runs_dir = root / "engine" / "runs"
    if not runs_dir.is_dir():
        return events
    for run_dir in sorted(runs_dir.iterdir()):
        ledger = load_ledger(run_dir)
        entries = ledger.get("entries")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
            metrics = {}
            for source_key, metric_key in (
                ("input_tokens", "prompt_tokens"),
                ("output_tokens", "completion_tokens"),
                ("cost_usd", "cost"),
            ):
                value = usage.get(source_key)
                if isinstance(value, (int, float)):
                    metrics[metric_key] = float(value)
            latency = entry.get("latency_seconds")
            if isinstance(latency, (int, float)):
                metrics["latency_seconds"] = float(latency)
            events.append(
                {
                    "id": str(entry.get("entry_id", f"{run_dir.name}-{len(events)}")),
                    "input": {"stage": entry.get("stage"), "seat": entry.get("seat")},
                    "output": {"raw_status": entry.get("raw_status")},
                    "metadata": {
                        "kind": "seat_call",
                        "run_id": run_dir.name,
                        "provider": entry.get("provider"),
                        "requested_model": entry.get("requested_model"),
                        "actual_model": entry.get("actual_model"),
                        "request_id": entry.get("request_id"),
                        "unknown_cost": usage.get("cost_usd") is None,
                    },
                    "metrics": metrics or None,
                    "tags": ["fusion-drive", "seat-call"],
                }
            )
    return events


def workflow_gate_events(root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    workflows_dir = root / "workflows"
    if not workflows_dir.is_dir():
        return events
    for lifecycle_path in sorted(workflows_dir.glob("*/host-lifecycle.json")):
        try:
            lifecycle = read_json(lifecycle_path)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        workflow_id = str(lifecycle.get("workflow_id", lifecycle_path.parent.name))
        gates = lifecycle.get("gates") if isinstance(lifecycle.get("gates"), dict) else {}
        for stage, record in gates.items():
            if not isinstance(record, dict):
                continue
            verdict = str(record.get("verdict", ""))
            metrics = {}
            recorded = unix_timestamp(record.get("recorded_at"))
            if recorded is not None:
                metrics["start"] = recorded
                metrics["end"] = recorded
            events.append(
                {
                    "id": f"{workflow_id}-gate-{stage}",
                    "input": {"workflow_id": workflow_id, "stage": stage},
                    "output": {"verdict": verdict},
                    "scores": {"gate_pass": 1.0 if verdict == "PASS" else 0.0},
                    "metadata": {
                        "kind": "workflow_gate",
                        "workflow_id": workflow_id,
                        "state": lifecycle.get("state"),
                        "profile": lifecycle.get("profile_name"),
                        "engine": lifecycle.get("engine_name"),
                        "reviewer_models": record.get("reviewer_models"),
                        "artifact_sha256": record.get("artifact_sha256"),
                    },
                    "metrics": metrics or None,
                    "tags": ["fusion-drive", "workflow-gate"],
                }
            )
    return events


def clean_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if value is not None}


def api_request(url: str, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def upload(events: list[dict[str, Any]], *, project_name: str, api_url: str) -> None:
    api_key = os.environ.get("BRAINTRUST_API_KEY")
    if not api_key:
        raise SystemExit(
            "BRAINTRUST_API_KEY is not set; set it in the environment to upload "
            "(events were not sent)."
        )
    project = api_request(f"{api_url}/project", {"name": project_name}, api_key)
    project_id = project.get("id")
    if not project_id:
        raise SystemExit(f"Project create/get returned no id: {project}")
    inserted = 0
    for offset in range(0, len(events), UPLOAD_BATCH_SIZE):
        batch = events[offset : offset + UPLOAD_BATCH_SIZE]
        response = api_request(
            f"{api_url}/project_logs/{project_id}/insert",
            {"events": batch},
            api_key,
        )
        inserted += len(response.get("row_ids", batch))
    print(f"Uploaded {inserted} events to Braintrust project '{project_name}' ({project_id}).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None, help="JSONL output path (default: <state>/braintrust-export/export-<utc>.jsonl)")
    parser.add_argument("--upload", action="store_true", help="POST events to the Braintrust API (requires BRAINTRUST_API_KEY)")
    parser.add_argument("--project", default="claude-fusion-drive", help="Braintrust project name for --upload")
    parser.add_argument("--api-url", default=API_URL_DEFAULT, help="Braintrust API base URL")
    args = parser.parse_args()

    root = state_root()
    if not root.is_dir():
        raise SystemExit(f"State directory not found: {root}")

    events = [
        clean_event(event)
        for event in (*job_events(root), *seat_call_events(root), *workflow_gate_events(root))
    ]
    kinds: dict[str, int] = {}
    for event in events:
        kind = str(event.get("metadata", {}).get("kind", "unknown"))
        kinds[kind] = kinds.get(kind, 0) + 1
    print(f"Collected {len(events)} events from {root}: {kinds}")

    out_path = args.out
    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = root / "braintrust-export" / f"export-{stamp}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    print(f"Wrote {out_path}")

    if args.upload:
        try:
            upload(events, project_name=args.project, api_url=args.api_url)
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:500]
            raise SystemExit(f"Braintrust API error {error.code}: {body}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
