from __future__ import annotations

import importlib.util
import io
import json
import os
import time
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "claude-fusion-drive"


def load_script(name: str) -> ModuleType:
    path = PLUGIN_ROOT / name
    spec = importlib.util.spec_from_file_location(f"test_{name.replace('.', '_')}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def host_payload() -> dict:
    return {
        "model": {"id": "claude-opus-4-7", "display_name": "Opus 4.7"},
        "effort": {"level": "xhigh"},
        "thinking": {"enabled": True},
        "context_window": {
            "context_window_size": 1_000_000,
            "used_percentage": 42.4,
            "total_input_tokens": 410_000,
            "total_output_tokens": 14_000,
        },
        "cost": {"total_cost_usd": 1.234, "total_duration_ms": 245_000},
    }


def test_three_line_status_prioritizes_live_state_stack_and_host_context(tmp_path: Path) -> None:
    statusline = load_script("statusline.py")
    write_json(
        tmp_path / "jobs" / "job-live" / "job.json",
        {"operation": "approval_gate", "status": "running"},
    )
    write_json(
        tmp_path / "jobs" / "job-done" / "job.json",
        {"operation": "fuse", "status": "completed"},
    )
    write_json(
        tmp_path / "workflows" / "workflow-live" / "host-lifecycle.json",
        {"state": "awaiting_pre_execution_gate"},
    )
    write_json(
        tmp_path / "workflows" / "workflow-done" / "host-lifecycle.json",
        {"state": "complete"},
    )

    lines = statusline.render_status(
        host_payload(),
        {"active_profile": "maximum-intelligence"},
        tmp_path,
        width=120,
        now=time.time(),
    )

    assert len(lines) == 3
    plain = "\n".join(statusline.ANSI_PATTERN.sub("", line) for line in lines)
    assert "FUSION DRIVE" in plain
    assert "maximum intelligence" in plain
    assert "approval gate · running" in plain
    assert "pre-exec gate" in plain
    assert "completed" not in plain
    assert "Opus 4.7 · xhigh" in plain
    assert "1M ctx" in plain
    assert "42%" in plain
    assert "$1.23" in plain
    assert "4m05s" in plain


def test_recent_failure_is_visible_but_completed_and_old_failure_are_hidden(tmp_path: Path) -> None:
    statusline = load_script("statusline.py")
    recent = tmp_path / "jobs" / "job-recent" / "job.json"
    old = tmp_path / "jobs" / "job-old" / "job.json"
    done = tmp_path / "jobs" / "job-done" / "job.json"
    write_json(
        recent,
        {"operation": "fuse", "status": "failed", "error": "judge returned malformed JSON"},
    )
    write_json(old, {"operation": "approval_gate", "status": "failed"})
    write_json(done, {"operation": "approval_gate", "status": "completed"})
    now = time.time()
    os.utime(old, (now - statusline.RECENT_FAILURE_SECONDS - 1, now - statusline.RECENT_FAILURE_SECONDS - 1))

    lines = statusline.render_status({}, {"active_profile": "mini-fuse"}, tmp_path, width=100, now=now)
    plain = "\n".join(statusline.ANSI_PATTERN.sub("", line) for line in lines)

    assert "✗ fusion · failed" in plain
    assert "judge returned malformed JSON" in plain
    assert "approval gate" not in plain
    assert "completed" not in plain


def test_status_is_null_safe_surfaces_corrupt_state_and_respects_width(tmp_path: Path) -> None:
    statusline = load_script("statusline.py")
    corrupt = tmp_path / "jobs" / "job-broken" / "job.json"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("{not json", encoding="utf-8")

    lines = statusline.render_status({}, {}, tmp_path, width=44)

    assert len(lines) == 3
    assert all(statusline.visible_length(line) <= 44 for line in lines)
    plain = "\n".join(statusline.ANSI_PATTERN.sub("", line) for line in lines)
    assert "state×1" in plain
    assert "model —" in plain
    assert "—%" in plain


def test_main_parses_stdin_and_uses_mocked_config_runtime_and_width(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    statusline = load_script("statusline.py")
    monkeypatch.setattr(statusline, "load_drive_context", lambda: ({"active_profile": "subscription-oauth"}, tmp_path))
    monkeypatch.setattr(statusline.sys, "stdin", io.StringIO(json.dumps(host_payload())))
    monkeypatch.setenv("COLUMNS", "52")

    assert statusline.main() == 0
    captured = capsys.readouterr()
    lines = captured.out.rstrip("\n").splitlines()
    assert len(lines) == 3
    assert all(statusline.visible_length(line) <= 52 for line in lines)
    plain = "\n".join(statusline.ANSI_PATTERN.sub("", line) for line in lines)
    assert "Opus 4.7" in plain
    assert "42%" in plain


def test_malformed_host_input_reports_the_error_without_a_traceback(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    statusline = load_script("statusline.py")
    monkeypatch.setattr(statusline, "load_drive_context", lambda: ({"active_profile": "mini-fuse"}, tmp_path))
    monkeypatch.setattr(statusline.sys, "stdin", io.StringIO("{bad"))

    assert statusline.main() == 0
    captured = capsys.readouterr()
    plain = statusline.ANSI_PATTERN.sub("", captured.out)
    assert "input JSON error" in plain
    assert "Traceback" not in captured.err


def test_subagent_rows_follow_documented_schema_and_width() -> None:
    subagent = load_script("subagent_statusline.py")
    rows, errors = subagent.render_rows(
        {
            "columns": 54,
            "model": {"display_name": "Parent Opus"},
            "tasks": [
                {
                    "id": "agent-1",
                    "name": "reviewer",
                    "type": "security-review",
                    "status": "running",
                    "label": "Audit auth boundary",
                    "tokenCount": 12_345,
                },
                {"name": "missing-id", "status": "pending"},
            ],
        }
    )

    assert len(rows) == 1
    assert rows[0]["id"] == "agent-1"
    assert subagent.visible_length(rows[0]["content"]) <= 54
    plain = subagent.ANSI_PATTERN.sub("", rows[0]["content"])
    assert "Audit auth boundary" in plain
    assert "running" in plain
    assert "12.3k tok" in plain
    assert "Parent Opus" not in plain  # root model is not the task model
    assert errors == ["task 1 has no id"]


def test_plugin_settings_ship_only_supported_subagent_statusline() -> None:
    settings = json.loads((PLUGIN_ROOT / "settings.json").read_text(encoding="utf-8"))

    assert set(settings) == {"subagentStatusLine"}
    command = settings["subagentStatusLine"]["command"]
    assert settings["subagentStatusLine"]["type"] == "command"
    assert "${CLAUDE_PLUGIN_ROOT}/subagent_statusline.py" in command
    assert not Path(command).is_absolute()


def stack_config() -> dict:
    return {
        "active_profile": "demo",
        "profiles": {"demo": {"engine": "demo_engine"}},
        "engines": {"demo_engine": {"panel": ["p1", "p2"], "judge": "j1", "fuser": "f1"}},
        "seats": {
            "p1": {"model": "claude-opus-5"},
            "p2": {"model": "x-ai/grok-4.5"},
            "j1": {"model": "gpt-5.6-sol"},
            "f1": {"model": "claude-fable-5"},
            "grok45-xr-mini-panel": {"model": "grok-4.5"},
            "sol-xr-mini-panel": {"model": "gpt-5.6-sol"},
            "grok45-xr-review": {"model": "grok-4.5"},
        },
        "subagent_presets": {},
    }


def test_model_abbreviations_drop_provider_prefixes() -> None:
    statusline = load_script("statusline.py")
    assert statusline.abbreviate_model("claude-opus-5") == "op5"
    assert statusline.abbreviate_model("anthropic/claude-fable-5") == "fb5"
    assert statusline.abbreviate_model("x-ai/grok-4.5") == "gr4.5"
    assert statusline.abbreviate_model("openai/gpt-5.6-sol") == "sol"
    assert statusline.abbreviate_model(None) == "—"


def test_stack_line_shows_every_role_and_the_subagent_config() -> None:
    statusline = load_script("statusline.py")
    line = statusline.stack_line(
        stack_config(),
        {"toggles": {"subagent_review": "exaflop", "preset": "high", "fusion_plan": True}},
        {"active_seats": []},
        200,
    )
    plain = statusline.ANSI_PATTERN.sub("", line)
    assert "op5·gr4.5" in plain
    assert "judge sol" in plain
    assert "fuse fb5" in plain
    # The rung name says nothing about what runs; the seats resolve to models.
    assert "sub gr4.5" in plain
    assert "plan fused high" in plain


def test_stack_line_reports_running_seats_and_fits_narrow_widths() -> None:
    statusline = load_script("statusline.py")
    snapshot = {
        "active_seats": [
            {"seat": "a", "running": True},
            {"seat": "b", "running": False},
        ]
    }
    wide = statusline.ANSI_PATTERN.sub(
        "", statusline.stack_line(stack_config(), {}, snapshot, 200)
    )
    assert "1/2 seats" in wide
    for width in (40, 60, 80, 120):
        line = statusline.stack_line(stack_config(), {}, snapshot, width)
        assert statusline.visible_length(line) <= width


def test_active_seats_reads_inflight_ledger_rows(tmp_path: Path) -> None:
    statusline = load_script("statusline.py")
    run_dir = tmp_path / "engine" / "runs" / "job-1"
    write_json(run_dir / "panel.json", {"results": [{"seat_name": "p1", "role": "panel", "status": "ok"}]})
    write_json(run_dir / "ledger.json", {"attempt_entries": [{"seat": "j1", "stage": "judge"}]})

    rows = statusline.active_seats(tmp_path, [{"job_id": "job-1"}])

    by_seat = {row["seat"]: row for row in rows}
    assert by_seat["p1"]["running"] is False
    # A judge seat never lands in panel.json; its reserved ledger row is the
    # only evidence it is in flight.
    assert by_seat["j1"]["running"] is True


def test_review_rung_resolves_to_seat_models_not_the_rung_name() -> None:
    statusline = load_script("statusline.py")
    config = {
        "seats": {
            "grok45-xr-mini-panel": {"model": "grok-4.5"},
            "sol-xr-mini-panel": {"model": "gpt-5.6-sol"},
            "grok45-xr-review": {"model": "grok-4.5"},
            "grok45-mini-panel": {"model": "grok-4.5"},
            "grok45-mini-judge": {"model": "grok-4.5"},
        }
    }
    # Duplicate models collapse, so the grok judge does not repeat the badge.
    assert statusline.review_models(config, "exaflop") == "gr4.5·sol"
    assert statusline.review_models(config, "light") == "gr4.5"
    assert statusline.review_models(config, "off") == "off"
    assert statusline.review_models(config, "") == "off"
    # An unknown rung, or one whose seats are absent, degrades to its own name.
    assert statusline.review_models(config, "unknown-rung") == "unknown-rung"
    assert statusline.review_models({"seats": {}}, "exaflop") == "exaflop"
