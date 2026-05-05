#!/usr/bin/env python3
"""Run a short Baba move segment and verify the expected observable delta.

This is a guardrail for benchmark agents: do not validate a route in hidden
reasoning. Name the expected rule/object/completion change, run the move
segment, and let this script decide whether the observation happened.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_send_keys import parse_moves


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
RUNS_ROOT = ROOT / "runs"
ROUTE_PLAN_NAME = "baba_route_plan.md"


DELTA_KEYS = (
    "rules_added",
    "rules_removed",
    "moved",
    "appeared",
    "disappeared",
)

MOVE_ITEM_RE = re.compile(
    r"^(?P<label>[^:]+):\s*"
    r"\((?P<x1>-?\d+),\s*(?P<y1>-?\d+)\)\s*->\s*"
    r"\((?P<x2>-?\d+),\s*(?P<y2>-?\d+)\)"
)

DIRECTION_ALIASES = {
    "+x": "+x",
    "x+": "+x",
    "right": "+x",
    "east": "+x",
    "-x": "-x",
    "x-": "-x",
    "left": "-x",
    "west": "-x",
    "+y": "+y",
    "y+": "+y",
    "down": "+y",
    "south": "+y",
    "-y": "-y",
    "y-": "-y",
    "up": "-y",
    "north": "-y",
}


def split_items(value: str | None) -> list[str]:
    if not value or value.strip() == "<none>":
        return []
    return [item.strip() for item in value.split(";") if item.strip()]


def normalize_rule(rule: str) -> str:
    text = rule.replace("[visible]", "").replace("[base]", "")
    return " ".join(text.lower().strip().split())


def parse_completion_value(value: str | None) -> int | None:
    if not value or "=" not in value:
        return None
    raw = value.rsplit("=", 1)[-1].strip()
    try:
        return int(float(raw))
    except ValueError:
        return None


def parse_coord_text(value: str) -> tuple[int, int]:
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"expected X,Y coordinate, got {value!r}")
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"expected integer X,Y coordinate, got {value!r}") from exc


def normalize_direction(value: str) -> str:
    key = value.strip().lower()
    try:
        return DIRECTION_ALIASES[key]
    except KeyError as exc:
        allowed = ", ".join(sorted({"+x", "-x", "+y", "-y", "left", "right", "up", "down"}))
        raise ValueError(f"expected direction one of {allowed}, got {value!r}") from exc


def parse_delta_spec(value: str) -> tuple[str, str]:
    if ":" not in value:
        raise ValueError(f"expected UNIT:DIR, got {value!r}")
    unit, direction = value.rsplit(":", 1)
    unit = unit.strip()
    if not unit:
        raise ValueError(f"expected non-empty UNIT in {value!r}")
    return unit, normalize_direction(direction)


def parse_position_at_spec(value: str) -> tuple[str, str]:
    if "@" not in value:
        raise ValueError(f"expected UNIT@X,Y, got {value!r}")
    unit, coord = value.split("@", 1)
    unit = unit.strip()
    coord = coord.strip()
    if not unit:
        raise ValueError(f"expected non-empty UNIT in {value!r}")
    parse_coord_text(coord)
    return unit, coord


def parse_moved_item(item: str) -> tuple[str, tuple[int, int], tuple[int, int]] | None:
    match = MOVE_ITEM_RE.match(item.strip())
    if not match:
        return None
    before = int(match.group("x1")), int(match.group("y1"))
    after = int(match.group("x2")), int(match.group("y2"))
    return match.group("label").strip(), before, after


def moved_item_matches_direction(item: str, unit: str, direction: str) -> bool:
    if not unit_matches(item, unit):
        return False
    parsed = parse_moved_item(item)
    if parsed is None:
        return False
    _label, before, after = parsed
    dx = after[0] - before[0]
    dy = after[1] - before[1]
    if direction == "+x":
        return dx > 0
    if direction == "-x":
        return dx < 0
    if direction == "+y":
        return dy > 0
    if direction == "-y":
        return dy < 0
    return False


def moved_item_reaches_position(item: str, unit: str, coord: tuple[int, int]) -> bool:
    if not unit_matches(item, unit):
        return False
    parsed = parse_moved_item(item)
    if parsed is None:
        return False
    _label, _before, after = parsed
    return after == coord


def parse_try_stdout(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {key: [] for key in DELTA_KEYS}
    parsed["active_rules_before"] = []
    parsed["active_rules_after"] = []
    parsed["completion_status"] = ""
    parsed["completion_value"] = None
    parsed["after_turn"] = None
    parsed["after_event"] = ""
    for line in stdout.splitlines():
        for key in DELTA_KEYS:
            prefix = key + "="
            if line.startswith(prefix):
                parsed[key] = split_items(line.removeprefix(prefix))
                break
        else:
            if line.startswith("completion_status="):
                value = line.removeprefix("completion_status=").strip()
                parsed["completion_status"] = value
                parsed["completion_value"] = parse_completion_value(value)
            elif line.startswith("active_rules_before="):
                parsed["active_rules_before"] = split_items(line.removeprefix("active_rules_before=").strip())
            elif line.startswith("active_rules_after="):
                parsed["active_rules_after"] = split_items(line.removeprefix("active_rules_after=").strip())
            elif line.startswith("after="):
                turn_match = re.search(r"\bturn:(\d+)\b", line)
                if turn_match:
                    parsed["after_turn"] = int(turn_match.group(1))
                event_match = re.search(r"\bevent:([^ ]+)", line)
                if event_match:
                    parsed["after_event"] = event_match.group(1)
    return parsed


def unit_label(item: str) -> str:
    label = item.split(":", 1)[0].split("@", 1)[0].strip().lower()
    return label


def unit_name_without_id(label: str) -> str:
    return label.split("#", 1)[0]


def unit_matches(item: str, expected: str) -> bool:
    label = unit_label(item)
    name = unit_name_without_id(label)
    target = expected.strip().lower()
    return target in {label, name}


def counterpart_name(name: str) -> str:
    if name.startswith("text_"):
        return name.removeprefix("text_")
    return "text_" + name


def counterpart_hint(items: list[str], expected: str, category: str) -> str | None:
    target = expected.strip().lower()
    if not target:
        return None
    counterpart = counterpart_name(target)
    if any(unit_matches(item, counterpart) for item in items):
        if target.startswith("text_"):
            return (
                f"{category}:{expected} did not match object `{counterpart}`. "
                f"Use `{counterpart}` for the physical object and `{target}` for the word tile."
            )
        return (
            f"{category}:{expected} did not match word tile `{counterpart}`. "
            f"Use `{target}` for the physical object and `{counterpart}` for the word tile."
        )
    return None


def rule_matches(items: list[str], expected: str) -> bool:
    target = normalize_rule(expected)
    return target in {normalize_rule(item) for item in items}


def matching_rules(items: list[str], expected: str) -> list[str]:
    target = normalize_rule(expected)
    return [item for item in items if normalize_rule(item) == target]


def rule_effect(rule: str) -> str:
    parts = normalize_rule(rule).split()
    if len(parts) >= 3 and parts[1] == "is":
        return parts[2]
    return ""


def rule_subject(rule: str) -> str:
    parts = normalize_rule(rule).split()
    if len(parts) >= 3 and parts[1] == "is":
        return parts[0]
    return ""


def rule_set(values: list[str]) -> set[str]:
    return {normalize_rule(value) for value in values if normalize_rule(value)}


def expects_completion_status_three(args: argparse.Namespace) -> bool:
    expected_status = args.expect_completion_status
    if args.expect_completion is not None:
        expected_status = args.expect_completion
    return expected_status == 3


def expects_win_rule_added(args: argparse.Namespace) -> bool:
    return any(rule_effect(value) == "win" for value in args.expect_rule_added)


def split_expectation_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for part in value.split(","):
            item = part.strip()
            if item:
                result.append(item)
    return result


def normalize_expectations(args: argparse.Namespace) -> None:
    for key in (
        "expect_rule_added",
        "expect_rule_removed",
        "expect_rule_kept",
        "expect_rule_present",
        "forbid_rule_added",
        "forbid_rule_removed",
        "forbid_rule_present",
        "expect_moved",
        "expect_moved_delta",
        "expect_appeared",
        "expect_disappeared",
    ):
        setattr(args, key, split_expectation_values(getattr(args, key) or []))
    args.expect_position_at_errors = []
    for value in args.expect_position_at or []:
        try:
            unit, coord = parse_position_at_spec(value)
        except ValueError as exc:
            args.expect_position_at_errors.append(str(exc))
            continue
        args.expect_position.append([unit, coord])


def validate_expectation_syntax(args: argparse.Namespace) -> list[str]:
    errors: list[str] = list(getattr(args, "expect_position_at_errors", []))
    for value in args.expect_moved_delta:
        try:
            parse_delta_spec(value)
        except ValueError as exc:
            errors.append(str(exc))
    for unit, coord in args.expect_position:
        if not unit.strip():
            errors.append(f"expected non-empty UNIT in --expect-position {unit!r} {coord!r}")
            continue
        try:
            parse_coord_text(coord)
        except ValueError as exc:
            errors.append(str(exc))
    conflict_checks = [
        ("expect-rule-added", args.expect_rule_added, "expect-rule-removed", args.expect_rule_removed),
        ("expect-rule-kept", args.expect_rule_kept, "expect-rule-removed", args.expect_rule_removed),
        ("expect-rule-present", args.expect_rule_present, "forbid-rule-present", args.forbid_rule_present),
        ("expect-rule-added", args.expect_rule_added, "forbid-rule-added", args.forbid_rule_added),
        ("expect-rule-removed", args.expect_rule_removed, "forbid-rule-removed", args.forbid_rule_removed),
    ]
    for left_name, left_values, right_name, right_values in conflict_checks:
        overlap = rule_set(left_values) & rule_set(right_values)
        for rule in sorted(overlap):
            errors.append(f"conflicting expectations: --{left_name} and --{right_name} both mention {rule!r}")
    return errors


def expectation_count(args: argparse.Namespace) -> int:
    total = 0
    for key in (
        "expect_rule_added",
        "expect_rule_removed",
        "expect_rule_kept",
        "expect_rule_present",
        "forbid_rule_added",
        "forbid_rule_removed",
        "forbid_rule_present",
        "expect_moved",
        "expect_moved_delta",
        "expect_appeared",
        "expect_disappeared",
    ):
        total += len(getattr(args, key) or [])
    total += len(args.expect_position or [])
    if args.expect_completion is not None or args.expect_completion_status is not None:
        total += 1
    return total


def expected_summary(args: argparse.Namespace) -> str:
    parts: list[str] = []
    for value in args.expect_rule_added:
        parts.append(f"rule_added:{value}")
    for value in args.expect_rule_removed:
        parts.append(f"rule_removed:{value}")
    for value in args.expect_rule_kept:
        parts.append(f"rule_kept:{value}")
    for value in args.expect_rule_present:
        parts.append(f"rule_present:{value}")
    for value in args.forbid_rule_added:
        parts.append(f"forbid_rule_added:{value}")
    for value in args.forbid_rule_removed:
        parts.append(f"forbid_rule_removed:{value}")
    for value in args.forbid_rule_present:
        parts.append(f"forbid_rule_present:{value}")
    for value in args.expect_moved:
        parts.append(f"moved:{value}")
    for value in args.expect_moved_delta:
        unit, direction = parse_delta_spec(value)
        parts.append(f"moved_delta:{unit}:{direction}")
    for unit, coord in args.expect_position:
        parts.append(f"position:{unit}@{coord}")
    for value in args.expect_appeared:
        parts.append(f"appeared:{value}")
    for value in args.expect_disappeared:
        parts.append(f"disappeared:{value}")
    if args.expect_completion is not None:
        parts.append(f"completion_status:{args.expect_completion}")
    if args.expect_completion_status is not None:
        parts.append(f"completion_status:{args.expect_completion_status}")
    return "; ".join(parts)


def append_common_args(command: list[str], args: argparse.Namespace) -> None:
    if args.config:
        command.extend(["--config", str(args.config)])
    if args.save_dir:
        command.extend(["--save-dir", str(args.save_dir)])
    if args.app_name:
        command.extend(["--app-name", args.app_name])
    if args.timeout is not None:
        command.extend(["--timeout", str(args.timeout)])
    if args.delay is not None:
        command.extend(["--delay", str(args.delay)])
    if args.hold_ms is not None:
        command.extend(["--hold-ms", str(args.hold_ms)])
    if args.method:
        command.extend(["--method", args.method])
    if args.no_activate:
        command.append("--no-activate")
    if args.pre_delay is not None:
        command.extend(["--pre-delay", str(args.pre_delay)])
    if args.focus:
        command.extend(["--focus", args.focus])
    else:
        focus_names = set()
        for value in (
            *args.expect_moved,
            *args.expect_appeared,
            *args.expect_disappeared,
        ):
            focus_names.add(value)
            focus_names.add(counterpart_name(value))
        for value in args.expect_moved_delta:
            unit, _direction = parse_delta_spec(value)
            focus_names.add(unit)
            focus_names.add(counterpart_name(unit))
        for unit, _coord in args.expect_position:
            focus_names.add(unit)
            focus_names.add(counterpart_name(unit))
        for value in (
            *args.expect_rule_added,
            *args.expect_rule_removed,
            *args.expect_rule_kept,
            *args.expect_rule_present,
            *args.forbid_rule_added,
            *args.forbid_rule_removed,
            *args.forbid_rule_present,
        ):
            subject = rule_subject(value)
            effect = rule_effect(value)
            for name in (subject, effect):
                if name and name not in {"is", "you", "win", "stop", "push", "defeat", "sink", "hot", "melt", "open", "shut", "select"}:
                    focus_names.add(name)
                    focus_names.add(counterpart_name(name))
            if effect == "you" and subject:
                focus_names.add(subject)
                focus_names.add(counterpart_name(subject))
        focus_values = sorted(focus_names)
        if focus_values:
            command.extend(["--focus", ",".join(focus_values)])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])


def build_try_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(SCRIPTS_DIR / "baba_try.py"), args.moves]
    append_common_args(command, args)
    return command


def read_live_rule_texts(args: argparse.Namespace) -> tuple[list[str], str | None]:
    command = [sys.executable, str(SCRIPTS_DIR / "read_baba_state.py"), "--json"]
    if args.config:
        command.extend(["--config", str(args.config)])
    if args.save_dir:
        command.extend(["--save-dir", str(args.save_dir)])
    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=min(args.command_timeout, 10.0),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "read_baba_state.py --json timed out"
    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        return [], message
    try:
        state = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return [], f"could not parse read_baba_state.py --json: {exc}"
    rules = state.get("rules")
    if not isinstance(rules, list):
        return [], "live state has no rules list"
    texts = []
    for rule in rules:
        if isinstance(rule, dict) and isinstance(rule.get("text"), str):
            texts.append(rule["text"])
    return texts, None


def runtime_preflight_errors(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if expects_completion_status_three(args) and not expects_win_rule_added(args):
        rules, warning = read_live_rule_texts(args)
        if warning:
            warnings.append(f"could not verify active WIN rule before completion check: {warning}")
        elif not any(rule_effect(rule) == "win" for rule in rules):
            errors.append(
                "expecting completion_status 3 without any active WIN rule; "
                "first create or keep an X IS WIN rule, or include --expect-rule-added '<x> is win'"
            )
    return errors, warnings


def evaluate(parsed: dict[str, Any], args: argparse.Namespace) -> tuple[bool, list[str]]:
    failures: list[str] = []
    movement_hint_added = False
    for value in args.expect_rule_added:
        if not rule_matches(parsed["rules_added"], value):
            failures.append(f"missing rule_added:{value}")
    for value in args.expect_rule_removed:
        if not rule_matches(parsed["rules_removed"], value):
            failures.append(f"missing rule_removed:{value}")
    for value in args.expect_rule_kept:
        if not rule_matches(parsed["active_rules_before"], value):
            failures.append(f"rule_kept:{value} was not active before the segment")
        elif not rule_matches(parsed["active_rules_after"], value):
            failures.append(f"missing rule_kept:{value}")
    for value in args.expect_rule_present:
        if not rule_matches(parsed["active_rules_after"], value):
            failures.append(f"missing rule_present:{value}")
    for value in args.forbid_rule_added:
        matches = matching_rules(parsed["rules_added"], value)
        if matches:
            failures.append(f"forbidden rule_added:{value}")
    for value in args.forbid_rule_removed:
        matches = matching_rules(parsed["rules_removed"], value)
        if matches:
            failures.append(f"forbidden rule_removed:{value}")
    for value in args.forbid_rule_present:
        matches = matching_rules(parsed["active_rules_after"], value)
        if matches:
            failures.append(f"forbidden rule_present:{value}")
    for value in args.expect_moved:
        if not any(unit_matches(item, value) for item in parsed["moved"]):
            failures.append(f"missing moved:{value}")
            hint = counterpart_hint(parsed["moved"], value, "moved")
            if hint:
                failures.append(hint)
            if not movement_hint_added:
                failures.append(
                    "push_chain_hint: PUSH/text moves only when the whole chain can shift and the cell beyond the far end is free; "
                    "edge/STOP/DEFEAT/non-push blockers, corners, and one-cell pockets can make the push impossible or unrecoverable."
                )
                failures.append(
                    "blocked_cell_hint: if a YOU object did not move, inspect the exact target cell with "
                    "`python3 scripts/read_baba_state.py --at X,Y`; truncated --limit group output can hide walls behind tile/decoration groups."
                )
                movement_hint_added = True
    for value in args.expect_moved_delta:
        unit, direction = parse_delta_spec(value)
        matching_moves = [item for item in parsed["moved"] if unit_matches(item, unit)]
        if not any(moved_item_matches_direction(item, unit, direction) for item in parsed["moved"]):
            failures.append(f"missing moved_delta:{unit}:{direction}")
            if matching_moves:
                failures.append(f"observed_moved_for_{unit}:" + "; ".join(matching_moves))
            hint = counterpart_hint(parsed["moved"], unit, "moved_delta")
            if hint:
                failures.append(hint)
            if not movement_hint_added:
                failures.append(
                    "push_chain_hint: PUSH/text moves only when the whole chain can shift and the cell beyond the far end is free; "
                    "edge/STOP/DEFEAT/non-push blockers, corners, and one-cell pockets can make the push impossible or unrecoverable."
                )
                failures.append(
                    "blocked_cell_hint: if a YOU object did not move, inspect the exact target cell with "
                    "`python3 scripts/read_baba_state.py --at X,Y`; truncated --limit group output can hide walls behind tile/decoration groups."
                )
                movement_hint_added = True
    for unit, coord_text in args.expect_position:
        coord = parse_coord_text(coord_text)
        matching_moves = [item for item in parsed["moved"] if unit_matches(item, unit)]
        if not any(moved_item_reaches_position(item, unit, coord) for item in parsed["moved"]):
            failures.append(f"missing position:{unit}@{coord[0]},{coord[1]}")
            if matching_moves:
                failures.append(f"observed_moved_for_{unit}:" + "; ".join(matching_moves))
            hint = counterpart_hint(parsed["moved"], unit, "position")
            if hint:
                failures.append(hint)
            if not movement_hint_added:
                failures.append(
                    "push_chain_hint: PUSH/text moves only when the whole chain can shift and the cell beyond the far end is free; "
                    "edge/STOP/DEFEAT/non-push blockers, corners, and one-cell pockets can make the push impossible or unrecoverable."
                )
                failures.append(
                    "blocked_cell_hint: if a YOU object did not move, inspect the exact target cell with "
                    "`python3 scripts/read_baba_state.py --at X,Y`; truncated --limit group output can hide walls behind tile/decoration groups."
                )
                movement_hint_added = True
    for value in args.expect_appeared:
        if not any(unit_matches(item, value) for item in parsed["appeared"]):
            failures.append(f"missing appeared:{value}")
            hint = counterpart_hint(parsed["appeared"], value, "appeared")
            if hint:
                failures.append(hint)
    for value in args.expect_disappeared:
        if not any(unit_matches(item, value) for item in parsed["disappeared"]):
            failures.append(f"missing disappeared:{value}")
            hint = counterpart_hint(parsed["disappeared"], value, "disappeared")
            if hint:
                failures.append(hint)

    expected_status = args.expect_completion_status
    if args.expect_completion is not None:
        expected_status = args.expect_completion
    if expected_status is not None and parsed["completion_value"] != expected_status:
        failures.append(
            f"completion_status:{expected_status} not reached "
            f"(observed {parsed['completion_status'] or '<missing>'})"
        )
        removed_win = [rule for rule in parsed["rules_removed"] if rule_effect(rule) == "win"]
        if removed_win:
            failures.append("completion blocked because WIN rule was removed:" + "; ".join(removed_win))
    removed_you = [rule for rule in parsed["rules_removed"] if rule_effect(rule) == "you"]
    if removed_you:
        failures.append("control rule removed; guard it with --expect-rule-kept:" + "; ".join(removed_you))
    return not failures, failures


def print_observed(parsed: dict[str, Any]) -> None:
    print("observed_rules_added=" + ("; ".join(parsed["rules_added"]) or "<none>"))
    print("observed_rules_removed=" + ("; ".join(parsed["rules_removed"]) or "<none>"))
    print("observed_active_rules_after=" + ("; ".join(parsed["active_rules_after"]) or "<none>"))
    print("observed_moved=" + ("; ".join(parsed["moved"]) or "<none>"))
    print("observed_appeared=" + ("; ".join(parsed["appeared"]) or "<none>"))
    print("observed_disappeared=" + ("; ".join(parsed["disappeared"]) or "<none>"))
    print("observed_completion_status=" + (parsed["completion_status"] or "<none>"))
    if parsed.get("after_turn") is not None:
        print(f"observed_after_turn={parsed['after_turn']}")
    if parsed.get("after_event"):
        print(f"observed_after_event={parsed['after_event']}")


def markdown_code(value: str) -> str:
    return "`" + value.replace("`", "\\`") + "`"


def observed_summary(parsed: dict[str, Any]) -> str:
    parts = []
    for key in DELTA_KEYS:
        value = "; ".join(parsed[key]) or "<none>"
        parts.append(f"{key}={value}")
    parts.append("completion_status=" + (parsed["completion_status"] or "<none>"))
    if parsed.get("after_turn") is not None:
        parts.append(f"after_turn={parsed['after_turn']}")
    return " | ".join(parts)


def is_undo_segment(moves: list[str]) -> bool:
    return bool(moves) and all(move in {"z", "undo"} for move in moves)


def moves_literal(moves: list[str]) -> str:
    return ",".join(moves)


def observed_delta_exists(parsed: dict[str, Any]) -> bool:
    return any(parsed[key] for key in DELTA_KEYS)


def preserved_progress(args: argparse.Namespace, parsed: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in args.expect_rule_kept:
        if rule_matches(parsed["active_rules_after"], value):
            values.append(f"rule_kept:{value}")
    for value in args.expect_rule_added:
        if rule_matches(parsed["rules_added"], value) or rule_matches(parsed["active_rules_after"], value):
            values.append(f"rule_present:{value}")
    for value in args.expect_rule_present:
        if rule_matches(parsed["active_rules_after"], value):
            values.append(f"rule_present:{value}")
    return values


def unsafe_full_undo_reason(
    moves: list[str],
    parsed: dict[str, Any],
    failures: list[str],
) -> str | None:
    if is_undo_segment(moves) or not failures or len(moves) <= 1:
        return None
    if observed_delta_exists(parsed):
        return (
            "failed multi-step segment still changed the live state; some inputs may have been blocked/no-op, "
            "so undoing the expanded move count can overshoot into earlier successful progress"
        )
    return (
        "failed multi-step segment showed no meaningful delta; it was likely blocked/no-op, "
        "so undoing the expanded move count can erase earlier successful progress"
    )


def failure_next_line(
    moves: list[str],
    args: argparse.Namespace,
    parsed: dict[str, Any],
    failures: list[str],
) -> str:
    if is_undo_segment(moves):
        return "discard pending plan; only read_baba_state.py --limit 60 or baba_restart.py"
    if unsafe_full_undo_reason(moves, parsed, failures):
        return (
            "discard pending plan; read state before any undo; if undo is necessary, "
            "use baba_undo.py --steps 1 and observe"
        )
    progress = preserved_progress(args, parsed)
    if progress:
        return "discard pending plan; preserved progress remains, read state and continue from the real delta"
    return (
        "discard pending plan; read state first; if undo is necessary, use "
        "baba_undo.py --steps 1 and observe"
    )


def has_primary_observable_delta(args: argparse.Namespace) -> bool:
    return bool(
        args.expect_rule_added
        or args.expect_rule_removed
        or args.expect_rule_present
        or args.expect_appeared
        or args.expect_disappeared
        or args.expect_completion is not None
        or args.expect_completion_status is not None
    )


def weak_movement_expectation_reason(args: argparse.Namespace, moves: list[str]) -> str | None:
    if args.allow_weak_move or not args.expect_moved:
        return None
    if args.expect_moved_delta or args.expect_position or has_primary_observable_delta(args):
        return None
    text_targets = [value for value in args.expect_moved if value.strip().lower().startswith("text_")]
    if text_targets:
        return (
            "movement-only expectation is too weak for pushed text "
            f"({', '.join(text_targets)}); use --expect-moved-delta UNIT:DIR "
            "or --expect-position UNIT X,Y"
        )
    if len(moves) > 1:
        return (
            "movement-only expectation is too weak for a multi-step segment; "
            "use --expect-moved-delta UNIT:DIR or --expect-position UNIT X,Y"
        )
    return None


def route_plan_path(args: argparse.Namespace) -> Path | None:
    try:
        config = load_config(args.config, refresh_status=False)
    except SystemExit:
        return None
    run_id = (config.current_run_id or "").strip()
    if not run_id:
        return None
    if not re.fullmatch(r"\d{3}_[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        return None
    return RUNS_ROOT / run_id / ROUTE_PLAN_NAME


def append_route_plan(
    args: argparse.Namespace,
    moves: list[str],
    parsed: dict[str, Any],
    *,
    passed: bool,
    failures: list[str],
) -> Path | None:
    path = route_plan_path(args)
    if path is None:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            "# Baba Route Plan\n\n"
            "This is a temporary scratchpad for planned short route segments. "
            "Do not treat it as a known-route source during benchmark solving.\n\n",
            encoding="utf-8",
        )

    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expected = expected_summary(args) or "<none>"
    status = "pass" if passed else "fail"
    next_line = (
        "continue from observed delta"
        if passed
        else failure_next_line(moves, args, parsed, failures)
    )
    body = (
        f"## {stamp} action_check\n\n"
        f"- moves: {markdown_code(args.moves)}\n"
        f"- expanded_moves: {markdown_code(','.join(moves))}\n"
        f"- expanded_step_count: {len(moves)}\n"
        f"- expected: {expected}\n"
        f"- check: {status}\n"
        f"- observed: {observed_summary(parsed)}\n"
    )
    if failures:
        body += f"- missing: {'; '.join(failures)}\n"
    body += f"- next: {next_line}\n\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(body)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("moves", help="Comma-separated moves, e.g. 'left*3,up'")
    parser.add_argument("--expect-rule-added", action="append", default=[], help="Rule expected to be newly formed.")
    parser.add_argument("--expect-rule-removed", action="append", default=[], help="Rule expected to be broken.")
    parser.add_argument("--expect-rule-kept", action="append", default=[], help="Rule expected to be active before and still active after the segment.")
    parser.add_argument("--expect-rule-present", action="append", default=[], help="Rule expected to be active after the segment.")
    parser.add_argument("--forbid-rule-added", action="append", default=[], help="Fail if this rule is newly formed.")
    parser.add_argument("--forbid-rule-removed", action="append", default=[], help="Fail if this rule is broken.")
    parser.add_argument("--forbid-rule-present", action="append", default=[], help="Fail if this rule is active after the segment.")
    parser.add_argument("--expect-moved", action="append", default=[], help="Unit/text expected to move, e.g. text_is. Comma-separated values are split.")
    parser.add_argument(
        "--expect-moved-delta",
        action="append",
        default=[],
        help="Unit/text expected to move in a net direction, e.g. text_is:+x, rock:left, baba:up.",
    )
    parser.add_argument(
        "--expect-position",
        nargs=2,
        action="append",
        default=[],
        metavar=("UNIT", "X,Y"),
        help="Unit/text expected to finish at a coordinate, e.g. --expect-position baba 7,4.",
    )
    parser.add_argument(
        "--expect-position-at",
        action="append",
        default=[],
        metavar="UNIT@X,Y",
        help="Equivalent compact form for --expect-position, e.g. text_is@4,6.",
    )
    parser.add_argument("--expect-appeared", action="append", default=[], help="Unit/text expected to appear. Comma-separated values are split.")
    parser.add_argument("--expect-disappeared", action="append", default=[], help="Unit/text expected to disappear. Comma-separated values are split.")
    parser.add_argument(
        "--expect-completion",
        nargs="?",
        const=3,
        type=int,
        help="Expect completion status 3, or pass a specific value such as --expect-completion 3.",
    )
    parser.add_argument("--expect-completion-status", type=int, help="Expect a specific completion status value.")
    parser.add_argument("--allow-no-expectation", action="store_true", help="Permit running without expected delta.")
    parser.add_argument("--allow-weak-move", action="store_true", help="Permit weak --expect-moved-only checks for one-off debugging.")
    parser.add_argument("--max-moves", type=int, default=8, help="Maximum expanded moves without --allow-long.")
    parser.add_argument("--allow-long", action="store_true", help="Allow action segments longer than --max-moves.")
    parser.add_argument("--dry-run", action="store_true", help="Validate arguments and print the command without moving.")
    parser.add_argument("--command-timeout", type=float, default=30.0, help="Subprocess timeout in seconds.")
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument("--timeout", type=float, help="Seconds baba_try.py waits after each move.")
    parser.add_argument("--delay", type=float, help="Delay after each key press.")
    parser.add_argument("--hold-ms", type=int, help="Milliseconds to hold each key.")
    parser.add_argument("--method", choices=["cgevent", "applescript"], help="Key injection method.")
    parser.add_argument("--no-activate", action="store_true", help="Do not activate Baba before sending.")
    parser.add_argument("--pre-delay", type=float, help="Delay after activating Baba.")
    parser.add_argument("--focus", help="Comma-separated unit names to show in baba_try.py output.")
    parser.add_argument("--limit", type=int, help="Limit printed changed units per category.")
    args = parser.parse_args()
    normalize_expectations(args)
    syntax_errors = validate_expectation_syntax(args)
    if syntax_errors:
        print("check=error")
        print("reason=invalid expectation syntax")
        for error in syntax_errors:
            print(f"syntax_error={error}")
        return 2

    moves = parse_moves(args.moves)
    if not moves:
        print("check=error")
        print("reason=moves must expand to at least one key")
        return 2
    if len(moves) > args.max_moves and not args.allow_long:
        print("check=error")
        print(f"reason=expanded move count {len(moves)} exceeds max_moves {args.max_moves}")
        print(
            "next=split the action into one 1-8 step observable segment with explicit --expect-*; "
            "do not use --allow-long during benchmark solving"
        )
        print(f"suggested_first_segment={moves_literal(moves[:args.max_moves])}")
        print(f"suggested_remaining={moves_literal(moves[args.max_moves:])}")
        return 2
    if expectation_count(args) == 0 and not args.allow_no_expectation:
        print("check=error")
        print("reason=declare at least one expected observable delta")
        print("examples=--expect-moved-delta text_is:+x | --expect-position baba 7,4 | --expect-rule-added 'rock is win' | --expect-completion 3")
        return 2
    weak_reason = weak_movement_expectation_reason(args, moves)
    if weak_reason:
        print("check=error")
        print(f"reason={weak_reason}")
        print("examples=--expect-moved-delta text_rock:-x | --expect-position text_rock 1,6 | --expect-rule-added 'rock is win'")
        return 2
    preflight_errors, preflight_warnings = runtime_preflight_errors(args)
    if preflight_errors:
        print("check=error")
        print("reason=preflight expectation failed")
        for error in preflight_errors:
            print(f"preflight_error={error}")
        print("allowed_next=python3 scripts/read_baba_state.py --limit 60")
        print("allowed_next=python3 scripts/baba_suggest_hypotheses.py --top 5")
        return 2
    for warning in preflight_warnings:
        print(f"preflight_warning={warning}")

    command = build_try_command(args)
    print("moves=" + ",".join(moves))
    print("expanded_move_count=" + str(len(moves)))
    print("expected=" + (expected_summary(args) or "<none>"))
    print("command=" + shlex.join(["python3", "scripts/baba_try.py", args.moves, *command[3:]]))

    if args.dry_run:
        print("check=planned")
        print("next=run without --dry-run when the expectation is precise")
        return 0

    try:
        proc = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=args.command_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        print("check=error")
        print(f"reason=baba_try.py timed out after {args.command_timeout:g}s")
        if exc.stdout:
            print("--- baba_try stdout ---")
            print(str(exc.stdout).rstrip())
        if exc.stderr:
            print("--- baba_try stderr ---", file=sys.stderr)
            print(str(exc.stderr).rstrip(), file=sys.stderr)
        return 1

    if proc.returncode != 0:
        print("check=error")
        print(f"reason=baba_try.py exited with {proc.returncode}")
        if proc.stdout:
            print("--- baba_try stdout ---")
            print(proc.stdout.rstrip())
        if proc.stderr:
            print("--- baba_try stderr ---", file=sys.stderr)
            print(proc.stderr.rstrip(), file=sys.stderr)
        return proc.returncode

    parsed = parse_try_stdout(proc.stdout)
    passed, failures = evaluate(parsed, args)
    print_observed(parsed)
    print("check=" + ("pass" if passed else "fail"))
    try:
        plan_path = append_route_plan(args, moves, parsed, passed=passed, failures=failures)
    except OSError as exc:
        plan_path = None
        print(f"route_plan_warning={exc}")
    if plan_path is not None:
        print(f"route_plan={plan_path}")
    if failures:
        print("missing=" + "; ".join(failures))
        undo_risk = unsafe_full_undo_reason(moves, parsed, failures)
        progress = preserved_progress(args, parsed)
        if undo_risk:
            print("next=read_state_before_any_undo")
            print("undo_expanded_steps_unsafe=true")
            print(f"unsafe_undo_steps={len(moves)}")
            print(f"unsafe_undo_reason={undo_risk}")
            if progress:
                print("preserved_progress=" + "; ".join(progress))
            print("allowed_next=python3 scripts/read_baba_state.py --limit 60")
            print("conditional_next=python3 scripts/baba_undo.py --steps 1")
            print("conditional_next=python3 scripts/baba_restart.py")
            print(
                "forbidden_next="
                f"do not run baba_undo.py --steps {len(moves)}; "
                "do not restart while preserved progress can still be continued; "
                "do not explain expected-but-unobserved moves; do not continue from mental coordinates; "
                "do not run another long segment; do not use action_check for undo"
            )
        else:
            print("next=read_state_or_single_step_undo")
            if progress:
                print("preserved_progress=" + "; ".join(progress))
            print("allowed_next=python3 scripts/read_baba_state.py --limit 60")
            if not is_undo_segment(moves):
                print("conditional_next=python3 scripts/baba_undo.py --steps 1")
            print("conditional_next=python3 scripts/baba_restart.py")
            print(
                "forbidden_next=do not explain expected-but-unobserved moves; do not continue from mental coordinates; "
                "do not run another long segment; do not use action_check for undo"
            )
    else:
        if parsed.get("completion_value") == 3 and parsed.get("after_turn") is not None:
            print(f"record_pass_score_hint=include --game-turns {parsed['after_turn']} when running baba_benchmark.py --record-pass")
        print("next=continue from the observed delta")
    print("--- baba_try stdout ---")
    print(proc.stdout.rstrip())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
