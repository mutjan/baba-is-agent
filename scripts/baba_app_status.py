#!/usr/bin/env python3
"""Report whether Baba Is You appears to be running and readable.

On macOS the app bundle is named "Baba Is You", but the focused process often
appears as the engine process "Chowdren". This script makes that distinction
explicit so agents do not use the bundle name as their only running check.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_send_keys import frontmost_process
from read_baba_state import current_save_file, load_save_state


KNOWN_APP_PROCESS_NAMES = ("Baba Is You",)
KNOWN_ENGINE_PROCESS_NAMES = ("Chowdren",)


def run_osascript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def system_process_names() -> list[str]:
    script = """
set oldDelimiters to AppleScript's text item delimiters
set AppleScript's text item delimiters to linefeed
tell application "System Events"
    set processNames to name of every process
end tell
set processText to processNames as text
set AppleScript's text item delimiters to oldDelimiters
return processText
"""
    output = run_osascript(script)
    return [line.strip() for line in output.splitlines() if line.strip()]


def detect_running_process(processes: list[str], app_name: str) -> tuple[bool, str, list[str]]:
    exact_candidates = [
        app_name,
        *KNOWN_APP_PROCESS_NAMES,
        *KNOWN_ENGINE_PROCESS_NAMES,
    ]
    ordered_unique: list[str] = []
    for name in exact_candidates:
        if name and name not in ordered_unique:
            ordered_unique.append(name)

    matches = [name for name in ordered_unique if name in processes]
    if matches:
        return True, matches[0], matches

    lower_processes = {name.lower(): name for name in processes}
    fuzzy_matches = []
    for candidate in ordered_unique:
        matched = lower_processes.get(candidate.lower())
        if matched is not None:
            fuzzy_matches.append(matched)
    if fuzzy_matches:
        return True, fuzzy_matches[0], fuzzy_matches

    return False, "", []


def read_save_status(save_dir: Path) -> dict[str, Any]:
    status: dict[str, Any] = {
        "save_state_available": False,
        "save_state_error": "",
    }
    try:
        save_file = current_save_file(save_dir)
        status["save_state_path"] = str(save_file)
        status["save_state_file_exists"] = save_file.exists()
        if not save_file.exists():
            return status
        state = load_save_state(save_file)
        if state is None:
            status["save_state_error"] = "codex_state section not found"
            return status
        meta = state.get("meta", {})
        status.update(
            {
                "save_state_available": True,
                "state_world": meta.get("world") or "",
                "state_level": meta.get("level") or "",
                "state_level_name": meta.get("level_name") or "",
                "state_turn": meta.get("turn"),
                "state_source": meta.get("source") or "",
                "state_last_command": meta.get("last_command") or "",
            }
        )
    except SystemExit as exc:
        status["save_state_error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - status scripts should report, not crash.
        status["save_state_error"] = f"{type(exc).__name__}: {exc}"
    return status


def build_status(config_path: Path | None, save_dir_override: Path | None) -> dict[str, Any]:
    config = load_config(config_path)
    save_dir = save_dir_override.resolve() if save_dir_override is not None else config.save_dir
    status: dict[str, Any] = {
        "config_path": str(config.config_path),
        "configured_app_name": config.app_name,
        "known_engine_process_names": list(KNOWN_ENGINE_PROCESS_NAMES),
        "process_probe_ok": False,
        "process_probe_error": "",
        "running_process_detected": False,
        "running_process_name": "",
        "matching_process_names": [],
        "frontmost_process": "",
        "frontmost_probe_error": "",
        "frontmost_is_game": False,
        "save_dir": str(save_dir),
        "game_files_found": config.game_files_found,
        "state_exporter_installed": config.state_exporter_installed,
        "note": (
            'On macOS, Baba Is You often runs as "Chowdren". Do not use '
            '`processes contains "Baba Is You"` as the only running check.'
        ),
    }

    processes: list[str] = []
    try:
        processes = system_process_names()
        running, process_name, matches = detect_running_process(processes, config.app_name)
        status.update(
            {
                "process_probe_ok": True,
                "running_process_detected": running,
                "running_process_name": process_name,
                "matching_process_names": matches,
            }
        )
    except subprocess.CalledProcessError as exc:
        status["process_probe_error"] = (exc.stderr or exc.stdout or str(exc)).strip()
    except Exception as exc:  # noqa: BLE001 - status scripts should report, not crash.
        status["process_probe_error"] = f"{type(exc).__name__}: {exc}"

    try:
        frontmost = frontmost_process()
        known_names = {config.app_name, *KNOWN_APP_PROCESS_NAMES, *KNOWN_ENGINE_PROCESS_NAMES}
        status["frontmost_process"] = frontmost
        status["frontmost_is_game"] = bool(frontmost and frontmost in known_names)
    except subprocess.CalledProcessError as exc:
        status["frontmost_probe_error"] = (exc.stderr or exc.stdout or str(exc)).strip()
    except Exception as exc:  # noqa: BLE001 - status scripts should report, not crash.
        status["frontmost_probe_error"] = f"{type(exc).__name__}: {exc}"

    status.update(read_save_status(save_dir))
    return status


def print_key_values(status: dict[str, Any]) -> None:
    ordered_keys = [
        "config_path",
        "configured_app_name",
        "known_engine_process_names",
        "process_probe_ok",
        "process_probe_error",
        "running_process_detected",
        "running_process_name",
        "matching_process_names",
        "frontmost_process",
        "frontmost_is_game",
        "frontmost_probe_error",
        "save_dir",
        "game_files_found",
        "state_exporter_installed",
        "save_state_available",
        "save_state_path",
        "save_state_file_exists",
        "save_state_error",
        "state_world",
        "state_level",
        "state_level_name",
        "state_turn",
        "state_source",
        "state_last_command",
        "note",
    ]
    for key in ordered_keys:
        if key in status:
            value = status[key]
            if isinstance(value, list):
                value = ",".join(str(item) for item in value)
            print(f"{key}={value}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Optional save directory override")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--require-running",
        action="store_true",
        help="Exit nonzero if no known Baba process is detected",
    )
    args = parser.parse_args()

    status = build_status(args.config, args.save_dir)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print_key_values(status)

    if args.require_running and not status.get("running_process_detected"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
