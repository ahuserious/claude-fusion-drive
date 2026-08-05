#!/usr/bin/env python3
"""Concise Claude Code subagent rows for Claude Fusion Drive.

Claude Code passes all visible tasks in one JSON object and expects one JSON
line per overridden row. The documented task schema does not contain a model or
context-window percentage, so this renderer does not invent either. It shows
the available task type, label, status, and token count instead.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from typing import Any, TextIO


RESET = "\033[0m"
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]+")
DIM_C = 240
TEXT_C = 252
RUN_C = 220
GOOD_C = 77
BAD_C = 196
WAIT_C = 81


def fg(color: int, text: str) -> str:
    return f"\033[38;5;{color}m{text}{RESET}"


def visible_length(text: str) -> int:
    return len(ANSI_PATTERN.sub("", text))


def safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = ANSI_PATTERN.sub("", str(value))
    text = CONTROL_PATTERN.sub(" ", text).strip()
    return text or fallback


def fit_line(line: str, width: int) -> str:
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


def _positive_int(value: Any, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(12, min(parsed, 240)) if parsed > 0 else fallback


def _token_label(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count < 0:
        return None
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M tok"
    if count >= 1_000:
        return f"{count / 1_000:.1f}k tok"
    return f"{count} tok"


def _status_style(status: str) -> tuple[str, int]:
    normalized = status.lower()
    if normalized in {"completed", "complete", "done", "success"}:
        return "✓", GOOD_C
    if normalized in {"failed", "error", "aborted"}:
        return "✗", BAD_C
    if normalized in {"queued", "pending", "waiting"}:
        return "○", WAIT_C
    return "●", RUN_C


def task_content(task: Mapping[str, Any], width: int) -> str:
    status = safe_text(task.get("status"), "working")
    icon, color = _status_style(status)
    label = safe_text(task.get("label") or task.get("name") or task.get("description"), "subagent")
    phase = safe_text(task.get("type"))
    tokens = _token_label(task.get("tokenCount"))

    prefix = fg(color, icon)
    full_parts = [fg(TEXT_C, label)]
    if phase and phase.lower() != label.lower():
        full_parts.append(fg(DIM_C, phase))
    full_parts.append(fg(color, status))
    if tokens:
        full_parts.append(fg(DIM_C, tokens))
    full = f"{prefix} " + f" {fg(DIM_C, '·')} ".join(full_parts)

    compact_parts = [fg(TEXT_C, label), fg(color, status)]
    if tokens:
        compact_parts.append(fg(DIM_C, tokens))
    compact = f"{prefix} " + f" {fg(DIM_C, '·')} ".join(compact_parts)
    narrow = f"{prefix} {fg(TEXT_C, label)} {fg(DIM_C, tokens or status)}"
    minimal = f"{prefix} {fg(TEXT_C, label)}"
    return choose_fit([full, compact, narrow, minimal], width)


def render_rows(payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    width = _positive_int(payload.get("columns"), 100)
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return [], ["subagent status input has no tasks array"]

    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            errors.append(f"task {index} is not an object")
            continue
        task_id = safe_text(task.get("id"))
        if not task_id:
            # Omitting an id preserves Claude Code's default rendering.
            errors.append(f"task {index} has no id")
            continue
        rows.append({"id": task_id, "content": task_content(task, width)})
    return rows, errors


def read_payload(stream: TextIO) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = stream.read()
    except OSError as error:
        return None, f"stdin {type(error).__name__}: {safe_text(error)}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        return None, f"input JSON error at column {error.colno}"
    if not isinstance(payload, dict):
        return None, "input JSON must be an object"
    return payload, None


def main() -> int:
    payload, input_error = read_payload(sys.stdin)
    if input_error:
        print(f"cfd subagent status error: {input_error}", file=sys.stderr)
        return 0
    assert payload is not None
    rows, errors = render_rows(payload)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False))
    if errors:
        print("cfd subagent status warning: " + "; ".join(errors), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
