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
import time
from pathlib import Path

from baba_config import load_config
from parse_baba_level import current_level, read_ini_like
from read_baba_state import load_state


DIRS = {
    "right": (1, 0),
    "left": (-1, 0),
    "down": (0, 1),
    "up": (0, -1),
}

ROOT = Path(__file__).resolve().parent

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


def save_map_coords(save_section: dict[str, str], map_level: str) -> dict[tuple[int, int], int]:
    coords: dict[tuple[int, int], int] = {}
    prefix = re.escape(map_level)
    for key, value in save_section.items():
        match = re.fullmatch(prefix + r",(\d+),(\d+)", key)
        if match:
            coords[(int(match.group(1)), int(match.group(2)))] = parse_int(value)
    return coords


def default_target_candidates(
    statuses: dict[str, int],
    map_level: str,
    level_items: list[dict[str, str]],
    excluded_level_ids: set[str],
) -> list[str]:
    candidates: list[tuple[int, int, tuple[int, str], str]] = []

    def add(priority: int, number: int, file_id: str) -> None:
        candidates.append((priority, number, natural_level_key(file_id), file_id))

    for item in level_items:
        file_id = item.get("file", "")
        if not file_id or file_id in excluded_level_ids or file_id == map_level:
            continue
        if statuses.get(file_id) == 3 or parse_int(item.get("style")) == 2:
            continue
        number = parse_int(item.get("number"), 10_000)
        if statuses.get(file_id) == 2:
            add(0, number, file_id)
        elif parse_int(item.get("state")) > 0:
            add(1, number, file_id)

    for level, status in statuses.items():
        if level not in excluded_level_ids and level != map_level and status == 2:
            add(2, 10_000, level)

    ordered: list[str] = []
    seen: set[str] = set()
    for *_sort_key, file_id in sorted(candidates):
        if file_id not in seen:
            seen.add(file_id)
            ordered.append(file_id)
    return ordered


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


def live_cursor_coord(save_dir: Path, map_level: str) -> tuple[int, int] | None:
    path = (save_dir / "codex_state.json").resolve()
    try:
        state = load_state(path, wait=False, timeout=0, since_mtime=None, save_dir=save_dir)
    except (OSError, SystemExit, ValueError):
        return None

    meta = state.get("meta", {})
    if meta.get("level") != map_level:
        return None

    cursors = []
    for unit in state.get("units", []):
        if unit.get("name") != "cursor":
            continue
        if unit.get("dead") or not unit.get("visible", True):
            continue
        x = unit.get("x")
        y = unit.get("y")
        if isinstance(x, int) and isinstance(y, int):
            cursors.append((x, y))

    return cursors[0] if len(cursors) == 1 else None


