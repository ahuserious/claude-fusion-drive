"""Bridge schema-v2 Fusion Drive profiles into the proven fusion runtime."""

from __future__ import annotations

import copy
import os
from typing import Any, Mapping, Optional

from relentless_inception.config import load_config as load_legacy_config
from relentless_inception.orchestrator import FusionOrchestrator
from relentless_inception.providers import ProviderRegistry

from .batching import execute_microbatch
from .config import load_config, runtime_dir, validate_config
from .errors import CapabilityError, ConfigurationError, ExternalActionRequired
from .lifecycle import initialize_lifecycle, record_gate
from .oauth import SubscriptionCliAdapter
from .report import workflow_report
from .util import canonical_hash, json_copy, text_hash


class HybridProviderRegistry(ProviderRegistry):
    """Delegate HTTP seats to the inherited registry and OAuth seats to CLIs."""

    def __init__(self, legacy_config: Mapping[str, Any], drive_config: Mapping[str, Any]):
        super().__init__(legacy_config)
        self.drive_config = dict(drive_config)
        self.oauth_adapter = SubscriptionCliAdapter(self.drive_config)

    def complete(
        self,
        seat_name: str,
        *,
        system: str,
        prompt: str,
        response_schema: Optional[Mapping[str, Any]] = None,
        schema_name: str = "structured_response",
        before_attempt: Any = None,
        on_semantic_failure_response: Any = None,
    ) -> Any:
        drive_seat = self.drive_config.get("seats", {}).get(seat_name, {})
        provider_name = drive_seat.get("provider")
        transport = self.drive_config.get("providers", {}).get(provider_name, {}).get("transport")
        if transport in {"claude_cli_oauth", "grok_cli_oauth"}:
            return self.oauth_adapter.complete(
                seat_name,
                system=system,
                prompt=prompt,
                response_schema=response_schema,
                schema_name=schema_name,
                before_attempt=before_attempt,
                on_semantic_failure_response=on_semantic_failure_response,
            )
        return super().complete(
            seat_name,
            system=system,
            prompt=prompt,
            response_schema=response_schema,
            schema_name=schema_name,
            before_attempt=before_attempt,
            on_semantic_failure_response=on_semantic_failure_response,
        )


def _legacy_provider(
    legacy: Mapping[str, Any],
    drive_provider: Mapping[str, Any],
) -> dict[str, Any]:
    transport = drive_provider["transport"]
    template_name = {
        "xai_responses": "xai_direct",
        "openrouter_chat": "openrouter",
        "openrouter_fusion": "openrouter_native_fusion",
        "openai_responses": "openai_direct",
        "anthropic_messages": "anthropic_direct",
    }.get(transport)
    if template_name:
        provider = copy.deepcopy(legacy["providers"][template_name])
    else:
        provider = {
            "enabled": True,
            "type": transport,
            "base_url": "cli://local",
            "api_key_env": drive_provider.get("auth", {}).get("api_key_env", "UNUSED_API_KEY"),
            "connect_timeout_seconds": 30,
            "request_timeout_seconds": drive_provider.get("request_timeout_seconds", 1800),
            "max_retries": 0,
            "max_concurrency": 1,
            "retry_statuses": [],
            "capabilities": {
                "tools": False,
                "structured_outputs": True,
                "reasoning": True,
                "streaming": False,
            },
        }
    provider["enabled"] = bool(drive_provider.get("enabled"))
    provider["max_concurrency"] = int(drive_provider.get("max_concurrency", 1))
    if "request_timeout_seconds" in drive_provider:
        provider["request_timeout_seconds"] = drive_provider["request_timeout_seconds"]
    if "max_retries" in drive_provider:
        provider["max_retries"] = drive_provider["max_retries"]
    api_key_env = drive_provider.get("auth", {}).get("api_key_env")
    if api_key_env:
        provider["api_key_env"] = api_key_env
    return provider


