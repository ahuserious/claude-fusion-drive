#!/usr/bin/env python3
"""Claude Code statusline for Claude Fusion Drive.

TUI-styled single line. Models render as color-family chips: Grok white-on-
black, Anthropic orange-on-gray, OpenAI and everything else black-on-white;
effective reasoning rides each chip as a colored mini-bar (▂▄▆█). Also shown:
profile badge, provider status dots, mini-fuse state, orchestration toggles
(fusion-plan, fusion preset, subagent review — stored in
<state>/statusline.json "toggles"), live fusion process status, Braintrust
link, hotkey slot legend (active slot in reverse video), and a hotkey
reminder. Width-aware: segments degrade in priority order to fit the budget
(``width`` in statusline.json, else $COLUMNS, else 120). Must never crash —
on any error it degrades to a minimal line.
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

RESET = "\033[0m"
ANSI_PATTERN = re.compile(r"\033\[[0-9;]*m")
TERMINAL_JOB_STATUSES = {"completed", "failed", "aborted"}
STALE_WORKFLOW_SECONDS = 7 * 24 * 3600
DEFAULT_WIDTH = 120


def fg(color: int, text: str) -> str:
    return f"\033[38;5;{color}m{text}{RESET}"


def chip(bg_color: int, fg_color: int, text: str) -> str:
    return f"\033[48;5;{bg_color}m\033[38;5;{fg_color}m{text}{RESET}"


def reverse(text: str) -> str:
    return f"\033[7m{text}\033[27m"


# Palette
DIM_C, LABEL_C, SEP_C = 240, 250, 237
GOOD_C, BAD_C, WARN_C = 77, 196, 220
BADGE_BG, BADGE_FG = 24, 195
WF_C, RUN_C = 111, 220
SEP = f"\033[38;5;{SEP_C}m│{RESET}"

# Model family chips: (bg, fg)
CHIP_GROK = (16, 231)      # black highlight, white text
CHIP_ANTHROPIC = (238, 208)  # gray highlight, orange text
CHIP_OPENAI = (231, 16)    # white highlight, black text
CHIP_OTHER = (231, 16)     # white highlight, black text

MODEL_SHORT = {
    "claude-fable-5": "fable5",
    "grok-4.5": "grok45",
    "gpt-5.6-sol": "sol",
    "openrouter/fusion": "fusion",
}
ANTHROPIC_MARKERS = ("claude", "fable", "opus", "sonnet", "haiku", "mythos")
OPENAI_MARKERS = ("gpt", "sol", "openai", "codex")
PROVIDER_SHORT = {
    "xai_api": "xai",
    "openrouter_api": "or",
    "openrouter_fusion_api": "orf",
    "openai_api": "oai",
    "anthropic_api": "ant",
    "grok_oauth": "grok",
    "claude_oauth": "claude",
}
# Effort / preset level → (superscript glyph, color) — no block glyphs; the
# solid bars read as stray highlights next to chip backgrounds.
EFFORT_STYLE = {
    "none": ("°", DIM_C), "minimal": ("ⁱ", 108), "low": ("ˡ", 77),
    "medium": ("ᵐ", 148), "high": ("ʰ", 220), "xhigh": ("ˣ", 208),
    "max": ("ᴹ", 199), "ultra": ("ᵁ", 201),
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
DEFAULT_TOGGLES = {"fusion_plan": True, "preset": "high", "subagent_review": True}


def visible_length(text: str) -> int:
    return len(ANSI_PATTERN.sub("", text))


def model_chip_colors(model: str) -> tuple[int, int]:
    lowered = model.lower()
    if "grok" in lowered:
        return CHIP_GROK
    if any(marker in lowered for marker in ANTHROPIC_MARKERS):
        return CHIP_ANTHROPIC
    if any(marker in lowered for marker in OPENAI_MARKERS):
        return CHIP_OPENAI
    return CHIP_OTHER


def short_model(model: str) -> str:
    key = model if model in MODEL_SHORT else model.split("/")[-1]
    return MODEL_SHORT.get(key, key.replace("claude-", "").replace("-", ""))


def model_chip(model: str, effort: str | None = None) -> str:
    bg_color, fg_color = model_chip_colors(model)
    name = short_model(model)
    if effort is None:
        return chip(bg_color, fg_color, name)
    # Effort marker sits OUTSIDE the chip so nothing highlighted trails the name.
    sup, sup_color = EFFORT_STYLE.get(effort, ("?", DIM_C))
    return f"{chip(bg_color, fg_color, name)}{fg(sup_color, sup)}"


def short_profile(name: str) -> str:
    known = {
        "xai-claude-oauth": "xai", "all-grok-4.5": "grok",
        "maximum-intelligence": "max", "openrouter-fusion": "orf",
        "subscription-oauth": "sub", "mini-fuse": "mini",
    }
    return known.get(name, name.split("-")[0][:5])


def seat_chip(config: dict, seat_name: str) -> str:
    seat = config.get("seats", {}).get(seat_name, {})
    return model_chip(str(seat.get("model", "?")), str(seat.get("effective_reasoning", "")))


def topology_segment(config: dict) -> str:
    profile = config["profiles"][config["active_profile"]]
    engine = config["engines"][profile["engine"]]
    arrow = fg(DIM_C, "→")
    if engine.get("kind") == "server_managed":
        models = fg(DIM_C, "+").join(model_chip(m) for m in engine.get("analysis_models", []))
        return f"{models}{arrow}{model_chip(str(engine.get('judge_model', '?')))}{fg(DIM_C, '·srv')}"
    counts: dict[str, int] = {}
    for seat_name in engine.get("panel", []):
        label = seat_chip(config, seat_name)
        counts[label] = counts.get(label, 0) + 1
    panel = fg(DIM_C, "+").join(
        label if n == 1 else f"{label}{fg(DIM_C, f'×{n}')}" for label, n in counts.items()
    )
    judge = seat_chip(config, str(engine.get("judge", "")))
    fuser = seat_chip(config, str(engine.get("fuser", "")))
    return f"{panel}{arrow}{judge}{arrow}{fuser}"


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
        return f"{fg(LABEL_C, 'prov')}{fg(GOOD_C, '●')}"
    return " ".join(
        f"{fg(LABEL_C, name)}{fg(GOOD_C if ok else BAD_C, '●' if ok else '○')}"
        for name, ok in states
    )


def mini_fuse_segment(config: dict) -> str:
    seats = config.get("seats", {})
    if not all(name in seats for name in MINI_FUSE_SEATS):
        return fg(DIM_C, "MF·n/a")
    if all(seats[name].get("enabled") for name in MINI_FUSE_SEATS):
        model = str(seats[MINI_FUSE_SEATS[0]].get("model", "?"))
        return f"{fg(LABEL_C, 'MF')}{fg(GOOD_C, '●')}{model_chip(model)}"
    return f"{fg(LABEL_C, 'MF')}{fg(DIM_C, '○off')}"


def toggles(sl_config: dict) -> dict:
    merged = dict(DEFAULT_TOGGLES)
    stored = sl_config.get("toggles")
    if isinstance(stored, dict):
        merged.update(stored)
    return merged


def toggles_segment(sl_config: dict) -> str:
    state = toggles(sl_config)
    plan_on = bool(state.get("fusion_plan"))
    review_on = bool(state.get("subagent_review"))
    preset = str(state.get("preset", "high"))
    sup, sup_color = EFFORT_STYLE.get(preset, ("?", DIM_C))
    plan = f"{fg(LABEL_C, 'plan')}{fg(GOOD_C if plan_on else BAD_C, '●' if plan_on else '○')}"
    pset = f"{fg(LABEL_C, 'pset')}{fg(sup_color, sup)}"
    review = f"{fg(LABEL_C, 'rev')}{fg(GOOD_C if review_on else BAD_C, '●' if review_on else '○')}"
    return f"{plan} {pset} {review}"


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
        parts.append(fg(RUN_C, f"▶{jobs}"))
    if workflow_states:
        states = "+".join(f"{s}×{n}" if n > 1 else s for s, n in sorted(workflow_states.items()))
        parts.append(f"{fg(DIM_C, '◔')}{fg(WF_C, states)}")
    return " ".join(parts) if parts else fg(DIM_C, "· idle")


def braintrust_segment(state_root: Path) -> str:
    label = fg(LABEL_C, "BT")
    if os.environ.get("BRAINTRUST_API_KEY"):
        return f"{label}{fg(GOOD_C, '●')}"
    export_dir = state_root / "braintrust-export"
    if export_dir.is_dir() and any(export_dir.iterdir()):
        return f"{label}{fg(WARN_C, '◐')}"
    return f"{label}{fg(BAD_C, '○')}"


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
            parts.append(fg(BADGE_FG, reverse(f"{sup}{label}")))
        else:
            parts.append(f"{fg(DIM_C, sup)}{fg(LABEL_C, label)}")
    return " ".join(parts)


def keys_segment() -> str:
    return fg(DIM_C, "⌨!fusion plan|pset|rev")


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

        def build(*, keys: bool, slots: bool, collapse_providers: bool, full_profile: bool) -> str:
            profile_name = str(config.get("active_profile", "?"))
            if not full_profile:
                profile_name = short_profile(profile_name)
            segments = [
                chip(BADGE_BG, BADGE_FG, f" ⚛ {profile_name} "),
                topology_segment(config),
                providers_segment(states, collapse_providers),
                mini_fuse_segment(config),
                toggles_segment(sl_config),
                live_segment(state_root),
                braintrust_segment(state_root),
            ]
            if slots:
                segments.append(slots_segment(sl_config, config))
            if keys:
                segments.append(keys_segment())
            return SEP.join(segment for segment in segments if segment)

        budget = width_budget(sl_config)
        # Degrade in priority order until the line fits the width budget.
        for attempt in (
            {"keys": True, "slots": True, "collapse_providers": False, "full_profile": True},
            {"keys": True, "slots": True, "collapse_providers": False, "full_profile": False},
            {"keys": False, "slots": True, "collapse_providers": False, "full_profile": False},
            {"keys": False, "slots": True, "collapse_providers": True, "full_profile": False},
            {"keys": False, "slots": False, "collapse_providers": True, "full_profile": False},
        ):
            line = build(**attempt)
            if visible_length(line) <= budget:
                break
        print(line)
    except Exception as error:  # statusline must never crash the host UI
        print(f"⚛ fusion-drive \033[38;5;240m(statusline error: {type(error).__name__}){RESET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
