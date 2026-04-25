#!/usr/bin/env python3
"""Detect a Baba Is You map route from save/map files.

The script is read-only by default. It uses the current save slot/world, reads
the active map level, infers the selector coordinate, then finds a shortest
cardinal path to the requested level node.
"""

from __future__ import annotations

import argparse
import collections
import re
import subprocess
import sys
from pathlib import Path

from parse_baba_level import DEFAULT_GAME_ROOT, DEFAULT_SAVE_DIR, current_level, read_ini_like


DIRS = {
    "right": (1, 0),
    "left": (-1, 0),
    "down": (0, 1),
    "up": (0, -1),
}

SURROUND_OFFSETS = {
    "r": (1, 0),
    "u": (0, -1),
    "l": (-1, 0),
    "d": (0, 1),
    "dr": (1, 1),
    "ur": (1, -1),
    "ul": (-1, -1),
    "dl": (-1, 1),
    "o": (0, 0),
}


def numbered_items(section: dict[str, str]) -> dict[int, dict[str, str]]:
    items: dict[int, dict[str, str]] = collections.defaultdict(dict)
    for key, value in section.items():
        match = re.fullmatch(r"(\d+)([A-Za-z_]+)", key)
        if match:
            items[int(match.group(1))][match.group(2)] = value
    return dict(items)


def parse_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value or default)
    except ValueError:
        return default


def save_statuses(save_section: dict[str, str]) -> dict[str, int]:
    statuses: dict[str, int] = {}
    for key, value in save_section.items():
        if re.fullmatch(r".*level", key):
            statuses[key] = parse_int(value)
    return statuses


def default_target(statuses: dict[str, int], map_level: str) -> str | None:
    candidates = [
        level
        for level, status in statuses.items()
        if level != map_level and status == 2
    ]
    return sorted(candidates, key=natural_level_key)[0] if candidates else None


def natural_level_key(level: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d+)level", level)
    return (int(match.group(1)), level) if match else (10_000, level)


def parse_levelsurrounds(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    tokens = [token for token in raw.split(",") if token]
    if len(tokens) % 2 == 1:
        tokens = tokens[1:]
    return {
        tokens[i]: tokens[i + 1]
        for i in range(0, len(tokens) - 1, 2)
        if tokens[i] in SURROUND_OFFSETS
    }


def coord_from_item(item: dict[str, str]) -> tuple[int, int] | None:
    if "X" not in item or "Y" not in item:
        return None
    return (parse_int(item["X"]), parse_int(item["Y"]))


def infer_cursor(
    selector: tuple[int, int],
    passable: set[tuple[int, int]],
    visible_level_coords: set[tuple[int, int]],
    visible_path_coords: set[tuple[int, int]],
    surrounds: dict[str, str],
) -> tuple[tuple[int, int], str]:
    if not surrounds:
        return selector, "selector"

    def kind(coord: tuple[int, int]) -> str:
        if coord in visible_level_coords:
            return "level"
        if coord in visible_path_coords:
            return "line"
        return "-"

    matches = []
    for candidate in passable:
        ok = True
        for direction, expected in surrounds.items():
            dx, dy = SURROUND_OFFSETS[direction]
            actual = "cursor" if direction == "o" else kind((candidate[0] + dx, candidate[1] + dy))
            if actual != expected:
                ok = False
                break
        if ok:
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0], "levelsurrounds"
    if selector in matches:
        return selector, f"selector among {len(matches)} levelsurrounds matches"
    return selector, f"selector fallback; {len(matches)} levelsurrounds matches"


def shortest_path(
    start: tuple[int, int],
    targets: set[tuple[int, int]],
    passable: set[tuple[int, int]],
) -> list[str] | None:
    queue = collections.deque([(start, [])])
    seen = {start}
    while queue:
        coord, path = queue.popleft()
        if coord in targets:
            return path
        for name, (dx, dy) in DIRS.items():
            nxt = (coord[0] + dx, coord[1] + dy)
            if nxt in passable and nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, [*path, name]))
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", help="Target level id, e.g. 1level. Defaults to next unlocked level.")
    parser.add_argument("--game-root", type=Path, default=DEFAULT_GAME_ROOT)
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR)
    parser.add_argument("--enter-key", choices=["enter", "confirm"], default="enter")
    parser.add_argument("--execute", action="store_true", help="Send the detected route with baba_send_keys.py")
    args = parser.parse_args()

    slot, world, _previous = current_level(args.save_dir)
    save_file = args.save_dir / f"{slot}ba.ba"
    save = read_ini_like(save_file)
    save_section = save.get(world, {})
    map_level = save_section.get("leveltree") or save_section.get("Previous")
    if not map_level:
        raise SystemExit(f"Could not find leveltree/Previous in {save_file} [{world}]")

    ld_path = args.game_root / world / f"{map_level}.ld"
    sections = read_ini_like(ld_path)
    general = sections.get("general", {})
    selector = (parse_int(general.get("selectorX")), parse_int(general.get("selectorY")))
    level_count = parse_int(general.get("levels"))
    path_count = parse_int(general.get("paths"))

    statuses = save_statuses(save_section)
    prize_total = parse_int(save.get(f"{world}_prize", {}).get("total"))
    target = args.target or default_target(statuses, map_level)
    if not target:
        raise SystemExit("Could not infer target. Pass a level id such as 1level.")

    levels = numbered_items(sections.get("levels", {}))
    paths = numbered_items(sections.get("paths", {}))

    level_by_coord: dict[tuple[int, int], list[dict[str, str]]] = collections.defaultdict(list)
    target_coords: set[tuple[int, int]] = set()
    for index, item in levels.items():
        if level_count and index >= level_count:
            continue
        coord = coord_from_item(item)
        if not coord:
            continue
        level_by_coord[coord].append(item)
        if item.get("file") == target:
            target_coords.add(coord)

    visible_path_coords = set()
    for index, item in paths.items():
        if path_count and index >= path_count:
            continue
        requirement = parse_int(item.get("requirement"))
        if requirement and requirement > prize_total:
            continue
        coord = coord_from_item(item)
        if coord is not None:
            visible_path_coords.add(coord)

    passable = set(visible_path_coords)
    visible_level_coords = set()
    for coord, items in level_by_coord.items():
        for item in items:
            file_id = item.get("file", "")
            if file_id == target or statuses.get(file_id, 0) > 0 or parse_int(item.get("state")) > 0:
                visible_level_coords.add(coord)
                passable.add(coord)
                break
    passable.add(selector)

    cursor, cursor_source = infer_cursor(
        selector,
        passable,
        visible_level_coords,
        visible_path_coords,
        parse_levelsurrounds(save_section.get("levelsurrounds")),
    )

    path = shortest_path(cursor, target_coords, passable)
    if path is None:
        raise SystemExit(f"No route from {cursor} to {target} at {sorted(target_coords)}")

    moves = [*path, args.enter_key]
    print(f"slot={slot} world={world} map={map_level}")
    print(f"cursor={cursor} source={cursor_source}")
    print(f"target={target} coords={sorted(target_coords)}")
    print("moves=" + ",".join(moves))
    print(f"command=python3 baba_send_keys.py '{','.join(moves)}'")

    if args.execute:
        subprocess.run([sys.executable, "baba_send_keys.py", ",".join(moves)], check=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
