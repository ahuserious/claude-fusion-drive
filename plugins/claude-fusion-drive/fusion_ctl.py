#!/usr/bin/env python3
"""Control-plane helper for the Fusion Drive statusline.

Subcommands:
  profile <name-or-slot>   Switch active_profile (validated propose+approve).
  mini-fuse on|off|status  Toggle the light-duty mini-fuse seats for subagent
                           and adversarial-review summarization.
  slots [set <n> <profile>]  Show or edit the statusline hotkey slots.
  status                   One-line summary (same data the statusline shows).

Profile and mini-fuse changes go through the plugin's own propose/approve
configuration flow, so they are schema-validated, secret-checked, and locked.
Run this yourself (or via a keybinding/`!` shell escape) — it is a deliberate
user action, which is why approval is auto-confirmed here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PLUGIN_ROOT))

from claude_fusion_drive.config import (  # noqa: E402
    approve_config,
    load_config,
    propose_config,
    runtime_dir,
)

MINI_FUSE_SEATS = ("grok45-mini-panel", "grok45-mini-judge", "grok45-mini-fuser")
DEFAULT_SLOTS = {
    "1": "xai-claude-oauth",
    "2": "all-grok-4.5",
    "3": "maximum-intelligence",
    "4": "mini-fuse",
}


def slots_path() -> Path:
    return runtime_dir() / "statusline.json"


def load_slots() -> dict[str, str]:
    try:
        data = json.loads(slots_path().read_text(encoding="utf-8"))
        slots = data.get("slots", {})
        if isinstance(slots, dict) and slots:
            return {str(k): str(v) for k, v in slots.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return dict(DEFAULT_SLOTS)


def save_slots(slots: dict[str, str]) -> None:
    slots_path().write_text(
        json.dumps({"slots": slots}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def apply_change(changes: dict, rationale: str) -> None:
    proposal = propose_config(changes, rationale=rationale)
    approve_config(proposal["proposal_hash"], confirmed=True)


def mini_fuse_enabled(config: dict) -> bool:
    seats = config.get("seats", {})
    return all(seats.get(name, {}).get("enabled") for name in MINI_FUSE_SEATS)


def cmd_profile(target: str) -> int:
    config = load_config()
    slots = load_slots()
    profile = slots.get(target, target)
    if profile not in config.get("profiles", {}):
        known = ", ".join(sorted(config.get("profiles", {})))
        print(f"Unknown profile or slot {target!r}. Profiles: {known}")
        return 1
    if config.get("active_profile") == profile:
        print(f"active_profile already {profile}")
        return 0
    apply_change({"active_profile": profile}, f"fusion_ctl profile switch to {profile}")
    print(f"active_profile → {profile}")
    return 0


def cmd_mini_fuse(action: str) -> int:
    config = load_config()
    if action == "status":
        print("mini-fuse:", "on" if mini_fuse_enabled(config) else "off")
        return 0
    if action not in {"on", "off"}:
        print("usage: fusion_ctl.py mini-fuse on|off|status")
        return 1
    desired = action == "on"
    if mini_fuse_enabled(config) == desired:
        print(f"mini-fuse already {action}")
        return 0
    changes = {"seats": {name: {"enabled": desired} for name in MINI_FUSE_SEATS}}
    apply_change(changes, f"fusion_ctl mini-fuse {action}")
    print(f"mini-fuse → {action}")
    return 0


def cmd_slots(args: list[str]) -> int:
    slots = load_slots()
    if args[:1] == ["set"] and len(args) == 3:
        slot, profile = args[1], args[2]
        config = load_config()
        if profile not in config.get("profiles", {}):
            print(f"Unknown profile {profile!r}")
            return 1
        slots[slot] = profile
        save_slots(slots)
    for slot in sorted(slots):
        print(f"  {slot}: {slots[slot]}")
    print(f"(edit {slots_path()} or `fusion_ctl.py slots set <n> <profile>`)")
    return 0


def cmd_status() -> int:
    config = load_config()
    engine = config["engines"][config["profiles"][config["active_profile"]]["engine"]]
    print(f"profile: {config['active_profile']}")
    print(f"panel: {engine.get('panel')}  judge: {engine.get('judge')}  fuser: {engine.get('fuser')}")
    print("mini-fuse:", "on" if mini_fuse_enabled(config) else "off")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    command, rest = args[0], args[1:]
    if command == "profile" and len(rest) == 1:
        return cmd_profile(rest[0])
    if command == "mini-fuse" and len(rest) == 1:
        return cmd_mini_fuse(rest[0])
    if command == "slots":
        return cmd_slots(rest)
    if command == "status":
        return cmd_status()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