def _legacy_seat(
    legacy: Mapping[str, Any],
    seat: Mapping[str, Any],
) -> dict[str, Any]:
    role = str(seat["role"])
    panel_template = (
        "grok45_researcher"
        if seat.get("provider") == "xai_api"
        else "openrouter_sol_pro_panel"
    )
    template_name = {
        "panel": panel_template,
        "judge": "grok45_judge",
        "fuser": "grok45_synthesizer",
        "verifier": "grok45_verifier",
    }[role]
    translated = copy.deepcopy(legacy["seats"][template_name])
    translated.update(
        {
            "enabled": bool(seat.get("enabled", True)),
            "provider": seat["provider"],
            "model": seat["model"],
            "role": "synthesizer" if role == "fuser" else role,
            "persona": seat["persona"],
            "reasoning_effort": seat["effective_reasoning"],
            "reasoning_max_tokens": seat.get("reasoning_max_tokens"),
            "max_output_tokens": seat["max_output_tokens"],
            "timeout_seconds": seat["timeout_seconds"],
            "tool_policy": seat.get("tool_policy", "none"),
            "server_tools": [],
            "first_tool_required": False,
            "structured_output": seat["structured_output"],
            "allow_model_fallbacks": False,
            "fallback_models": [],
            "fallback_seats": [],
        }
    )
    if "openrouter_fusion" in seat:
        translated["fusion"] = copy.deepcopy(seat["openrouter_fusion"])
    else:
        translated.pop("fusion", None)
    return translated


def translate_config(
    drive_config: Mapping[str, Any],
    *,
    profile_name: str | None = None,
) -> tuple[dict[str, Any], str]:
    errors = validate_config(drive_config)
    if errors:
        raise ConfigurationError("Cannot translate invalid Fusion Drive configuration:\n- " + "\n- ".join(errors))
    profile_name = profile_name or str(drive_config["active_profile"])
    drive_profile = drive_config.get("profiles", {}).get(profile_name)
    if not isinstance(drive_profile, Mapping):
        raise ConfigurationError(f"Unknown Fusion Drive profile: {profile_name}")
    engine_name = str(drive_profile["engine"])
    engine = drive_config["engines"][engine_name]
    gate_set = drive_config["gate_sets"][drive_profile["gate_set"]]

    legacy = load_legacy_config(include_user=False, validate=False)
    legacy["providers"] = {
        name: _legacy_provider(legacy, provider)
        for name, provider in drive_config["providers"].items()
        if provider["transport"] != "claude_host"
    }
    if engine_name == "openrouter_fusion":
        legacy["providers"]["openrouter_fusion_api"]["enabled"] = True
    legacy["seats"] = {
        name: _legacy_seat(load_legacy_config(include_user=False, validate=False), seat)
        for name, seat in drive_config["seats"].items()
        if drive_config["providers"][seat["provider"]]["transport"] != "claude_host"
    }

    base_profile = copy.deepcopy(load_legacy_config(include_user=False, validate=False)["profiles"]["maximum_intelligence"])
    fallback_engine = drive_config["engines"]["in_harness"] if engine_name == "openrouter_fusion" else engine
    panel = list(fallback_engine.get("panel", []))
    base_profile["fusion"].update(
        {
            "engine": "client_orchestrated",
            "panel": panel,
            "optional_panel": list(fallback_engine.get("optional_panel", [])),
            "judge": fallback_engine.get("judge", "gpt56sol-judge"),
            "synthesizer": fallback_engine.get("fuser", "gpt56sol-fuser"),
            "native_fusion_seat": engine.get("seat", "openrouter-fusion-seat"),
            "min_live_seats": int(engine.get("min_live_seats", max(1, len(panel)))),
            "max_panel_seats": max(1, len(panel) + len(fallback_engine.get("optional_panel", []))),
            "max_concurrency": int(fallback_engine.get("max_concurrency", 1)),
            "independent_first_pass": bool(fallback_engine.get("independent_first_pass", True)),
            "anonymize_model_identity": bool(fallback_engine.get("anonymize_model_identity", True)),
            "prohibit_majority_vote": bool(fallback_engine.get("prohibit_majority_vote", True)),
            "preserve_minority_findings": bool(fallback_engine.get("preserve_minority_findings", True)),
        }
    )
    base_profile["fusion"]["native_openrouter_fusion"] = {
        "enabled": engine_name == "openrouter_fusion",
        "fallback_to_client_orchestrated": engine.get("fallback_engine") == "in_harness",
    }
    base_profile["gates"].update(
        {
            "enabled": bool(gate_set["enabled"]),
            "fail_closed": bool(gate_set["fail_closed"]),
            "reviewers": list(gate_set["reviewers"]),
            "max_concurrency": int(gate_set["max_concurrency"]),
            "required_passes": int(gate_set["required_passes"]),
            "max_revision_cycles": int(gate_set["max_revision_cycles"]),
        }
    )
    original_stages = copy.deepcopy(base_profile["gates"]["stages"])
    translated_stages = {}
    for stage_name, stage in gate_set["stages"].items():
        if stage_name == "synthesis":
            continue
        template = original_stages.get(stage_name, original_stages["pre_execution"])
        translated_stages[stage_name] = {
            **template,
            "enabled": True,
            "required_evidence": copy.deepcopy(stage["required_evidence"]),
        }
    base_profile["gates"]["stages"] = translated_stages
    for key, value in drive_profile["budgets"].items():
        if key in base_profile["budgets"]:
            base_profile["budgets"][key] = copy.deepcopy(value)
    base_profile["execution"].update(
        {
            "model": drive_profile["execution"]["model"],
            "reasoning_effort": drive_profile["execution"]["reasoning"],
            "allow_recursive_claude_cli": False,
            "require_fused_plan": True,
            "require_pre_execution_gate": True,
            "require_post_execution_gate": True,
        }
    )
    base_profile["observability"]["enabled"] = True
    base_profile["observability"]["artifact_directory"] = str(runtime_dir() / "engine" / "runs")

    translated_profile_name = "fusion_drive"
    legacy["profiles"] = {translated_profile_name: base_profile}
    legacy["active_profile"] = translated_profile_name
    legacy["native_claude"].update(
        {
            "enabled": True,
            "mode": "host_handoff",
            "executor_model": drive_profile["execution"]["model"],
            "executor_reasoning_effort": drive_profile["execution"]["reasoning"],
            "reviewer_models": ["claude-fable-5"],
            "reviewer_reasoning_effort": "xhigh",
            "require_fusion_before_execution": True,
            "require_gate_after_execution": True,
        }
    )
    return legacy, translated_profile_name


