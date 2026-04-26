#!/usr/bin/env python3
"""Search constrained Baba Is You routes.

The solver is intentionally small and conservative. It currently contains the
optimized strategy for baba/6level, where the solved target pattern is known.
It searches macro pushes instead of raw movement: each edge walks Baba to a
valid push position, pushes one text chain by one tile, and keeps BABA IS YOU
active after every push.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import subprocess
import sys
from collections import deque
from pathlib import Path

from baba_config import load_config
from parse_baba_level import (
    active_rules,
    collect_positions,
    current_level,
    parse_currobjlist,
    parse_global_tiles,
    parse_level_binary,
    read_ini_like,
)


ROOT = Path(__file__).resolve().parent
LABELS = ("B", "I", "Y", "F", "W")
DIRS = (
    ("up", (0, -1)),
    ("down", (0, 1)),
    ("left", (-1, 0)),
    ("right", (1, 0)),
)


def one_coord(positions: dict[str, list[tuple[int, int, int]]], name: str) -> tuple[int, int]:
    coords = positions.get(name, [])
    if len(coords) != 1:
        raise SystemExit(f"Expected exactly one {name}, found {len(coords)}")
    x, y, _layer = coords[0]
    return (x, y)


def text_coord(positions: dict[str, list[tuple[int, int, int]]], word: str) -> tuple[int, int]:
    return one_coord(positions, f"text_{word}")


def load_level(
    game_root: Path,
    save_dir: Path,
    world_arg: str | None,
    level_arg: str | None,
) -> tuple[str, str, str, int, int, dict[str, list[tuple[int, int, int]]], list[tuple[str, tuple[int, int], str, str, str]]]:
    if world_arg and level_arg:
        world = world_arg
        level = level_arg
    else:
        _slot, world, level = current_level(save_dir)

    level_dir = game_root / world
    ld_path = level_dir / f"{level}.ld"
    l_path = level_dir / f"{level}.l"
    sections = read_ini_like(ld_path)
    name = sections.get("general", {}).get("name", "<unknown>")
    level_data = ld_path.read_text(errors="replace")
    code_to_name, _name_to_symbol = parse_global_tiles(game_root.parent / "values.lua")
    level_code_to_name, _level_name_to_symbol = parse_currobjlist(level_data)
    code_to_name.update(level_code_to_name)
    width, height, layers = parse_level_binary(l_path)
    positions = collect_positions(width, height, layers, code_to_name)
    rules = active_rules(width, height, layers, code_to_name)
    return world, level, name, width, height, positions, rules


def compress_moves(route: list[str]) -> str:
    parts: list[list[str | int]] = []
    for move in route:
        if parts and parts[-1][0] == move:
            parts[-1][1] = int(parts[-1][1]) + 1
        else:
            parts.append([move, 1])
    return ",".join(f"{move}*{count}" if count != 1 else str(move) for move, count in parts)


def has_rule(boxes: tuple[tuple[int, int], ...], subj: str, prop: str) -> bool:
    pos = dict(zip(LABELS, boxes))
    first = pos[subj]
    middle = pos["I"]
    last = pos[prop]
    return (
        first[1] == middle[1] == last[1]
        and first[0] + 1 == middle[0]
        and middle[0] + 1 == last[0]
    ) or (
        first[0] == middle[0] == last[0]
        and first[1] + 1 == middle[1]
        and middle[1] + 1 == last[1]
    )


def baba_you(boxes: tuple[tuple[int, int], ...]) -> bool:
    return has_rule(boxes, "B", "Y")


def flag_win(boxes: tuple[tuple[int, int], ...]) -> bool:
    return has_rule(boxes, "F", "W")


def recover_path(
    prev: dict[tuple[int, int], tuple[tuple[int, int] | None, str | None]],
    dest: tuple[int, int],
) -> list[str] | None:
    if dest not in prev:
        return None
    route: list[str] = []
    cur = dest
    while prev[cur][0] is not None:
        parent, move = prev[cur]
        assert parent is not None and move is not None
        route.append(move)
        cur = parent
    return route[::-1]


def reachable(
    actor: tuple[int, int],
    boxes: tuple[tuple[int, int], ...],
    bounds: tuple[int, int],
    blockers: set[tuple[int, int]],
) -> dict[tuple[int, int], tuple[tuple[int, int] | None, str | None]]:
    width, height = bounds
    occupied = set(boxes) | blockers
    queue = deque([actor])
    prev: dict[tuple[int, int], tuple[tuple[int, int] | None, str | None]] = {actor: (None, None)}
    while queue:
        coord = queue.popleft()
        for name, (dx, dy) in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if (
                nxt in prev
                or not (1 <= nxt[0] <= width - 2 and 1 <= nxt[1] <= height - 2)
                or nxt in occupied
            ):
                continue
            prev[nxt] = (coord, name)
            queue.append(nxt)
    return prev


def solve_baba_6level(
    width: int,
    height: int,
    positions: dict[str, list[tuple[int, int, int]]],
    *,
    max_states: int,
    heuristic_weight: int,
) -> tuple[list[str], int, tuple[tuple[int, int], tuple[tuple[int, int], ...]]]:
    start_actor = one_coord(positions, "baba")
    flag = one_coord(positions, "flag")
    grass = {(x, y) for x, y, _layer in positions.get("grass", [])}

    # Only the right-side GRASS IS STOP rule is fixed for this level strategy.
    fixed_text = {
        text_coord(positions, "grass"),
        positions["text_is"][1][:2] if len(positions.get("text_is", [])) > 1 else text_coord(positions, "is"),
        text_coord(positions, "stop"),
    }
    blockers = grass | fixed_text

    start_boxes = (
        text_coord(positions, "baba"),
        positions["text_is"][0][:2],
        text_coord(positions, "you"),
        text_coord(positions, "flag"),
        text_coord(positions, "win"),
    )
    target_boxes = ((14, 5), (15, 5), (16, 5), (15, 4), (15, 6))

    def heuristic(boxes: tuple[tuple[int, int], ...]) -> int:
        return sum(
            abs(boxes[index][0] - target_boxes[index][0])
            + abs(boxes[index][1] - target_boxes[index][1])
            for index in range(len(boxes))
        )

    start = (start_actor, start_boxes)
    queue: list[tuple[int, int, int, tuple[tuple[int, int], tuple[tuple[int, int], ...]]]] = []
    counter = itertools.count()
    heapq.heappush(queue, (heuristic_weight * heuristic(start_boxes), 0, next(counter), start))
    parent: dict[
        tuple[tuple[int, int], tuple[tuple[int, int], ...]],
        tuple[tuple[tuple[int, int], tuple[tuple[int, int], ...]] | None, list[str] | None],
    ] = {start: (None, None)}
    cost = {start: 0}
    seen = 0

    while queue and seen < max_states:
        _priority, route_cost, _count, state = heapq.heappop(queue)
        if route_cost != cost[state]:
            continue
        seen += 1
        actor, boxes = state

        if boxes == target_boxes and baba_you(boxes) and flag_win(boxes):
            final_walk = recover_path(reachable(actor, boxes, (width, height), blockers), flag)
            if final_walk is not None:
                route: list[str] = []
                cur = state
                while parent[cur][0] is not None:
                    prev_state, moves = parent[cur]
                    assert prev_state is not None and moves is not None
                    route[:0] = moves
                    cur = prev_state
                route.extend(final_walk)
                return route, seen, state

        prev = reachable(actor, boxes, (width, height), blockers)
        occupied = {coord: index for index, coord in enumerate(boxes)}
        for index, pos in enumerate(boxes):
            for move, (dx, dy) in DIRS:
                stand = (pos[0] - dx, pos[1] - dy)
                if stand not in prev:
                    continue
                chain: list[int] = []
                cursor = pos
                while cursor in occupied:
                    chain.append(occupied[cursor])
                    cursor = (cursor[0] + dx, cursor[1] + dy)
                if (
                    not (1 <= cursor[0] <= width - 2 and 1 <= cursor[1] <= height - 2)
                    or cursor in blockers
                ):
                    continue
                next_boxes = list(boxes)
                for chain_index in reversed(chain):
                    bx, by = next_boxes[chain_index]
                    next_boxes[chain_index] = (bx + dx, by + dy)
                next_boxes_tuple = tuple(next_boxes)
                if len(set(next_boxes_tuple)) != len(next_boxes_tuple):
                    continue
                if not baba_you(next_boxes_tuple):
                    continue
                walk = recover_path(prev, stand)
                assert walk is not None
                next_state = (pos, next_boxes_tuple)
                next_cost = route_cost + len(walk) + 1
                if next_cost >= cost.get(next_state, sys.maxsize):
                    continue
                cost[next_state] = next_cost
                parent[next_state] = (state, [*walk, move])
                heapq.heappush(
                    queue,
                    (
                        next_cost + heuristic_weight * heuristic(next_boxes_tuple),
                        next_cost,
                        next(counter),
                        next_state,
                    ),
                )

    raise SystemExit(f"No route found after {seen} states")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--world", help="World folder. Defaults to current save world.")
    parser.add_argument("--level", help="Level id. Defaults to current save level.")
    parser.add_argument("--max-states", type=int, default=250_000)
    parser.add_argument(
        "--heuristic-weight",
        type=int,
        default=4,
        help="Higher values bias search toward the known solved 6level target.",
    )
    parser.add_argument("--execute", action="store_true", help="Send the found route")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay used with --execute")
    args = parser.parse_args()

    config = load_config(args.config)
    game_root = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir
    world, level, name, width, height, positions, rules = load_level(
        game_root, save_dir, args.world, args.level
    )

    if (world, level) != ("baba", "6level"):
        raise SystemExit("Only baba/6level is currently implemented")

    print(f"world={world} level={level} name={name}")
    print("initial_rules=" + "; ".join(f"{a} {b} {c}" for _d, _p, a, b, c in rules))
    route, seen, final_state = solve_baba_6level(
        width,
        height,
        positions,
        max_states=args.max_states,
        heuristic_weight=args.heuristic_weight,
    )
    compact = compress_moves(route)
    print(f"states={seen}")
    print(f"steps={len(route)}")
    print(f"moves={compact}")
    actor, boxes = final_state
    print(f"final_actor={actor}")
    print("final_text=" + ", ".join(f"{label}:{coord}" for label, coord in zip(LABELS, boxes)))
    print(f"command=python3 scripts/baba_send_keys.py '{compact}' --delay {args.delay}")

    if args.execute:
        subprocess.run(
            [sys.executable, str(ROOT / "baba_send_keys.py"), compact, "--delay", str(args.delay)],
            check=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
