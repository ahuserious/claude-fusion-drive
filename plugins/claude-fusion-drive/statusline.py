#!/usr/bin/env python3
"""Claude Code statusline for Claude Fusion Drive.

Renders one compact line: active profile, fusion topology (panel/judge/fuser
with effective reasoning as superscripts), provider sign-in state, mini-fuse
on/off, live fusion process status, Braintrust link state, and the hotkey
slot legend. Width-aware: segments degrade in priority order to fit the
budget (``width`` in <state>/statusline.json, else $COLUMNS, else 120) so the
host never hard-truncates the tail. Must never crash — on any error it
degrades to a minimal line.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT))

DIM, RESET = "\033[2m", "\033[0m"
GREEN, RED, YELLOW, CYAN = "\033[32m", "\033[31m", "\033[33m", "\033[36m"
SEP = f"{DIM}│{RESET}"
ANSI_PATTERN = re.compile(r"\033\[[0-9;]*m")
TERMINAL_JOB_STATUSES = {"completed", "failed", "aborted"}
STALE_WORKFLOW_SECONDS = 7 * 24 * 3600
DEFAULT_WIDTH = 120

MODEL_SHORT = {
    "claude-fable-5": "fable5",
    "grok-4.5": "grok45",
    "gpt-5.6-sol": "sol",
    "openrouter/fusion": "fusion",
}
PROVIDER_SHORT = {
    "xai_api": "xai",
    "openrouter_api": "or",
    "openrouter_fusion_api": "orf",
    "openai_api": "oai",
    "anthropic_api": "ant",
    "grok_oauth": "grok",
    "claude_oauth": "claude",
}
EFFORT_SUP = {
    "none": "°", "minimal": "ⁱ", "low": "ˡ", "medium": "ᵐ",
    "high": "ʰ", "xhigh": "ˣ", "max": "ᴹ", "ultra": "ᵁ",
}
STATE_SHORT = {
    "awaiting_plan_gate": "plan-gate",
    "awaiting_user_confirmation": "confirm",
    "awaiting_claude_goal": "goal",
    "awaiting_pre_execution_gate": "pre-gate",
    "ready_for_execution": "ready",
    "executing": "exec",
    "awaiting_post_execution": "post-gate",
    "awaiting_final": "final",
    "awaiting_summary": "summary",
}
SUPERSCRIPT = {"1": "¹", "2": "²", "3": "³", "4": "⁴",
               "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹"}
MINI_FUSE_SEATS = ("grok45-mini-panel", "grok45-mini-judge", "grok45-mini-fuser")


def visible_length(text: str) -> int:
    return len(ANSI_PATTERN.sub("", text))


def short_model(model: str) -> str:
    model = model.split("/")[-1] if "/" in model else model
    return MODEL_SHORT.get(model, model.replace("claude-", "").replace("-", ""))


def short_profile(name: str) -> str:
    known = {
        "xai-claude-oauth": "xai", "all-grok-4.5": "grok",
        "maximum-intelligence": "max", "openrouter-fusion": "orf",
        "subscription-oauth": "sub", "mini-fuse": "mini",
    }
    return known.get(name, name.split("-")[0][:5])


def seat_label(config: dict, seat_name: str) -> str:
    seat = config.get("seats", {}).get(seat_name, {})
    effort = str(seat.get("effective_reasoning", "?"))
    return f"{short_model(str(seat.get('model', '?')))}{EFFORT_SUP.get(effort, '?')}"


def topology_segment(config: dict) -> str:
    profile = config["profiles"][config["active_profile"]]
    engine = config["engines"][profile["engine"]]
    if engine.get("kind") == "server_managed":
        models = "+".join(short_model(m) for m in engine.get("analysis_models", []))
        judge = short_model(str(engine.get("judge_model", "?")))
        return f"P:{models} JF:{judge}{DIM}·srv{RESET}"
    counts: dict[str, int] = {}
    for seat_name in engine.get("panel", []):
        label = seat_label(config, seat_name)
        counts[label] = counts.get(label, 0) + 1
    panel = "+".join(label if n == 1 else f"{label}×{n}" for label, n in counts.items())
    judge = seat_label(config, str(engine.get("judge", "")))
    fuser = seat_label(config, str(engine.get("fuser", "")))
    return f"P:{panel} J:{judge} F:{fuser}"


def provider_signed_in(provider: dict) -> bool:
    mode = provider.get("auth", {}).get("mode")
    if mode == "api_key_env":
        return bool(os.environ.get(str(provider.get("auth", {}).get("api_key_env", ""))))
    if mode == "cli_oauth_keychain":
        return shutil.which(str(provider.get("command", ""))) is not None
    return True


def provider_states(config: dict) -> list[tuple[str, bool]]:
    states = []
    for name, provider in sorted(config.get("providers", {}).items()):
        # claude_host is this very session; showing it is always-✓ noise.
        if not provider.get("enabled") or name == "claude_host":
            continue
        states.append((PROVIDER_SHORT.get(name, name), provider_signed_in(provider)))
    return states


def providers_segment(states: list[tuple[str, bool]], collapsed: bool) -> str:
    if collapsed and all(ok for _, ok in states):
        return f"prov{GREEN}✓{RESET}"
    return "".join(
        f"{name}{(GREEN if ok else RED)}{'✓' if ok else '✗'}{RESET}" for name, ok in states
    )


def mini_fuse_segment(config: dict) -> str:
    seats = config.get("seats", {})
    if not all(name in seats for name in MINI_FUSE_SEATS):
        return f"{DIM}MF·n/a{RESET}"
    if all(seats[name].get("enabled") for name in MINI_FUSE_SEATS):
        model = short_model(str(seats[MINI_FUSE_SEATS[0]].get("model", "?")))
        return f"MF{GREEN}✓{RESET}{model}"
    return f"MF{DIM}·off{RESET}"


def live_segment(state_root: Path) -> str:
    now = time.time()
    active_jobs: dict[str, int] = {}
    jobs_dir = state_root / "jobs"
    if jobs_dir.is_dir():
        for job_path in jobs_dir.glob("job-*/job.json"):
            try:
                job = json.loads(job_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if job.get("status") not in TERMINAL_JOB_STATUSES:
                op = str(job.get("operation", "job")).replace("approval_gate", "gate")
                active_jobs[op] = active_jobs.get(op, 0) + 1
    workflow_states: dict[str, int] = {}
    workflows_dir = state_root / "workflows"
    if workflows_dir.is_dir():
        for lifecycle_path in workflows_dir.glob("*/host-lifecycle.json"):
            try:
                if now - lifecycle_path.stat().st_mtime > STALE_WORKFLOW_SECONDS:
                    continue
                state = str(json.loads(lifecycle_path.read_text(encoding="utf-8")).get("state", ""))
            except (json.JSONDecodeError, OSError):
                continue
            if state and state != "complete":
                short = STATE_SHORT.get(state, state)
                workflow_states[short] = workflow_states.get(short, 0) + 1
    parts = []
    if active_jobs:
        jobs = "+".join(f"{op}×{n}" if n > 1 else op for op, n in sorted(active_jobs.items()))
        parts.append(f"{YELLOW}▶{jobs}{RESET}")
    if workflow_states:
        states = "+".join(f"{s}×{n}" if n > 1 else s for s, n in sorted(workflow_states.items()))
        parts.append(f"wf:{states}")
    return " ".join(parts) if parts else f"{DIM}idle{RESET}"


def braintrust_segment(state_root: Path) -> str:
    if os.environ.get("BRAINTRUST_API_KEY"):
        return f"BT{GREEN}✓{RESET}"
    export_dir = state_root / "braintrust-export"
    if export_dir.is_dir() and any(export_dir.iterdir()):
        return f"BT{YELLOW}~{RESET}"
    return f"BT{RED}✗{RESET}"


def read_statusline_config(state_root: Path) -> dict:
    try:
        data = json.loads((state_root / "statusline.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def slots_segment(sl_config: dict, config: dict) -> str:
    slots = {"1": "xai-claude-oauth", "2": "all-grok-4.5",
             "3": "maximum-intelligence", "4": "mini-fuse"}
    if isinstance(sl_config.get("slots"), dict) and sl_config["slots"]:
        slots = {str(k): str(v) for k, v in sl_config["slots"].items()}
    active = config.get("active_profile")
    parts = []
    for slot in sorted(slots)[:6]:
        label = short_profile(slots[slot])
        sup = SUPERSCRIPT.get(slot, slot)
        if slots[slot] == active:
            parts.append(f"{CYAN}{sup}{label}{RESET}")
        else:
            parts.append(f"{DIM}{sup}{RESET}{label}")
    return "".join(parts)


def width_budget(sl_config: dict) -> int:
    configured = sl_config.get("width")
    if isinstance(configured, int) and configured > 40:
        return configured
    try:
        columns = int(os.environ.get("COLUMNS", ""))
        if columns > 40:
            return columns - 2
    except ValueError:
        pass
    return DEFAULT_WIDTH


def main() -> int:
    try:
        sys.stdin.read()
    except OSError:
        pass
    try:
        from claude_fusion_drive.config import load_config, runtime_dir

        config = load_config()
        state_root = runtime_dir()
        sl_config = read_statusline_config(state_root)
        states = provider_states(config)

        def build(*, slots: bool, collapse_providers: bool, full_profile: bool) -> str:
            profile_name = str(config.get("active_profile", "?"))
            if not full_profile:
                profile_name = short_profile(profile_name)
            segments = [
                f"{CYAN}⚛ {profile_name}{RESET}",
                topology_segment(config),
                providers_segment(states, collapse_providers),
                mini_fuse_segment(config),
                live_segment(state_root),
                braintrust_segment(state_root),
            ]
            if slots:
                segments.append(slots_segment(sl_config, config))
            return SEP.join(segment for segment in segments if segment)

        budget = width_budget(sl_config)
        # Degrade in priority order until the line fits the width budget.
        for attempt in (
            {"slots": True, "collapse_providers": False, "full_profile": True},
            {"slots": True, "collapse_providers": False, "full_profile": False},
            {"slots": True, "collapse_providers": True, "full_profile": False},
            {"slots": False, "collapse_providers": True, "full_profile": False},
        ):
            line = build(**attempt)
            if visible_length(line) <= budget:
                break
        print(line)
    except Exception as error:  # statusline must never crash the host UI
        print(f"⚛ fusion-drive {DIM}(statusline error: {type(error).__name__}){RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
