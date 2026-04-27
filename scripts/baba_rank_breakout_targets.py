#!/usr/bin/env python3
"""Rank OPEN+SHUT breakout targets from the current live Baba state.

This is a cheap target selector, not a route solver. It answers the question:
"If I can remove one STOP object by using an OPEN tool, which object actually
opens new reachable space?"
"""

from __future__ import annotations

import argparse
import collections
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_step import state_path
from read_baba_state import load_state


Coord = tuple[int, int]
DIRS: tuple[tuple[str, Coord], ...] = (
    ("up", (0, -1)),
    ("down", (0, 1)),
    ("left", (-1, 0)),
    ("right", (1, 0)),
)
TEXT_IS_PUSH = ("text", "push")


@dataclass(frozen=True)
class Unit:
    name: str
    unit_id: int | None
    coord: Coord
    unit_type: str
    word: str | None


@dataclass(frozen=True)
class CollisionSlot:
    tool: str
    tool_coord: Coord | None
    tool_target: Coord
    actor_stand: Coord
    push: str
    actor_stand_reachable: bool
    tool_already_there: bool
    setup_distance: int | None
    setup_steps: int | None = None
    setup_route: str | None = None


@dataclass(frozen=True)
class TargetRank:
    score: int
    subject: str
    coord: Coord
    active_shut: bool
    reachable_gain: int
    external_gain: int
    before_neighbors: tuple[Coord, ...]
    new_neighbors: tuple[Coord, ...]
    win_distance: int | None
    best_setup_distance: int | None
    collision_slots: tuple[CollisionSlot, ...]


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


def active_rule_set(state: dict[str, Any]) -> set[tuple[str, str]]:
    rules: set[tuple[str, str]] = set()
    for rule in state.get("rules", []):
        subject = norm(rule.get("target"))
        effect = norm(rule.get("effect"))
        if subject and effect:
            rules.add((subject, effect))
    return rules


def in_bounds(width: int, height: int, coord: Coord) -> bool:
    x, y = coord
    return 1 <= x <= width - 2 and 1 <= y <= height - 2


def neighbors(width: int, height: int, coord: Coord) -> list[tuple[str, Coord]]:
    result = []
    x, y = coord
    for name, (dx, dy) in DIRS:
        nxt = (x + dx, y + dy)
        if in_bounds(width, height, nxt):
            result.append((name, nxt))
    return result


def unit_coords_by_name(units: list[Unit]) -> dict[str, list[Coord]]:
    coords: dict[str, list[Coord]] = collections.defaultdict(list)
    for unit in units:
        coords[unit.name].append(unit.coord)
    return coords


def stop_subjects(props: dict[str, set[str]]) -> set[str]:
    return {subject for subject, values in props.items() if "stop" in values}


def push_subjects(props: dict[str, set[str]]) -> set[str]:
    subjects = {subject for subject, values in props.items() if "push" in values}
    subjects.add("text")
    return subjects


def dangerous_tiles(props: dict[str, set[str]], coords_by_name: dict[str, list[Coord]], actor_subjects: set[str]) -> set[Coord]:
    dangerous: set[Coord] = set()
    defeat_subjects = {subject for subject, values in props.items() if "defeat" in values}
    for subject in defeat_subjects:
        dangerous.update(coords_by_name.get(subject, []))

    hot_subjects = {subject for subject, values in props.items() if "hot" in values}
    melt_subjects = {subject for subject, values in props.items() if "melt" in values}
    if actor_subjects & melt_subjects:
        for subject in hot_subjects:
            dangerous.update(coords_by_name.get(subject, []))
    return dangerous


def forbidden_actor_moves(width: int, height: int, dangerous: set[Coord]) -> set[tuple[Coord, str]]:
    forbidden: set[tuple[Coord, str]] = set()
    for tile in dangerous:
        for move, (dx, dy) in DIRS:
            stand = (tile[0] - dx, tile[1] - dy)
            if in_bounds(width, height, stand):
                forbidden.add((stand, move))
    return forbidden


