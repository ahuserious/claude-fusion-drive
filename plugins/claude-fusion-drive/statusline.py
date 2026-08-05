#!/usr/bin/env python3
"""Two-line Claude Code status line for Claude Fusion Drive.

Claude Code supplies live session data as JSON on stdin. Fusion Drive adds the
active profile and durable job/lifecycle state from its runtime directory. The
renderer is deliberately small: product/workflow state on line one, then the
host model, effort, context window, cost, and duration on line two.

The status path must not interfere with Claude Code. Malformed or partial data
therefore renders a compact warning instead of raising, while recent failures
and unreadable state files remain visible rather than being silently discarded.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO


RESET = "\033[0m"
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")

DIM_C = 240
TEXT_C = 252
ACCENT_C = 81
PROFILE_C = 208
GOOD_C = 77
WARN_C = 220
BAD_C = 196
BAR_EMPTY_C = 238
BADGE_BG = 24
BADGE_FG = 195

DEFAULT_WIDTH = 120
STALE_WORKFLOW_SECONDS = 7 * 24 * 3600
RECENT_FAILURE_SECONDS = 30 * 60
TERMINAL_JOB_STATUSES = {"completed", "aborted"}
TERMINAL_WORKFLOW_STATES = {"complete"}

STATE_LABELS = {
    "awaiting_plan_gate": "plan gate",
    "awaiting_user_confirmation": "confirm plan",
    "awaiting_claude_goal": "create goal",
    "awaiting_pre_execution_gate": "pre-exec gate",
    "ready_for_execution": "ready",
    "executing": "executing",
    "awaiting_post_execution": "post-exec gate",
    "awaiting_final": "final gate",
    "awaiting_summary": "summary gate",
}

PROFILE_LABELS = {
    "xai-claude-oauth": "xai + claude",
    "all-grok-4.5": "all grok",
    "maximum-intelligence": "maximum intelligence",
    "openrouter-fusion": "openrouter fusion",
    "subscription-oauth": "subscription",
    "mini-fuse": "mini fuse",
    "exaflop-reactor": "exaflop",
    "exaflop-mini": "exaflop mini",
}


def fg(color: int, text: str) -> str:
    return f"\033[38;5;{color}m{text}{RESET}"


def badge(text: str) -> str:
    return f"\033[48;5;{BADGE_BG}m\033[38;5;{BADGE_FG}m{text}{RESET}"


def visible_length(text: str) -> int:
    return len(ANSI_PATTERN.sub("", text))


def safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = ANSI_PATTERN.sub("", str(value))
    text = CONTROL_PATTERN.sub(" ", text).strip()
    return text or fallback


def fit_line(line: str, width: int) -> str:
    """Keep a rendered row within the host width, even for hostile labels."""

    if visible_length(line) <= width:
        return line
    plain = ANSI_PATTERN.sub("", line)
    if width <= 1:
        return plain[:width]
    return plain[: width - 1] + "…"


def choose_fit(variants: list[str], width: int) -> str:
    for variant in variants:
        if visible_length(variant) <= width:
            return variant
    return fit_line(variants[-1], width)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def width_budget(host: Mapping[str, Any], status_config: Mapping[str, Any]) -> int:
    """Resolve usable columns without assuming stdout is attached to a TTY."""

    candidates = (
        host.get("columns"),
        os.environ.get("COLUMNS"),
        status_config.get("width"),
        shutil.get_terminal_size(fallback=(DEFAULT_WIDTH, 24)).columns,
    )
    for candidate in candidates:
        width = _positive_int(candidate)
        if width is not None:
            return max(12, min(width, 240))
    return DEFAULT_WIDTH


def read_host_payload(stream: TextIO) -> tuple[dict[str, Any], str | None]:
    try:
        raw = stream.read()
    except OSError as error:
        return {}, f"stdin {type(error).__name__}: {safe_text(error)}"
    if not raw.strip():
        return {}, "stdin contained no status JSON"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        return {}, f"input JSON error at column {error.colno}"
    if not isinstance(payload, dict):
        return {}, "input JSON must be an object"
    return payload, None


def read_status_config(state_root: Path) -> tuple[dict[str, Any], str | None]:
    path = state_root / "statusline.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except (json.JSONDecodeError, OSError) as error:
        return {}, f"status config {type(error).__name__}: {safe_text(error)}"
    if not isinstance(payload, dict):
        return {}, "status config must be an object"
    return payload, None


def _read_state_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    label = f"{path.parent.name}/{path.name}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None, f"{label} is not an object"
        return payload, None
    except (json.JSONDecodeError, OSError) as error:
        return None, f"{label} {type(error).__name__}: {safe_text(error)}"


def _modified_at(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def runtime_snapshot(state_root: Path, now: float | None = None) -> dict[str, list[dict[str, Any]] | list[str]]:
    """Read live state without mutating or validating lifecycle receipts."""

    current_time = time.time() if now is None else now
    active_jobs: list[dict[str, Any]] = []
    active_workflows: list[dict[str, Any]] = []
    recent_failures: list[dict[str, Any]] = []
    errors: list[str] = []

    jobs_dir = state_root / "jobs"
    if jobs_dir.is_dir():
        for path in jobs_dir.glob("job-*/job.json"):
            payload, error = _read_state_file(path)
            if error:
                errors.append(error)
                continue
            assert payload is not None
            modified_at = _modified_at(path)
            status = safe_text(payload.get("status"), "unknown").lower()
            item = {
                "kind": "job",
                "job_id": safe_text(payload.get("job_id")) or path.parent.name,
                "operation": safe_text(payload.get("operation"), "fusion job"),
                "status": status,
                "error": safe_text(payload.get("error")),
                "modified_at": modified_at,
            }
            if status == "failed":
                if current_time - modified_at <= RECENT_FAILURE_SECONDS:
                    recent_failures.append(item)
                continue
            if status in TERMINAL_JOB_STATUSES:
                if status == "aborted" and current_time - modified_at <= RECENT_FAILURE_SECONDS:
                    recent_failures.append(item)
                continue
            active_jobs.append(item)

    workflows_dir = state_root / "workflows"
    if workflows_dir.is_dir():
        for path in workflows_dir.glob("*/host-lifecycle.json"):
            payload, error = _read_state_file(path)
            if error:
                errors.append(error)
                continue
            assert payload is not None
            modified_at = _modified_at(path)
            state = safe_text(payload.get("state"), "unknown").lower()
            item = {
                "kind": "workflow",
                "state": state,
                "modified_at": modified_at,
                "stale": current_time - modified_at > STALE_WORKFLOW_SECONDS,
            }
            if state == "aborted":
                if current_time - modified_at <= RECENT_FAILURE_SECONDS:
                    recent_failures.append(item)
                continue
            if state in TERMINAL_WORKFLOW_STATES:
                continue
            active_workflows.append(item)

    newest_first = lambda item: float(item.get("modified_at", 0.0))
    active_jobs.sort(key=newest_first, reverse=True)
    active_workflows.sort(key=newest_first, reverse=True)
    recent_failures.sort(key=newest_first, reverse=True)
    return {
        "active_jobs": active_jobs,
        "active_workflows": active_workflows,
        "recent_failures": recent_failures,
        "active_seats": active_seats(state_root, active_jobs),
        "errors": errors,
    }


def active_seats(
    state_root: Path,
    jobs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-seat rows for the running jobs, matching what `fusion watch` shows.

    panel.json is rewritten as each panel seat finishes, and ledger.json
    reserves an attempt row before a seat's transport starts — which is what
    makes an in-flight seat visible at all. Judge and fuser seats never reach
    panel.json, so their ledger entry is the only evidence they exist.
    """

    rows: list[dict[str, Any]] = []
    for job in jobs:
        job_id = safe_text(job.get("job_id"))
        if not job_id:
            continue
        run_dir = state_root / "engine" / "runs" / job_id
        panel, _ = _read_state_file(run_dir / "panel.json")
        ledger, _ = _read_state_file(run_dir / "ledger.json")
        seen: set[str] = set()

        results = (panel or {}).get("results")
        for result in results if isinstance(results, list) else []:
            if not isinstance(result, Mapping):
                continue
            seat = safe_text(result.get("seat_name"), "?")
            seen.add(seat)
            rows.append(
                {
                    "seat": seat,
                    "role": safe_text(result.get("role")),
                    "status": safe_text(result.get("status"), "done"),
                    "running": False,
                }
            )

        entries = (ledger or {}).get("attempt_entries")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, Mapping):
                continue
            seat = safe_text(entry.get("seat"), "?")
            if seat in seen:
                continue
            seen.add(seat)
            rows.append(
                {
                    "seat": seat,
                    "role": safe_text(entry.get("stage")),
                    "status": "in-flight",
                    "running": True,
                }
            )
    return rows


