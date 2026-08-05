from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_fusion_drive.batching import (
    execute_microbatch,
    plan_batch,
    prepare_provider_batch,
    submit_provider_batch,
)
from claude_fusion_drive.config import load_config
from claude_fusion_drive.engine import translate_config
from claude_fusion_drive.errors import CapabilityError, ExternalActionRequired
from claude_fusion_drive.oauth import SubscriptionCliAdapter, oauth_instructions, oauth_status
from relentless_inception.errors import BudgetExceeded
from relentless_inception.state import BudgetTracker


def test_oauth_instructions_never_store_identity() -> None:
    claude = oauth_instructions("claude_oauth", load_config(include_user=False))
    grok = oauth_instructions("grok_oauth", load_config(include_user=False))
    codex = oauth_instructions("codex_oauth", load_config(include_user=False))
    assert (
        "env -u ANTHROPIC_API_KEY -u XAI_API_KEY -u OPENAI_API_KEY claude"
        == claude["command"]
    )
    assert (
        "env -u ANTHROPIC_API_KEY -u XAI_API_KEY -u OPENAI_API_KEY grok"
        == grok["command"]
    )
    assert (
        "env -u ANTHROPIC_API_KEY -u XAI_API_KEY -u OPENAI_API_KEY codex"
        == codex["command"]
    )
    rendered = json.dumps([claude, grok, codex])
    assert "danrepaci" not in rendered.lower()
    assert "gmail.com" not in rendered.lower()
    assert "does not store" in claude["identity_hint_policy"]


def test_offline_oauth_status_does_not_spawn(monkeypatch) -> None:
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/fake")

    def forbidden(*args, **kwargs):
        raise AssertionError("offline status must not run a subprocess")

    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", forbidden)
    result = oauth_status("claude_oauth", online=False, config=load_config(include_user=False))
    assert result["authenticated"] is None
    assert result["token_accessed"] is False


def test_claude_oauth_adapter_isolates_prompt_and_unsets_api_key(
    isolated_runtime, monkeypatch
) -> None:
    captured = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("XAI_API_KEY", "must-not-reach-child")
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        prompt_path = Path(kwargs["cwd"]) / "prompt.txt"
        captured["prompt_mode"] = prompt_path.stat().st_mode & 0o777
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "result": "PONG",
                    "model": "claude-fable-5",
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", fake_run)
    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "fable5-oauth-panel",
        system="Return PONG.",
        prompt="PONG",
    )
    assert response.text == "PONG"
    assert "--safe-mode" in captured["args"]
    assert "--no-session-persistence" in captured["args"]
    assert "--tools" in captured["args"]
    assert "--effort" in captured["args"]
    assert "max" in captured["args"]
    assert "PONG" not in captured["args"]
    assert captured["input"].endswith("PONG\n")
    assert captured["prompt_mode"] == 0o600
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert "XAI_API_KEY" not in captured["env"]
    assert response.usage.cost_usd is None
    assert response.route["billing"] == "subscription"


def _fake_codex_run(captured, *, usage=None, message="PONG", events=None):
    """Mimic `codex exec --json`: JSONL on stdout, final message in a file."""

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        message_path = Path(args[args.index("--output-last-message") + 1])
        message_path.write_text(message, encoding="utf-8")
        if "--output-schema" in args:
            # The seat's temporary directory is removed once complete() returns,
            # so the schema has to be read while the child is still "running".
            schema_path = Path(args[args.index("--output-schema") + 1])
            captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        stream = events if events is not None else [
            {"type": "thread.started", "thread_id": "thread-abc"},
            {"type": "turn.started"},
            {
                "type": "turn.completed",
                "usage": usage
                if usage is not None
                else {
                    "input_tokens": 11,
                    "cached_input_tokens": 4,
                    "output_tokens": 2,
                    "reasoning_output_tokens": 7,
                },
            },
        ]
        return SimpleNamespace(
            returncode=0,
            stdout="\n".join(json.dumps(event) for event in stream),
            stderr="",
        )

    return fake_run