def movement_blockers(
    *,
    units: list[Unit],
    props: dict[str, set[str]],
    remove_subject: str | None = None,
    remove_coord: Coord | None = None,
) -> set[Coord]:
    blockers: set[Coord] = set()
    stops = stop_subjects(props)
    pushes = push_subjects(props)
    for unit in units:
        if remove_subject == unit.name and remove_coord == unit.coord:
            continue
        if unit.unit_type == "text":
            blockers.add(unit.coord)
            continue
        if unit.name in stops or unit.name in pushes:
            blockers.add(unit.coord)
    return blockers


def reachable(
    starts: list[Coord],
    *,
    width: int,
    height: int,
    blockers: set[Coord],
    forbidden: set[tuple[Coord, str]],
) -> set[Coord]:
    queue = collections.deque(starts)
    seen = set(starts)
    while queue:
        coord = queue.popleft()
        for move, (dx, dy) in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if (
                (coord, move) in forbidden
                or nxt in seen
                or not in_bounds(width, height, nxt)
                or nxt in blockers
            ):
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def active_you_subjects(props: dict[str, set[str]]) -> set[str]:
    return {subject for subject, values in props.items() if "you" in values}


def actor_starts(units: list[Unit], you_subjects: set[str]) -> list[Coord]:
    starts = [unit.coord for unit in units if unit.unit_type != "text" and unit.name in you_subjects]
    if not starts:
        raise SystemExit("No visible YOU object found in live state")
    return starts


def open_push_tools(props: dict[str, set[str]], units: list[Unit]) -> dict[str, list[Coord]]:
    by_name = unit_coords_by_name(units)
    tools: dict[str, list[Coord]] = {}
    for subject, values in props.items():
        if subject == "text":
            continue
        if "open" in values and "push" in values and by_name.get(subject):
            tools[subject] = by_name[subject]
    return tools


def win_like_targets(props: dict[str, set[str]], units: list[Unit]) -> set[Coord]:
    targets: set[Coord] = set()
    win_subjects = {subject for subject, values in props.items() if "win" in values}
    for unit in units:
        if unit.unit_type != "text" and unit.name in win_subjects:
            targets.add(unit.coord)
        if unit.unit_type == "text" and unit.word == "win":
            targets.add(unit.coord)
    return targets


def min_distance(sources: set[Coord], targets: set[Coord]) -> int | None:
    if not sources or not targets:
        return None
    return min(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in sources for b in targets)


def compress_moves(route: list[str]) -> str:
    parts: list[list[str | int]] = []
    for move in route:
        if parts and parts[-1][0] == move:
            parts[-1][1] = int(parts[-1][1]) + 1
        else:
            parts.append([move, 1])
    return ",".join(f"{move}*{count}" if count != 1 else str(move) for move, count in parts)


def collision_slots_for_target(
    *,
    target: Coord,
    tools: dict[str, list[Coord]],
    before_reachable: set[Coord],
    width: int,
    height: int,
    blockers_without_target: set[Coord],
) -> tuple[CollisionSlot, ...]:
    slots: list[CollisionSlot] = []
    for move, (dx, dy) in DIRS:
        tool_target = (target[0] - dx, target[1] - dy)
        actor_stand = (tool_target[0] - dx, tool_target[1] - dy)
        if not in_bounds(width, height, tool_target) or not in_bounds(width, height, actor_stand):
            continue
        for tool, coords in sorted(tools.items()):
            tool_there = tool_target in coords
            occupied = tool_target in blockers_without_target and not tool_there
            if occupied:
                continue
            setup_distance = min(abs(coord[0] - tool_target[0]) + abs(coord[1] - tool_target[1]) for coord in coords) if coords else None
            slots.append(
                CollisionSlot(
                    tool=tool,
                    tool_coord=coords[0] if len(coords) == 1 else None,
                    tool_target=tool_target,
                    actor_stand=actor_stand,
                    push=move,
                    actor_stand_reachable=actor_stand in before_reachable,
                    tool_already_there=tool_there,
                    setup_distance=setup_distance,
                )
            )
    return tuple(slots)


@dataclass(frozen=True)
class SetupBox:
    name: str
    unit_id: int | None
    word: str | None
    coord: Coord
    unit_type: str