def _operation_label(value: Any) -> str:
    operation = safe_text(value, "fusion job").replace("_", " ")
    return {
        "approval gate": "approval gate",
        "fuse": "fusion",
    }.get(operation, operation)


def _activity_parts(snapshot: Mapping[str, Any], compact: bool = False) -> list[str]:
    jobs = snapshot.get("active_jobs")
    workflows = snapshot.get("active_workflows")
    failures = snapshot.get("recent_failures")
    errors = snapshot.get("errors")
    jobs = jobs if isinstance(jobs, list) else []
    workflows = workflows if isinstance(workflows, list) else []
    failures = failures if isinstance(failures, list) else []
    errors = errors if isinstance(errors, list) else []

    parts: list[str] = []
    if jobs and isinstance(jobs[0], Mapping):
        job = jobs[0]
        operation = _operation_label(job.get("operation"))
        status = safe_text(job.get("status"), "working")
        label = operation if compact else f"{operation} · {status}"
        suffix = f" +{len(jobs) - 1}" if len(jobs) > 1 else ""
        parts.append(fg(WARN_C, f"▶ {label}{suffix}"))
    if workflows and isinstance(workflows[0], Mapping):
        workflow = workflows[0]
        state = safe_text(workflow.get("state"), "workflow")
        label = STATE_LABELS.get(state, state.replace("_", " "))
        if workflow.get("stale"):
            label += " · stale"
        suffix = f" +{len(workflows) - 1}" if len(workflows) > 1 else ""
        parts.append(fg(ACCENT_C, f"◇ {label}{suffix}"))
    if failures and isinstance(failures[0], Mapping):
        failure = failures[0]
        if failure.get("kind") == "job":
            failure_label = _operation_label(failure.get("operation"))
        else:
            failure_label = "workflow"
        if compact:
            failure_text = f"✗ {failure_label}"
        else:
            failure_status = safe_text(
                failure.get("status") or failure.get("state"),
                "failed",
            )
            failure_detail = safe_text(failure.get("error"))
            failure_text = f"✗ {failure_label} · {failure_status}"
            if failure_detail:
                failure_text += f" · {failure_detail[:80]}"
        parts.append(fg(BAD_C, failure_text))
    if errors:
        if compact:
            error_label = f"⚠ state×{len(errors)}"
        else:
            suffix = f" +{len(errors) - 1}" if len(errors) > 1 else ""
            error_label = f"⚠ {safe_text(errors[0])}{suffix}"
        parts.append(fg(BAD_C, error_label))
    if not parts:
        parts.append(fg(DIM_C, "idle"))
    return parts