def test_codex_oauth_adapter_isolates_prompt_and_unsets_api_key(
    isolated_runtime, monkeypatch
) -> None:
    captured = {}
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", _fake_codex_run(captured))

    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "sol-codex-panel",
        system="Return PONG.",
        prompt="PONG",
    )

    args = captured["args"]
    assert response.text == "PONG"
    assert args[1] == "exec"
    assert "--ignore-user-config" in args
    assert "--skip-git-repo-check" in args
    assert "--ephemeral" in args
    assert "--json" in args
    assert args[-1] == "-", "the prompt must arrive on stdin, not in argv"
    assert 'model_reasoning_effort="xhigh"' in args
    assert "tools.web_search=false" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    # The prompt itself must never reach the process table.
    assert "PONG" not in args
    assert captured["input"].endswith("PONG\n")
    # A stray metered key would silently bill the API instead of the subscription.
    assert "OPENAI_API_KEY" not in captured["env"]
    assert response.route["billing"] == "subscription"
    assert response.route["tools_disabled"] is False
    assert response.route["sandbox_policy"] == "read-only"
    assert response.usage.cost_usd is None
    assert response.request_id == "thread-abc"


def test_codex_usage_counters_are_renamed_onto_envelope_names(
    isolated_runtime, monkeypatch
) -> None:
    captured = {}
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", _fake_codex_run(captured))

    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "sol-codex-panel", system="s", prompt="p"
    )

    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 2
    assert response.usage.reasoning_tokens == 7
    assert response.usage.cached_tokens == 4
    assert response.usage.input_output_usage_complete is True


def test_codex_turn_failure_is_rejected(isolated_runtime, monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(
        "claude_fusion_drive.oauth.subprocess.run",
        _fake_codex_run(
            captured,
            message="partial text that must not be trusted",
            events=[
                {"type": "thread.started", "thread_id": "thread-abc"},
                {"type": "turn.failed", "error": {"message": "unsupported reasoning effort"}},
            ],
        ),
    )

    with pytest.raises(CapabilityError):
        SubscriptionCliAdapter(load_config(include_user=False)).complete(
            "sol-codex-panel", system="s", prompt="p"
        )


def test_codex_structured_output_writes_a_schema_file(isolated_runtime, monkeypatch) -> None:
    captured = {}
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(
        "claude_fusion_drive.oauth.subprocess.run",
        _fake_codex_run(captured, message='{"verdict":"ok"}'),
    )
    schema = {"type": "object", "properties": {"verdict": {"type": "string"}}}

    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "sol-codex-panel", system="s", prompt="p", response_schema=schema
    )

    # Codex takes a schema file path, unlike the inline --json-schema the other CLIs accept.
    assert "--output-schema" in captured["args"]
    assert captured["schema"] == schema
    assert response.text == '{"verdict":"ok"}'


def test_claude_oauth_structured_output_is_canonical(
    isolated_runtime, monkeypatch
) -> None:
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")
    structured_output = {"z": 2, "a": [{"b": True, "a": 1}]}

    def fake_run(args, **kwargs):
        assert "--json-schema" in args
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "human-readable fallback",
                    "structured_output": structured_output,
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", fake_run)
    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "fable5-oauth-fuser",
        system="Return structured output.",
        prompt="task",
        response_schema={"type": "object"},
    )
    assert response.text == '{"a":[{"a":1,"b":true}],"z":2}'


def test_claude_oauth_accepts_final_result_envelope_in_json_sequence(
    isolated_runtime, monkeypatch
) -> None:
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")
    raw_output = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "PONG",
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "claude_fusion_drive.oauth.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=raw_output,
            stderr="",
        ),
    )
    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "fable5-oauth-panel",
        system="Return PONG.",
        prompt="task",
    )
    assert response.text == "PONG"
    assert response.usage.input_output_usage_complete is True