class FusionDriveEngine:
    def __init__(self, config: Mapping[str, Any] | None = None):
        self.config = dict(config or load_config())
        os.environ.setdefault("RELENTLESS_INCEPTION_HOME", str(runtime_dir() / "engine"))

    def _orchestrator(self, profile_name: str | None = None) -> tuple[FusionOrchestrator, str]:
        legacy, translated_profile = translate_config(self.config, profile_name=profile_name)
        registry = HybridProviderRegistry(legacy, self.config)
        return FusionOrchestrator(legacy, registry=registry), translated_profile

    def fuse(
        self,
        task: str,
        *,
        context: str = "",
        mechanical_evidence: str = "",
        profile_name: str | None = None,
        resume_run_id: str | None = None,
    ) -> dict[str, Any]:
        if not task.strip():
            raise ConfigurationError("Fusion task cannot be empty")
        selected_profile = profile_name or str(self.config["active_profile"])
        orchestrator, translated_profile = self._orchestrator(selected_profile)
        result = orchestrator.fuse(
            task,
            context=context,
            mechanical_evidence=mechanical_evidence,
            profile_name=translated_profile,
            run_id=resume_run_id,
        ).to_dict()
        workflow_id = str(result["run_id"])
        gate = result.get("gate", {})
        gate_passed = bool(gate.get("passed") or gate.get("verdict") == "PASS" or gate.get("status") == "passed")
        synthesis_receipt = {
            "stage": "synthesis",
            "verdict": "PASS" if gate_passed else "NEEDS_WORK",
            "artifact_sha256": text_hash(str(result.get("synthesis", ""))),
            "engine_gate": json_copy(gate),
        }
        lifecycle = initialize_lifecycle(
            workflow_id,
            run_id=str(result["run_id"]),
            plan_sha256=text_hash(str(result["synthesis"])),
            config_sha256=canonical_hash(self.config),
            profile_name=selected_profile,
            engine_name=str(self.config["profiles"][selected_profile]["engine"]),
            host_goal_creation_tool=str(
                self.config["lifecycle"]["host_goal_creation_tool"]
            ),
            synthesis_gate_receipt=synthesis_receipt,
        )
        return {
            **result,
            "workflow_id": workflow_id,
            "profile": selected_profile,
            "engine": str(self.config["profiles"][selected_profile]["engine"]),
            "host_lifecycle": lifecycle,
            "workflow_report": workflow_report(self.config, profile_name=selected_profile),
            "next_action": (
                "Run the plan gate, then show the fused plan, Mermaid graph, and complete effective configuration. "
                "Do not execute until the user explicitly confirms the exact plan."
            ),
        }

    def approval_gate(
        self,
        task: str,
        artifact: str,
        *,
        stage: str,
        mechanical_evidence: str = "",
        profile_name: str | None = None,
        workflow_id: str | None = None,
        expected_lifecycle_sha256: str | None = None,
        resume_run_id: str | None = None,
    ) -> dict[str, Any]:
        selected_profile = profile_name or str(self.config["active_profile"])
        orchestrator, translated_profile = self._orchestrator(selected_profile)
        gate = orchestrator.adversarial_gate(
            task,
            artifact,
            mechanical_evidence=mechanical_evidence,
            profile_name=translated_profile,
            run_id=resume_run_id,
        )
        verdict = str(gate.get("verdict") or ("PASS" if gate.get("passed") else "FAIL")).upper()
        if verdict not in {"PASS", "NEEDS_WORK", "FAIL"}:
            verdict = "FAIL"
        output: dict[str, Any] = {
            "stage": stage,
            "verdict": verdict,
            "gate": gate,
            "artifact_sha256": text_hash(artifact),
            "profile": selected_profile,
            "engine": str(self.config["profiles"][selected_profile]["engine"]),
        }
        if workflow_id:
            if not expected_lifecycle_sha256:
                raise ConfigurationError("expected_lifecycle_sha256 is required when recording a workflow gate")
            gate_set = self.config["gate_sets"][
                self.config["profiles"][selected_profile]["gate_set"]
            ]
            reviewer_models = [
                self.config["seats"][seat_name]["model"] for seat_name in gate_set["reviewers"]
            ]
            output["host_lifecycle"] = record_gate(
                workflow_id,
                stage=stage,
                verdict=verdict,
                artifact_sha256=text_hash(artifact),
                evidence=[mechanical_evidence] if mechanical_evidence else [],
                reviewer_models=reviewer_models,
                expected_lifecycle_sha256=expected_lifecycle_sha256,
            )
        return output

    def batch_fuse(
        self,
        tasks: list[Mapping[str, Any]],
        *,
        profile_name: str | None = None,
        confirmed_external_costs: bool,
        max_concurrency: int | None = None,
    ) -> dict[str, Any]:
        if not confirmed_external_costs:
            raise ExternalActionRequired("Batch fusion can incur multiple provider charges and requires confirmation")
        selected_profile = profile_name or str(self.config["active_profile"])
        engine_name = self.config["profiles"][selected_profile]["engine"]
        configured = int(self.config["engines"][engine_name].get("max_concurrency", 1))
        concurrency = min(max_concurrency or configured, configured)

        def worker(item: Mapping[str, Any]) -> dict[str, Any]:
            return self.fuse(
                str(item["task"]),
                context=str(item.get("context", "")),
                mechanical_evidence=str(item.get("mechanical_evidence", "")),
                profile_name=selected_profile,
            )

        results = execute_microbatch(tasks, worker, max_concurrency=concurrency)
        return {
            "profile": selected_profile,
            "engine": engine_name,
            "batch_mode": "bounded_microbatch",
            "max_concurrency": concurrency,
            "results": results,
            "cost_statement": "Concurrency is not represented as a provider discount; each fusion run retains its own ledger.",
        }