MODEL_ABBREVIATIONS = {
    "claude-opus-5": "op5",
    "claude-fable-5": "fb5",
    "claude-sonnet-5": "sn5",
    "claude-haiku-4-5": "hk4.5",
    "grok-4.5": "gr4.5",
    "gpt-5.6-sol": "sol",
    "gpt-5.6-luna": "luna",
    "gpt-5.6-terra": "terra",
}

# Which seats each subagent-review rung actually dispatches. The rung name is
# not shown: "exaflop" says nothing about what will run, so the seats are
# resolved to their models instead and stay truthful if the seats are retargeted.
REVIEW_RUNG_SEATS = {
    "light": ("grok45-mini-panel", "grok45-mini-judge"),
    "exaflop": ("grok45-xr-mini-panel", "sol-xr-mini-panel", "grok45-xr-review"),
}


def abbreviate_model(model: Any) -> str:
    """Shorten a model slug for the stack line.

    Provider prefixes are dropped first so `anthropic/claude-opus-5` and
    `claude-opus-5` collapse to the same badge.
    """

    text = safe_text(model)
    if not text:
        return "—"
    bare = text.rpartition("/")[2]
    if bare in MODEL_ABBREVIATIONS:
        return MODEL_ABBREVIATIONS[bare]
    return bare[:10]


