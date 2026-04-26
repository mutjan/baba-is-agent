#!/usr/bin/env python3
"""Search Baba Is You routes with a generic macro-push model.

The important lesson from level 6 is not its final coordinates. The reusable
method is:

1. Derive blockers from active rules instead of object appearance.
2. Keep only relevant movable text in the search state.
3. Search macro pushes: walk to a push position, push one text chain one tile.
4. Preserve the current YOU rule while trying to build a requested rule.

This is still a conservative solver. It handles text-moving rule construction
well, but does not yet model moving non-text PUSH objects or multiple YOU units.
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
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
Coord = tuple[int, int]
Pattern = tuple[tuple[str, tuple[Coord, ...]], ...]
DIRS = (
    ("up", (0, -1)),
    ("down", (0, 1)),
    ("left", (-1, 0)),
    ("right", (1, 0)),
)
MAX_DISTANCE = 1_000_000


@dataclass(frozen=True)
class TextUnit:
    label: str
    word: str
    coord: tuple[int, int]


@dataclass(frozen=True)
class LevelData:
    world: str
    level: str
    name: str
    width: int
    height: int
    positions: dict[str, list[tuple[int, int, int]]]
    rules: list[tuple[str, tuple[int, int], str, str, str]]


@dataclass(frozen=True)
class SearchConfig:
    goal_subject: str
    goal_property: str
    preserve_you: bool
    touch_win: bool
    max_states: int
    heuristic_weight: int
    pattern_margin: int


@dataclass(frozen=True)
class SearchProblem:
    level: LevelData
    actor_name: str
    start_actor: tuple[int, int]
    selected: tuple[TextUnit, ...]
    fixed: tuple[TextUnit, ...]
    start_boxes: tuple[tuple[int, int], ...]
    config: SearchConfig
    target_patterns: tuple[Pattern, ...]
    target_assignments: tuple[tuple[tuple[int, Coord], ...], ...]


State = tuple[tuple[int, int], tuple[tuple[int, int], ...]]


@dataclass(frozen=True)
class PushOption:
    move: str
    preserves_you: bool
    resulting_rules: tuple[tuple[str, str], ...]


def compress_moves(route: list[str]) -> str:
    parts: list[list[str | int]] = []
    for move in route:
        if parts and parts[-1][0] == move:
            parts[-1][1] = int(parts[-1][1]) + 1
        else:
            parts.append([move, 1])
    return ",".join(f"{move}*{count}" if count != 1 else str(move) for move, count in parts)


def rule_coords(direction: str, start: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    dx, dy = (1, 0) if direction == "H" else (0, 1)
    x, y = start
    return (x, y), (x + dx, y + dy), (x + 2 * dx, y + 2 * dy)


def load_level(
    game_root: Path,
    save_dir: Path,
    world_arg: str | None,
    level_arg: str | None,
) -> LevelData:
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
    return LevelData(world, level, name, width, height, positions, rules)


def text_units(positions: dict[str, list[tuple[int, int, int]]]) -> tuple[TextUnit, ...]:
    units: list[TextUnit] = []
    word_counts: dict[str, int] = defaultdict(int)
    for name, coords in sorted(positions.items()):
        if not name.startswith("text_"):
            continue
        word = name.removeprefix("text_")
        for x, y, _layer in coords:
            index = word_counts[word]
            word_counts[word] += 1
            units.append(TextUnit(f"{word}#{index}", word, (x, y)))
    return tuple(sorted(units, key=lambda unit: (unit.coord[1], unit.coord[0], unit.label)))


def text_at(units: tuple[TextUnit, ...], coord: tuple[int, int]) -> TextUnit | None:
    for unit in units:
        if unit.coord == coord:
            return unit
    return None


def text_unit_map(units: tuple[TextUnit, ...]) -> dict[tuple[int, int], TextUnit]:
    return {unit.coord: unit for unit in units}


def current_you_rule(level: LevelData, units: tuple[TextUnit, ...]) -> tuple[str, tuple[TextUnit, TextUnit, TextUnit]]:
    you_rules = [rule for rule in level.rules if rule[4] == "you"]
    if not you_rules:
        raise SystemExit("No initial YOU rule found")

    direction, start, subject, _middle, _prop = you_rules[0]
    coords = rule_coords(direction, start)
    rule_units = tuple(text_at(units, coord) for coord in coords)
    if any(unit is None for unit in rule_units):
        raise SystemExit(f"Could not map YOU rule text units at {coords}")
    first, middle, last = rule_units
    assert first is not None and middle is not None and last is not None
    return subject, (first, middle, last)


def one_object_coord(level: LevelData, name: str) -> tuple[int, int]:
    coords = level.positions.get(name, [])
    if len(coords) != 1:
        raise SystemExit(f"Expected exactly one current YOU object '{name}', found {len(coords)}")
    x, y, _layer = coords[0]
    return (x, y)


def text_rules_from_coords(
    units: tuple[TextUnit, ...],
    coords_by_label: dict[str, Coord],
) -> tuple[tuple[str, str], ...]:
    words_by_coord: dict[Coord, list[str]] = defaultdict(list)
    for unit in units:
        words_by_coord[coords_by_label[unit.label]].append(unit.word)

    rules: set[tuple[str, str]] = set()
    for coord, first_words in words_by_coord.items():
        x, y = coord
        for _name, (dx, dy) in (("right", (1, 0)), ("down", (0, 1))):
            middle = (x + dx, y + dy)
            last = (x + 2 * dx, y + 2 * dy)
            if "is" not in words_by_coord.get(middle, []):
                continue
            for first in first_words:
                for prop in words_by_coord.get(last, []):
                    rules.add((first, prop))
    return tuple(sorted(rules))


def initial_rule_units(
    level: LevelData,
    units: tuple[TextUnit, ...],
) -> list[tuple[str, tuple[int, int], str, str, str, tuple[TextUnit, TextUnit, TextUnit]]]:
    result = []
    for direction, start, first, middle, last in level.rules:
        coords = rule_coords(direction, start)
        mapped = tuple(text_at(units, coord) for coord in coords)
        if any(unit is None for unit in mapped):
            continue
        first_unit, middle_unit, last_unit = mapped
        assert first_unit is not None and middle_unit is not None and last_unit is not None
        result.append((direction, start, first, middle, last, (first_unit, middle_unit, last_unit)))
    return result


def object_coords(level: LevelData, names: set[str]) -> set[Coord]:
    coords: set[Coord] = set()
    for name in names:
        coords.update((x, y) for x, y, _layer in level.positions.get(name, []))
    return coords


def initial_rule_sets(level: LevelData) -> tuple[set[str], set[str], set[str], set[str]]:
    stop_subjects = {first for _direction, _start, first, _middle, last in level.rules if last == "stop"}
    hot_subjects = {first for _direction, _start, first, _middle, last in level.rules if last == "hot"}
    melt_subjects = {first for _direction, _start, first, _middle, last in level.rules if last == "melt"}
    defeat_subjects = {first for _direction, _start, first, _middle, last in level.rules if last == "defeat"}
    return stop_subjects, hot_subjects, melt_subjects, defeat_subjects


def actor_blockers(level: LevelData, actor_name: str, units: tuple[TextUnit, ...]) -> set[Coord]:
    stop_subjects, hot_subjects, melt_subjects, defeat_subjects = initial_rule_sets(level)
    blockers = object_coords(level, stop_subjects | defeat_subjects)
    if actor_name in melt_subjects:
        blockers.update(object_coords(level, hot_subjects))
    blockers.update(unit.coord for unit in units)
    return blockers


def push_blockers(level: LevelData) -> set[Coord]:
    stop_subjects, _hot_subjects, _melt_subjects, _defeat_subjects = initial_rule_sets(level)
    return object_coords(level, stop_subjects)


def reachable_initial_actor(
    level: LevelData,
    actor_name: str,
    start: Coord,
    units: tuple[TextUnit, ...],
) -> set[Coord]:
    blockers = actor_blockers(level, actor_name, units)
    queue = deque([start])
    seen = {start}
    while queue:
        coord = queue.popleft()
        for _name, (dx, dy) in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if (
                nxt in seen
                or not (1 <= nxt[0] <= level.width - 2 and 1 <= nxt[1] <= level.height - 2)
                or nxt in blockers
            ):
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def initial_push_options(
    level: LevelData,
    actor_name: str,
    start: Coord,
    units: tuple[TextUnit, ...],
    unit: TextUnit,
) -> tuple[PushOption, ...]:
    reachable = reachable_initial_actor(level, actor_name, start, units)
    coord_to_unit = text_unit_map(units)
    text_coords = set(coord_to_unit)
    blockers = push_blockers(level)
    base_coords = {candidate.label: candidate.coord for candidate in units}
    options: list[PushOption] = []

    for move, (dx, dy) in DIRS:
        stand = (unit.coord[0] - dx, unit.coord[1] - dy)
        if stand not in reachable:
            continue

        chain: list[TextUnit] = []
        cursor = unit.coord
        while cursor in coord_to_unit:
            chain.append(coord_to_unit[cursor])
            cursor = (cursor[0] + dx, cursor[1] + dy)
        if (
            not (1 <= cursor[0] <= level.width - 2 and 1 <= cursor[1] <= level.height - 2)
            or cursor in blockers
            or cursor in text_coords
        ):
            continue

        next_coords = dict(base_coords)
        for chain_unit in chain:
            x, y = next_coords[chain_unit.label]
            next_coords[chain_unit.label] = (x + dx, y + dy)
        next_rules = text_rules_from_coords(units, next_coords)
        options.append(
            PushOption(
                move=move,
                preserves_you=(actor_name, "you") in next_rules,
                resulting_rules=next_rules,
            )
        )
    return tuple(options)


def rule_mobility_lines(level: LevelData) -> list[str]:
    units = text_units(level.positions)
    actor_name, _you_units = current_you_rule(level, units)
    start = one_object_coord(level, actor_name)
    lines = [f"rule_mobility_actor={actor_name}@{start}"]
    for direction, start_coord, first, middle, last, rule_units in initial_rule_units(level, units):
        option_bits = []
        for unit in rule_units:
            options = initial_push_options(level, actor_name, start, units, unit)
            if not options:
                continue
            moves = ",".join(
                f"{option.move}{'*' if option.preserves_you else '!'}"
                for option in options
            )
            option_bits.append(f"{unit.word}#{unit.label.split('#')[-1]}@{unit.coord}:{moves}")
        status = "fixed" if not option_bits else "pushable"
        lines.append(
            f"  {direction} {start_coord}: {first} is {last} -> {status}"
            + (f" ({'; '.join(option_bits)})" if option_bits else "")
        )
    lines.append("  legend: '*' keeps current YOU active; '!' breaks current YOU")
    return lines


def all_rule_triples(
    width: int,
    height: int,
    *,
    window: tuple[int, int, int, int] | None,
) -> tuple[tuple[Coord, Coord, Coord], ...]:
    if window is None:
        min_x, max_x, min_y, max_y = 1, width - 2, 1, height - 2
    else:
        min_x, max_x, min_y, max_y = window

    triples: list[tuple[Coord, Coord, Coord]] = []
    for x in range(min_x, max_x + 1):
        for y in range(min_y, max_y + 1):
            for _name, (dx, dy) in (("right", (1, 0)), ("down", (0, 1))):
                first = (x, y)
                middle = (x + dx, y + dy)
                last = (x + 2 * dx, y + 2 * dy)
                if (
                    1 <= last[0] <= width - 2
                    and 1 <= last[1] <= height - 2
                    and min_x <= middle[0] <= max_x
                    and min_y <= middle[1] <= max_y
                    and min_x <= last[0] <= max_x
                    and min_y <= last[1] <= max_y
                ):
                    triples.append((first, middle, last))
    return tuple(triples)


def can_satisfy_pattern(
    pattern: dict[str, set[Coord]],
    selected: tuple[TextUnit, ...],
    fixed: tuple[TextUnit, ...],
) -> bool:
    selected_count: dict[str, int] = defaultdict(int)
    fixed_coords: dict[str, set[Coord]] = defaultdict(set)
    for unit in selected:
        selected_count[unit.word] += 1
    for unit in fixed:
        fixed_coords[unit.word].add(unit.coord)

    for word, coords in pattern.items():
        unsatisfied = {coord for coord in coords if coord not in fixed_coords.get(word, set())}
        if len(unsatisfied) > selected_count.get(word, 0):
            return False
    return True


def freeze_pattern(pattern: dict[str, set[Coord]]) -> Pattern:
    return tuple(sorted((word, tuple(sorted(coords))) for word, coords in pattern.items()))


def build_target_patterns(
    level: LevelData,
    actor_name: str,
    selected: tuple[TextUnit, ...],
    fixed: tuple[TextUnit, ...],
    config: SearchConfig,
) -> tuple[Pattern, ...]:
    relevant_words = {actor_name, "is", "you", config.goal_subject, config.goal_property}
    relevant_coords = [unit.coord for unit in selected if unit.word in relevant_words]
    if relevant_coords:
        xs = [coord[0] for coord in relevant_coords]
        ys = [coord[1] for coord in relevant_coords]
        window = (
            max(1, min(xs) - config.pattern_margin),
            min(level.width - 2, max(xs) + config.pattern_margin),
            max(1, min(ys) - config.pattern_margin),
            min(level.height - 2, max(ys) + config.pattern_margin),
        )
    else:
        window = None

    triples = all_rule_triples(level.width, level.height, window=window)
    patterns: list[Pattern] = []
    for you_first, you_is, you_last in triples:
        for goal_first, goal_is, goal_last in triples:
            pattern: dict[str, set[Coord]] = defaultdict(set)
            if config.preserve_you:
                pattern[actor_name].add(you_first)
                pattern["is"].add(you_is)
                pattern["you"].add(you_last)
            pattern[config.goal_subject].add(goal_first)
            pattern["is"].add(goal_is)
            pattern[config.goal_property].add(goal_last)
            if can_satisfy_pattern(pattern, selected, fixed):
                patterns.append(freeze_pattern(pattern))
    return tuple(patterns)


def assignment_options_for_word(
    word: str,
    targets: tuple[Coord, ...],
    selected: tuple[TextUnit, ...],
    fixed: tuple[TextUnit, ...],
) -> list[tuple[tuple[int, Coord], ...]]:
    fixed_coords = {unit.coord for unit in fixed if unit.word == word}
    remaining = tuple(coord for coord in targets if coord not in fixed_coords)
    selected_indices = tuple(index for index, unit in enumerate(selected) if unit.word == word)
    if len(remaining) > len(selected_indices):
        return []
    if not remaining:
        return [()]
    return [
        tuple(zip(indices, remaining))
        for indices in itertools.permutations(selected_indices, len(remaining))
    ]


def build_target_assignments(
    patterns: tuple[Pattern, ...],
    selected: tuple[TextUnit, ...],
    fixed: tuple[TextUnit, ...],
) -> tuple[tuple[tuple[int, Coord], ...], ...]:
    assignments: list[tuple[tuple[int, Coord], ...]] = []
    for pattern in patterns:
        per_word_options: list[list[tuple[tuple[int, Coord], ...]]] = []
        for word, targets in pattern:
            options = assignment_options_for_word(word, targets, selected, fixed)
            if not options:
                per_word_options = []
                break
            per_word_options.append(options)
        for product in itertools.product(*per_word_options):
            merged: dict[int, Coord] = {}
            ok = True
            for option in product:
                for index, coord in option:
                    if index in merged and merged[index] != coord:
                        ok = False
                        break
                    merged[index] = coord
                if not ok:
                    break
            if ok:
                assignments.append(tuple(sorted(merged.items())))
    return tuple(dict.fromkeys(assignments))


def build_problem(
    level: LevelData,
    config: SearchConfig,
    *,
    extra_words: list[str],
    all_is: bool,
) -> SearchProblem:
    units = text_units(level.positions)
    actor_name, you_units = current_you_rule(level, units)

    selected_labels = {unit.label for unit in you_units}
    needed_words = {config.goal_subject, config.goal_property, *extra_words}
    if all_is:
        needed_words.add("is")
    for unit in units:
        if unit.word in needed_words:
            selected_labels.add(unit.label)

    selected = tuple(unit for unit in units if unit.label in selected_labels)
    fixed = tuple(unit for unit in units if unit.label not in selected_labels)
    start_boxes = tuple(unit.coord for unit in selected)
    start_actor = one_object_coord(level, actor_name)
    patterns = build_target_patterns(level, actor_name, selected, fixed, config)
    if not patterns:
        raise SystemExit(
            "No candidate target patterns can be built with the selected text. "
            "Try --all-is or --select-text WORD."
        )
    assignments = build_target_assignments(patterns, selected, fixed)
    if not assignments:
        raise SystemExit(
            "No target assignments can be built with the selected text. "
            "Try --all-is or --select-text WORD."
        )
    return SearchProblem(level, actor_name, start_actor, selected, fixed, start_boxes, config, patterns, assignments)


def text_positions(problem: SearchProblem, boxes: tuple[tuple[int, int], ...]) -> dict[str, tuple[str, tuple[int, int]]]:
    positions: dict[str, tuple[str, tuple[int, int]]] = {}
    for unit, coord in zip(problem.selected, boxes):
        positions[unit.label] = (unit.word, coord)
    for unit in problem.fixed:
        positions[unit.label] = (unit.word, unit.coord)
    return positions


def active_text_rules(
    problem: SearchProblem, boxes: tuple[tuple[int, int], ...]
) -> list[tuple[tuple[int, int], str, str]]:
    coord_words: dict[tuple[int, int], list[str]] = defaultdict(list)
    for word, coord in text_positions(problem, boxes).values():
        coord_words[coord].append(word)

    rules: list[tuple[tuple[int, int], str, str]] = []
    for coord, first_words in coord_words.items():
        x, y = coord
        for _name, (dx, dy) in DIRS:
            middle_coord = (x + dx, y + dy)
            last_coord = (x + 2 * dx, y + 2 * dy)
            if "is" not in coord_words.get(middle_coord, []):
                continue
            for first in first_words:
                for last in coord_words.get(last_coord, []):
                    rules.append((coord, first, last))
    return rules


def has_text_rule(problem: SearchProblem, boxes: tuple[tuple[int, int], ...], subject: str, prop: str) -> bool:
    return any(first == subject and last == prop for _coord, first, last in active_text_rules(problem, boxes))


def semantic_blockers(problem: SearchProblem, boxes: tuple[tuple[int, int], ...]) -> set[tuple[int, int]]:
    stop_subjects = {first for _coord, first, last in active_text_rules(problem, boxes) if last == "stop"}
    blockers: set[tuple[int, int]] = set()
    for subject in stop_subjects:
        blockers.update((x, y) for x, y, _layer in problem.level.positions.get(subject, []))
    blockers.update(unit.coord for unit in problem.fixed)
    return blockers


def in_bounds(problem: SearchProblem, coord: tuple[int, int]) -> bool:
    x, y = coord
    return 1 <= x <= problem.level.width - 2 and 1 <= y <= problem.level.height - 2


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
    problem: SearchProblem,
    actor: tuple[int, int],
    boxes: tuple[tuple[int, int], ...],
) -> dict[tuple[int, int], tuple[tuple[int, int] | None, str | None]]:
    occupied = set(boxes) | semantic_blockers(problem, boxes)
    queue = deque([actor])
    prev: dict[tuple[int, int], tuple[tuple[int, int] | None, str | None]] = {actor: (None, None)}
    while queue:
        coord = queue.popleft()
        for name, (dx, dy) in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if nxt in prev or not in_bounds(problem, nxt) or nxt in occupied:
                continue
            prev[nxt] = (coord, name)
            queue.append(nxt)
    return prev


def target_rule_heuristic(problem: SearchProblem, boxes: tuple[tuple[int, int], ...]) -> int:
    goal_ok = has_text_rule(problem, boxes, problem.config.goal_subject, problem.config.goal_property)
    you_ok = (not problem.config.preserve_you) or has_text_rule(problem, boxes, problem.actor_name, "you")
    if goal_ok and you_ok:
        return 0

    best = MAX_DISTANCE
    for assignment in problem.target_assignments:
        distance = sum(
            abs(boxes[index][0] - target[0]) + abs(boxes[index][1] - target[1])
            for index, target in assignment
        )
        best = min(best, distance)
    return best


def final_walk_to_goal(problem: SearchProblem, actor: tuple[int, int], boxes: tuple[tuple[int, int], ...]) -> list[str] | None:
    if not problem.config.touch_win:
        return []
    if problem.config.goal_property != "win":
        return []

    targets = {
        (x, y)
        for x, y, _layer in problem.level.positions.get(problem.config.goal_subject, [])
    }
    if not targets:
        return []

    prev = reachable(problem, actor, boxes)
    best: list[str] | None = None
    for target in targets:
        route = recover_path(prev, target)
        if route is not None and (best is None or len(route) < len(best)):
            best = route
    return best


def solve(problem: SearchProblem) -> tuple[list[str], int, State]:
    start: State = (problem.start_actor, problem.start_boxes)
    queue: list[tuple[int, int, int, State]] = []
    counter = itertools.count()
    first_h = target_rule_heuristic(problem, problem.start_boxes)
    heapq.heappush(queue, (problem.config.heuristic_weight * first_h, 0, next(counter), start))
    parent: dict[State, tuple[State | None, list[str] | None]] = {start: (None, None)}
    cost = {start: 0}
    seen = 0

    while queue and seen < problem.config.max_states:
        _priority, route_cost, _count, state = heapq.heappop(queue)
        if route_cost != cost[state]:
            continue
        seen += 1
        actor, boxes = state

        goal_ok = has_text_rule(problem, boxes, problem.config.goal_subject, problem.config.goal_property)
        you_ok = (not problem.config.preserve_you) or has_text_rule(problem, boxes, problem.actor_name, "you")
        if goal_ok and you_ok:
            final_walk = final_walk_to_goal(problem, actor, boxes)
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

        prev = reachable(problem, actor, boxes)
        occupied = {coord: index for index, coord in enumerate(boxes)}
        blockers = semantic_blockers(problem, boxes)
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
                if not in_bounds(problem, cursor) or cursor in blockers:
                    continue

                next_boxes = list(boxes)
                for chain_index in reversed(chain):
                    bx, by = next_boxes[chain_index]
                    next_boxes[chain_index] = (bx + dx, by + dy)
                next_boxes_tuple = tuple(next_boxes)
                if len(set(next_boxes_tuple)) != len(next_boxes_tuple):
                    continue
                if problem.config.preserve_you and not has_text_rule(problem, next_boxes_tuple, problem.actor_name, "you"):
                    continue

                walk = recover_path(prev, stand)
                assert walk is not None
                next_state: State = (pos, next_boxes_tuple)
                next_cost = route_cost + len(walk) + 1
                if next_cost >= cost.get(next_state, sys.maxsize):
                    continue
                cost[next_state] = next_cost
                parent[next_state] = (state, [*walk, move])
                heuristic = target_rule_heuristic(problem, next_boxes_tuple)
                heapq.heappush(
                    queue,
                    (
                        next_cost + problem.config.heuristic_weight * heuristic,
                        next_cost,
                        next(counter),
                        next_state,
                    ),
                )

    raise SystemExit(f"No route found after {seen} states")


def print_analysis(problem: SearchProblem) -> None:
    print(f"world={problem.level.world} level={problem.level.level} name={problem.level.name}")
    print("initial_rules=" + "; ".join(f"{a} {b} {c}" for _d, _p, a, b, c in problem.level.rules))
    print("initial_rule_mobility:")
    for line in rule_mobility_lines(problem.level):
        print(line)
    print(f"current_you={problem.actor_name} is you actor={problem.start_actor}")
    print(f"goal={problem.config.goal_subject} is {problem.config.goal_property}")
    print("selected_text=" + ", ".join(f"{unit.label}:{unit.word}@{unit.coord}" for unit in problem.selected))
    print(f"fixed_text_count={len(problem.fixed)}")
    print(f"target_patterns={len(problem.target_patterns)}")
    print(f"target_assignments={len(problem.target_assignments)}")
    blockers = sorted(semantic_blockers(problem, problem.start_boxes))
    print("initial_blockers=" + ", ".join(str(coord) for coord in blockers))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--game-root", type=Path, help="Override configured Worlds directory")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--world", help="World folder. Defaults to current save world.")
    parser.add_argument("--level", help="Level id. Defaults to current save level.")
    parser.add_argument(
        "--make-rule",
        nargs=3,
        metavar=("SUBJECT", "IS", "PROPERTY"),
        default=("flag", "is", "win"),
        help="Rule to build, e.g. --make-rule flag is win",
    )
    parser.add_argument(
        "--select-text",
        action="append",
        default=[],
        metavar="WORD",
        help="Also include all text_WORD blocks in the movable search state.",
    )
    parser.add_argument("--all-is", action="store_true", help="Include every text_is block as movable")
    parser.add_argument("--allow-break-you", action="store_true", help="Do not require the initial YOU rule to stay active")
    parser.add_argument("--no-touch-win", action="store_true", help="Stop after building the requested rule")
    parser.add_argument("--max-states", type=int, default=250_000)
    parser.add_argument(
        "--heuristic-weight",
        type=int,
        default=4,
        help="Higher values make the search faster and greedier.",
    )
    parser.add_argument("--analyze", action="store_true", help="Print the derived search problem without searching")
    parser.add_argument(
        "--pattern-margin",
        type=int,
        default=2,
        help="Search target rule patterns inside the relevant text bounding box plus this margin.",
    )
    parser.add_argument("--execute", action="store_true", help="Send the found route")
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay used with --execute. Defaults to input_delay in baba_config.json.",
    )
    args = parser.parse_args()

    subject, middle, prop = (part.lower() for part in args.make_rule)
    if middle != "is":
        raise SystemExit("--make-rule must be shaped like: SUBJECT is PROPERTY")

    config = load_config(args.config)
    game_root = args.game_root or config.game_root
    save_dir = args.save_dir or config.save_dir
    delay = args.delay if args.delay is not None else config.input_delay
    level = load_level(game_root, save_dir, args.world, args.level)
    search_config = SearchConfig(
        goal_subject=subject,
        goal_property=prop,
        preserve_you=not args.allow_break_you,
        touch_win=not args.no_touch_win,
        max_states=args.max_states,
        heuristic_weight=args.heuristic_weight,
        pattern_margin=args.pattern_margin,
    )
    problem = build_problem(level, search_config, extra_words=args.select_text, all_is=args.all_is)
    print_analysis(problem)

    if args.analyze:
        return 0

    route, seen, final_state = solve(problem)
    compact = compress_moves(route)
    actor, boxes = final_state
    print(f"states={seen}")
    print(f"steps={len(route)}")
    print(f"moves={compact}")
    print(f"final_actor={actor}")
    print(
        "final_selected_text="
        + ", ".join(f"{unit.label}:{coord}" for unit, coord in zip(problem.selected, boxes))
    )
    print(f"command=python3 scripts/baba_send_keys.py '{compact}' --delay {delay}")

    if args.execute:
        subprocess.run(
            [sys.executable, str(ROOT / "baba_send_keys.py"), compact, "--delay", str(delay)],
            check=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
