#!/usr/bin/env python3
"""Shared configuration for local Baba Is You tooling."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "baba_config.json"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "baba_config.example.json"

DEFAULT_CONFIG: dict[str, str] = {
    "game_root": (
        "~/Library/Application Support/Steam/steamapps/common/"
        "Baba Is You/Baba Is You.app/Contents/Resources/Data/Worlds"
    ),
    "save_dir": "~/Library/Application Support/Baba_Is_You",
    "app_name": "Baba Is You",
}


@dataclass(frozen=True)
class BabaConfig:
    game_root: Path
    save_dir: Path
    app_name: str
    config_path: Path


def expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def write_default_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if EXAMPLE_CONFIG_PATH.exists():
        shutil.copyfile(EXAMPLE_CONFIG_PATH, path)
    else:
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")


def load_config(path: Path | None = None) -> BabaConfig:
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
    merged = {**DEFAULT_CONFIG, **raw}
    return BabaConfig(
        game_root=expand_path(str(merged["game_root"])),
        save_dir=expand_path(str(merged["save_dir"])),
        app_name=str(merged["app_name"]),
        config_path=config_path,
    )