def review_models(config: Mapping[str, Any], review: str) -> str:
    """The distinct models the current subagent-review rung will dispatch.

    Falls back to the rung name only if none of its seats are configured, so an
    unrecognised or retargeted rung still reports something honest.
    """

    if review in {"", "off", "false", "0", "none"}:
        return "off"
    seats = REVIEW_RUNG_SEATS.get(review)
    if not seats:
        return review
    badges: list[str] = []
    for seat_name in seats:
        seat = config.get("seats", {}).get(seat_name)
        if not isinstance(seat, Mapping):
            continue
        badge_text = abbreviate_model(seat.get("model"))
        if badge_text not in badges:
            badges.append(badge_text)
    return "·".join(badges) if badges else review


def model_substitutions(config: Mapping[str, Any]) -> list[dict[str, str]]:
    """Fallbacks this configuration actually triggers.

    Imported lazily: the status line must still render if the plugin package
    cannot be imported, which is why nothing here is a module-level dependency.
    """

    if not config.get("model_fallbacks"):
        return []
    try:
        from claude_fusion_drive.fallback import active_substitutions
    except Exception:
        return []
    try:
        return active_substitutions(config)
    except Exception:
        return []


def _seat_model(config: Mapping[str, Any], seat_name: Any) -> str:
    seat = config.get("seats", {}).get(safe_text(seat_name))
    if not isinstance(seat, Mapping):
        return "—"
    return abbreviate_model(seat.get("model"))


def active_engine(config: Mapping[str, Any]) -> Mapping[str, Any]:
    profile = config.get("profiles", {}).get(safe_text(config.get("active_profile")))
    if not isinstance(profile, Mapping):
        return {}
    engine = config.get("engines", {}).get(safe_text(profile.get("engine")))
    return engine if isinstance(engine, Mapping) else {}


def stack_line(
    config: Mapping[str, Any],
    status_config: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    width: int,
) -> str:
    """Which models actually run, how subagents are configured, what is live."""

    engine = active_engine(config)
    panel = engine.get("panel")
    panel = panel if isinstance(panel, list) else []
    panel_models = [_seat_model(config, name) for name in panel]
    panel_text = "·".join(panel_models) if panel_models else "—"
    judge = _seat_model(config, engine.get("judge"))
    fuser = _seat_model(config, engine.get("fuser"))

    toggles = status_config.get("toggles")
    toggles = toggles if isinstance(toggles, Mapping) else {}
    review = safe_text(toggles.get("subagent_review"), "off").lower()
    review_label = review_models(config, review)
    preset = safe_text(toggles.get("preset"), "high")
    plan_on = bool(toggles.get("fusion_plan"))

    segments = [
        f"{fg(DIM_C, 'panel')} {fg(TEXT_C, panel_text)}",
        f"{fg(DIM_C, 'judge')} {fg(TEXT_C, judge)}",
        f"{fg(DIM_C, 'fuse')} {fg(TEXT_C, fuser)}",
        f"{fg(DIM_C, 'sub')} {fg(ACCENT_C if review != 'off' else DIM_C, review_label)}",
        f"{fg(DIM_C, 'plan')} {fg(ACCENT_C if plan_on else DIM_C, ('fused ' + preset) if plan_on else 'direct')}",
    ]

    substitutions = model_substitutions(config)
    if substitutions:
        # Prefixed and bare slugs abbreviate identically, so the same swap can
        # arrive twice; show each distinct pair once.
        seen_pairs: list[str] = []
        for item in substitutions:
            if not isinstance(item, Mapping):
                continue
            pair = f"{abbreviate_model(item.get('from'))}→{abbreviate_model(item.get('to'))}"
            if pair not in seen_pairs:
                seen_pairs.append(pair)
        segments.append(fg(WARN_C, f"⇄ {', '.join(seen_pairs)}"))

    seats = snapshot.get("active_seats")
    seats = seats if isinstance(seats, list) else []
    running = [seat for seat in seats if isinstance(seat, Mapping) and seat.get("running")]
    if seats:
        seat_text = f"▶ {len(running)}/{len(seats)} seats"
        segments.append(fg(WARN_C if running else GOOD_C, seat_text))

    separator = f"  {fg(DIM_C, '│')}  "
    full = separator.join(segments)
    compact = " ".join(
        [
            f"{fg(TEXT_C, panel_text)}",
            f"{fg(DIM_C, 'J')}{fg(TEXT_C, judge)}",
            f"{fg(DIM_C, 'F')}{fg(TEXT_C, fuser)}",
            f"{fg(DIM_C, 'sub')} {review_label}",
        ]
        + ([fg(WARN_C, f"▶{len(running)}")] if seats else [])
    )
    minimal = f"{fg(TEXT_C, panel_text)} {fg(DIM_C, 'J')}{judge} {fg(DIM_C, 'F')}{fuser}"
    return choose_fit([full, compact, minimal], width)


