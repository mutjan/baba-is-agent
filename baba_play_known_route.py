#!/usr/bin/env python3
"""Print or execute known Baba Is You level routes.

These routes assume the game is already inside the named level and at the
level's initial state. Use baba_map_route.py to enter a level from the map.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from parse_baba_level import DEFAULT_SAVE_DIR, current_level


ROUTES = {
    "0level": {
        "name": "baba is you",
        "moves": "right*8",
        "note": "Push the center rock column right until Baba reaches the flag.",
    },
    "1level": {
        "name": "where do i go?",
        "moves": "left*5,down,left,up*5,right*7,up*3,left*5,up,left,down*2,right,down,right",
        "note": (
            "Break WALL IS STOP, move the lower IS to FLAG IS, move WIN into "
            "place, then touch the flag."
        ),
    },
    "3level": {
        "name": "out of reach",
        "moves": "down*3,right*4,up,left*2,up,left,down*7,right*2,up*3,right,down*3,left*3,up*8,right*2",
        "note": (
            "Sink one rock to open the water exit, move ROCK onto FLAG IS WIN "
            "to make ROCK IS WIN and break ROCK IS PUSH, then step onto the "
            "remaining rock."
        ),
    },
}


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR)
    parser.add_argument("--level", help="Level id to use. Defaults to save Previous.")
    parser.add_argument("--list", action="store_true", help="List known routes")
    parser.add_argument("--execute", action="store_true", help="Send the route with baba_send_keys.py")
    parser.add_argument("--delay", type=float, default=0.12)
    args = parser.parse_args()

    if args.list:
        for level_id, route in sorted(ROUTES.items()):
            moves = route["moves"]
            print(f"{level_id}: {route['name']} -> {moves}")
        return 0

    if args.level:
        level = args.level
        slot = None
        world = None
    else:
        slot, world, level = current_level(args.save_dir)

    route = ROUTES.get(level)
    if not route:
        known = ", ".join(sorted(ROUTES))
        raise SystemExit(f"No known route for {level}. Known routes: {known}")

    moves = route["moves"]
    expanded = expand_moves(moves)
    if slot is not None and world is not None:
        print(f"slot={slot} world={world} level={level} name={route['name']}")
    else:
        print(f"level={level} name={route['name']}")
    print(f"moves={moves}")
    print(f"expanded_steps={len(expanded)}")
    print(f"note={route['note']}")
    print(f"command=python3 baba_send_keys.py '{moves}' --delay {args.delay}")

    if args.execute:
        subprocess.run(
            [sys.executable, "baba_send_keys.py", moves, "--delay", str(args.delay)],
            check=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
