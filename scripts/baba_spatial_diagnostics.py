#!/usr/bin/env python3
"""Diagnose edge/corner push limits and actor enclosure from live Baba state."""

from __future__ import annotations

import argparse
import collections
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_loop_guard import check_allowed, record_analysis
from baba_step import state_path
from read_baba_state import load_state


Coord = tuple[int, int]
DIRS: tuple[tuple[str, Coord], ...] = (
    ("up", (0, -1)),
    ("right", (1, 0)),
    ("down", (0, 1)),
    ("left", (-1, 0)),
)
HAZARD_PROPS = {"defeat", "sink", "hot", "melt"}


@dataclass(frozen=True)
class Unit:
    name: str
    unit_id: int | None
    coord: Coord
    unit_type: str
    word: str | None


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def load_current_state(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    path = args.path.expanduser().resolve() if args.path else state_path(save_dir, None)
    return load_state(
        path,
        wait=args.wait,
        timeout=args.timeout,
        since_mtime=None,
        save_dir=save_dir,
    )


def visible_units(state: dict[str, Any]) -> list[Unit]:
    units: list[Unit] = []
    for raw in state.get("units", []):
        if raw.get("dead") or not raw.get("visible", True):
            continue
        name = norm(raw.get("name"))
        x = raw.get("x")
        y = raw.get("y")
        if not name or x is None or y is None:
            continue
        units.append(
            Unit(
                name=name,
                unit_id=raw.get("id"),
                coord=(int(x), int(y)),
                unit_type=norm(raw.get("unit_type")),
                word=norm(raw.get("word")) or None,
            )
        )
    return units


def props_by_subject(state: dict[str, Any]) -> dict[str, set[str]]:
    props: dict[str, set[str]] = collections.defaultdict(set)
    for rule in state.get("rules", []):
        subject = norm(rule.get("target"))
        effect = norm(rule.get("effect"))
        if subject and effect:
            props[subject].add(effect)
    return props


def in_bounds(width: int, height: int, coord: Coord) -> bool:
    x, y = coord
    return 1 <= x <= width - 2 and 1 <= y <= height - 2


def unit_label(unit: Unit) -> str:
    word = f":{unit.word}" if unit.word else ""
    suffix = f"#{unit.unit_id}" if unit.unit_id is not None else ""
    return f"{unit.name}{suffix}{word}@{unit.coord}"


def push_subjects(props: dict[str, set[str]]) -> set[str]:
    subjects = {subject for subject, values in props.items() if "push" in values}
    subjects.add("text")
    return subjects


def stop_subjects(props: dict[str, set[str]]) -> set[str]:
    return {subject for subject, values in props.items() if "stop" in values}


def is_text(unit: Unit) -> bool:
    return unit.unit_type == "text" or unit.name.startswith("text_") or unit.word is not None


def is_pushable(unit: Unit, props: dict[str, set[str]]) -> bool:
    return is_text(unit) or unit.name in push_subjects(props)


def is_boundary(coord: Coord, width: int, height: int) -> bool:
    x, y = coord
    return x in {1, width - 2} or y in {1, height - 2}


def boundary_kind(coord: Coord, width: int, height: int) -> tuple[str, list[str]]:
    x, y = coord
    left = x == 1
    right = x == width - 2
    top = y == 1
    bottom = y == height - 2
    locks: list[str] = []
    if left or right:
        locks.append("horizontal_locked")
    if top or bottom:
        locks.append("vertical_locked")
    if (left or right) and (top or bottom):
        locks.append("corner_locked")
        return "corner", locks
    if locks:
        return "edge", locks
    return "interior", locks


def geometric_push_dirs(coord: Coord, width: int, height: int) -> list[str]:
    dirs: list[str] = []
    x, y = coord
    for move, (dx, dy) in DIRS:
        stand = (x - dx, y - dy)
        tail = (x + dx, y + dy)
        if in_bounds(width, height, stand) and in_bounds(width, height, tail):
            dirs.append(move)
    return dirs


def units_by_coord(units: list[Unit]) -> dict[Coord, list[Unit]]:
    by_coord: dict[Coord, list[Unit]] = collections.defaultdict(list)
    for unit in units:
        by_coord[unit.coord].append(unit)
    return by_coord


def dangerous_coords(props: dict[str, set[str]], units: list[Unit], actor: str) -> set[Coord]:
    danger: set[Coord] = set()
    for unit in units:
        unit_props = props.get(unit.name, set())
        if unit_props & {"defeat", "sink"}:
            danger.add(unit.coord)
        if "hot" in unit_props and "melt" in props.get(actor, set()):
            danger.add(unit.coord)
    return danger


def movement_blockers(units: list[Unit], props: dict[str, set[str]], actor: str) -> set[Coord]:
    stops = stop_subjects(props)
    pushes = push_subjects(props)
    blockers: set[Coord] = set()
    for unit in units:
        if unit.name == actor and not is_text(unit):
            continue
        if is_text(unit) or unit.name in stops or unit.name in pushes:
            blockers.add(unit.coord)
    blockers.update(dangerous_coords(props, units, actor))
    return blockers


def reachable(starts: list[Coord], *, width: int, height: int, blockers: set[Coord]) -> set[Coord]:
    queue = collections.deque(starts)
    seen = set(starts)
    while queue:
        coord = queue.popleft()
        for _move, (dx, dy) in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if nxt in seen or not in_bounds(width, height, nxt) or nxt in blockers:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def push_chain_status(
    unit: Unit,
    move: str,
    *,
    width: int,
    height: int,
    by_coord: dict[Coord, list[Unit]],
    props: dict[str, set[str]],
    actor_reachable: set[Coord],
) -> dict[str, Any]:
    dx, dy = dict(DIRS)[move]
    x, y = unit.coord
    stand = (x - dx, y - dy)
    cursor = unit.coord
    chain: list[str] = []
    while True:
        pushers = [candidate for candidate in by_coord.get(cursor, []) if is_pushable(candidate, props)]
        if not pushers:
            break
        chain.extend(unit_label(candidate) for candidate in pushers)
        cursor = (cursor[0] + dx, cursor[1] + dy)

    tail_units = by_coord.get(cursor, [])
    tail_blocked_by = [
        unit_label(candidate)
        for candidate in tail_units
        if candidate.name in stop_subjects(props) or (not is_pushable(candidate, props) and "stop" in props.get(candidate.name, set()))
    ]
    tail_ok = in_bounds(width, height, cursor) and not tail_blocked_by
    return {
        "move": move,
        "stand": stand,
        "tail": cursor,
        "stand_in_bounds": in_bounds(width, height, stand),
        "tail_in_bounds": in_bounds(width, height, cursor),
        "stand_reachable": stand in actor_reachable if actor_reachable else None,
        "tail_ok": tail_ok,
        "blocked_by": tail_blocked_by,
        "chain": chain,
    }


def boundary_reports(
    units: list[Unit],
    props: dict[str, set[str]],
    *,
    width: int,
    height: int,
    actor_reachable: set[Coord],
    unit_filters: set[str],
    all_boundary_units: bool,
    limit: int,
) -> list[dict[str, Any]]:
    by_coord = units_by_coord(units)
    reports: list[dict[str, Any]] = []
    for unit in sorted(units, key=lambda item: (item.coord[1], item.coord[0], item.name, item.unit_id or -1)):
        if not is_boundary(unit.coord, width, height):
            continue
        names = {unit.name}
        if unit.word:
            names.update({unit.word, f"text_{unit.word}"})
        if unit_filters and not (names & unit_filters):
            continue
        pushable = is_pushable(unit, props)
        if not all_boundary_units and not pushable:
            continue
        kind, locks = boundary_kind(unit.coord, width, height)
        geom_dirs = geometric_push_dirs(unit.coord, width, height)
        slots = [
            push_chain_status(
                unit,
                move,
                width=width,
                height=height,
                by_coord=by_coord,
                props=props,
                actor_reachable=actor_reachable,
            )
            for move in geom_dirs
        ]
        reports.append(
            {
                "unit": unit_label(unit),
                "name": unit.name,
                "word": unit.word,
                "coord": unit.coord,
                "pushable": pushable,
                "boundary": kind,
                "locks": locks,
                "geometric_push_dirs": geom_dirs,
                "actual_push_dirs": [
                    slot["move"]
                    for slot in slots
                    if slot["tail_ok"] and slot["stand_reachable"] is not False
                ],
                "push_slots": slots,
            }
        )
        if limit and len(reports) >= limit:
            break
    return reports


def enclosure_report(
    units: list[Unit],
    props: dict[str, set[str]],
    *,
    width: int,
    height: int,
    actor: str,
) -> dict[str, Any]:
    actor_positions = [unit.coord for unit in units if unit.name == actor and not is_text(unit)]
    blockers = movement_blockers(units, props, actor)
    actor_reachable = reachable(actor_positions, width=width, height=height, blockers=blockers) if actor_positions else set()
    all_cells = {(x, y) for x in range(1, width - 1) for y in range(1, height - 1)}
    passable_cells = all_cells - blockers
    unreachable = passable_cells - actor_reachable

    stop_coords: dict[str, set[Coord]] = collections.defaultdict(set)
    for unit in units:
        if unit.name in stop_subjects(props):
            stop_coords[unit.name].add(unit.coord)

    candidates: list[dict[str, Any]] = []
    for subject, coords in sorted(stop_coords.items()):
        if subject == "level":
            continue
        after_blockers = blockers - coords
        after = reachable(actor_positions, width=width, height=height, blockers=after_blockers) if actor_positions else set()
        gained = after - actor_reachable
        frontier = sorted(
            coord
            for coord in coords
            if any((coord[0] - dx, coord[1] - dy) in actor_reachable for _move, (dx, dy) in DIRS)
        )
        if gained or frontier:
            candidates.append(
                {
                    "subject": subject,
                    "stop_coords": sorted(coords),
                    "frontier_coords": frontier,
                    "reachable_gain_if_rule_removed": len(gained),
                }
            )
    candidates.sort(key=lambda item: (-int(item["reachable_gain_if_rule_removed"]), item["subject"]))

    return {
        "actor": actor,
        "actor_positions": actor_positions,
        "actor_found": bool(actor_positions),
        "reachable_cells": len(actor_reachable),
        "passable_cells": len(passable_cells),
        "unreachable_passable_cells": len(unreachable),
        "enclosed_by_stop": any(item["reachable_gain_if_rule_removed"] > 0 for item in candidates),
        "needs_break_first": bool(actor_positions) and any(item["reachable_gain_if_rule_removed"] > 0 for item in candidates),
        "break_first_candidates": candidates[:8],
        "reachable_set": actor_reachable,
    }


def as_json_payload(
    state: dict[str, Any],
    boundary: list[dict[str, Any]],
    enclosure: dict[str, Any],
) -> str:
    payload = {
        "level": {
            "world": state.get("meta", {}).get("world"),
            "level": state.get("meta", {}).get("level"),
            "name": state.get("meta", {}).get("level_name"),
            "turn": state.get("meta", {}).get("turn"),
            "size": [state.get("meta", {}).get("room_width"), state.get("meta", {}).get("room_height")],
        },
        "boundary_push_limits": boundary,
        "actor_enclosure": {key: value for key, value in enclosure.items() if key != "reachable_set"},
        "rules_of_thumb": {
            "corner": "corner boundary pushable units have zero geometric push directions",
            "edge": "edge boundary pushable units can only move along the edge axis before other blockers are considered",
            "enclosure": "if removing a STOP subject increases actor reachability, break or alter that rule before planning goals outside the compartment",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def print_human(state: dict[str, Any], boundary: list[dict[str, Any]], enclosure: dict[str, Any]) -> None:
    meta = state.get("meta", {})
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    print(
        "level="
        f"{meta.get('world')}/{meta.get('level')} "
        f"name={meta.get('level_name') or '<unknown>'} turn={meta.get('turn')} "
        f"bounds=x=1..{width - 2} y=1..{height - 2}"
    )
    print("corner_rule=corner pushable units have no geometric push directions; treat them as immovable until rules/position change")
    print("edge_rule=edge pushable units can only be pushed along the edge axis before blockers/chains are considered")
    print()
    print("Actor enclosure:")
    print(f"  actor={enclosure['actor']} positions={enclosure['actor_positions'] or '<none>'}")
    print(
        "  reachable="
        f"{enclosure['reachable_cells']}/{enclosure['passable_cells']} "
        f"unreachable_passable={enclosure['unreachable_passable_cells']}"
    )
    print(f"  enclosed_by_stop={str(enclosure['enclosed_by_stop']).lower()}")
    print(f"  needs_break_first={str(enclosure['needs_break_first']).lower()}")
    if enclosure["break_first_candidates"]:
        print("  break_first_candidates:")
        for item in enclosure["break_first_candidates"]:
            print(
                "    "
                f"{item['subject']} gain={item['reachable_gain_if_rule_removed']} "
                f"frontier={item['frontier_coords']} stop_coords={item['stop_coords']}"
            )
    else:
        print("  break_first_candidates=<none>")

    print()
    print("Boundary push limits:")
    if not boundary:
        print("  <none>")
    for item in boundary:
        print(
            "  "
            f"{item['unit']} boundary={item['boundary']} locks={','.join(item['locks']) or '<none>'} "
            f"pushable={str(item['pushable']).lower()} "
            f"geometric_push_dirs={','.join(item['geometric_push_dirs']) or '<none>'} "
            f"actual_push_dirs={','.join(item['actual_push_dirs']) or '<none>'}"
        )
        for slot in item["push_slots"]:
            stand_reachable = slot["stand_reachable"]
            stand_text = "unknown" if stand_reachable is None else str(stand_reachable).lower()
            blocked = ",".join(slot["blocked_by"]) if slot["blocked_by"] else "<none>"
            print(
                "    "
                f"{slot['move']}: stand={slot['stand']} stand_reachable={stand_text} "
                f"tail={slot['tail']} tail_ok={str(slot['tail_ok']).lower()} blocked_by={blocked}"
            )
    print()
    print("next=use these facts to choose one 1-3 step baba_action_check.py segment; do not continue edge/corner push prose")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override JSON state path")
    parser.add_argument("--wait", action="store_true", help="Wait for state to appear")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--actor", default="baba", help="Actor/object name to test for enclosure. Default: baba")
    parser.add_argument("--unit", action="append", default=[], help="Restrict boundary report to a name/word such as text_win, win, rock.")
    parser.add_argument("--all-boundary-units", action="store_true", help="Include non-pushable boundary units too.")
    parser.add_argument("--limit", type=int, default=20, help="Limit boundary units printed. Use 0 for all.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--ignore-loop-guard", action="store_true", help="Bypass the analysis/action loop guard for manual debugging.")
    args = parser.parse_args()

    decision = check_allowed("suggest", args.config, ignore=args.ignore_loop_guard)
    if not decision.allowed:
        if args.json:
            print(json.dumps({"loop_guard": "action_required", "state": decision.state, "reason": decision.reason}, ensure_ascii=False, indent=2))
        else:
            decision.print_block()
        return 2

    state = load_current_state(args)
    meta = state.get("meta", {})
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    if width < 3 or height < 3:
        raise SystemExit("Live state is missing usable room_width/room_height")
    units = visible_units(state)
    props = props_by_subject(state)
    enclosure = enclosure_report(units, props, width=width, height=height, actor=norm(args.actor))
    boundary = boundary_reports(
        units,
        props,
        width=width,
        height=height,
        actor_reachable=enclosure["reachable_set"],
        unit_filters={norm(item) for item in args.unit},
        all_boundary_units=args.all_boundary_units,
        limit=args.limit,
    )

    if not args.ignore_loop_guard:
        record_analysis("suggest", args.config, detail=f"spatial actor={norm(args.actor)}")
    if args.json:
        print(as_json_payload(state, boundary, enclosure))
    else:
        print_human(state, boundary, enclosure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