def short_profile(value: str) -> str:
    return {
        "maximum-intelligence": "max",
        "openrouter-fusion": "or fusion",
        "subscription-oauth": "sub",
        "xai-claude-oauth": "xai+claude",
        "all-grok-4.5": "grok",
    }.get(value, value[:12])


def product_line(
    config: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    width: int,
    errors: list[str] | None = None,
) -> str:
    profile = safe_text(config.get("active_profile"), "unconfigured")
    profile_label = PROFILE_LABELS.get(profile, profile.replace("-", " "))
    full_activity = "  ".join(_activity_parts(snapshot))
    compact_activity = " ".join(_activity_parts(snapshot, compact=True))
    issue = ""
    if errors:
        issue = "  " + fg(BAD_C, "⚠ " + safe_text(errors[0]))

    full = (
        f"{badge(' ⚛ FUSION DRIVE ')}  {fg(PROFILE_C, profile_label)}"
        f"  {fg(DIM_C, '│')}  {full_activity}{issue}"
    )
    compact = (
        f"{badge(' ⚛ CFD ')} {fg(PROFILE_C, short_profile(profile))}"
        f" {fg(DIM_C, '│')} {compact_activity}{issue}"
    )
    minimal_issue = fg(BAD_C, " ⚠") if errors else ""
    minimal = f"{badge('CFD')} {compact_activity}{minimal_issue}"
    return choose_fit([full, compact, minimal], width)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _context_values(host: Mapping[str, Any]) -> tuple[float | None, int | None]:
    context = host.get("context_window")
    if not isinstance(context, Mapping):
        return None, None
    size_value = _number(context.get("context_window_size"))
    size = int(size_value) if size_value is not None and size_value > 0 else None
    used = _number(context.get("used_percentage"))
    if used is None and size:
        input_tokens = _number(context.get("total_input_tokens"))
        output_tokens = _number(context.get("total_output_tokens"))
        if input_tokens is not None and output_tokens is not None:
            used = (input_tokens + output_tokens) * 100 / size
    if used is not None:
        used = max(0.0, min(used, 100.0))
    return used, size


def _context_size_label(size: int | None) -> str:
    if size is None:
        return "ctx"
    if size >= 1_000_000:
        value = size / 1_000_000
        prefix = f"{value:g}M"
    elif size >= 1_000:
        value = size / 1_000
        prefix = f"{value:g}k"
    else:
        prefix = str(size)
    return f"{prefix} ctx"


def context_bar(used: float | None, width: int) -> str:
    if used is None:
        filled = 0
        color = DIM_C
    else:
        filled = round(width * used / 100)
        color = BAD_C if used >= 90 else WARN_C if used >= 70 else GOOD_C
    filled = max(0, min(filled, width))
    return fg(color, "█" * filled) + fg(BAR_EMPTY_C, "░" * (width - filled))


def _duration_label(milliseconds: Any) -> str | None:
    value = _number(milliseconds)
    if value is None or value < 0:
        return None
    seconds = int(value / 1000)
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m{seconds % 60:02d}s"
    return f"{minutes // 60}h{minutes % 60:02d}m"