def active_text_rules_from_boxes(units: list[Unit], selected_boxes: tuple[SetupBox, ...], boxes: tuple[Coord, ...]) -> set[tuple[str, str]]:
    selected_keys = {(box.name, box.unit_id) for box in selected_boxes if box.unit_type == "text"}
    words_by_coord: dict[Coord, list[str]] = collections.defaultdict(list)
    for unit in units:
        if unit.unit_type != "text":
            continue
        key = (unit.name, unit.unit_id)
        if key in selected_keys:
            continue
        word = unit.word or unit.name.removeprefix("text_")
        words_by_coord[unit.coord].append(word)
    for box, coord in zip(selected_boxes, boxes):
        if box.unit_type == "text":
            word = box.word or box.name.removeprefix("text_")
            words_by_coord[coord].append(word)

    rules: set[tuple[str, str]] = set()
    for coord, first_words in words_by_coord.items():
        x, y = coord
        for _move, (dx, dy) in (("right", (1, 0)), ("down", (0, 1))):
            if "is" not in words_by_coord.get((x + dx, y + dy), []):
                continue
            for first in first_words:
                for last in words_by_coord.get((x + 2 * dx, y + 2 * dy), []):
                    rules.add((first, last))
    return rules


def setup_fixed_blockers(
    units: list[Unit],
    props: dict[str, set[str]],
    selected_boxes: tuple[SetupBox, ...],
) -> set[Coord]:
    selected_keys = {(box.name, box.unit_id) for box in selected_boxes}
    stops = stop_subjects(props)
    blockers: set[Coord] = set()
    for unit in units:
        if (unit.name, unit.unit_id) in selected_keys:
            continue
        if unit.unit_type == "text" or unit.name in stops:
            blockers.add(unit.coord)
    return blockers


def setup_reachable(
    actor: Coord,
    *,
    width: int,
    height: int,
    fixed_blockers: set[Coord],
    boxes: tuple[Coord, ...],
    forbidden: set[tuple[Coord, str]],
) -> dict[Coord, tuple[Coord | None, str | None]]:
    occupied = fixed_blockers | set(boxes)
    queue = collections.deque([actor])
    prev: dict[Coord, tuple[Coord | None, str | None]] = {actor: (None, None)}
    while queue:
        coord = queue.popleft()
        for move, (dx, dy) in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if (
                (coord, move) in forbidden
                or nxt in prev
                or not in_bounds(width, height, nxt)
                or nxt in occupied
            ):
                continue
            prev[nxt] = (coord, move)
            queue.append(nxt)
    return prev


def recover_setup_walk(prev: dict[Coord, tuple[Coord | None, str | None]], dest: Coord) -> list[str] | None:
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


def solve_setup_route(
    *,
    state: dict[str, Any],
    subject: str,
    slot: CollisionSlot,
    max_states: int,
) -> tuple[int, str] | None:
    if slot.tool_coord is None:
        return None
    meta = state.get("meta", {})
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    units = visible_units(state)
    props = props_by_subject(state)
    coords_by_name = unit_coords_by_name(units)
    you = active_you_subjects(props)
    starts = actor_starts(units, you)
    if len(starts) != 1:
        return None
    actor_start = starts[0]
    forbidden = forbidden_actor_moves(width, height, dangerous_tiles(props, coords_by_name, you))

    selected: list[SetupBox] = []
    for unit in units:
        if unit.unit_type != "text" and unit.name == slot.tool and unit.coord == slot.tool_coord:
            selected.append(SetupBox(unit.name, unit.unit_id, unit.word, unit.coord, unit.unit_type))
        elif unit.unit_type == "text" and (unit.word or unit.name.removeprefix("text_")) == "shut":
            selected.append(SetupBox(unit.name, unit.unit_id, unit.word, unit.coord, unit.unit_type))
    if not any(box.name == slot.tool and box.coord == slot.tool_coord for box in selected):
        return None

    selected_tuple = tuple(selected)
    start_boxes = tuple(box.coord for box in selected_tuple)
    fixed_blockers = setup_fixed_blockers(units, props, selected_tuple)
    tool_indices = tuple(
        index for index, box in enumerate(selected_tuple) if box.name == slot.tool and box.coord == slot.tool_coord
    )
    if not tool_indices:
        return None

    start = (actor_start, start_boxes)
    queue = collections.deque([start])
    parent: dict[tuple[Coord, tuple[Coord, ...]], tuple[tuple[Coord, tuple[Coord, ...]] | None, list[str] | None]] = {
        start: (None, None)
    }
    seen = 0
    while queue and seen < max_states:
        actor, boxes = queue.popleft()
        seen += 1
        rules = active_text_rules_from_boxes(units, selected_tuple, boxes)
        if (
            any(boxes[index] == slot.tool_target for index in tool_indices)
            and actor == slot.actor_stand
            and (subject, "shut") in rules
        ):
            route: list[str] = []
            cur = (actor, boxes)
            while parent[cur][0] is not None:
                prev_state, moves = parent[cur]
                assert prev_state is not None and moves is not None
                route[:0] = moves
                cur = prev_state
            return len(route), compress_moves(route)

        prev = setup_reachable(
            actor,
            width=width,
            height=height,
            fixed_blockers=fixed_blockers,
            boxes=boxes,
            forbidden=forbidden,
        )
        occupied = {coord: index for index, coord in enumerate(boxes)}
        for index, pos in enumerate(boxes):
            for move, (dx, dy) in DIRS:
                stand = (pos[0] - dx, pos[1] - dy)
                if stand not in prev or (stand, move) in forbidden:
                    continue
                chain: list[int] = []
                cursor = pos
                while cursor in occupied:
                    chain.append(occupied[cursor])
                    cursor = (cursor[0] + dx, cursor[1] + dy)
                if not in_bounds(width, height, cursor) or cursor in fixed_blockers:
                    continue
                next_boxes = list(boxes)
                for chain_index in reversed(chain):
                    bx, by = next_boxes[chain_index]
                    next_boxes[chain_index] = (bx + dx, by + dy)
                next_boxes_tuple = tuple(next_boxes)
                if len(set(next_boxes_tuple)) != len(next_boxes_tuple):
                    continue
                walk = recover_setup_walk(prev, stand)
                assert walk is not None
                next_state = (pos, next_boxes_tuple)
                if next_state in parent:
                    continue
                parent[next_state] = ((actor, boxes), [*walk, move])
                queue.append(next_state)
    return None


