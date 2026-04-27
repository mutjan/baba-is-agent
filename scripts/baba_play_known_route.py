#!/usr/bin/env python3
"""Print or execute known Baba Is You level routes from JSON data.

Known routes assume the game is already inside the named level and at the
level's initial state. Use baba_map_route.py to enter a level from the map.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from baba_config import load_config
from parse_baba_level import current_level


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
RUNS_ROOT = ROOT / "runs"


def default_routes_path(config: Any) -> Path:
    if not config.current_run_id:
        raise SystemExit(
            "No current_run_id configured. Run "
            "`python3 scripts/baba_config.py --set-current-run-id 001_agent_model` "
            "or pass --routes."
        )
    return RUNS_ROOT / config.current_run_id / "baba_known_routes.json"


def load_routes(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Known route file does not exist: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != "codex-baba-known-routes-v1" or not isinstance(doc.get("routes"), dict):
        raise SystemExit(f"Unsupported known route file: {path}")
    return doc


def save_routes(doc: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def route_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return doc["routes"]


def expand_moves(raw: str) -> list[str]:
    moves: list[str] = []
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        if "*" in token:
            name, count = token.split("*", 1)
            moves.extend([name] * int(count))
        else:
            moves.append(token)
    return moves


def route_hold_ms(route: dict[str, Any], override: int | None) -> int:
    if override is not None:
        return override
    return int(route.get("hold_ms", 90))


def route_delay(config_delay: float, override: float | None) -> float:
    return override if override is not None else config_delay


def known_route_command(moves: str, *, delay: float, hold_ms: int) -> list[str]:
    return [
        sys.executable,
        str(SCRIPTS_DIR / "baba_send_keys.py"),
        moves,
        "--delay",
        str(delay),
        "--hold-ms",
        str(hold_ms),
    ]


def known_route_display_command(moves: str, *, delay: float, hold_ms: int) -> list[str]:
    return [
        "python3",
        "scripts/baba_send_keys.py",
        moves,
        "--delay",
        str(delay),
        "--hold-ms",
        str(hold_ms),
    ]


def print_route(level: str, route: dict[str, Any], *, delay: float, hold_ms: int) -> None:
    moves = str(route["moves"])
    expanded = expand_moves(moves)
    print(f"level={level} name={route['name']}")
    print(f"moves={moves}")
    print(f"expanded_steps={len(expanded)}")
    print(f"hold_ms={hold_ms}")
    print(f"delay={delay}")
    if route.get("last_score_steps") is not None:
        print(f"last_score_steps={route['last_score_steps']}")
    if route.get("best_score_steps") is not None:
        print(f"best_score_steps={route['best_score_steps']}")
    if route.get("last_score_source") is not None:
        print(f"last_score_source={route['last_score_source']}")
    if route.get("last_elapsed_seconds") is not None:
        print(f"last_elapsed_seconds={route['last_elapsed_seconds']}")
    if route.get("best_elapsed_seconds") is not None:
        print(f"best_elapsed_seconds={route['best_elapsed_seconds']}")
    print(f"note={route['note']}")
    display = shlex.join(known_route_display_command(moves, delay=delay, hold_ms=hold_ms))
    print(f"command={display}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--routes", type=Path, help="Known routes JSON path")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--level", help="Level id to use. Defaults to save Previous.")
    parser.add_argument("--list", action="store_true", help="List known routes")
    parser.add_argument("--execute", action="store_true", help="Send the route with baba_send_keys.py")
    parser.add_argument("--delay", type=float, help="Override configured input_delay")
    parser.add_argument("--hold-ms", type=int, help="Override route/default key hold")
    args = parser.parse_args()

    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    routes_path = args.routes or default_routes_path(config)
    routes_doc = load_routes(routes_path)
    routes = route_map(routes_doc)

    if args.list:
        for level_id, route in sorted(routes.items()):
            score = ""
            if route.get("best_score_steps") is not None:
                score = f" best_score={route['best_score_steps']} steps"
            elif route.get("best_elapsed_seconds") is not None:
                score = f" legacy_best_time={route['best_elapsed_seconds']}s"
            print(f"{level_id}: {route['name']} -> {route['moves']}{score}")
        return 0

    if args.level:
        level = args.level
    else:
        slot, world, level = current_level(save_dir)
        print(f"slot={slot} world={world}")

    route = routes.get(level)
    if not route:
        known = ", ".join(sorted(routes))
        raise SystemExit(f"No known route for {level}. Known routes: {known}")

    delay = route_delay(config.input_delay, args.delay)
    hold_ms = route_hold_ms(route, args.hold_ms)
    print_route(level, route, delay=delay, hold_ms=hold_ms)

    if args.execute:
        subprocess.run(known_route_command(str(route["moves"]), delay=delay, hold_ms=hold_ms), check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
