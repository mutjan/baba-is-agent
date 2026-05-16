#!/usr/bin/env python3
"""Suggest the next safe action for a Baba benchmark agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_loop_guard import status as loop_guard_status
from parse_baba_level import current_level, read_ini_like
from read_baba_state import current_save_file, load_agent_state


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"


def to_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def completion_status(save_dir: Path, world: str | None, level: str | None) -> int | None:
    if not world or not level:
        return None
    save_file = current_save_file(save_dir)
    return to_int(read_ini_like(save_file).get(world, {}).get(level))


def active_attempt(run_id: str) -> Path | None:
    if not run_id:
        return None
    path = RUNS_ROOT / run_id / "baba_benchmark_active.json"
    return path if path.exists() else None


def read_active_attempt(run_id: str) -> dict[str, Any] | None:
    path = active_attempt(run_id)
    if not path:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def route_hint(config_path: Path | None, save_dir: Path | None) -> dict[str, str]:
    command = [sys.executable, str(ROOT / "scripts" / "baba_map_route.py"), "--dry-run"]
    if config_path:
        command.extend(["--config", str(config_path)])
    if save_dir:
        command.extend(["--save-dir", str(save_dir)])
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    hint: dict[str, str] = {
        "route_command": "python3 scripts/baba_map_route.py --execute",
    }
    if proc.returncode != 0:
        hint["route_error"] = (proc.stderr or proc.stdout).strip()
        return hint
    for line in proc.stdout.splitlines():
        if line.startswith("target="):
            hint["route_target"] = line.removeprefix("target=").strip()
        elif line.startswith("moves="):
            hint["route_moves"] = line.removeprefix("moves=").strip()
        elif line.startswith("skipped_unreachable="):
            hint["route_skipped_unreachable"] = line.removeprefix("skipped_unreachable=").strip()
    return hint


def visible_unit_names(state: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for unit in state.get("units", []):
        if unit.get("dead") or not unit.get("visible", True):
            continue
        name = unit.get("name")
        if name:
            names.add(str(name))
    return names


def classify_context(state: dict[str, Any] | None) -> str:
    if not state:
        return "unknown"
    names = visible_unit_names(state)
    if "cursor" in names and "level" in names:
        return "map"
    return "level"


DIRS: tuple[tuple[str, int, int, str], ...] = (
    ("up", 0, -1, "-y"),
    ("right", 1, 0, "+x"),
    ("down", 0, 1, "+y"),
    ("left", -1, 0, "-x"),
)


def active_props(state: dict[str, Any]) -> dict[str, set[str]]:
    props: dict[str, set[str]] = {}
    for rule in state.get("rules", []):
        target = str(rule.get("target") or "").strip().lower()
        effect = str(rule.get("effect") or "").strip().lower()
        if target and effect:
            props.setdefault(target, set()).add(effect)
    return props


def visible_units(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        unit
        for unit in state.get("units", [])
        if not unit.get("dead") and unit.get("visible", True) and unit.get("x") is not None and unit.get("y") is not None
    ]


def unit_coord(unit: dict[str, Any]) -> tuple[int, int]:
    return int(unit.get("x") or 0), int(unit.get("y") or 0)


def unit_name(unit: dict[str, Any]) -> str:
    return str(unit.get("name") or "").strip().lower()


def is_text(unit: dict[str, Any]) -> bool:
    return bool(unit.get("word")) or unit_name(unit).startswith("text_")


def has_stop(units: list[dict[str, Any]], props: dict[str, set[str]]) -> bool:
    return any("stop" in props.get(unit_name(unit), set()) for unit in units)


def concrete_check_hints(state: dict[str, Any] | None, *, limit: int = 3) -> list[str]:
    if not state:
        return []
    props = active_props(state)
    you_names = {name for name, unit_props in props.items() if "you" in unit_props}
    if not you_names:
        return []
    units = visible_units(state)
    actor = next((unit for unit in units if unit_name(unit) in you_names), None)
    if actor is None:
        return []
    actor_name = unit_name(actor)
    ax, ay = unit_coord(actor)
    meta = state.get("meta", {})
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for unit in units:
        by_cell.setdefault(unit_coord(unit), []).append(unit)

    hints: list[str] = []
    for move, dx, dy, delta in DIRS:
        target = (ax + dx, ay + dy)
        if width and height and not (1 <= target[0] <= width - 2 and 1 <= target[1] <= height - 2):
            continue
        target_units = by_cell.get(target, [])
        target_text = next((unit for unit in target_units if is_text(unit)), None)
        if target_text is not None:
            tail = (target[0] + dx, target[1] + dy)
            if width and height and not (1 <= tail[0] <= width - 2 and 1 <= tail[1] <= height - 2):
                continue
            tail_units = by_cell.get(tail, [])
            if has_stop(tail_units, props) or any(is_text(unit) for unit in tail_units):
                continue
            text_name = unit_name(target_text)
            hints.append(
                "python3 scripts/baba_action_check.py "
                f"{move!r} --expect-moved-delta {text_name}:{delta} --expect-moved-delta {actor_name}:{delta} "
                f"--expect-position-at {actor_name}@{target[0]},{target[1]} "
                f"--expect-position-at {text_name}@{tail[0]},{tail[1]}"
            )
        elif not has_stop(target_units, props):
            hints.append(
                "python3 scripts/baba_action_check.py "
                f"{move!r} --expect-moved-delta {actor_name}:{delta} "
                f"--expect-position-at {actor_name}@{target[0]},{target[1]}"
            )
        if len(hints) >= limit:
            break
    return hints


def recommendation(config_path: Path | None, save_dir_override: Path | None) -> dict[str, Any]:
    config = load_config(config_path)
    save_dir = save_dir_override or config.save_dir
    save_file = current_save_file(save_dir)
    state = load_agent_state(save_file) if save_file.exists() else None
    meta = (state or {}).get("meta", {})
    _slot, previous_world, previous_level = current_level(save_dir)
    runtime_state_available = state is not None
    world = meta.get("world") or previous_world
    level = meta.get("level") or previous_level
    name = meta.get("level_name")
    status = completion_status(save_dir, world, level)
    context = classify_context(state)
    active_path = active_attempt(config.current_run_id)
    active = read_active_attempt(config.current_run_id)
    active_world = active.get("world") if active else None
    active_level = active.get("level") if active else None
    active_status = completion_status(save_dir, active_world, active_level) if active_world and active_level else None
    guard = loop_guard_status(config.config_path)

    payload: dict[str, Any] = {
        "context": context,
        "world": world,
        "level": level,
        "name": name,
        "runtime_state_available": runtime_state_available,
        "completion_status": status,
        "current_run_id": config.current_run_id or "",
        "active_attempt": str(active_path) if active_path else "",
        "active_level": f"{active_world}/{active_level}" if active_world and active_level else "",
        "active_completion_status": active_status,
        "loop_guard_state": guard["state"],
        "loop_guard_required_next": guard["required_next"],
        "loop_guard_path": guard["path"],
    }

    if not runtime_state_available:
        payload.update(
            {
                "next_mcp_tool": "app_status",
                "next_script": "python3 scripts/baba_app_status.py",
                "reason": "No fresh agent_state runtime snapshot is available. Restart Baba Is You or trigger a level reload, then inspect state before solving.",
            }
        )
    elif context == "map":
        payload.update(
            {
                "next_mcp_tool": "navigate_next",
                "next_script": "python3 scripts/baba_map_route.py --execute",
                "reason": "Current state is a map/sub-map controlled by cursor is select; do not solve or score it as a normal level. navigate_next is MCP-only; do not invent scripts/baba_navigate_next.py.",
            }
        )
        payload.update(route_hint(config_path, save_dir))
    elif status == 3:
        payload.update(
            {
                "next_mcp_tool": "return_to_map",
                "next_script": "python3 scripts/baba_return_to_map.py",
                "reason": "Current level is already complete; return to the map before choosing the next target.",
            }
        )
    elif active and active_status == 3:
        payload.update(
            {
                "next_mcp_tool": "record_pass",
                "next_script": "python3 scripts/baba_benchmark.py --record-pass --moves '<verified full route>' --note '<short summary>'",
                "reason": "The active benchmark level is complete; record the pass before navigating further.",
            }
        )
    elif active and (active_world != world or active_level != level):
        payload.update(
            {
                "next_mcp_tool": "start_benchmark",
                "next_script": "python3 start_benchmark.py --force-new",
                "reason": "Active benchmark attempt does not match the live level. Do not solve or record until the active attempt is reset.",
            }
        )
    elif active:
        hints = concrete_check_hints(state)
        payload.update(
            {
                "next_mcp_tool": "check_moves",
                "next_script": "python3 scripts/baba_action_check.py '<short move segment>' --expect-moved-delta '<unit-or-text>:<dir>'",
                "reason": "A benchmark attempt is active for this run; name one expected observable delta and let the script validate it.",
                "suggested_check_1": hints[0] if len(hints) > 0 else "",
                "suggested_check_2": hints[1] if len(hints) > 1 else "",
                "suggested_check_3": hints[2] if len(hints) > 2 else "",
            }
        )
    elif config.current_run_id:
        payload.update(
            {
                "next_mcp_tool": "start_benchmark",
                "next_script": "python3 start_benchmark.py",
                "reason": "Current state looks like a normal unsolved level and no active attempt is recorded.",
            }
        )
    else:
        payload.update(
            {
                "next_mcp_tool": "set_current_run_id",
                "next_script": "python3 scripts/baba_config.py --set-current-run-id 001_agent_model",
                "reason": "current_run_id is unset; set the run id before starting benchmark records.",
            }
        )
    return payload


def print_payload(payload: dict[str, Any]) -> None:
    for key in (
        "context",
        "world",
        "level",
        "name",
        "completion_status",
        "current_run_id",
        "active_attempt",
        "active_level",
        "active_completion_status",
        "loop_guard_state",
        "loop_guard_required_next",
        "loop_guard_path",
        "next_mcp_tool",
        "next_script",
        "suggested_check_1",
        "suggested_check_2",
        "suggested_check_3",
        "route_command",
        "route_target",
        "route_moves",
        "route_skipped_unreachable",
        "route_error",
        "reason",
    ):
        print(f"{key}={payload.get(key) or ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()

    payload = recommendation(args.config, args.save_dir)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_payload(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