def infer_cursor(
    selector: tuple[int, int],
    passable: set[tuple[int, int]],
    visible_level_coords: set[tuple[int, int]],
    visible_path_coords: set[tuple[int, int]],
    surrounds: dict[str, str],
    preferred_coords: set[tuple[int, int]] | None = None,
) -> tuple[tuple[int, int], str]:
    if not surrounds:
        preferred = sorted(preferred_coords or set())
        if len(preferred) == 1:
            return preferred[0], "previous"
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
            if direction in {"dr", "ur", "ul", "dl"} and actual == "line":
                actual = "-"
            if actual != expected and not (expected == "-" and actual == "line"):
                ok = False
                break
        if ok:
            matches.append(candidate)

    if len(matches) == 1:
        return matches[0], "levelsurrounds"
    preferred_matches = sorted(set(matches) & (preferred_coords or set()))
    if len(preferred_matches) == 1:
        return preferred_matches[0], f"previous among {len(matches)} levelsurrounds matches"
    if selector in matches:
        return selector, f"selector among {len(matches)} levelsurrounds matches"
    preferred = sorted(preferred_coords or set())
    if len(preferred) == 1:
        return preferred[0], f"previous fallback; {len(matches)} levelsurrounds matches"
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
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--enter-key", choices=["enter", "confirm"], default="enter")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan only. This is the default; kept for agents that expect a dry-run flag.",
    )
    parser.add_argument("--execute", action="store_true", help="Send the detected route with baba_send_keys.py")
    parser.add_argument("--hold-ms", type=int, default=90, help="Key hold passed to baba_send_keys.py with --execute")
    parser.add_argument(
        "--no-rules-summary",
        action="store_true",
        help="Do not print the entered level's initial active rules after --execute",
    )
    args = parser.parse_args()
    config = load_config(args.config)
    game_root = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir

    slot, world, previous = current_level(save_dir)
    save_file = save_dir / f"{slot}ba.ba"
    save = read_ini_like(save_file)
    save_section = save.get(world, {})
    leveltree = save_section.get("leveltree") or save_section.get("Previous")
    if not leveltree:
        raise SystemExit(f"Could not find leveltree/Previous in {save_file} [{world}]")
    leveltree_parts = [part for part in leveltree.split(",") if part]
    map_level = leveltree_parts[-1]
    excluded_level_ids = set(leveltree_parts)

    ld_path = game_root / world / f"{map_level}.ld"
    sections = read_ini_like(ld_path)
    general = sections.get("general", {})
    selector = (parse_int(general.get("selectorX")), parse_int(general.get("selectorY")))
    level_count = parse_int(general.get("levels"))
    path_count = parse_int(general.get("paths"))

    statuses = save_statuses(save_section)
    prize_total = parse_int(save.get(f"{world}_prize", {}).get("total"))
    levels = numbered_items(sections.get("levels", {}))
    paths = numbered_items(sections.get("paths", {}))
    requested_target = args.target
    level_by_coord: dict[tuple[int, int], list[dict[str, str]]] = collections.defaultdict(list)
    coords_by_file: dict[str, set[tuple[int, int]]] = collections.defaultdict(set)
    previous_coords: set[tuple[int, int]] = set()
    for index, item in levels.items():
        if level_count and index >= level_count:
            continue
        coord = coord_from_item(item)
        if not coord:
            continue
        file_id = item.get("file", "")
        level_by_coord[coord].append(item)
        if file_id:
            coords_by_file[file_id].add(coord)
        if file_id == previous:
            previous_coords.add(coord)

    save_path_coords = {
        coord
        for coord, status in save_map_coords(save_section, map_level).items()
        if status > 0
    }
    unlocked_path_coords = set()
    for index, item in paths.items():
        if path_count and index >= path_count:
            continue
        requirement = parse_int(item.get("requirement"))
        if requirement and requirement > prize_total:
            continue
        coord = coord_from_item(item)
        if coord is not None:
            unlocked_path_coords.add(coord)
    visible_path_coords = save_path_coords or unlocked_path_coords

    passable = set(visible_path_coords)
    visible_level_coords = set()
    for coord, items in level_by_coord.items():
        for item in items:
            file_id = item.get("file", "")
            if file_id == requested_target or statuses.get(file_id, 0) > 0 or parse_int(item.get("state")) > 0:
                visible_level_coords.add(coord)
                passable.add(coord)
                break
    passable.add(selector)

    live_cursor = live_cursor_coord(save_dir, map_level)
    if live_cursor is not None:
        passable.add(live_cursor)
        cursor = live_cursor
        cursor_source = "live_state"
    else:
        cursor, cursor_source = infer_cursor(
            selector,
            passable,
            visible_level_coords,
            visible_path_coords,
            parse_levelsurrounds(save_section.get("levelsurrounds")),
            previous_coords,
        )

    target = requested_target
    target_coords: set[tuple[int, int]] = set()
    path: list[str] | None = None
    skipped_targets: list[str] = []
    if target:
        target_coords = coords_by_file.get(target, set())
        if not target_coords:
            raise SystemExit(f"Could not find map coordinates for {target}.")
        path = shortest_path(cursor, target_coords, passable)
    else:
        candidates = default_target_candidates(statuses, map_level, list(levels.values()), excluded_level_ids)
        for candidate in candidates:
            coords = coords_by_file.get(candidate, set())
            candidate_path = shortest_path(cursor, coords, passable) if coords else None
            if candidate_path is None:
                skipped_targets.append(candidate)
                continue
            target = candidate
            target_coords = coords
            path = candidate_path
            break
        if not target:
            suffix = f" Skipped unreachable candidates: {', '.join(skipped_targets)}." if skipped_targets else ""
            raise SystemExit(f"Could not infer a reachable target. Pass a level id such as 1level.{suffix}")

    if path is None:
        raise SystemExit(f"No route from {cursor} to {target} at {sorted(target_coords)}")

    moves = [*path, args.enter_key]
    print(f"slot={slot} world={world} map={map_level}")
    if leveltree != map_level:
        print(f"leveltree={leveltree}")
    print(f"cursor={cursor} source={cursor_source}")
    print(f"target={target} coords={sorted(target_coords)}")
    if skipped_targets:
        print("skipped_unreachable=" + ",".join(skipped_targets))
    print("moves=" + ",".join(moves))
    print(f"command=python3 scripts/baba_send_keys.py '{','.join(moves)}' --hold-ms {args.hold_ms}")

    if args.execute:
        subprocess.run(
            [sys.executable, str(ROOT / "baba_send_keys.py"), ",".join(moves), "--hold-ms", str(args.hold_ms)],
            check=True,
        )
        if not args.no_rules_summary:
            for _ in range(20):
                try:
                    _slot, _world, current = current_level(save_dir)
                except SystemExit:
                    current = None
                if current == target:
                    break
                time.sleep(0.1)
            print()
            print("Entered level initial rules:")
            subprocess.run([sys.executable, str(ROOT / "parse_baba_level.py"), "--rules-only"], check=False)
        print()
        print("next_command=python3 start_benchmark.py")
        print("next_reason=Start or resume the benchmark for the entered level before solving it.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