@pytest.mark.parametrize(
    ("payload", "expected_text"),
    [
        ([{"answer": "yes"}], '[{"answer":"yes"}]'),
        ([{"message": "model data"}], '[{"message":"model data"}]'),
        ({"answer": "yes"}, '{"answer":"yes"}'),
        (42, "42"),
        (True, "true"),
        ("plain JSON string", "plain JSON string"),
    ],
)
def test_claude_oauth_preserves_valid_bare_json_as_model_text(
    isolated_runtime, monkeypatch, payload, expected_text
) -> None:
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        "claude_fusion_drive.oauth.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(payload),
            stderr="",
        ),
    )
    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "fable5-oauth-panel",
        system="Return JSON.",
        prompt="task",
    )
    assert response.text == expected_text


@pytest.mark.parametrize(
    ("raw_output", "category"),
    [
        ("", "empty_output"),
        ("null", "null_output"),
        ('{"type":"result","result":null}', "null_or_empty_result"),
        ('{"type":"result","is_error":true,"result":"TOPSECRET"}', "error_envelope"),
        ('{"type":"result","result":"TOPSECRET"', "malformed_json"),
    ],
)
def test_claude_oauth_rejects_unusable_output_with_sanitized_diagnostics(
    isolated_runtime, monkeypatch, raw_output, category
) -> None:
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        "claude_fusion_drive.oauth.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=raw_output,
            stderr="",
        ),
    )
    with pytest.raises(CapabilityError) as captured:
        SubscriptionCliAdapter(load_config(include_user=False)).complete(
            "fable5-oauth-panel",
            system="system",
            prompt="task",
        )
    error = str(captured.value)
    assert category in error
    assert "TOPSECRET" not in error
    assert '"type":' in error
    assert '"length":' in error
    assert '"sha256":' in error
    assert '"exit_status":0' in error


def test_grok_oauth_adapter_disables_tools_web_memory_and_subagents(
    isolated_runtime, monkeypatch
) -> None:
    captured = {}
    monkeypatch.setenv("XAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-child")
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/grok")

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        prompt_path = Path(args[args.index("--prompt-file") + 1])
        captured["prompt"] = prompt_path.read_text(encoding="utf-8")
        captured["prompt_mode"] = prompt_path.stat().st_mode & 0o777
        return SimpleNamespace(returncode=0, stdout=json.dumps({"response": "PONG"}), stderr="")

    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", fake_run)
    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "grok45-oauth-panel",
        system="Return PONG.",
        prompt="PONG",
    )
    args = captured["args"]
    assert "--prompt-file" in args
    assert "--single" not in args
    assert "--no-subagents" in args
    assert "--disable-web-search" in args
    assert "--no-memory" in args
    assert "--permission-mode" in args
    assert "high" in args
    assert "PONG" not in args
    assert captured["prompt"].endswith("PONG\n")
    assert captured["prompt_mode"] == 0o600
    assert captured["input"] is None
    assert captured["stdin"] == subprocess.DEVNULL
    assert "XAI_API_KEY" not in captured["env"]
    assert "ANTHROPIC_API_KEY" not in captured["env"]
    assert response.route["reasoning"]["requested"] == "xhigh"
    assert response.route["reasoning"]["effective"] == "high"