def with_setup_routes(
    state: dict[str, Any],
    rank: TargetRank,
    *,
    max_states: int,
) -> TargetRank:
    slots = []
    for slot in rank.collision_slots:
        solved = solve_setup_route(state=state, subject=rank.subject, slot=slot, max_states=max_states)
        if solved is None:
            slots.append(slot)
            continue
        steps, route = solved
        slots.append(
            CollisionSlot(
                tool=slot.tool,
                tool_coord=slot.tool_coord,
                tool_target=slot.tool_target,
                actor_stand=slot.actor_stand,
                push=slot.push,
                actor_stand_reachable=slot.actor_stand_reachable,
                tool_already_there=slot.tool_already_there,
                setup_distance=slot.setup_distance,
                setup_steps=steps,
                setup_route=route,
            )
        )
    solved_steps = [slot.setup_steps for slot in slots if slot.setup_steps is not None]
    best_steps = min(solved_steps) if solved_steps else None
    score = rank.score
    if best_steps is None:
        score -= 200
    else:
        score += 180 - best_steps * 2
    return TargetRank(
        score=score,
        subject=rank.subject,
        coord=rank.coord,
        active_shut=rank.active_shut,
        reachable_gain=rank.reachable_gain,
        external_gain=rank.external_gain,
        before_neighbors=rank.before_neighbors,
        new_neighbors=rank.new_neighbors,
        win_distance=rank.win_distance,
        best_setup_distance=best_steps if best_steps is not None else rank.best_setup_distance,
        collision_slots=tuple(slots),
    )


