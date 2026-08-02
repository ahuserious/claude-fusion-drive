#!/usr/bin/env python3
"""Stdio MCP server for Claude Fusion Drive."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from claude_fusion_drive import __version__
from claude_fusion_drive.auto_eval import collect_run_evidence, generate_auto_eval
from claude_fusion_drive.batching import (
    batch_capabilities,
    plan_batch,
    prepare_provider_batch,
    provider_batch_status,
    submit_provider_batch,
)
from claude_fusion_drive.capabilities import advanced_workflow_plan, capability_probe
from claude_fusion_drive.config import (
    approve_config,
    config_get,
    deep_set,
    effective_config_report,
    load_config,
    load_schema,
    propose_config,
    config_history,
    config_rollback_propose,
    runtime_dir,
    validate_config,
)
from claude_fusion_drive.engine import FusionDriveEngine, translate_config
from claude_fusion_drive.errors import ConfigurationError, FusionDriveError
from claude_fusion_drive.human_sim import (
    abort_campaign,
    campaign_plan,
    campaign_report,
    campaign_status,
    create_campaign,
    human_sim_questions,
    pause_campaign,
    record_campaign_goal,
    record_campaign_iteration,
    resume_campaign,
)
from claude_fusion_drive.jobs import (
    job_abort,
    job_result,
    job_status,
    start_approval_gate_job,
    start_fuse_job,
)
from claude_fusion_drive.lifecycle import (
    confirm_plan,
    finish_execution,
    lifecycle_summary,
    load_lifecycle,
    record_claude_goal,
    record_gate,
    start_execution,
)
from claude_fusion_drive.oauth import SubscriptionCliAdapter, oauth_instructions, oauth_status
from claude_fusion_drive.presets import list_presets, resolve_preset
from claude_fusion_drive.report import cost_estimate, gate_set_list, provider_list, workflow_report
from claude_fusion_drive.rescue import create_rescue_packet, record_rescue_attempt, resume_rescue
from claude_fusion_drive.util import json_copy
from relentless_inception.errors import RelentlessInceptionError
from relentless_inception.providers import ProviderRegistry

import legacy_mcp_server as legacy


os.environ.setdefault("RELENTLESS_INCEPTION_HOME", str(runtime_dir() / "engine"))
SERVER_INFO = {"name": "claude-fusion-drive", "version": __version__}


def _tool(
    name: str,
    description: str,
    properties: Mapping[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": dict(properties),
            "required": required or [],
        },
    }


TEXT = {"type": "string"}
BOOL = {"type": "boolean"}
STRING_LIST = {"type": "array", "items": {"type": "string"}}
OBJECT = {"type": "object"}
OBJECT_LIST = {"type": "array", "items": {"type": "object"}}


TOOLS = [
    _tool("config_show", "Return the complete merged schema-v2 configuration, reasoning normalization, and validation state.", {}),
    _tool("config_schema", "Return the documented schema-v2 configuration schema.", {}),
    _tool("config_get", "Read one dotted configuration path.", {"path": TEXT}, ["path"]),
    _tool(
        "config_set",
        "Compatibility command: propose one dotted setting change and return the complete updated report; it does not apply without final approval.",
        {"path": TEXT, "value": {}, "rationale": TEXT},
        ["path", "value"],
    ),
    _tool(
        "config_propose",
        "Validate a merge-style configuration proposal and return its exact hash, diff payload, Mermaid graph, reasoning mappings, and full redacted candidate for final approval.",
        {"changes": OBJECT, "rationale": TEXT},
        ["changes"],
    ),
    _tool(
        "config_approve",
        "Atomically apply the exact persisted proposal hash after explicit final confirmation.",
        {"proposal_hash": TEXT, "confirmed": BOOL},
        ["proposal_hash", "confirmed"],
    ),
    _tool("config_validate", "Validate schema-v2 invariants and cross-references.", {}),
    _tool(
        "doctor",
        "Run profile-aware offline configuration, local integration, binary, host-tool, and batch-capability checks without reading credentials.",
        {"host_mcp_tools": STRING_LIST, "profile": TEXT},
    ),
    _tool(
        "workflow_report",
        "Return the planning Mermaid graph, all gates, presets, effective reasoning flags, and complete redacted settings.",
        {"profile": TEXT},
    ),
    _tool(
        "capability_probe",
        "Probe repo-merge, GitNexus CLI/MCP exposure, provider transports, and batch support without installing tools or reading credentials.",
        {"host_mcp_tools": STRING_LIST, "profile": TEXT},
    ),
    _tool(
        "advanced_workflow_plan",
        "Plan GitNexus context analysis and approval-gated repo-merge work for advanced repository workflows.",
        {"task": TEXT, "repository_count": {"type": "integer", "minimum": 1}, "requires_merge": BOOL, "host_mcp_tools": STRING_LIST},
        ["task"],
    ),
    _tool("preset_list", "List resolved per-subagent fusion presets and immutable hashes.", {}),
    _tool("gate_set_list", "List configured gate sets with reviewers, quorum, reasoning, and stages.", {}),
    _tool("provider_list", "List provider routes with transport, billing, and auth mode; credential values are never read.", {}),
    _tool("cost_estimate", "Bounded per-seat cost estimate for a profile; unknown costs stay explicitly unknown.", {"profile": TEXT, "assumed_input_tokens_per_call": {"type": "integer", "minimum": 1}, "calls_per_seat": {"type": "integer", "minimum": 1}}),
    _tool("config_history", "List persisted configuration proposals, newest first, fully redacted.", {"limit": {"type": "integer", "minimum": 1, "maximum": 500}}),
    _tool("config_rollback_propose", "Propose restoring a previously approved configuration; exact-hash approval still required.", {"proposal_hash": TEXT, "rationale": TEXT}, ["proposal_hash"]),
    _tool("preset_resolve", "Resolve one subagent driver, worker engine, batching, and inherited gate preset.", {"name": TEXT}, ["name"]),
    _tool(
        "fuse",
        "Run the selected planning fusion, persist the handoff/lifecycle, and return the plan plus Mermaid and complete settings. Billable external calls may occur; no execution is performed.",
        {"task": TEXT, "context": TEXT, "mechanical_evidence": TEXT, "profile": TEXT, "resume_run_id": TEXT},
        ["task"],
    ),
    _tool(
        "fuse_start",
        "Start a durable non-blocking fusion job. Reusing the same idempotency key with the same immutable request returns the existing job and never redispatches provider work.",
        {
            "task": TEXT,
            "context": TEXT,
            "mechanical_evidence": TEXT,
            "profile": TEXT,
            "idempotency_key": TEXT,
            "confirmed_external_costs": BOOL,
        },
        ["task", "idempotency_key", "confirmed_external_costs"],
    ),
    _tool(
        "approval_gate",
        "Run Grok 4.5 approval reviewers for a named stage and optionally append a compare-and-swap lifecycle receipt.",
        {
            "task": TEXT,
            "artifact": TEXT,
            "stage": TEXT,
            "mechanical_evidence": TEXT,
            "profile": TEXT,
            "workflow_id": TEXT,
            "expected_lifecycle_sha256": TEXT,
            "resume_run_id": TEXT,
        },
        ["task", "artifact", "stage"],
    ),
    _tool(
        "approval_gate_start",
        "Start a durable non-blocking approval-gate job with exact-request idempotency and optional lifecycle recording.",
        {
            "task": TEXT,
            "artifact": TEXT,
            "stage": TEXT,
            "mechanical_evidence": TEXT,
            "profile": TEXT,
            "workflow_id": TEXT,
            "expected_lifecycle_sha256": TEXT,
            "idempotency_key": TEXT,
            "confirmed_external_costs": BOOL,
        },
        [
            "task",
            "artifact",
            "stage",
            "idempotency_key",
            "confirmed_external_costs",
        ],
    ),
    _tool(
        "job_status",
        "Read a durable asynchronous job receipt and fail closed if its worker exited without a terminal receipt.",
        {"job_id": TEXT},
        ["job_id"],
    ),
    _tool(
        "job_result",
        "Return and hash-verify the completed result of a durable asynchronous job.",
        {"job_id": TEXT},
        ["job_id"],
    ),
    _tool(
        "job_abort",
        "Request recoverable cancellation through the job and inherited run kill switch; active provider calls are never force-killed.",
        {"job_id": TEXT},
        ["job_id"],
    ),
    _tool(
        "adversarial_gate",
        "Compatibility alias for the inherited unrecorded adversarial gate. Prefer approval_gate for staged lifecycle receipts.",
        {"task": TEXT, "artifact": TEXT, "mechanical_evidence": TEXT, "profile": TEXT, "resume_run_id": TEXT},
        ["task", "artifact"],
    ),
    _tool(
        "subagent_fuse",
        "Run a bounded batch of subagent fusion tasks under a resolved preset. The Claude host owns the native driver; external costs require confirmation.",
        {"tasks": OBJECT_LIST, "preset": TEXT, "confirmed_external_costs": BOOL, "max_concurrency": {"type": "integer", "minimum": 1}},
        ["tasks", "preset", "confirmed_external_costs"],
    ),
    _tool("run_status", "Read a persisted inherited-engine run manifest.", {"run_id": TEXT}, ["run_id"]),
    _tool("run_abort", "Create the recoverable per-run kill switch.", {"run_id": TEXT}, ["run_id"]),
    _tool("execution_handoff", "Read and validate a persisted host execution handoff; this never launches recursive Claude.", {"run_id": TEXT}, ["run_id"]),
    _tool("provider_models", "Query a configured HTTP provider model catalog; this is an online non-completion request.", {"provider": TEXT, "limit": {"type": "integer", "minimum": 1, "maximum": 500}}, ["provider"]),
    _tool(
        "provider_test",
        "Send one tiny billable tool-free completion after explicit confirmation. Fusion fan-out seats are refused.",
        {"seat": TEXT, "confirmed": BOOL},
        ["seat", "confirmed"],
    ),
    _tool("oauth_instructions", "Return interactive sign-in instructions without storing identity or tokens.", {"provider": TEXT}, ["provider"]),
    _tool("oauth_status", "Check CLI availability offline or explicitly test OAuth online, with API-key overrides removed.", {"provider": TEXT, "online": BOOL}, ["provider"]),
    _tool(
        "oauth_test",
        "Run one isolated subscription-backed, tool-free completion after explicit confirmation.",
        {"seat": TEXT, "confirmed": BOOL},
        ["seat", "confirmed"],
    ),
    _tool("batch_capabilities", "Return the per-provider truth table for async batches, OAuth, billing, concurrency, and discounts.", {}),
    _tool(
        "batch_plan",
        "Choose provider async batch or bounded microbatch without claiming concurrency itself is a discount.",
        {"tasks": OBJECT_LIST, "provider": TEXT, "model": TEXT, "requested_mode": TEXT},
        ["tasks", "provider", "model"],
    ),
    _tool(
        "batch_prepare",
        "Create an immutable OpenAI or Anthropic provider Batch API request bundle without submitting it.",
        {"tasks": OBJECT_LIST, "provider": TEXT, "model": TEXT},
        ["tasks", "provider", "model"],
    ),
    _tool(
        "batch_submit",
        "Submit a prepared provider batch. This is billable and requires explicit confirmation.",
        {"batch_id": TEXT, "confirmed": BOOL},
        ["batch_id", "confirmed"],
    ),
    _tool("batch_status", "Read a local batch manifest or explicitly poll its provider status.", {"batch_id": TEXT, "online": BOOL}, ["batch_id"]),
    _tool("lifecycle_status", "Read and summarize a workflow lifecycle and its next legal action.", {"workflow_id": TEXT}, ["workflow_id"]),
    _tool(
        "lifecycle_gate_record",
        "Append an independently obtained gate receipt using compare-and-swap.",
        {
            "workflow_id": TEXT,
            "stage": TEXT,
            "verdict": TEXT,
            "artifact_sha256": TEXT,
            "evidence": STRING_LIST,
            "reviewer_models": STRING_LIST,
            "expected_lifecycle_sha256": TEXT,
        },
        ["workflow_id", "stage", "verdict", "artifact_sha256", "expected_lifecycle_sha256"],
    ),
    _tool(
        "plan_confirm",
        "Record explicit confirmation of the exact fused plan hash; this receipt cannot cryptographically prove human identity.",
        {"workflow_id": TEXT, "confirmed": BOOL, "user_message_sha256": TEXT, "expected_plan_sha256": TEXT, "expected_lifecycle_sha256": TEXT},
        ["workflow_id", "confirmed", "user_message_sha256", "expected_plan_sha256", "expected_lifecycle_sha256"],
    ),
    _tool(
        "goal_record",
        "Record the configured Claude host thread-creation receipt after the user asks to execute. MCP itself cannot create a host thread.",
        {"workflow_id": TEXT, "goal_thread_id": TEXT, "objective_sha256": TEXT, "host_tool": TEXT, "expected_lifecycle_sha256": TEXT},
        ["workflow_id", "goal_thread_id", "objective_sha256", "host_tool", "expected_lifecycle_sha256"],
    ),
    _tool(
        "execution_start",
        "Transition a confirmed, goal-backed, pre-gated workflow into execution.",
        {"workflow_id": TEXT, "execution_scope_sha256": TEXT, "expected_lifecycle_sha256": TEXT},
        ["workflow_id", "execution_scope_sha256", "expected_lifecycle_sha256"],
    ),
    _tool(
        "execution_finish",
        "Record the execution result hash and move to post-execution verification.",
        {"workflow_id": TEXT, "result_sha256": TEXT, "expected_lifecycle_sha256": TEXT},
        ["workflow_id", "result_sha256", "expected_lifecycle_sha256"],
    ),
    _tool(
        "rescue_create",
        "Create an immutable rescue problem packet with acceptance criteria and bounded work units.",
        {"problem": TEXT, "acceptance_criteria": STRING_LIST, "work_units": OBJECT_LIST, "constraints": STRING_LIST, "evidence_bar": STRING_LIST},
        ["problem", "acceptance_criteria", "work_units"],
    ),
    _tool(
        "rescue_record",
        "Append a preserved rescue attempt and checkpoint; repeated identical failures trigger human handoff.",
        {
            "packet_id": TEXT,
            "unit_id": TEXT,
            "outcome": TEXT,
            "evidence": STRING_LIST,
            "failure_fingerprint": TEXT,
            "diagnosis": TEXT,
            "checkpoint": OBJECT,
            "expected_manifest_sha256": TEXT,
        },
        ["packet_id", "unit_id", "outcome", "expected_manifest_sha256"],
    ),
    _tool("rescue_resume", "Return pending units and the last proven checkpoints for a rescue packet.", {"packet_id": TEXT}, ["packet_id"]),
    _tool("human_sim_questions", "Prompt for UI/UX, accessibility, logs, performance, security, data, and external-write testing preferences.", {}),
    _tool(
        "human_sim_create",
        "Create a bounded, manifest-driven simulated-user campaign and optional explicitly confirmed extra-goal request.",
        {
            "preferences": OBJECT,
            "acceptance_criteria": STRING_LIST,
            "scenarios": OBJECT_LIST,
            "request_extra_goal": BOOL,
            "confirmed_extra_goal": BOOL,
        },
        ["preferences", "acceptance_criteria", "scenarios"],
    ),
    _tool(
        "human_sim_record",
        "Append one scenario iteration and recompute stop or handoff conditions.",
        {
            "campaign_id": TEXT,
            "scenario_id": TEXT,
            "passed": BOOL,
            "evidence": STRING_LIST,
            "errors": OBJECT_LIST,
            "performance_pass": BOOL,
            "criteria_evidenced": BOOL,
            "stalled_subagents": STRING_LIST,
            "expected_manifest_sha256": TEXT,
        },
        ["campaign_id", "scenario_id", "passed", "evidence", "expected_manifest_sha256"],
    ),
    _tool(
        "human_sim_goal_record",
        "Record the host-created extra Claude goal for an explicitly confirmed campaign.",
        {"campaign_id": TEXT, "goal_thread_id": TEXT, "expected_manifest_sha256": TEXT},
        ["campaign_id", "goal_thread_id", "expected_manifest_sha256"],
    ),
    _tool("human_sim_status", "Read campaign completion, errors, performance, stalls, goal, and next action.", {"campaign_id": TEXT}, ["campaign_id"]),
    _tool("human_sim_plan", "Return the persisted campaign plan and scenario topology without iteration bodies.", {"campaign_id": TEXT}, ["campaign_id"]),
    _tool("human_sim_pause", "Pause an active campaign; recording is blocked until resume.", {"campaign_id": TEXT, "expected_manifest_sha256": TEXT, "reason": TEXT}, ["campaign_id", "expected_manifest_sha256"]),
    _tool("human_sim_resume", "Resume a paused campaign.", {"campaign_id": TEXT, "expected_manifest_sha256": TEXT, "reason": TEXT}, ["campaign_id", "expected_manifest_sha256"]),
    _tool("human_sim_abort", "Terminally abort a campaign with an explicit reason; evidence is preserved.", {"campaign_id": TEXT, "expected_manifest_sha256": TEXT, "reason": TEXT}, ["campaign_id", "expected_manifest_sha256", "reason"]),
    _tool("human_sim_report", "Summarize campaign evidence: per-scenario outcomes, errors, stalls, and lifecycle events.", {"campaign_id": TEXT}, ["campaign_id"]),
    _tool(
        "auto_eval",
        "Evaluate supplied evidence and write a deterministic standalone HTML tearsheet with embedded SVGs and no external assets or QuantStats.",
        {"evidence": OBJECT, "output_path": TEXT},
        ["evidence"],
    ),
    _tool(
        "auto_eval_run",
        "Collect persisted run evidence and write its deterministic standalone HTML/SVG tearsheet.",
        {"run_id": TEXT, "output_path": TEXT},
        ["run_id"],
    ),
]


def _args(arguments: Mapping[str, Any], key: str, default: Any = None) -> Any:
    return arguments[key] if key in arguments else default


def _single_change(path: str, value: Any) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    deep_set(changes, path, value)
    return changes


def call_tool(name: str, arguments: Mapping[str, Any]) -> Any:
    if name == "config_show":
        return effective_config_report()
    if name == "config_schema":
        return load_schema()
    if name == "config_get":
        return {"path": arguments["path"], "value": config_get(str(arguments["path"]))}
    if name in {"config_set", "config_propose"}:
        changes = (
            _single_change(str(arguments["path"]), arguments.get("value"))
            if name == "config_set"
            else arguments["changes"]
        )
        proposal = propose_config(changes, rationale=str(arguments.get("rationale", "")))
        proposal["workflow_report"] = workflow_report(proposal["candidate"])
        return proposal
    if name == "config_approve":
        approved = approve_config(str(arguments["proposal_hash"]), confirmed=bool(arguments["confirmed"]))
        approved["workflow_report"] = workflow_report(approved["config"])
        return approved
    if name == "config_validate":
        errors = validate_config(load_config(validate=False))
        return {"ok": not errors, "errors": errors}
    if name in {"doctor", "capability_probe"}:
        tools = arguments.get("host_mcp_tools", [])
        diagnostic_config = load_config(validate=False)
        capability = capability_probe(
            host_mcp_tools=tools,
            config=diagnostic_config,
            profile_name=arguments.get("profile"),
        )
        if name == "capability_probe":
            return capability
        errors = validate_config(diagnostic_config)
        readiness = capability["readiness"]
        return {
            "ok": not errors and readiness["ok"],
            "version": __version__,
            "config": {"ok": not errors, "errors": errors},
            "capabilities": capability,
            "batching": batch_capabilities(diagnostic_config),
        }
    if name == "workflow_report":
        return workflow_report(profile_name=arguments.get("profile"))
    if name == "advanced_workflow_plan":
        return advanced_workflow_plan(
            str(arguments["task"]),
            repository_count=int(arguments.get("repository_count", 1)),
            requires_merge=bool(arguments.get("requires_merge", False)),
            host_mcp_tools=arguments.get("host_mcp_tools", []),
        )
    if name == "preset_list":
        return list_presets()
    if name == "gate_set_list":
        return gate_set_list()
    if name == "provider_list":
        return provider_list()
    if name == "cost_estimate":
        return cost_estimate(
            profile_name=arguments.get("profile"),
            assumed_input_tokens_per_call=int(arguments.get("assumed_input_tokens_per_call", 20000)),
            calls_per_seat=int(arguments.get("calls_per_seat", 1)),
        )
    if name == "config_history":
        return config_history(limit=int(arguments.get("limit", 50)))
    if name == "config_rollback_propose":
        rollback = config_rollback_propose(
            str(arguments["proposal_hash"]),
            rationale=str(arguments.get("rationale", "")),
        )
        rollback["workflow_report"] = workflow_report(rollback["candidate"])
        return rollback
    if name == "preset_resolve":
        return resolve_preset(str(arguments["name"]))
    if name == "fuse":
        return FusionDriveEngine().fuse(
            str(arguments["task"]),
            context=str(arguments.get("context", "")),
            mechanical_evidence=str(arguments.get("mechanical_evidence", "")),
            profile_name=arguments.get("profile"),
            resume_run_id=arguments.get("resume_run_id"),
        )
    if name == "fuse_start":
        return start_fuse_job(
            task=str(arguments["task"]),
            context=str(arguments.get("context", "")),
            mechanical_evidence=str(
                arguments.get("mechanical_evidence", "")
            ),
            profile_name=arguments.get("profile"),
            idempotency_key=str(arguments["idempotency_key"]),
            confirmed_external_costs=bool(
                arguments["confirmed_external_costs"]
            ),
        )
    if name == "approval_gate":
        return FusionDriveEngine().approval_gate(
            str(arguments["task"]),
            str(arguments["artifact"]),
            stage=str(arguments["stage"]),
            mechanical_evidence=str(arguments.get("mechanical_evidence", "")),
            profile_name=arguments.get("profile"),
            workflow_id=arguments.get("workflow_id"),
            expected_lifecycle_sha256=arguments.get("expected_lifecycle_sha256"),
            resume_run_id=arguments.get("resume_run_id"),
        )
    if name == "approval_gate_start":
        return start_approval_gate_job(
            task=str(arguments["task"]),
            artifact=str(arguments["artifact"]),
            stage=str(arguments["stage"]),
            mechanical_evidence=str(
                arguments.get("mechanical_evidence", "")
            ),
            profile_name=arguments.get("profile"),
            workflow_id=arguments.get("workflow_id"),
            expected_lifecycle_sha256=arguments.get(
                "expected_lifecycle_sha256"
            ),
            idempotency_key=str(arguments["idempotency_key"]),
            confirmed_external_costs=bool(
                arguments["confirmed_external_costs"]
            ),
        )
    if name == "job_status":
        return job_status(str(arguments["job_id"]))
    if name == "job_result":
        return job_result(str(arguments["job_id"]))
    if name == "job_abort":
        return job_abort(str(arguments["job_id"]))
    if name == "adversarial_gate":
        return legacy.call_tool(name, arguments)
    if name == "subagent_fuse":
        preset = resolve_preset(str(arguments["preset"]))
        drive = load_config()
        worker_engine_name = str(preset["worker_engine_name"])
        matching_profiles = sorted(
            profile_name
            for profile_name, profile in drive["profiles"].items()
            if profile.get("engine") == worker_engine_name
        )
        if not matching_profiles:
            raise ConfigurationError(
                f"Preset '{preset['name']}' uses worker engine '{worker_engine_name}' "
                "but no configured profile runs that engine"
            )
        active_profile = str(drive.get("active_profile", ""))
        selected_profile = (
            active_profile if active_profile in matching_profiles else matching_profiles[0]
        )
        return {
            "preset": preset,
            "profile": selected_profile,
            "batch": FusionDriveEngine(drive).batch_fuse(
                list(arguments["tasks"]),
                profile_name=selected_profile,
                confirmed_external_costs=bool(arguments["confirmed_external_costs"]),
                max_concurrency=arguments.get("max_concurrency"),
            ),
        }
    if name in {"run_status", "run_abort", "execution_handoff"}:
        return legacy.call_tool(name, arguments)
    if name == "provider_models":
        drive = load_config()
        legacy_config, _ = translate_config(drive)
        provider = str(arguments["provider"])
        return {
            "provider": provider,
            "models": ProviderRegistry(legacy_config).list_models(provider, limit=int(arguments.get("limit", 100))),
        }
    if name == "provider_test":
        if not arguments.get("confirmed"):
            raise FusionDriveError("provider_test is billable and requires confirmed=true")
        drive = load_config()
        seat = str(arguments["seat"])
        transport = drive["providers"][drive["seats"][seat]["provider"]]["transport"]
        if transport == "openrouter_fusion":
            raise FusionDriveError("OpenRouter Fusion test is refused because one request may fan out to multiple models")
        if transport in {"grok_cli_oauth", "claude_cli_oauth"}:
            raise FusionDriveError("Use oauth_test for CLI OAuth seats")
        legacy_config, _ = translate_config(drive)
        return ProviderRegistry(legacy_config).test_seat(seat)
    if name == "oauth_instructions":
        return oauth_instructions(str(arguments["provider"]))
    if name == "oauth_status":
        return oauth_status(str(arguments["provider"]), online=bool(arguments.get("online", False)))
    if name == "oauth_test":
        if not arguments.get("confirmed"):
            raise FusionDriveError("oauth_test consumes subscription usage and requires confirmed=true")
        response = SubscriptionCliAdapter().complete(
            str(arguments["seat"]),
            system="Return exactly PONG. Do not use tools.",
            prompt="PONG",
        )
        return response.to_dict()
    if name == "batch_capabilities":
        return batch_capabilities()
    if name == "batch_plan":
        return plan_batch(
            arguments["tasks"],
            provider_name=str(arguments["provider"]),
            model=str(arguments["model"]),
            requested_mode=str(arguments.get("requested_mode", "bounded_microbatch")),
        )
    if name == "batch_prepare":
        return prepare_provider_batch(
            arguments["tasks"],
            provider_name=str(arguments["provider"]),
            model=str(arguments["model"]),
        )
    if name == "batch_submit":
        return submit_provider_batch(str(arguments["batch_id"]), confirmed=bool(arguments["confirmed"]))
    if name == "batch_status":
        return provider_batch_status(str(arguments["batch_id"]), online=bool(arguments.get("online", False)))
    if name == "lifecycle_status":
        return lifecycle_summary(str(arguments["workflow_id"]))
    if name == "lifecycle_gate_record":
        return record_gate(
            str(arguments["workflow_id"]),
            stage=str(arguments["stage"]),
            verdict=str(arguments["verdict"]),
            artifact_sha256=str(arguments["artifact_sha256"]),
            evidence=list(arguments.get("evidence", [])),
            reviewer_models=list(arguments.get("reviewer_models", [])),
            expected_lifecycle_sha256=str(arguments["expected_lifecycle_sha256"]),
        )
    if name == "plan_confirm":
        return confirm_plan(
            str(arguments["workflow_id"]),
            confirmed=bool(arguments["confirmed"]),
            user_message_sha256=str(arguments["user_message_sha256"]),
            expected_plan_sha256=str(arguments["expected_plan_sha256"]),
            expected_lifecycle_sha256=str(arguments["expected_lifecycle_sha256"]),
        )
    if name == "goal_record":
        return record_claude_goal(
            str(arguments["workflow_id"]),
            goal_thread_id=str(arguments["goal_thread_id"]),
            objective_sha256=str(arguments["objective_sha256"]),
            host_tool=str(arguments["host_tool"]),
            expected_lifecycle_sha256=str(arguments["expected_lifecycle_sha256"]),
        )
    if name == "execution_start":
        return start_execution(
            str(arguments["workflow_id"]),
            execution_scope_sha256=str(arguments["execution_scope_sha256"]),
            expected_lifecycle_sha256=str(arguments["expected_lifecycle_sha256"]),
        )
    if name == "execution_finish":
        return finish_execution(
            str(arguments["workflow_id"]),
            result_sha256=str(arguments["result_sha256"]),
            expected_lifecycle_sha256=str(arguments["expected_lifecycle_sha256"]),
        )
    if name == "rescue_create":
        return create_rescue_packet(
            problem=str(arguments["problem"]),
            acceptance_criteria=arguments["acceptance_criteria"],
            work_units=arguments["work_units"],
            constraints=arguments.get("constraints", []),
            evidence_bar=arguments.get("evidence_bar", []),
        )
    if name == "rescue_record":
        return record_rescue_attempt(
            str(arguments["packet_id"]),
            unit_id=str(arguments["unit_id"]),
            outcome=str(arguments["outcome"]),
            evidence=arguments.get("evidence", []),
            failure_fingerprint=arguments.get("failure_fingerprint"),
            diagnosis=str(arguments.get("diagnosis", "")),
            checkpoint=arguments.get("checkpoint"),
            expected_manifest_sha256=str(arguments["expected_manifest_sha256"]),
        )
    if name == "rescue_resume":
        return resume_rescue(str(arguments["packet_id"]))
    if name == "human_sim_questions":
        return human_sim_questions()
    if name == "human_sim_create":
        return create_campaign(
            preferences=arguments["preferences"],
            acceptance_criteria=arguments["acceptance_criteria"],
            scenarios=arguments["scenarios"],
            request_extra_goal=bool(arguments.get("request_extra_goal", False)),
            confirmed_extra_goal=bool(arguments.get("confirmed_extra_goal", False)),
        )
    if name == "human_sim_record":
        return record_campaign_iteration(
            str(arguments["campaign_id"]),
            scenario_id=str(arguments["scenario_id"]),
            passed=bool(arguments["passed"]),
            evidence=arguments["evidence"],
            errors=arguments.get("errors", []),
            performance_pass=arguments.get("performance_pass"),
            criteria_evidenced=arguments.get("criteria_evidenced"),
            stalled_subagents=arguments.get("stalled_subagents", []),
            expected_manifest_sha256=str(arguments["expected_manifest_sha256"]),
        )
    if name == "human_sim_goal_record":
        return record_campaign_goal(
            str(arguments["campaign_id"]),
            goal_thread_id=str(arguments["goal_thread_id"]),
            expected_manifest_sha256=str(arguments["expected_manifest_sha256"]),
        )
    if name == "human_sim_status":
        return campaign_status(str(arguments["campaign_id"]))
    if name == "human_sim_plan":
        return campaign_plan(str(arguments["campaign_id"]))
    if name == "human_sim_pause":
        return pause_campaign(
            str(arguments["campaign_id"]),
            expected_manifest_sha256=str(arguments["expected_manifest_sha256"]),
            reason=str(arguments.get("reason", "")),
        )
    if name == "human_sim_resume":
        return resume_campaign(
            str(arguments["campaign_id"]),
            expected_manifest_sha256=str(arguments["expected_manifest_sha256"]),
            reason=str(arguments.get("reason", "")),
        )
    if name == "human_sim_abort":
        return abort_campaign(
            str(arguments["campaign_id"]),
            expected_manifest_sha256=str(arguments["expected_manifest_sha256"]),
            reason=str(arguments["reason"]),
        )
    if name == "human_sim_report":
        return campaign_report(str(arguments["campaign_id"]))
    if name == "auto_eval":
        return generate_auto_eval(arguments["evidence"], output_path=arguments.get("output_path"))
    if name == "auto_eval_run":
        evidence = collect_run_evidence(str(arguments["run_id"]))
        return generate_auto_eval(evidence, output_path=arguments.get("output_path"))
    raise FusionDriveError(f"Unknown tool: {name}")


def _arguments(params: Mapping[str, Any]) -> dict[str, Any]:
    value = params.get("arguments", {})
    if not isinstance(value, dict):
        raise FusionDriveError("Tool arguments must be an object")
    return value


def _text_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)}],
        "isError": is_error,
    }


def handle(message: Mapping[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}, "resources": {"subscribe": False, "listChanged": False}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        try:
            result = _text_result(call_tool(str(params.get("name")), _arguments(params)))
        except (
            FusionDriveError,
            RelentlessInceptionError,
            FileNotFoundError,
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            result = _text_result({"ok": False, "error": str(exc)}, is_error=True)
    elif method == "resources/list":
        result = {
            "resources": [
                {"uri": "claude-fusion-drive://config", "name": "Effective configuration", "mimeType": "application/json"},
                {"uri": "claude-fusion-drive://schema", "name": "Configuration schema", "mimeType": "application/schema+json"},
                {"uri": "claude-fusion-drive://workflow", "name": "Workflow report", "mimeType": "application/json"},
                {"uri": "claude-fusion-drive://doctor", "name": "Offline readiness report", "mimeType": "application/json"},
            ]
        }
    elif method == "resources/read":
        uri = str(message.get("params", {}).get("uri"))
        if uri == "claude-fusion-drive://config":
            value = effective_config_report()
        elif uri == "claude-fusion-drive://schema":
            value = load_schema()
        elif uri == "claude-fusion-drive://workflow":
            value = workflow_report()
        elif uri == "claude-fusion-drive://doctor":
            value = call_tool("doctor", {})
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002, "message": f"Unknown resource: {uri}"}}
        result = {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False),
                }
            ]
        }
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            response = handle(message)
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":"), ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
