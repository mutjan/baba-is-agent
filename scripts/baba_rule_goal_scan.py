#!/usr/bin/env python3
"""Scan for the next small rule delta likely needed before solving a Baba level.

This is not a route solver. It deliberately ignores exact walking/pushing paths
and ranks rule-level goals such as adding WIN, removing a hazard, or preparing an
OPEN/SHUT breakout. The next step should still be a short action_check segment.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_loop_guard import check_allowed, record_analysis
from read_baba_state import load_state


Coord = tuple[int, int]
DIR_MOVES: tuple[tuple[str, Coord], ...] = (
    ("up", (0, -1)),
    ("right", (1, 0)),
    ("down", (0, 1)),
    ("left", (-1, 0)),
)
DIRS: tuple[Coord, ...] = tuple(delta for _name, delta in DIR_MOVES)
META_SUBJECTS = {"cursor", "empty", "level", "text"}
HAZARD_PROPS = {"defeat", "sink", "hot", "melt"}
RULE_DELTA_PROPS = {"stop", "shut", "open", "push", "you", "win", "move"} | HAZARD_PROPS


@dataclass(frozen=True)
class Unit:
    name: str
    coord: Coord
    unit_type: str
    word: str | None
    visible: bool = True


@dataclass
class Candidate:
    score: int
    kind: str
    delta: str
    rule: str | None
    reasons: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    search_command: str | None = None
    action_check_expect: str | None = None

    def sort_key(self) -> tuple[int, str, str]:
        return (-self.score, self.kind, self.delta)


@dataclass(frozen=True)
class RuleInstance:
    subject: str
    prop: str
    direction: str
    coords: tuple[Coord, Coord, Coord]


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def rule_text(subject: str, prop: str) -> str:
    return f"{subject} is {prop}"


def turn_int(meta: dict[str, Any]) -> int:
    try:
        return int(meta.get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def load_current_state(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    path = args.path.expanduser().resolve() if args.path else None
    return load_state(path, wait=args.wait, timeout=args.timeout, since_mtime=None, save_dir=save_dir)


def text_word(raw: dict[str, Any] | Unit) -> str:
    if isinstance(raw, Unit):
        if raw.word:
            return raw.word
        name = raw.name
    else:
        word = norm(raw.get("word"))
        if word:
            return word
        name = norm(raw.get("name"))
    return name.removeprefix("text_") if name.startswith("text_") else name


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
                coord=(int(x), int(y)),
                unit_type=norm(raw.get("unit_type")),
                word=norm(raw.get("word")) or None,
                visible=bool(raw.get("visible", True)),
            )
        )
    return units


def is_text(unit: Unit) -> bool:
    return unit.unit_type == "text" or unit.name.startswith("text_") or unit.word is not None


def is_pushable(unit: Unit, props: dict[str, set[str]]) -> bool:
    return is_text(unit) or "push" in props.get(unit.name, set())


def in_bounds(width: int, height: int, coord: Coord) -> bool:
    x, y = coord
    return 1 <= x <= width - 2 and 1 <= y <= height - 2


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    units = visible_units(state)
    objects: collections.Counter[str] = collections.Counter()
    text_positions: dict[str, list[Coord]] = collections.defaultdict(list)
    for unit in units:
        if is_text(unit):
            word = text_word(unit)
            if word:
                text_positions[word].append(unit.coord)
        else:
            objects[unit.name] += 1

    active_rules: set[tuple[str, str]] = set()
    visible_rules: set[tuple[str, str]] = set()
    props: dict[str, set[str]] = collections.defaultdict(set)
    for rule in state.get("rules", []):
        subject = norm(rule.get("target"))
        effect = norm(rule.get("effect"))
        if not subject or not effect:
            continue
        active_rules.add((subject, effect))
        props[subject].add(effect)
        if rule.get("visible", True):
            visible_rules.add((subject, effect))

    return {
        "meta": state.get("meta", {}),
        "units": units,
        "objects": objects,
        "text_positions": {word: sorted(coords) for word, coords in text_positions.items()},
        "text_words": set(text_positions),
        "active_rules": active_rules,
        "visible_rules": visible_rules,
        "props": props,
    }


def edge_text_warnings(summary: dict[str, Any]) -> list[str]:
    meta = summary["meta"]
    try:
        width = int(meta.get("room_width") or 0)
        height = int(meta.get("room_height") or 0)
    except (TypeError, ValueError):
        return []
    if width < 3 or height < 3:
        return []
    warnings: list[str] = []
    for word, coords in sorted(summary["text_positions"].items()):
        for x, y in coords:
            left = x == 1
            right = x == width - 2
            top = y == 1
            bottom = y == height - 2
            if not (left or right or top or bottom):
                continue
            locks: list[str] = []
            if left or right:
                locks.append("horizontal_locked")
            if top or bottom:
                locks.append("vertical_locked")
            if (left or right) and (top or bottom):
                locks.append("corner_locked")
            warnings.append(f"text_{word}@({x},{y}):{','.join(locks)}")
    return warnings


def text_units_by_coord(summary: dict[str, Any]) -> dict[Coord, list[Unit]]:
    by_coord: dict[Coord, list[Unit]] = collections.defaultdict(list)
    for unit in summary["units"]:
        if is_text(unit):
            by_coord[unit.coord].append(unit)
    return by_coord


def units_by_coord(summary: dict[str, Any]) -> dict[Coord, list[Unit]]:
    by_coord: dict[Coord, list[Unit]] = collections.defaultdict(list)
    for unit in summary["units"]:
        by_coord[unit.coord].append(unit)
    return by_coord


def visible_rule_instances(summary: dict[str, Any]) -> list[RuleInstance]:
    by_coord = text_units_by_coord(summary)
    instances: list[RuleInstance] = []
    for start, first_units in by_coord.items():
        x, y = start
        for direction, (dx, dy) in (("right", (1, 0)), ("down", (0, 1))):
            middle = (x + dx, y + dy)
            end = (x + 2 * dx, y + 2 * dy)
            middle_words = [text_word(unit) for unit in by_coord.get(middle, [])]
            if "is" not in middle_words:
                continue
            end_words = [text_word(unit) for unit in by_coord.get(end, [])]
            for first in first_units:
                subject = text_word(first)
                for prop in end_words:
                    instances.append(RuleInstance(subject, prop, direction, (start, middle, end)))
    return instances


def boundary_locks(summary: dict[str, Any], coord: Coord) -> list[str]:
    meta = summary["meta"]
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    x, y = coord
    locks: list[str] = []
    if width >= 3 and x in {1, width - 2}:
        locks.append("horizontal_locked")
    if height >= 3 and y in {1, height - 2}:
        locks.append("vertical_locked")
    if "horizontal_locked" in locks and "vertical_locked" in locks:
        locks.append("corner_locked")
    return locks


def push_slots_for_text_coords(summary: dict[str, Any], actors: list[str], coords: set[Coord]) -> list[str]:
    props: dict[str, set[str]] = summary["props"]
    reach = reachability(summary, props, actors)
    actor_reachable: set[Coord] = reach["reachable"]
    width = int(summary["meta"].get("room_width") or 0)
    height = int(summary["meta"].get("room_height") or 0)
    by_coord = units_by_coord(summary)
    stop_subjects = {subject for subject, values in props.items() if "stop" in values}
    slots: list[str] = []

    for coord in sorted(coords):
        for unit in by_coord.get(coord, []):
            if not is_text(unit):
                continue
            x, y = coord
            for move, (dx, dy) in DIR_MOVES:
                stand = (x - dx, y - dy)
                if stand not in actor_reachable:
                    continue
                cursor = coord
                while True:
                    pushers = [candidate for candidate in by_coord.get(cursor, []) if is_pushable(candidate, props)]
                    if not pushers:
                        break
                    cursor = (cursor[0] + dx, cursor[1] + dy)
                if not in_bounds(width, height, cursor):
                    continue
                tail_blocked = any(candidate.name in stop_subjects for candidate in by_coord.get(cursor, []))
                if tail_blocked:
                    continue
                slots.append(f"text_{text_word(unit)}@{coord}->{move}")
    return slots


def push_slots_for_words(summary: dict[str, Any], actors: list[str], words: set[str]) -> list[str]:
    coords: set[Coord] = set()
    for unit in summary["units"]:
        if is_text(unit) and text_word(unit) in words:
            coords.add(unit.coord)
    return push_slots_for_text_coords(summary, actors, coords)


def rule_text_feasibility(
    summary: dict[str, Any],
    actors: list[str],
    *,
    subject: str,
    prop: str,
    existing_rule: bool,
) -> tuple[int, list[str], list[str]]:
    risks: list[str] = []
    evidence: list[str] = []
    words = {subject, "is", prop}
    if existing_rule:
        instances = [
            item
            for item in visible_rule_instances(summary)
            if item.subject == subject and item.prop == prop
        ]
        coords = {coord for item in instances for coord in item.coords}
        if instances:
            evidence.append(
                "rule_text_instances="
                + ", ".join(f"{item.direction}:{item.coords}" for item in instances[:3])
            )
        else:
            coords = {
                unit.coord
                for unit in summary["units"]
                if is_text(unit) and text_word(unit) in words
            }
            risks.append("could not map active rule to a visible text triple")
    else:
        coords = {
            unit.coord
            for unit in summary["units"]
            if is_text(unit) and text_word(unit) in words
        }

    locked = [
        f"text@{coord}:{','.join(locks)}"
        for coord in sorted(coords)
        if (locks := boundary_locks(summary, coord))
    ]
    if locked:
        risks.append("rule text on boundary: " + "; ".join(locked[:4]))

    slots = push_slots_for_text_coords(summary, actors, coords)
    if slots:
        evidence.append("current_text_push_options=" + ", ".join(slots[:6]))
        return 0, evidence, risks

    penalty = 80 if existing_rule else 35
    risks.append("no current actor-reachable push slot found for this rule text")
    return penalty, evidence, risks


def add_rule_available(summary: dict[str, Any], subject: str, prop: str) -> bool:
    text_words: set[str] = summary["text_words"]
    return subject in text_words and "is" in text_words and prop in text_words


def add_rule_search_command(summary: dict[str, Any], subject: str, prop: str) -> str | None:
    if not add_rule_available(summary, subject, prop):
        return None
    live = "--from-live-state " if turn_int(summary["meta"]) > 0 else ""
    return (
        "python3 scripts/baba_search_route.py "
        f"{live}"
        f"--make-rule \"{rule_text(subject, prop)}\" "
        f"--select-text {subject} --select-text {prop} --all-is --no-touch-win --analyze"
    )


def replace_rule_subject_search_command(summary: dict[str, Any], subject: str, prop: str, instance: RuleInstance) -> str | None:
    if not add_rule_available(summary, subject, prop):
        return None
    live = "--from-live-state " if turn_int(summary["meta"]) > 0 else ""
    x, y = instance.coords[0]
    target_dir = "down" if instance.direction == "down" else "right"
    return (
        "python3 scripts/baba_search_route.py "
        f"{live}"
        f"--make-rule \"{rule_text(subject, prop)}\" "
        f"--select-text {subject} --select-text {prop} --all-is "
        f"--target-start {x},{y} --target-dir {target_dir} "
        "--no-touch-win --analyze"
    )


def props_without(summary: dict[str, Any], subject: str, prop: str) -> dict[str, set[str]]:
    copied = {key: set(values) for key, values in summary["props"].items()}
    copied.get(subject, set()).discard(prop)
    return collections.defaultdict(set, copied)


def actor_subjects(summary: dict[str, Any], actor_arg: str | None) -> list[str]:
    if actor_arg:
        return [norm(actor_arg)]
    subjects = sorted(subject for subject, props in summary["props"].items() if "you" in props and subject not in META_SUBJECTS)
    return subjects or ["baba"]


def movement_blockers(units: list[Unit], props: dict[str, set[str]], actors: set[str]) -> set[Coord]:
    stop_subjects = {subject for subject, values in props.items() if "stop" in values}
    push_subjects = {subject for subject, values in props.items() if "push" in values}
    hot_subjects = {subject for subject, values in props.items() if "hot" in values}
    melt_actors = bool(actors & {subject for subject, values in props.items() if "melt" in values})
    blockers: set[Coord] = set()
    for unit in units:
        if not is_text(unit) and unit.name in actors:
            continue
        unit_props = props.get(unit.name, set())
        if is_text(unit) or unit.name in stop_subjects or unit.name in push_subjects:
            blockers.add(unit.coord)
        if unit_props & {"defeat", "sink"}:
            blockers.add(unit.coord)
        if melt_actors and unit.name in hot_subjects:
            blockers.add(unit.coord)
    return blockers


def reachable(starts: list[Coord], *, width: int, height: int, blockers: set[Coord]) -> set[Coord]:
    queue = collections.deque(starts)
    seen = set(starts)
    while queue:
        coord = queue.popleft()
        for dx, dy in DIRS:
            nxt = (coord[0] + dx, coord[1] + dy)
            if nxt in seen or nxt in blockers or not in_bounds(width, height, nxt):
                continue
            seen.add(nxt)
            queue.append(nxt)
    return seen


def reachability(summary: dict[str, Any], props: dict[str, set[str]], actors: list[str]) -> dict[str, Any]:
    meta = summary["meta"]
    width = int(meta.get("room_width") or 0)
    height = int(meta.get("room_height") or 0)
    actor_set = set(actors)
    starts = [
        unit.coord
        for unit in summary["units"]
        if not is_text(unit) and unit.name in actor_set
    ]
    blockers = movement_blockers(summary["units"], props, actor_set)
    seen = reachable(starts, width=width, height=height, blockers=blockers) if starts and width >= 3 and height >= 3 else set()
    return {"starts": starts, "reachable": seen, "blockers": blockers, "width": width, "height": height}


def win_coords(summary: dict[str, Any], props: dict[str, set[str]]) -> list[tuple[str, Coord]]:
    wins = {subject for subject, values in props.items() if "win" in values and subject not in META_SUBJECTS}
    coords: list[tuple[str, Coord]] = []
    for unit in summary["units"]:
        if not is_text(unit) and unit.name in wins:
            coords.append((unit.name, unit.coord))
    return sorted(coords, key=lambda item: (item[0], item[1]))


def object_positions(summary: dict[str, Any], subject: str) -> list[Coord]:
    return sorted(
        unit.coord
        for unit in summary["units"]
        if not is_text(unit) and unit.name == subject
    )


def completion_status(summary: dict[str, Any], props: dict[str, set[str]], actors: list[str]) -> dict[str, Any]:
    reach = reachability(summary, props, actors)
    reachable_cells: set[Coord] = reach["reachable"]
    actor_set = set(actors)
    win_subjects = sorted(subject for subject, values in props.items() if "win" in values and subject not in META_SUBJECTS)
    self_win = sorted(actor_set & set(win_subjects))
    reachable_wins = [(name, coord) for name, coord in win_coords(summary, props) if coord in reachable_cells]
    return {
        "actors": actors,
        "actor_positions": reach["starts"],
        "win_subjects": win_subjects,
        "self_win_subjects": self_win,
        "reachable_win_objects": reachable_wins,
        "completion_rule_ready": bool(self_win or reachable_wins),
        "reachable_count": len(reachable_cells),
    }


def mechanic_warnings(summary: dict[str, Any]) -> list[str]:
    props: dict[str, set[str]] = summary["props"]
    push_sink = sorted(
        subject
        for subject, values in props.items()
        if subject not in META_SUBJECTS and {"push", "sink"} <= values
    )
    stop_subjects = sorted(
        subject
        for subject, values in props.items()
        if subject not in META_SUBJECTS and "stop" in values
    )
    if push_sink and stop_subjects:
        return [
            "PUSH+SINK objects cannot be pushed through STOP blockers; treat them as tools for non-STOP objects/hazards, "
            "or first remove/bypass STOP with SHUT+OPEN or by breaking X IS STOP. "
            f"push_sink={','.join(push_sink)} stop={','.join(stop_subjects)}"
        ]
    return []


def append_unique(candidates: list[Candidate], candidate: Candidate) -> None:
    key = (candidate.kind, candidate.delta, candidate.rule)
    for index, existing in enumerate(candidates):
        if (existing.kind, existing.delta, existing.rule) == key:
            if candidate.score > existing.score:
                candidates[index] = candidate
            return
    candidates.append(candidate)


def add_add_rule_candidate(
    candidates: list[Candidate],
    summary: dict[str, Any],
    *,
    score: int,
    subject: str,
    prop: str,
    reasons: list[str],
    evidence: list[str] | None = None,
    risks: list[str] | None = None,
    actors: list[str],
) -> None:
    rule = rule_text(subject, prop)
    candidate_risks = list(risks or [])
    if not add_rule_available(summary, subject, prop):
        missing = sorted({"is", subject, prop} - summary["text_words"])
        candidate_risks.append("missing visible text: " + ", ".join(missing))
        score -= 30
    else:
        penalty, feasibility_evidence, feasibility_risks = rule_text_feasibility(
            summary,
            actors,
            subject=subject,
            prop=prop,
            existing_rule=False,
        )
        score -= penalty
        candidate_risks.extend(feasibility_risks)
        candidate_evidence = list(evidence or []) + feasibility_evidence
        evidence = candidate_evidence
    append_unique(
        candidates,
        Candidate(
            score=score,
            kind="add_rule",
            delta=f"+ {rule}",
            rule=rule,
            reasons=reasons,
            evidence=evidence or [],
            risks=candidate_risks,
            search_command=add_rule_search_command(summary, subject, prop),
            action_check_expect=f"--expect-rule-added '{rule}'",
        ),
    )


def add_remove_rule_candidate(
    candidates: list[Candidate],
    summary: dict[str, Any],
    *,
    score: int,
    subject: str,
    prop: str,
    reasons: list[str],
    evidence: list[str] | None = None,
    risks: list[str] | None = None,
    visible: bool,
    actors: list[str],
) -> None:
    rule = rule_text(subject, prop)
    candidate_risks = list(risks or [])
    if not visible:
        score -= 15
        candidate_risks.append("rule is active but not visible in exported rule list")
    else:
        penalty, feasibility_evidence, feasibility_risks = rule_text_feasibility(
            summary,
            actors,
            subject=subject,
            prop=prop,
            existing_rule=True,
        )
        score -= penalty
        candidate_risks.extend(feasibility_risks)
        candidate_evidence = list(evidence or []) + feasibility_evidence
        evidence = candidate_evidence
    append_unique(
        candidates,
        Candidate(
            score=score,
            kind="remove_rule",
            delta=f"- {rule}",
            rule=rule,
            reasons=reasons,
            evidence=evidence or [],
            risks=candidate_risks,
            action_check_expect=f"--expect-rule-removed '{rule}'",
        ),
    )


def add_replace_rule_subject_candidate(
    candidates: list[Candidate],
    summary: dict[str, Any],
    *,
    score: int,
    subject: str,
    prop: str,
    old_subject: str,
    instance: RuleInstance,
    reasons: list[str],
    evidence: list[str] | None = None,
    risks: list[str] | None = None,
    actors: list[str],
) -> None:
    rule = rule_text(subject, prop)
    old_rule = rule_text(old_subject, prop)
    candidate_risks = list(risks or [])
    if not add_rule_available(summary, subject, prop):
        missing = sorted({"is", subject, prop} - summary["text_words"])
        candidate_risks.append("missing visible text: " + ", ".join(missing))
        score -= 30
    else:
        subject_text_coords = {
            unit.coord
            for unit in summary["units"]
            if is_text(unit) and text_word(unit) == subject
        }
        subject_slots = push_slots_for_text_coords(summary, actors, subject_text_coords)
        if instance.coords[0] in subject_text_coords:
            evidence = list(evidence or []) + [f"replacement_subject_already_at_target={instance.coords[0]}"]
        elif subject_slots:
            evidence = list(evidence or []) + ["replacement_subject_push_options=" + ", ".join(subject_slots[:6])]
        else:
            score -= 45
            candidate_risks.append(f"no current actor-reachable push slot found for text_{subject}")
        coords = set(instance.coords)
        coords.update(subject_text_coords)
        locked = [
            f"text@{coord}:{','.join(locks)}"
            for coord in sorted(coords)
            if (locks := boundary_locks(summary, coord))
        ]
        if locked:
            candidate_risks.append("rule text on boundary: " + "; ".join(locked[:4]))
        slots = push_slots_for_text_coords(summary, actors, coords)
        if slots:
            evidence = list(evidence or []) + ["current_text_push_options=" + ", ".join(slots[:8])]
        else:
            score -= 25
            candidate_risks.append("no current actor-reachable push slot found for replacement text")
    append_unique(
        candidates,
        Candidate(
            score=score,
            kind="replace_rule_subject",
            delta=f"replace {old_subject} with {subject}: + {rule}; - {old_rule}",
            rule=rule,
            reasons=reasons,
            evidence=evidence or [],
            risks=candidate_risks,
            search_command=replace_rule_subject_search_command(summary, subject, prop, instance),
            action_check_expect=f"--expect-rule-added '{rule}' --expect-rule-removed '{old_rule}'",
        ),
    )


def build_candidates(summary: dict[str, Any], actors: list[str]) -> tuple[list[Candidate], dict[str, Any]]:
    candidates: list[Candidate] = []
    props: dict[str, set[str]] = summary["props"]
    active_rules: set[tuple[str, str]] = summary["active_rules"]
    visible_rules: set[tuple[str, str]] = summary["visible_rules"]
    objects: collections.Counter[str] = summary["objects"]
    status = completion_status(summary, props, actors)
    base_reach = reachability(summary, props, actors)
    base_reachable: set[Coord] = base_reach["reachable"]

    if not status["actor_positions"]:
        append_unique(
            candidates,
            Candidate(
                score=120,
                kind="not_applicable",
                delta="no actor positions found",
                rule=None,
                reasons=[
                    "rule goal scan needs a concrete controllable actor in the current level state",
                    "this is often a map/sub-map state or the wrong --actor",
                ],
                evidence=["actors=" + ", ".join(actors)],
                risks=["use navigate_next/start_benchmark or pass --actor <object> after confirming the live state"],
            ),
        )
        return sorted(candidates, key=Candidate.sort_key), status

    if status["completion_rule_ready"]:
        evidence = []
        if status["self_win_subjects"]:
            evidence.append("self_win=" + ", ".join(status["self_win_subjects"]))
        if status["reachable_win_objects"]:
            evidence.append("reachable_win=" + ", ".join(f"{name}@{coord}" for name, coord in status["reachable_win_objects"]))
        append_unique(
            candidates,
            Candidate(
                score=110,
                kind="no_rule_change",
                delta="no rule delta needed",
                rule=None,
                reasons=["existing YOU/WIN conditions already look sufficient at rule level"],
                evidence=evidence,
                risks=["verify with a short contact/completion action; reachability is approximate"],
                action_check_expect="--expect-completion 3",
            ),
        )

    for subject, prop in sorted(active_rules):
        if subject in META_SUBJECTS or prop not in {"stop"} | HAZARD_PROPS:
            continue
        after_props = props_without(summary, subject, prop)
        after_status = completion_status(summary, after_props, actors)
        after_reach = reachability(summary, after_props, actors)
        gained = len(after_reach["reachable"] - base_reachable)
        score = 34
        reasons = [f"removing {rule_text(subject, prop)} changes movement risk/blocking at rule level"]
        evidence = [f"reachable_gain_if_removed={gained}"]
        risks = ["this only identifies a rule goal; verify by moving one text/rule piece with action_check"]
        if after_status["completion_rule_ready"] and not status["completion_rule_ready"]:
            score += 60
            reasons.append("existing WIN becomes reachable/ready after this rule disappears")
            evidence.append("win_after_removal=true")
        elif after_status["reachable_win_objects"]:
            score += 40
            reasons.append("WIN object remains in the reachable region after this rule disappears")
        if prop in HAZARD_PROPS:
            score += 18
            reasons.append(f"{subject} stops being {prop}")
        if prop == "stop":
            score += 10
            reasons.append(f"{subject} stops blocking free movement")
        if gained > 0:
            score += min(32, gained)
            reasons.append("actor reachable region expands")
        if subject in objects:
            evidence.append(f"{subject}_objects={objects[subject]}")
        add_remove_rule_candidate(
            candidates,
            summary,
            score=score,
            subject=subject,
            prop=prop,
            reasons=reasons,
            evidence=evidence,
            risks=risks,
            visible=(subject, prop) in visible_rules,
            actors=actors,
        )

    you_subjects = sorted(subject for subject, values in props.items() if "you" in values and subject not in META_SUBJECTS)
    win_subjects = sorted(subject for subject, values in props.items() if "win" in values and subject not in META_SUBJECTS)
    push_subjects = sorted(subject for subject, values in props.items() if "push" in values and subject not in META_SUBJECTS)
    stop_subjects = sorted(subject for subject, values in props.items() if "stop" in values and subject not in META_SUBJECTS)
    open_subjects = sorted(subject for subject, values in props.items() if "open" in values and subject not in META_SUBJECTS)
    shut_subjects = sorted(subject for subject, values in props.items() if "shut" in values and subject not in META_SUBJECTS)
    move_subjects = sorted(subject for subject, values in props.items() if "move" in values and subject not in META_SUBJECTS)

    for subject in win_subjects:
        if subject in move_subjects or (subject, "move") in active_rules:
            continue
        subject_coords = object_positions(summary, subject)
        if not subject_coords or "move" not in summary["text_words"]:
            continue
        reachable_coords = [coord for coord in subject_coords if coord in base_reachable]
        unreachable_coords = [coord for coord in subject_coords if coord not in base_reachable]
        score = 62
        reasons = [
            f"{subject} is already WIN",
            "adding MOVE can let the WIN object leave an enclosure or deliver itself as the next rule-level experiment",
        ]
        evidence = [f"{subject}_objects=" + ", ".join(str(coord) for coord in subject_coords[:6])]
        risks = [
            "MOVE is directional and stateful; after forming the rule, verify one tick with --expect-moved-delta or --expect-position",
            "do not assume movement helps if the first tick sends the WIN object into a pocket, hazard, or away from the actor",
        ]
        if unreachable_coords:
            score += 34
            reasons.append(f"{subject} WIN objects are outside current actor reachability")
            evidence.append("unreachable_" + subject + "=" + ", ".join(str(coord) for coord in unreachable_coords[:6]))
        if reachable_coords:
            score -= 12
            risks.append(f"{subject} already appears reachable; direct contact may be cheaper than adding MOVE")
            evidence.append("reachable_" + subject + "=" + ", ".join(str(coord) for coord in reachable_coords[:6]))
        if subject in push_subjects:
            score += 8
            reasons.append(f"{subject} is PUSH, so the moving WIN object may also be a manipulable phase target")
        add_add_rule_candidate(
            candidates,
            summary,
            score=score,
            subject=subject,
            prop="move",
            reasons=reasons,
            evidence=evidence,
            risks=risks,
            actors=actors,
        )

    for subject in sorted(set(win_subjects) | set(objects)):
        if subject in META_SUBJECTS:
            continue
        subject_coords = object_positions(summary, subject)
        if not subject_coords:
            continue
        unreachable_coords = [coord for coord in subject_coords if coord not in base_reachable]
        for target in you_subjects or actors:
            target = norm(target)
            if not target or target in META_SUBJECTS or subject == target or (subject, target) in active_rules:
                continue
            score = 52
            reasons = [
                f"transforming {subject} into current YOU subject {target} can create a controllable body before the final route is known"
            ]
            evidence = [
                f"{subject}_objects=" + ", ".join(str(coord) for coord in subject_coords[:6]),
                f"current_you_subject={target}",
            ]
            risks = [
                "stage goal, not a direct win proof; verify the transform with action_check before planning the next phase"
            ]
            if subject in win_subjects:
                score += 36
                reasons.append(f"{subject} is already WIN, so moving control to that object class is a meaningful phase change")
                risks.append(f"after {rule_text(subject, target)}, transformed objects may no longer count as {subject} for {rule_text(subject, 'win')}")
            if unreachable_coords:
                score += 34
                reasons.append(f"{subject} objects are outside current {target} reachability")
                evidence.append("unreachable_" + subject + "=" + ", ".join(str(coord) for coord in unreachable_coords[:6]))
            if subject in stop_subjects:
                score += 6
                reasons.append(f"{subject} is STOP, so the transform may also change a blocking object into controllable material")
            if subject in push_subjects:
                score += 4
                reasons.append(f"{subject} is PUSH, so it is already a manipulable object class")
            add_add_rule_candidate(
                candidates,
                summary,
                score=score,
                subject=subject,
                prop=target,
                reasons=reasons,
                evidence=evidence,
                risks=risks,
                actors=actors,
            )

    if not win_subjects or not status["completion_rule_ready"]:
        direct_subjects = sorted(set(you_subjects) | set(push_subjects) | set(objects))
        for subject in direct_subjects:
            if subject in META_SUBJECTS or (subject, "win") in active_rules:
                continue
            score = 56
            reasons = ["adding a WIN rule can satisfy the missing pass condition"]
            evidence: list[str] = []
            risks = ["do not search this as the final target if another blocker/hazard must be changed first"]
            if subject in you_subjects:
                score += 36
                reasons.append(f"{subject} is already YOU")
            if subject in objects:
                score += 8
                evidence.append(f"{subject}_objects={objects[subject]}")
            if subject in push_subjects:
                score += 6
                reasons.append(f"{subject} is pushable")
            if props.get(subject, set()) & HAZARD_PROPS:
                score -= 18
                risks.append(f"{subject} currently has hazard props: {','.join(sorted(props[subject] & HAZARD_PROPS))}")
            add_add_rule_candidate(
                candidates,
                summary,
                score=score,
                subject=subject,
                prop="win",
                reasons=reasons,
                evidence=evidence,
                risks=risks,
                actors=actors,
            )

    win_instances = [
        instance
        for instance in visible_rule_instances(summary)
        if instance.prop == "win" and instance.subject not in META_SUBJECTS
    ]
    if win_instances and not status["completion_rule_ready"]:
        replace_subjects = sorted(set(you_subjects) | set(push_subjects) | set(objects))
        actor_positions = set(status["actor_positions"])
        for instance in win_instances:
            old_subject = instance.subject
            old_reachable = bool(object_positions(summary, old_subject)) and any(
                coord in base_reachable for coord in object_positions(summary, old_subject)
            )
            for subject in replace_subjects:
                if (
                    subject in META_SUBJECTS
                    or subject == old_subject
                    or (subject, "win") in active_rules
                ):
                    continue
                subject_coords = object_positions(summary, subject)
                reachable_coords = [coord for coord in subject_coords if coord in base_reachable]
                touched_coords = [coord for coord in subject_coords if coord in actor_positions]
                score = 70
                reasons = [
                    f"existing {rule_text(old_subject, 'win')} has reusable IS/WIN text; replace only the subject text to make {rule_text(subject, 'win')}"
                ]
                evidence = [
                    f"replace_target={instance.direction}:{instance.coords}",
                    f"current_win_rule={rule_text(old_subject, 'win')}",
                ]
                risks = [
                    "this is a one-rule delta: verify the subject replacement with action_check before planning contact"
                ]
                if subject in you_subjects:
                    score += 24
                    reasons.append(f"{subject} is already YOU")
                if reachable_coords:
                    score += 18
                    evidence.append("reachable_" + subject + "=" + ", ".join(str(coord) for coord in reachable_coords[:6]))
                if touched_coords:
                    score += 28
                    reasons.append(f"a current YOU object is already on {subject}; replacement may complete after contact/update")
                    evidence.append("touched_" + subject + "=" + ", ".join(str(coord) for coord in touched_coords[:6]))
                if subject in push_subjects:
                    score += 8
                    reasons.append(f"{subject} is pushable")
                if old_reachable:
                    score -= 18
                    risks.append(f"{old_subject} WIN object already appears reachable; contact may be cheaper than replacement")
                if subject in stop_subjects:
                    score -= 10
                    risks.append(f"{subject} is STOP; remove/bypass STOP before relying on contact")
                add_replace_rule_subject_candidate(
                    candidates,
                    summary,
                    score=score,
                    subject=subject,
                    prop="win",
                    old_subject=old_subject,
                    instance=instance,
                    reasons=reasons,
                    evidence=evidence,
                    risks=risks,
                    actors=actors,
                )

    if win_subjects:
        actor_positions = set(status["actor_positions"])
        for subject in sorted(set(objects) - set(META_SUBJECTS) - set(win_subjects) - set(you_subjects)):
            subject_coords = object_positions(summary, subject)
            if not subject_coords:
                continue
            reachable_coords = [coord for coord in subject_coords if coord in base_reachable]
            touched_coords = [coord for coord in subject_coords if coord in actor_positions]
            for target in win_subjects:
                if subject == target or (subject, target) in active_rules:
                    continue
                score = 44
                reasons = [
                    f"{target} is already WIN; transforming {subject} into {target} can turn a reachable/touched object into a WIN object"
                ]
                evidence = [
                    f"{subject}_objects=" + ", ".join(str(coord) for coord in subject_coords[:6]),
                    f"current_win_subject={target}",
                ]
                risks = [
                    "stage goal: verify the transform with action_check, then test contact/completion immediately"
                ]
                if reachable_coords:
                    score += 22
                    reasons.append(f"{subject} is in current actor reachability")
                    evidence.append("reachable_" + subject + "=" + ", ".join(str(coord) for coord in reachable_coords[:6]))
                if touched_coords:
                    score += 34
                    reasons.append(f"a current YOU object is already on {subject}; adding the transform may complete immediately")
                    evidence.append("touched_" + subject + "=" + ", ".join(str(coord) for coord in touched_coords[:6]))
                if subject in stop_subjects:
                    score -= 12
                    risks.append(f"{subject} is STOP; remove or bypass STOP before relying on contact")
                add_add_rule_candidate(
                    candidates,
                    summary,
                    score=score,
                    subject=subject,
                    prop=target,
                    reasons=reasons,
                    evidence=evidence,
                    risks=risks,
                    actors=actors,
                )

    for subject in sorted(set(objects) | set(win_subjects) | set(push_subjects)):
        if subject in META_SUBJECTS or subject in you_subjects or (subject, "you") in active_rules:
            continue
        score = 38
        reasons = ["adding a YOU rule can test a control-shift solution without planning a full route"]
        risks = ["high risk: preserve current YOU unless the short action explicitly tests the control shift"]
        if subject in win_subjects:
            score += 48
            reasons.append(f"{subject} is already WIN; making it YOU may complete immediately")
        if subject in stop_subjects:
            score += 10
            reasons.append(f"{subject} is STOP, so control shift may bypass a wall/body bottleneck")
        if subject in push_subjects:
            score += 8
            reasons.append(f"{subject} is PUSH, so it may be a controllable tool")
        add_add_rule_candidate(
            candidates,
            summary,
            score=score,
            subject=subject,
            prop="you",
            reasons=reasons,
            evidence=[f"{subject}_objects={objects.get(subject, 0)}"],
            risks=risks,
            actors=actors,
        )

    for blocker in stop_subjects:
        after_props = props_without(summary, blocker, "stop")
        after_reach = reachability(summary, after_props, actors)
        gained = len(after_reach["reachable"] - base_reachable)
        if (blocker, "shut") not in active_rules:
            score = 46 + min(30, gained)
            reasons = [f"{blocker} is STOP; making it SHUT can turn a wall/door into a removable obstacle"]
            evidence = [f"reachable_gain_if_stop_removed={gained}"]
            risks = ["OPEN+SHUT still needs a movable OPEN tool and contact verification"]
            if open_subjects:
                score += 18
                reasons.append("an OPEN subject already exists: " + ", ".join(open_subjects))
            if gained <= 0:
                score -= 12
                risks.append("removing this STOP subject did not expand approximate actor reachability")
            add_add_rule_candidate(
                candidates,
                summary,
                score=score,
                subject=blocker,
                prop="shut",
                reasons=reasons,
                evidence=evidence,
                risks=risks,
                actors=actors,
            )

    possible_tools = sorted((set(push_subjects) | set(objects)) - set(META_SUBJECTS))
    for blocker in shut_subjects:
        if blocker not in stop_subjects:
            continue
        for tool in possible_tools:
            if tool == blocker or (tool, "open") in active_rules:
                continue
            score = 42
            reasons = [f"{blocker} is already SHUT; making a movable tool OPEN may enable OPEN+SHUT removal"]
            risks = ["verify the actual collision with action_check; this scan does not solve object pushing"]
            if tool in push_subjects:
                score += 20
                reasons.append(f"{tool} is already PUSH")
            if objects.get(tool):
                score += 6
            add_add_rule_candidate(
                candidates,
                summary,
                score=score,
                subject=tool,
                prop="open",
                reasons=reasons,
                evidence=[f"{tool}_objects={objects.get(tool, 0)}"],
                risks=risks,
                actors=actors,
            )

    return sorted(candidates, key=Candidate.sort_key), status


def as_json(summary: dict[str, Any], status: dict[str, Any], candidates: list[Candidate], *, top: int, show_search: bool) -> str:
    props: dict[str, set[str]] = summary["props"]
    payload = {
        "level": {
            "world": summary["meta"].get("world"),
            "level": summary["meta"].get("level"),
            "name": summary["meta"].get("level_name"),
            "turn": summary["meta"].get("turn"),
        },
        "rule_status": {
            "you": sorted(subject for subject, values in props.items() if "you" in values),
            "win": sorted(subject for subject, values in props.items() if "win" in values),
            "stop": sorted(subject for subject, values in props.items() if "stop" in values),
            "open": sorted(subject for subject, values in props.items() if "open" in values),
            "shut": sorted(subject for subject, values in props.items() if "shut" in values),
            "move": sorted(subject for subject, values in props.items() if "move" in values),
            "hazards": sorted(
                f"{subject}:{prop}"
                for subject, values in props.items()
                for prop in values & HAZARD_PROPS
            ),
        },
        "completion_probe": {
            "actors": status["actors"],
            "actor_positions": status["actor_positions"],
            "win_subjects": status["win_subjects"],
            "self_win_subjects": status["self_win_subjects"],
            "reachable_win_objects": status["reachable_win_objects"],
            "completion_rule_ready": status["completion_rule_ready"],
            "reachable_count": status["reachable_count"],
        },
        "edge_text_warnings": edge_text_warnings(summary),
        "mechanic_warnings": mechanic_warnings(summary),
        "protocol": {
            "scope": "rule_goal_scan only chooses one next rule delta; it is not a route or proof",
            "next": "choose one candidate, then run at most one --analyze or a 1-8 step action_check with explicit --expect-*",
            "search_target": "for add_rule/replace_rule_subject candidates, search only this one rule delta; for remove_rule candidates, use action_check --expect-rule-removed",
        },
        "candidates": [
            {
                "score": item.score,
                "kind": item.kind,
                "delta": item.delta,
                "rule": item.rule,
                "reasons": item.reasons,
                "evidence": item.evidence,
                "risks": item.risks,
                "action_check_expect": item.action_check_expect,
                "search_next": item.search_command if show_search else None,
                "search_next_suppressed": bool(item.search_command and not show_search),
            }
            for item in candidates[:top]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def print_human(summary: dict[str, Any], status: dict[str, Any], candidates: list[Candidate], *, top: int, show_search: bool) -> None:
    meta = summary["meta"]
    props: dict[str, set[str]] = summary["props"]
    print(
        "level="
        f"{meta.get('world')}/{meta.get('level')} "
        f"name={meta.get('level_name') or '<unknown>'} "
        f"turn={meta.get('turn')}"
    )
    print("scan_scope=rule goals only; this does not prove a route or replace action_check")
    print("rule_status:")
    for prop in ("you", "win", "stop", "open", "shut", "push", "move", "defeat", "sink", "hot", "melt"):
        subjects = sorted(subject for subject, values in props.items() if prop in values)
        if subjects:
            print(f"  {prop}: {', '.join(subjects)}")
    print("completion_probe:")
    print(f"  actors={status['actors']} positions={status['actor_positions'] or '<none>'}")
    print(f"  win_subjects={status['win_subjects'] or '<none>'}")
    print(f"  reachable_win_objects={status['reachable_win_objects'] or '<none>'}")
    print(f"  completion_rule_ready={str(status['completion_rule_ready']).lower()}")
    warnings = edge_text_warnings(summary)
    if warnings:
        print("edge_text_warnings:")
        for warning in warnings[:10]:
            print(f"  {warning}")
        if len(warnings) > 10:
            print(f"  ... {len(warnings) - 10} more")
    mech_warnings = mechanic_warnings(summary)
    if mech_warnings:
        print("mechanic_warnings:")
        for warning in mech_warnings:
            print(f"  {warning}")
    print()
    print("rule_goal_candidates:")
    if not candidates:
        print("  <none>")
    for index, item in enumerate(candidates[:top], 1):
        print(f"{index}. score={item.score} kind={item.kind} delta={item.delta}")
        print("   why=" + "; ".join(item.reasons))
        if item.evidence:
            print("   evidence=" + "; ".join(item.evidence))
        if item.risks:
            print("   risk=" + "; ".join(item.risks))
        if item.action_check_expect:
            print(f"   action_check_expect={item.action_check_expect}")
        if item.search_command and show_search:
            print(f"   search_next={item.search_command}")
            print("   search_rule=run at most one --analyze/search for this one rule delta, then immediately verify with action_check")
        elif item.search_command:
            print("   search_next_suppressed=use --show-search only after choosing this one candidate")
    print()
    if candidates and all(item.kind == "not_applicable" for item in candidates[:top]):
        print("next=do not plan a rule route from this state; confirm live level or use navigate_next/start_benchmark first")
    else:
        print("next=choose one candidate; add_rule/replace_rule_subject may use one --analyze, remove_rule should use a 1-8 step action_check with --expect-rule-removed")
    print("forbidden=do not turn this list into a full route plan; do not search final WIN if a higher ranked blocker/hazard rule must change first")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override JSON state path")
    parser.add_argument("--wait", action="store_true", help="Wait for state to appear")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--actor", help="Actor subject to use for reachability. Defaults to active YOU subjects, then baba.")
    parser.add_argument("--top", type=int, default=8, help="Number of rule-goal candidates to print")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--show-search", action="store_true", help="Reveal single-rule search_next commands for add_rule candidates")
    parser.add_argument("--ignore-loop-guard", action="store_true", help="Bypass the analysis/action loop guard for manual debugging")
    args = parser.parse_args()

    decision = check_allowed("suggest", args.config, ignore=args.ignore_loop_guard)
    if not decision.allowed:
        if args.json:
            print(json.dumps({"loop_guard": "action_required", "state": decision.state, "reason": decision.reason}, ensure_ascii=False, indent=2))
        else:
            decision.print_block()
        return 2

    state = load_current_state(args)
    summary = summarize(state)
    actors = actor_subjects(summary, args.actor)
    candidates, status = build_candidates(summary, actors)
    guard_path = None
    if not args.ignore_loop_guard:
        guard_path = record_analysis("suggest", args.config, detail=f"rule_goal_scan top={args.top}")

    if args.json:
        print(as_json(summary, status, candidates, top=args.top, show_search=args.show_search))
    else:
        print_human(summary, status, candidates, top=args.top, show_search=args.show_search)
        if guard_path:
            print(f"loop_guard=after_suggest path={guard_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