@pytest.mark.parametrize(
    ("failure_mode", "expected_category", "usage_complete"),
    [
        ("timeout", "timeout", False),
        ("nonzero", "nonzero_exit", False),
        ("unusable", "error_envelope", True),
    ],
)
def test_oauth_failure_reserves_once_and_persists_semantic_receipt(
    isolated_runtime,
    monkeypatch,
    failure_mode,
    expected_category,
    usage_complete,
) -> None:
    dispatches = 0
    reservations = 0
    failed_responses = []
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")

    def reserve() -> None:
        nonlocal reservations
        reservations += 1

    def fail(*args, **kwargs):
        nonlocal dispatches
        dispatches += 1
        if failure_mode == "timeout":
            raise subprocess.TimeoutExpired(cmd="claude", timeout=1)
        if failure_mode == "nonzero":
            return SimpleNamespace(
                returncode=7,
                stdout="",
                stderr="TOPSECRET provider error",
            )
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "is_error": True,
                    "result": "TOPSECRET",
                    "usage": {"input_tokens": 3, "output_tokens": 1},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", fail)
    with pytest.raises(CapabilityError):
        SubscriptionCliAdapter(load_config(include_user=False)).complete(
            "fable5-oauth-panel",
            system="system",
            prompt="task",
            before_attempt=reserve,
            on_semantic_failure_response=failed_responses.append,
        )
    assert dispatches == 1
    assert reservations == 1
    assert len(failed_responses) == 1
    failed_response = failed_responses[0]
    assert failed_response.usage.cost_usd is None
    assert failed_response.usage.input_output_usage_complete is usage_complete
    diagnostics = failed_response.route["semantic_failure"]
    assert diagnostics["category"] == expected_category
    assert set(diagnostics) == {
        "category",
        "type",
        "length",
        "sha256",
        "exit_status",
    }
    assert "TOPSECRET" not in json.dumps(failed_response.to_dict())


def test_failed_oauth_call_is_counted_as_unknown_before_fail_closed(
    isolated_runtime, monkeypatch
) -> None:
    legacy, profile_name = translate_config(
        load_config(include_user=False),
        profile_name="subscription-oauth",
    )
    tracker = BudgetTracker(legacy["profiles"][profile_name]["budgets"])
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(
        "claude_fusion_drive.oauth.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=9,
            stdout="",
            stderr="private provider diagnostic",
        ),
    )

    with pytest.raises(BudgetExceeded):
        SubscriptionCliAdapter(load_config(include_user=False)).complete(
            "fable5-oauth-panel",
            system="system",
            prompt="task",
            before_attempt=lambda: tracker.reserve_attempt(
                "panel",
                "fable5-oauth-panel",
            ),
            on_semantic_failure_response=lambda response: tracker.record(
                "panel",
                "fable5-oauth-panel",
                response,
            ),
        )

    snapshot = tracker.snapshot()
    assert snapshot["attempts"] == 1
    assert snapshot["calls"] == 1
    assert snapshot["unknown_cost_calls"] == 1
    assert snapshot["known_cost_usd"] == 0.0
    assert snapshot["entries"][0]["usage"]["cost_usd"] is None
    assert (
        snapshot["entries"][0]["route"]["semantic_failure"]["category"]
        == "nonzero_exit"
    )
    assert "private provider diagnostic" not in json.dumps(snapshot)


def test_batch_planner_falls_back_truthfully_for_xai_and_oauth() -> None:
    tasks = [{"task": "one"}]
    xai = plan_batch(
        tasks,
        provider_name="xai_api",
        model="grok-4.5",
        requested_mode="provider_async",
        config=load_config(include_user=False),
    )
    oauth = plan_batch(
        tasks,
        provider_name="claude_oauth",
        model="claude-fable-5",
        requested_mode="provider_async",
        config=load_config(include_user=False),
    )
    assert xai["selected_mode"] == "bounded_microbatch"
    assert "rejects grok-4.5" in xai["selection_reason"]
    assert oauth["selected_mode"] == "bounded_microbatch"
    assert oauth["max_concurrency"] == 1
    assert "not the xAI Batch API" not in oauth["selection_reason"]
    assert "not an API batch discount" in oauth["selection_reason"]