def rank_targets(state: dict[str, Any], *, subject_filter: str | None, only_active_shut: bool) -> list[TargetRank]:
    meta = state.get("meta", {})
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    units = visible_units(state)
    props = props_by_subject(state)
    rules = active_rule_set(state)
    coords_by_name = unit_coords_by_name(units)
    you = active_you_subjects(props)
    starts = actor_starts(units, you)
    dangerous = dangerous_tiles(props, coords_by_name, you)
    forbidden = forbidden_actor_moves(width, height, dangerous)
    blockers = movement_blockers(units=units, props=props)
    base_reachable = reachable(starts, width=width, height=height, blockers=blockers, forbidden=forbidden)
    tools = open_push_tools(props, units)
    win_targets = win_like_targets(props, units)

    candidates: list[TargetRank] = []
    candidate_subjects = sorted(stop_subjects(props) - {"level"})
    if subject_filter:
        candidate_subjects = [subject_filter]
    for subject in candidate_subjects:
        active_shut = (subject, "shut") in rules
        if only_active_shut and not active_shut:
            continue
        for coord in sorted(set(coords_by_name.get(subject, [])), key=lambda item: (item[1], item[0])):
            removed_blockers = movement_blockers(
                units=units,
                props=props,
                remove_subject=subject,
                remove_coord=coord,
            )
            after = reachable(starts, width=width, height=height, blockers=removed_blockers, forbidden=forbidden)
            gained = after - base_reachable
            external = gained - {coord}
            before_neighbors = tuple(
                sorted((nxt for _move, nxt in neighbors(width, height, coord) if nxt in base_reachable), key=lambda item: (item[1], item[0]))
            )
            new_neighbors = tuple(
                sorted((nxt for _move, nxt in neighbors(width, height, coord) if nxt in external), key=lambda item: (item[1], item[0]))
            )
            slots = collision_slots_for_target(
                target=coord,
                tools=tools,
                before_reachable=base_reachable,
                width=width,
                height=height,
                blockers_without_target=removed_blockers,
            )
            reachable_slots = [slot for slot in slots if slot.actor_stand_reachable]
            immediate_slots = [slot for slot in reachable_slots if slot.tool_already_there]
            setup_distances = [slot.setup_distance for slot in reachable_slots if slot.setup_distance is not None]
            best_setup_distance = min(setup_distances) if setup_distances else None
            win_distance = min_distance(external or gained, win_targets)
            score = (
                len(external) * 4
                + len(new_neighbors) * 35
                + len(before_neighbors) * 10
                + len(reachable_slots) * 8
                + len(immediate_slots) * 20
                + (30 if active_shut else 0)
            )
            if win_distance is not None:
                score += max(0, 80 - win_distance * 8)
            if best_setup_distance is not None:
                score -= best_setup_distance * 3
            if not before_neighbors:
                score -= 30
            if not new_neighbors:
                score -= 20
            if not slots:
                score -= 10
            candidates.append(
                TargetRank(
                    score=score,
                    subject=subject,
                    coord=coord,
                    active_shut=active_shut,
                    reachable_gain=len(gained),
                    external_gain=len(external),
                    before_neighbors=before_neighbors,
                    new_neighbors=new_neighbors,
                    win_distance=win_distance,
                    best_setup_distance=best_setup_distance,
                    collision_slots=slots,
                )
            )
    return sorted(
        candidates,
        key=lambda item: (
            -item.score,
            item.win_distance if item.win_distance is not None else 9999,
            item.best_setup_distance if item.best_setup_distance is not None else 9999,
            -item.external_gain,
            item.coord[1],
            item.coord[0],
        ),
    )


def slot_to_dict(slot: CollisionSlot) -> dict[str, Any]:
    return {
        "tool": slot.tool,
        "tool_coord": slot.tool_coord,
        "tool_target": slot.tool_target,
        "actor_stand": slot.actor_stand,
        "push": slot.push,
        "actor_stand_reachable": slot.actor_stand_reachable,
        "tool_already_there": slot.tool_already_there,
        "setup_distance": slot.setup_distance,
        "setup_steps": slot.setup_steps,
        "setup_route": slot.setup_route,
    }


def rank_to_dict(rank: TargetRank) -> dict[str, Any]:
    return {
        "score": rank.score,
        "subject": rank.subject,
        "coord": rank.coord,
        "active_shut": rank.active_shut,
        "reachable_gain": rank.reachable_gain,
        "external_gain": rank.external_gain,
        "before_neighbors": rank.before_neighbors,
        "new_neighbors": rank.new_neighbors,
        "win_distance": rank.win_distance,
        "best_setup_distance": rank.best_setup_distance,
        "collision_slots": [slot_to_dict(slot) for slot in rank.collision_slots],
    }


