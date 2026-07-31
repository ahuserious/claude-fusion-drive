"""Safe Claude Code and Grok CLI OAuth adapters.

The adapters intentionally delegate token ownership to each CLI/keychain. API
environment variables are removed from child processes so an API key cannot
silently override the requested subscription OAuth path.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from relentless_inception.types import ModelResponse, Usage

from .config import load_config, runtime_dir
from .errors import CapabilityError
from .reasoning import normalize_reasoning
from .util import atomic_write_text, canonical_json, exclusive_lock, text_hash


EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
TOKEN_PATTERN = re.compile(r"\b(?:sk|xai|oauth|bearer)[-_A-Za-z0-9.]{12,}\b", re.IGNORECASE)
ENVELOPE_FIELDS = {
    "content",
    "error",
    "is_error",
    "message",
    "response",
    "result",
    "structured_output",
    "subtype",
}
OAUTH_API_KEY_ENVIRONMENTS = ("ANTHROPIC_API_KEY", "XAI_API_KEY")


def _safe_error(value: str, limit: int = 500) -> str:
    value = EMAIL_PATTERN.sub("<redacted-email>", value)
    value = TOKEN_PATTERN.sub("<redacted-token>", value)
    return value.strip()[:limit]


def oauth_instructions(provider_name: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    config = dict(config or load_config())
    provider = config.get("providers", {}).get(provider_name)
    if not isinstance(provider, Mapping):
        raise CapabilityError(f"Unknown provider: {provider_name}")
    transport = provider.get("transport")
    api_env = provider.get("auth", {}).get("api_key_env")
    unset_flags = " ".join(
        f"-u {environment_name}"
        for environment_name in OAUTH_API_KEY_ENVIRONMENTS
    )
    if transport == "claude_cli_oauth":
        command = f"env {unset_flags} claude"
        login = "Run /login in the interactive Claude Code session and choose the subscription account."
    elif transport == "grok_cli_oauth":
        command = f"env {unset_flags} grok"
        login = "Run /login in the interactive Grok session if the CLI reports that OAuth is not active."
    else:
        raise CapabilityError(f"Provider {provider_name} is not a CLI OAuth provider")
    return {
        "provider": provider_name,
        "command": command,
        "interactive_step": login,
        "identity_hint_policy": "The plugin does not store an email address, X handle, token, cookie, or keychain path.",
        "api_override_removed": api_env,
        "api_overrides_removed": list(OAUTH_API_KEY_ENVIRONMENTS),
        "verification": "Use oauth_status with online=true after completing the interactive login.",
    }


def oauth_status(
    provider_name: str,
    *,
    online: bool = False,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    config = dict(config or load_config())
    provider = config.get("providers", {}).get(provider_name)
    if not isinstance(provider, Mapping):
        raise CapabilityError(f"Unknown provider: {provider_name}")
    transport = provider.get("transport")
    command = str(provider.get("command", ""))
    binary = shutil.which(command)
    result: dict[str, Any] = {
        "provider": provider_name,
        "transport": transport,
        "binary_path": binary,
        "online_checked": online,
        "authenticated": None,
        "identity_disclosed": False,
        "token_accessed": False,
        "billing": provider.get("billing"),
    }
    if not binary or not online:
        return result
    env = os.environ.copy()
    for environment_name in OAUTH_API_KEY_ENVIRONMENTS:
        env.pop(environment_name, None)
    if transport == "claude_cli_oauth":
        args = [binary, "auth", "status", "--json"]
    elif transport == "grok_cli_oauth":
        args = [binary, "models"]
    else:
        raise CapabilityError(f"Provider {provider_name} is not a CLI OAuth provider")
    try:
        completed = subprocess.run(
            args,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["error"] = _safe_error(str(exc))
        return result
    result["authenticated"] = completed.returncode == 0
    result["exit_code"] = completed.returncode
    if completed.returncode:
        result["error"] = _safe_error(completed.stderr or completed.stdout)
    return result


class _CliOutputFailure(CapabilityError):
    def __init__(self, diagnostics: Mapping[str, Any]):
        self.diagnostics = dict(diagnostics)
        super().__init__(f"CLI output rejected: {canonical_json(self.diagnostics)}")


def _output_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, bytes):
        return "bytes"
    return "unknown"


def _diagnostics(
    raw_output: str,
    *,
    value: Any,
    category: str,
    exit_status: int | str,
) -> dict[str, Any]:
    return {
        "category": category,
        "type": _output_type(value),
        "length": len(raw_output),
        "sha256": text_hash(raw_output),
        "exit_status": exit_status,
    }


def _decode_json_output(raw_output: str) -> tuple[Any, bool]:
    if not raw_output.strip():
        raise _CliOutputFailure(
            _diagnostics(
                raw_output,
                value=raw_output,
                category="empty_output",
                exit_status=0,
            )
        )
    try:
        return json.loads(raw_output), False
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        values: list[Any] = []
        cursor = 0
        while cursor < len(raw_output):
            while cursor < len(raw_output) and raw_output[cursor].isspace():
                cursor += 1
            if cursor >= len(raw_output):
                break
            try:
                value, cursor = decoder.raw_decode(raw_output, cursor)
            except json.JSONDecodeError as exc:
                raise _CliOutputFailure(
                    _diagnostics(
                        raw_output,
                        value=raw_output,
                        category="malformed_json",
                        exit_status=0,
                    )
                ) from exc
            values.append(value)
        if len(values) < 2:
            raise _CliOutputFailure(
                _diagnostics(
                    raw_output,
                    value=raw_output,
                    category="malformed_json",
                    exit_status=0,
                )
            )
        return values, True


def _is_result_envelope(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("type") in {"result", "error"}:
        return True
    return bool(ENVELOPE_FIELDS.intersection(value))


def _envelope_metadata(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, list) and value and isinstance(value[-1], Mapping):
        return value[-1]
    return {}


def _canonical_model_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    return canonical_json(value)


def _extract_text(
    payload: Any,
    *,
    raw_output: str,
    response_schema: Mapping[str, Any] | None,
    is_json_sequence: bool,
) -> tuple[str, Mapping[str, Any]]:
    selected = payload
    if is_json_sequence:
        if not isinstance(payload, list) or not payload or not _is_result_envelope(payload[-1]):
            raise _CliOutputFailure(
                _diagnostics(
                    raw_output,
                    value=payload,
                    category="malformed_sequence",
                    exit_status=0,
                )
            )
        selected = payload[-1]
    elif (
        isinstance(payload, list)
        and payload
        and isinstance(payload[-1], Mapping)
        and payload[-1].get("type") in {"result", "error"}
    ):
        selected = payload[-1]

    if selected is None:
        raise _CliOutputFailure(
            _diagnostics(
                raw_output,
                value=selected,
                category="null_output",
                exit_status=0,
            )
        )

    if not isinstance(selected, Mapping) or not _is_result_envelope(selected):
        text = _canonical_model_text(selected)
        if text is None:
            raise _CliOutputFailure(
                _diagnostics(
                    raw_output,
                    value=selected,
                    category="empty_output",
                    exit_status=0,
                )
            )
        return text, {}

    envelope = selected
    envelope_type = str(envelope.get("type", "")).lower()
    envelope_subtype = str(envelope.get("subtype", "")).lower()
    if (
        envelope.get("is_error") is True
        or envelope_type == "error"
        or "error" in envelope_subtype
        or ("error" in envelope and envelope.get("error") not in (None, False, ""))
    ):
        raise _CliOutputFailure(
            _diagnostics(
                raw_output,
                value=envelope,
                category="error_envelope",
                exit_status=0,
            )
        )

    if response_schema is not None and "structured_output" in envelope:
        structured_text = _canonical_model_text(envelope.get("structured_output"))
        if structured_text is None:
            raise _CliOutputFailure(
                _diagnostics(
                    raw_output,
                    value=envelope.get("structured_output"),
                    category="null_or_empty_structured_output",
                    exit_status=0,
                )
            )
        return structured_text, envelope

    output_field_present = False
    for key in ("result", "response", "text", "content", "message"):
        if key not in envelope:
            continue
        output_field_present = True
        value = envelope.get(key)
        text = _canonical_model_text(value)
        if text is not None:
            return text, envelope

    raise _CliOutputFailure(
        _diagnostics(
            raw_output,
            value=envelope,
            category=(
                "null_or_empty_result"
                if output_field_present
                else "malformed_envelope"
            ),
            exit_status=0,
        )
    )


def _usage(payload: Mapping[str, Any]) -> Usage:
    raw = payload.get("usage", {})
    if not isinstance(raw, Mapping):
        raw = {}

    invalid_usage = False

    def integer(*names: str) -> tuple[int, bool]:
        nonlocal invalid_usage
        for name in names:
            if name not in raw:
                continue
            value = raw.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value, True
            invalid_usage = True
            return 0, False
        return 0, False

    input_tokens, input_complete = integer("input_tokens", "inputTokens")
    output_tokens, output_complete = integer("output_tokens", "outputTokens")
    reasoning_tokens, _ = integer("reasoning_tokens", "reasoningTokens")
    cached_tokens, _ = integer("cached_tokens", "cache_read_input_tokens")
    input_output_usage_complete = input_complete and output_complete
    usage_error = None
    if invalid_usage:
        usage_error = "CLI returned invalid usage metadata"
    elif raw and not input_output_usage_complete:
        usage_error = "CLI returned incomplete usage metadata"

    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cached_tokens=cached_tokens,
        tool_calls=0,
        cost_usd=None,
        unknown_cost_fail_closed=False,
        input_output_usage_complete=input_output_usage_complete,
        raw_usage_invalid=invalid_usage,
        accounting_error=usage_error,
    )


class SubscriptionCliAdapter:
    """Execute one isolated, tool-free CLI completion under a principal lock."""

    def __init__(self, config: Mapping[str, Any] | None = None):
        self.config = dict(config or load_config())

    def complete(
        self,
        seat_name: str,
        *,
        system: str,
        prompt: str,
        response_schema: Mapping[str, Any] | None = None,
        schema_name: str = "structured_response",
        before_attempt: Callable[[], None] | None = None,
        on_semantic_failure_response: Callable[[ModelResponse], None] | None = None,
    ) -> ModelResponse:
        seat = self.config.get("seats", {}).get(seat_name)
        if not isinstance(seat, Mapping):
            raise CapabilityError(f"Unknown OAuth seat: {seat_name}")
        provider_name = str(seat.get("provider"))
        provider = self.config.get("providers", {}).get(provider_name)
        if not isinstance(provider, Mapping):
            raise CapabilityError(f"Seat {seat_name} references unknown provider")
        transport = provider.get("transport")
        if transport not in {"claude_cli_oauth", "grok_cli_oauth"}:
            raise CapabilityError(f"Seat {seat_name} is not a CLI OAuth seat")
        binary = shutil.which(str(provider.get("command", "")))
        if not binary:
            raise CapabilityError(f"CLI binary is unavailable for {provider_name}")

        model = str(seat["model"])
        reasoning = normalize_reasoning(provider, model, str(seat.get("reasoning", "xhigh")))
        timeout = float(seat.get("timeout_seconds", provider.get("request_timeout_seconds", 1800)))
        env = os.environ.copy()
        api_env = provider.get("auth", {}).get("api_key_env")
        for environment_name in OAUTH_API_KEY_ENVIRONMENTS:
            env.pop(environment_name, None)
        combined_prompt = f"{system.strip()}\n\nUSER TASK\n{prompt.strip()}\n"

        jobs_root = runtime_dir() / "oauth-jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()

        def base_route() -> dict[str, Any]:
            return {
                "transport": transport,
                "auth_mode": "cli_oauth_keychain",
                "billing": "subscription",
                "reasoning": reasoning,
                "tools_disabled": True,
                "api_key_override_removed": bool(api_env),
                "api_key_overrides_removed": list(OAUTH_API_KEY_ENVIRONMENTS),
                "schema_name": schema_name,
            }

        def record_semantic_failure(
            diagnostics: Mapping[str, Any],
            *,
            metadata: Mapping[str, Any] | None = None,
        ) -> None:
            if on_semantic_failure_response is None:
                return
            route = base_route()
            route["semantic_failure"] = dict(diagnostics)
            on_semantic_failure_response(
                ModelResponse(
                    text="",
                    provider=provider_name,
                    requested_model=model,
                    actual_model=model,
                    usage=_usage(metadata or {}),
                    latency_seconds=time.monotonic() - started,
                    request_id=None,
                    route=route,
                    raw_status="failed",
                )
            )

        with exclusive_lock(runtime_dir() / "locks" / f"{provider_name}.lock"):
            with tempfile.TemporaryDirectory(prefix=f"{provider_name}-", dir=jobs_root) as temporary:
                temporary_path = Path(temporary)
                os.chmod(temporary_path, 0o700)
                prompt_path = temporary_path / "prompt.txt"
                atomic_write_text(prompt_path, combined_prompt, mode=0o600)
                if transport == "claude_cli_oauth":
                    args = [
                        binary,
                        "--print",
                        "--model",
                        model,
                        "--effort",
                        reasoning["effective"],
                        "--output-format",
                        "json",
                        "--tools",
                        "",
                        "--safe-mode",
                        "--no-session-persistence",
                    ]
                    if response_schema:
                        args.extend(["--json-schema", json.dumps(response_schema, separators=(",", ":"), sort_keys=True)])
                    prompt_input = prompt_path.read_text(encoding="utf-8")
                    subprocess_stdin = None
                else:
                    args = [
                        binary,
                        "--prompt-file",
                        str(prompt_path),
                        "--model",
                        model,
                        "--reasoning-effort",
                        reasoning["effective"],
                        "--output-format",
                        "json",
                        "--tools",
                        "",
                        "--no-subagents",
                        "--disable-web-search",
                        "--no-memory",
                        "--permission-mode",
                        "plan",
                        "--cwd",
                        str(temporary_path),
                    ]
                    if response_schema:
                        args.extend(["--json-schema", json.dumps(response_schema, separators=(",", ":"), sort_keys=True)])
                    prompt_input = None
                    subprocess_stdin = subprocess.DEVNULL
                if before_attempt is not None:
                    before_attempt()
                try:
                    completed = subprocess.run(
                        args,
                        input=prompt_input,
                        stdin=subprocess_stdin,
                        env=env,
                        cwd=temporary_path,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    timeout_output = exc.stdout or exc.stderr or ""
                    if isinstance(timeout_output, bytes):
                        timeout_output = timeout_output.decode("utf-8", errors="replace")
                    diagnostics = _diagnostics(
                        str(timeout_output),
                        value=timeout_output,
                        category="timeout",
                        exit_status="timeout",
                    )
                    record_semantic_failure(diagnostics)
                    raise _CliOutputFailure(diagnostics) from exc
                if completed.returncode:
                    process_output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
                    diagnostics = _diagnostics(
                        process_output,
                        value=process_output,
                        category="nonzero_exit",
                        exit_status=int(completed.returncode),
                    )
                    record_semantic_failure(diagnostics)
                    raise _CliOutputFailure(diagnostics)
                raw_output = completed.stdout or ""
                try:
                    payload, is_json_sequence = _decode_json_output(raw_output)
                    text, metadata = _extract_text(
                        payload,
                        raw_output=raw_output,
                        response_schema=response_schema,
                        is_json_sequence=is_json_sequence,
                    )
                except _CliOutputFailure as exc:
                    metadata = (
                        _envelope_metadata(payload)
                        if "payload" in locals()
                        else {}
                    )
                    record_semantic_failure(exc.diagnostics, metadata=metadata)
                    raise
                actual_model = str(metadata.get("model", model))
                request_id = metadata.get("request_id") or metadata.get("session_id")
                return ModelResponse(
                    text=text,
                    provider=provider_name,
                    requested_model=model,
                    actual_model=actual_model,
                    usage=_usage(metadata),
                    latency_seconds=time.monotonic() - started,
                    request_id=str(request_id) if request_id else None,
                    route=base_route(),
                )
