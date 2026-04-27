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
from parse_baba_level import read_ini_like
from read_baba_state import current_save_file, load_save_state


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


def recommendation(config_path: Path | None, save_dir_override: Path | None) -> dict[str, Any]:
    config = load_config(config_path)
    save_dir = save_dir_override or config.save_dir
    save_file = current_save_file(save_dir)
    state = load_save_state(save_file) if save_file.exists() else None
    meta = (state or {}).get("meta", {})
    world = meta.get("world")
    level = meta.get("level")
    name = meta.get("level_name")
    status = completion_status(save_dir, world, level)
    context = classify_context(state)
    active_path = active_attempt(config.current_run_id)
    active = read_active_attempt(config.current_run_id)
    active_world = active.get("world") if active else None
    active_level = active.get("level") if active else None
    active_status = completion_status(save_dir, active_world, active_level) if active_world and active_level else None

    payload: dict[str, Any] = {
        "context": context,
        "world": world,
        "level": level,
        "name": name,
        "completion_status": status,
        "current_run_id": config.current_run_id or "",
        "active_attempt": str(active_path) if active_path else "",
        "active_level": f"{active_world}/{active_level}" if active_world and active_level else "",
        "active_completion_status": active_status,
    }

    if context == "map":
        payload.update(
            {
                "next_mcp_tool": "navigate_next",
                "next_script": "python3 scripts/baba_map_route.py --execute",
                "reason": "Current state is a map/sub-map controlled by cursor is select; do not solve or score it as a normal level.",
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
        payload.update(
            {
                "next_mcp_tool": "check_moves",
                "next_script": "python3 scripts/baba_action_check.py '<short move segment>' --expect-moved '<unit-or-text>'",
                "reason": "A benchmark attempt is active for this run; name one expected observable delta and let the script validate it.",
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
        "next_mcp_tool",
        "next_script",
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