def format_slots(slots: tuple[CollisionSlot, ...], limit: int = 3) -> str:
    if not slots:
        return "<none>"
    ordered = sorted(
        slots,
        key=lambda slot: (
            not slot.actor_stand_reachable,
            not slot.tool_already_there,
            slot.tool,
            slot.push,
        ),
    )
    parts = []
    for slot in ordered[:limit]:
        flags = []
        if slot.actor_stand_reachable:
            flags.append("stand_reachable")
        if slot.tool_already_there:
            flags.append("tool_there")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        setup = f", setup_dist={slot.setup_distance}" if slot.setup_distance is not None else ""
        if slot.setup_steps is not None:
            setup += f", setup_steps={slot.setup_steps}, setup_route={slot.setup_route}"
        parts.append(
            f"{slot.tool}: tool->{slot.tool_target}, stand={slot.actor_stand}, push={slot.push}{setup}{suffix}"
        )
    if len(ordered) > limit:
        parts.append(f"... +{len(ordered) - limit}")
    return "; ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override live state JSON path")
    parser.add_argument("--wait", action="store_true", help="Wait for a state update if needed")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--subject", help="Only rank this STOP subject, e.g. wall or door")
    parser.add_argument("--only-active-shut", action="store_true", help="Only rank subjects currently marked SHUT")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--setup-search", action="store_true", help="Try a small macro-push search to place the OPEN tool in each collision slot")
    parser.add_argument("--setup-candidates", type=int, default=8, help="Only run --setup-search on this many pre-ranked targets")
    parser.add_argument("--setup-max-states", type=int, default=5_000, help="Per-slot state limit for --setup-search")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    state = load_current_state(args)
    meta = state.get("meta", {})
    units = visible_units(state)
    props = props_by_subject(state)
    coords_by_name = unit_coords_by_name(units)
    you = active_you_subjects(props)
    forbidden = forbidden_actor_moves(
        int(meta.get("room_width") or 0),
        int(meta.get("room_height") or 0),
        dangerous_tiles(props, coords_by_name, you),
    )
    ranks = rank_targets(state, subject_filter=norm(args.subject) or None, only_active_shut=args.only_active_shut)
    if args.setup_search:
        head = ranks[: args.setup_candidates]
        tail = ranks[args.setup_candidates :]
        ranks = [with_setup_routes(state, rank, max_states=args.setup_max_states) for rank in head] + tail
        ranks = sorted(
            ranks,
            key=lambda item: (
                -item.score,
                item.win_distance if item.win_distance is not None else 9999,
                item.best_setup_distance if item.best_setup_distance is not None else 9999,
                -item.external_gain,
                item.coord[1],
                item.coord[0],
            ),
        )

    if args.json:
        print(
            json.dumps(
                {
                    "level": f"{meta.get('world')}/{meta.get('level')}",
                    "name": meta.get("level_name"),
                    "turn": meta.get("turn"),
                    "you": sorted(you),
                    "forbidden_actor_moves": sorted(forbidden, key=lambda item: (item[0][1], item[0][0], item[1])),
                    "targets": [rank_to_dict(rank) for rank in ranks[: args.top]],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(f"level={meta.get('world')}/{meta.get('level')} name={meta.get('level_name')} turn={meta.get('turn')}")
    print("you=" + ", ".join(sorted(you)))
    if forbidden:
        print(
            "forbidden_actor_moves="
            + "; ".join(f"{coord}->{move}" for coord, move in sorted(forbidden, key=lambda item: (item[0][1], item[0][0], item[1])))
        )
    else:
        print("forbidden_actor_moves=<none>")
    print()
    print("breakout_targets:")
    if not ranks:
        print("  <none>")
        return 0
    for index, rank in enumerate(ranks[: args.top], start=1):
        print(
            f"{index}. score={rank.score} {rank.subject}@{rank.coord} "
            f"active_shut={rank.active_shut} reach_gain={rank.reachable_gain} external_gain={rank.external_gain} "
            f"win_dist={rank.win_distance if rank.win_distance is not None else '<none>'} "
            f"setup_dist={rank.best_setup_distance if rank.best_setup_distance is not None else '<none>'}"
        )
        print(f"   gate=from {list(rank.before_neighbors) or '<none>'} to {list(rank.new_neighbors) or '<none>'}")
        print(f"   collision={format_slots(rank.collision_slots)}")
        if not rank.active_shut:
            print(f"   rule_needed={rank.subject} is shut")
        if rank.collision_slots:
            print("   verify=after collision, run baba_action_check.py '<push>' --expect-disappeared '<tool>' --expect-disappeared '" + rank.subject + "'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