@pytest.mark.parametrize(
    ("provider", "model", "bundle"),
    [
        ("openai_api", "gpt-5.6-sol", "requests.jsonl"),
        ("anthropic_api", "claude-fable-5", "requests.json"),
    ],
)
def test_prepare_provider_batch_is_immutable(
    isolated_runtime, provider: str, model: str, bundle: str
) -> None:
    first = prepare_provider_batch(
        [{"custom_id": "a", "task": "task a"}, {"custom_id": "b", "task": "task b"}],
        provider_name=provider,
        model=model,
        config=load_config(include_user=False),
    )
    second = prepare_provider_batch(
        [{"custom_id": "a", "task": "task a"}, {"custom_id": "b", "task": "task b"}],
        provider_name=provider,
        model=model,
        config=load_config(include_user=False),
    )
    assert first["batch_id"] == second["batch_id"]
    assert first["bundle"] == bundle
    assert Path(first["directory"], bundle).is_file()
    assert first["requires_submission_confirmation"] is True


def test_xai_provider_batch_prepare_is_rejected(isolated_runtime) -> None:
    with pytest.raises(CapabilityError, match="unavailable"):
        prepare_provider_batch(
            [{"task": "task"}],
            provider_name="xai_api",
            model="grok-4.5",
            config=load_config(include_user=False),
        )


def test_batch_submission_requires_explicit_confirmation(isolated_runtime) -> None:
    prepared = prepare_provider_batch(
        [{"task": "task"}],
        provider_name="openai_api",
        model="gpt-5.6-sol",
        config=load_config(include_user=False),
    )
    with pytest.raises(ExternalActionRequired, match="confirmed=true"):
        submit_provider_batch(
            prepared["batch_id"],
            confirmed=False,
            config=load_config(include_user=False),
        )


def test_openai_batch_submission_shapes_requests(isolated_runtime, monkeypatch) -> None:
    config = load_config(include_user=False)
    prepared = prepare_provider_batch(
        [{"task": "task"}],
        provider_name="openai_api",
        model="gpt-5.6-sol",
        config=config,
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    requests = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode()

    def opener(request, timeout=60):
        requests.append(request)
        if request.full_url.endswith("/files"):
            return Response({"id": "file-123"})
        return Response({"id": "batch-123", "status": "validating"})

    result = submit_provider_batch(
        prepared["batch_id"],
        confirmed=True,
        config=config,
        opener=opener,
    )
    assert result["remote"]["id"] == "batch-123"
    assert [request.full_url.rsplit("/", 1)[-1] for request in requests] == ["files", "batches"]
    assert all("test-key" not in json.dumps(result) for _ in [0])


def test_microbatch_preserves_order_and_failures() -> None:
    def worker(value):
        if value == 2:
            raise ValueError("two failed")
        return value * 10

    result = execute_microbatch([1, 2, 3], worker, max_concurrency=2)
    assert result[0] == {"ok": True, "value": 10}
    assert result[1]["ok"] is False
    assert result[2] == {"ok": True, "value": 30}


def test_grok_camel_case_envelope_is_not_returned_as_the_answer(
    isolated_runtime, monkeypatch
) -> None:
    """The Grok CLI names its fields in camelCase.

    When those spellings were unrecognised the envelope failed the result-shape
    check, so the whole telemetry payload — cost, session ids, the model's
    private reasoning — was canonicalised and handed back as the seat's answer.
    """
    monkeypatch.setattr("claude_fusion_drive.oauth.shutil.which", lambda _: "/usr/bin/grok")

    def fake_run(args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "modelUsage": {"grok-4.5": {"costUSD": 0.12}},
                    "sessionId": "019fd10e-d0ad-7500",
                    "thought": "private reasoning that must not leak into the panel",
                    "structuredOutput": {"answer": "4"},
                    "text": '{"answer":"4"}',
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr("claude_fusion_drive.oauth.subprocess.run", fake_run)
    response = SubscriptionCliAdapter(load_config(include_user=False)).complete(
        "grok45-oauth-panel",
        system="Panel seat.",
        prompt="What is 2+2?",
        response_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    assert response.text == '{"answer":"4"}'
    assert "thought" not in response.text
    assert "costUSD" not in response.text
    assert response.usage.input_tokens == 5