def _cost_label(value: Any) -> str | None:
    cost = _number(value)
    if cost is None or cost < 0:
        return None
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def session_line(host: Mapping[str, Any], width: int) -> str:
    model_block = host.get("model")
    model_block = model_block if isinstance(model_block, Mapping) else {}
    model = safe_text(model_block.get("display_name") or model_block.get("id"), "model —")

    effort_block = host.get("effort")
    effort_block = effort_block if isinstance(effort_block, Mapping) else {}
    effort = safe_text(effort_block.get("level"))
    if not effort:
        thinking_block = host.get("thinking")
        if isinstance(thinking_block, Mapping) and thinking_block.get("enabled") is True:
            effort = "thinking"
        else:
            effort = "effort —"

    used, context_size = _context_values(host)
    percent = "—%" if used is None else f"{used:.0f}%"
    context_label = _context_size_label(context_size)
    bar_width = 20 if width >= 100 else 12 if width >= 68 else 8 if width >= 46 else 4
    bar = context_bar(used, bar_width)

    cost_block = host.get("cost")
    cost_block = cost_block if isinstance(cost_block, Mapping) else {}
    cost = _cost_label(cost_block.get("total_cost_usd"))
    duration = _duration_label(cost_block.get("total_duration_ms"))
    metrics = [value for value in (cost, duration) if value]
    metrics_text = "  " + fg(DIM_C, " · ".join(metrics)) if metrics else ""

    full = (
        f"{fg(TEXT_C, model)} {fg(DIM_C, '·')} {fg(PROFILE_C, effort)}"
        f"  {fg(DIM_C, context_label)} [{bar}] {fg(TEXT_C, percent)}{metrics_text}"
    )
    no_duration_metrics = ""
    if cost:
        no_duration_metrics = "  " + fg(DIM_C, cost)
    compact = (
        f"{fg(TEXT_C, model)} {fg(PROFILE_C, effort)}"
        f"  {fg(DIM_C, context_label)} [{bar}] {percent}{no_duration_metrics}"
    )
    narrow = f"{fg(TEXT_C, model)} {fg(PROFILE_C, effort)}  [{bar}] {percent}"
    minimal = f"{fg(TEXT_C, model)} [{bar}] {percent}"
    return choose_fit([full, compact, narrow, minimal], width)


def render_status(
    host: Mapping[str, Any],
    config: Mapping[str, Any],
    state_root: Path,
    *,
    width: int,
    errors: list[str] | None = None,
    now: float | None = None,
    status_config: Mapping[str, Any] | None = None,
) -> list[str]:
    snapshot = runtime_snapshot(state_root, now=now)
    return [
        product_line(config, snapshot, width, errors=errors),
        stack_line(config, status_config or {}, snapshot, width),
        session_line(host, width),
    ]


def load_drive_context() -> tuple[dict[str, Any], Path]:
    """Separated for focused tests and soft failure in ``main``."""

    plugin_root = Path(__file__).resolve().parent
    if str(plugin_root) not in sys.path:
        sys.path.insert(0, str(plugin_root))
    from claude_fusion_drive.config import load_config, runtime_dir

    return load_config(), runtime_dir()


def main() -> int:
    host, input_error = read_host_payload(sys.stdin)
    load_error: str | None = None
    try:
        config, state_root = load_drive_context()
    except Exception as error:  # a status line must not take down the host UI
        config = {}
        configured_root = os.environ.get("CLAUDE_FUSION_DRIVE_HOME")
        state_root = Path(configured_root).expanduser() if configured_root else Path.home() / ".claude" / "claude-fusion-drive"
        load_error = f"config {type(error).__name__}: {safe_text(error)}"

    status_config, status_config_error = read_status_config(state_root)
    errors = [error for error in (input_error, load_error, status_config_error) if error]
    width = width_budget(host, status_config)
    try:
        lines = render_status(
            host,
            config,
            state_root,
            width=width,
            errors=errors,
            status_config=status_config,
        )
    except Exception as error:  # last-resort guard with visible evidence
        detail = safe_text(error, "unknown error")
        lines = [fit_line(f"CFD status error: {type(error).__name__}: {detail}", width)]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
