#!/usr/bin/env python3
"""Shared configuration for local Baba Is You tooling."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "baba_config.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "baba_config.example.json"
STATE_EXPORTER_TARGET_NAME = "codex_state_export.lua"
STATE_EXPORTER_MARKER = "codex-baba-state-export-v1"

DEFAULT_CONFIG: dict[str, Any] = {
    "game_root": (
        "~/Library/Application Support/Steam/steamapps/common/"
        "Baba Is You/Baba Is You.app/Contents/Resources/Data/Worlds"
    ),
    "save_dir": "~/Library/Application Support/Baba_Is_You",
    "app_name": "Baba Is You",
    "input_delay": 0.02,
    "game_files_found": False,
    "state_exporter_installed": False,
}


@dataclass(frozen=True)
class BabaConfig:
    game_root: Path
    save_dir: Path
    app_name: str
    input_delay: float
    game_files_found: bool
    state_exporter_installed: bool
    config_path: Path


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def detect_game_files(game_root: Path) -> bool:
    data_dir = game_root.parent
    return game_root.is_dir() and (data_dir / "values.lua").is_file()


def has_marker(path: Path, marker: str) -> bool:
    if not path.is_file():
        return False
    try:
        return marker in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def detect_state_exporter_installed(game_root: Path) -> bool:
    data_dir = game_root.parent
    candidates = [data_dir / "Lua" / STATE_EXPORTER_TARGET_NAME]
    if game_root.is_dir():
        candidates.extend(game_root.glob(f"*/Lua/{STATE_EXPORTER_TARGET_NAME}"))
    return any(has_marker(path, STATE_EXPORTER_MARKER) for path in candidates)


def add_detected_status(raw: dict[str, Any]) -> dict[str, Any]:
    merged = {**DEFAULT_CONFIG, **raw}
    game_root = expand_path(str(merged["game_root"]))
    game_files_found = detect_game_files(game_root)
    state_exporter_installed = (
        detect_state_exporter_installed(game_root) if game_files_found else False
    )
    return {
        **raw,
        "game_files_found": game_files_found,
        "state_exporter_installed": state_exporter_installed,
    }


def refresh_config_status(path: Path, raw: dict[str, Any] | None = None) -> dict[str, Any]:
    config_path = expand_path(str(path))
    current = raw if raw is not None else json.loads(config_path.read_text(encoding="utf-8"))
    updated = add_detected_status(current)
    if updated != current:
        config_path.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
    return updated


def write_default_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if EXAMPLE_CONFIG_PATH.exists():
        raw = json.loads(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        raw = DEFAULT_CONFIG
    detected = add_detected_status(raw)
    path.write_text(json.dumps(detected, indent=2) + "\n", encoding="utf-8")


def load_config(path: Path | None = None, *, refresh_status: bool = True) -> BabaConfig:
    raw_path = path if path is not None else Path(os.environ.get("BABA_CONFIG", str(DEFAULT_CONFIG_PATH)))
    config_path = expand_path(str(raw_path))
    if not config_path.exists():
        write_default_config(config_path)
        raise SystemExit(
            "Created config file at "
            f"{config_path}.\n"
            "Review the paths, then rerun the command. Set BABA_CONFIG to use "
            "a different config file."
        )

    raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    if refresh_status:
        raw = refresh_config_status(config_path, raw)
    merged = {**DEFAULT_CONFIG, **raw}
    input_delay = float(merged["input_delay"])
    if input_delay < 0:
        raise SystemExit("input_delay must be non-negative")
    return BabaConfig(
        game_root=expand_path(str(merged["game_root"])),
        save_dir=expand_path(str(merged["save_dir"])),
        app_name=str(merged["app_name"]),
        input_delay=input_delay,
        game_files_found=bool_value(merged["game_files_found"]),
        state_exporter_installed=bool_value(merged["state_exporter_installed"]),
        config_path=config_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    print(f"config_path={config.config_path}")
    print(f"game_root={config.game_root}")
    print(f"save_dir={config.save_dir}")
    print(f"game_files_found={config.game_files_found}")
    print(f"state_exporter_installed={config.state_exporter_installed}")
    print(f"input_delay={config.input_delay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
