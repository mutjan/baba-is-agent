#!/usr/bin/env python3
"""Read the minimal Codex Baba Is You Lua probe from world_data.txt."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from baba_config import load_config
from parse_baba_level import current_level, read_ini_like


PROBE_SCHEMA = "codex-baba-state-probe-v1"


def probe_path(worlds_dir: Path, world: str) -> Path:
    return worlds_dir / world / "world_data.txt"


def read_probe(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    data = read_ini_like(path).get("codex_probe")
    if not data or data.get("schema") != PROBE_SCHEMA:
        return None
    return data


def load_probe(path: Path, *, wait: bool, timeout: float, since_mtime: float | None) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        if path.exists():
            stat = path.stat()
            if since_mtime is None or stat.st_mtime > since_mtime:
                probe = read_probe(path)
                if probe is not None:
                    return {"path": str(path), "mtime": stat.st_mtime, "probe": probe}

        if not wait or time.monotonic() >= deadline:
            raise SystemExit(f"Probe not found in {path}")

        time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--world", help="World folder. Defaults to current save world.")
    parser.add_argument("--wait", action="store_true", help="Wait until probe data exists or changes")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait with --wait")
    parser.add_argument(
        "--since-mtime",
        type=float,
        help="With --wait, require world_data.txt mtime to become greater than this value",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    worlds_dir = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir
    _slot, current_world, _level = current_level(save_dir)
    world = args.world or current_world
    path = probe_path(worlds_dir, world)
    state = load_probe(path, wait=args.wait, timeout=args.timeout, since_mtime=args.since_mtime)

    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    probe = state["probe"]
    print(f"probe_path={state['path']}")
    print(f"schema={probe.get('schema')}")
    print(f"source={probe.get('source')}")
    print(f"sequence={probe.get('sequence')}")
    print(f"world={probe.get('world') or world}")
    print(f"level={probe.get('level') or '<unknown>'}")
    print(f"loaded={probe.get('loaded')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
