#!/usr/bin/env python3
"""Read the latest state emitted by the Baba Is You Lua state exporter."""

from __future__ import annotations

import argparse
import collections
import json
import hashlib
import sys
import time
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_loop_guard import check_allowed, record_analysis
from parse_baba_level import current_level, read_ini_like


META_SUBJECTS = {"cursor", "level", "text"}
HAZARD_PROPERTIES = {"defeat", "sink", "hot", "melt"}
BLOCKING_PROPERTIES = {"stop"}
RISK_PROPERTIES = BLOCKING_PROPERTIES | HAZARD_PROPERTIES
Coord = tuple[int, int]


def current_save_file(save_dir: Path) -> Path:
    slot, _world, _level = current_level(save_dir)
    return save_dir / f"{slot}ba.ba"


def decode_field(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            code = value[index + 1]
            if code == "t":
                result.append("\t")
            elif code == "n":
                result.append("\n")
            elif code == "r":
                result.append("\r")
            else:
                result.append(code)
            index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def row_fields(value: str, expected: int) -> list[str]:
    fields = [decode_field(part) for part in value.split("\t")]
    if len(fields) < expected:
        fields.extend([""] * (expected - len(fields)))
    return fields


def to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def to_bool(value: str | None) -> bool:
    return value == "1" or str(value).lower() == "true"


def load_agent_state(save_file: Path) -> dict[str, Any] | None:
    sections = read_ini_like(save_file)
    raw = sections.get("agent_state")
    if not raw or raw.get("schema") != "baba-agent-state-export-v1":
        return None
    for key in ('turn', 'sequence', 'world', 'level', 'unit_count', 'rule_count'):
        if key not in raw:
            raise ValueError(f'incomplete export: missing {key}')
    for kind in ('unit', 'rule'):
        count = to_int(raw.get(kind + '_count'))
        if count is None or count < 0:
            raise ValueError(f'invalid {kind}_count')
        if any(not raw.get(f'{kind}_{i}') for i in range(1, count + 1)):
            raise ValueError(f'incomplete {kind} rows')

    meta = {
        "schema": raw.get("schema"),
        "source": raw.get("source"),
        "turn": to_int(raw.get("turn")),
        "sequence": to_int(raw.get("sequence")),
        "last_command": raw.get("last_command"),
        "last_player": to_int(raw.get("last_player")),
        "world": raw.get("world"),
        "level": raw.get("level"),
        "level_name": raw.get("level_name"),
        "room_width": to_int(raw.get("room_width")),
        "room_height": to_int(raw.get("room_height")),
        "last_key": to_int(raw.get("last_key")),
        "storage": "save",
        "storage_path": str(save_file),
    }

    rules = []
    for index in range(1, (to_int(raw.get("rule_count")) or 0) + 1):
        text, target, verb, effect, base, visible, condition_count, source_id_count = row_fields(
            raw.get(f"rule_{index}", ""),
            8,
        )
        rules.append(
            {
                "text": text,
                "target": target,
                "verb": verb,
                "effect": effect,
                "base": to_bool(base),
                "visible": to_bool(visible),
                "condition_count": to_int(condition_count) or 0,
                "source_id_count": to_int(source_id_count) or 0,
            }
        )

    feature_index = []
    for index in range(1, (to_int(raw.get("feature_count")) or 0) + 1):
        name, count = row_fields(raw.get(f"feature_{index}", ""), 2)
        feature_index.append({"name": name, "count": to_int(count) or 0})

    units = []
    for index in range(1, (to_int(raw.get("unit_count")) or 0) + 1):
        (
            runtime_id,
            unit_id,
            name,
            unit_type,
            word,
            x,
            y,
            direction,
            float_value,
            type_value,
            zlayer,
            dead,
            visible,
        ) = row_fields(raw.get(f"unit_{index}", ""), 13)
        units.append(
            {
                "runtime_id": to_int(runtime_id),
                "id": to_int(unit_id),
                "name": name,
                "unit_type": unit_type,
                "word": word or None,
                "x": to_int(x),
                "y": to_int(y),
                "dir": to_int(direction),
                "float": to_int(float_value),
                "type": to_int(type_value),
                "zlayer": to_int(zlayer),
                "dead": to_bool(dead),
                "visible": to_bool(visible),
            }
        )

    return {"meta": meta, "rules": rules, "feature_index": feature_index, "units": units}


class StateReadError(SystemExit):
    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f'{reason}: {detail}')


def state_fingerprint(state: dict[str, Any]) -> str:
    """Identity of a complete observation, excluding storage metadata."""
    meta = state.get('meta', {})
    value = {
        'meta': {k: meta.get(k) for k in ('world', 'level', 'turn', 'sequence', 'source')},
        'rules': state.get('rules', []),
        'units': [{k: u.get(k) for k in ('id','name','x','y','dir','dead','visible','float')}
                  for u in state.get('units', [])],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_state(
    path: Path | None,
    *,
    wait: bool,
    timeout: float,
    since_mtime: float | None,
    save_dir: Path | None = None,
    since_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    config_save_dir: Path | None = save_dir
    baseline = state_fingerprint(since_state) if since_state is not None else None
    last_reason, last_detail = 'state_missing', str(path)
    while True:
        if config_save_dir is None:
            config_save_dir = load_config().save_dir
        try:
            save_file = current_save_file(config_save_dir)
        except (OSError, ValueError, SystemExit) as exc:
            save_file = config_save_dir / 'unavailable-save'
            last_reason, last_detail = 'state_parse_failed', str(exc)
        candidates = [(path, 'json')] if path is not None else [(save_file, 'save')]
        found = False
        for candidate, storage in candidates:
            if not candidate.exists():
                continue
            found = True
            try:
                stat = candidate.stat()
                state = json.loads(candidate.read_text(encoding='utf-8')) if storage == 'json' else load_agent_state(candidate)
                if not isinstance(state, dict) or not isinstance(state.get('meta'), dict) or not isinstance(state.get('units'), list) or not isinstance(state.get('rules'), list):
                    raise ValueError('missing complete state structure')
                if any(state['meta'].get(k) is None for k in ('level', 'world', 'turn', 'sequence')):
                    raise ValueError('incomplete state metadata')
                state['meta'].update(storage=storage, storage_path=str(candidate))
                changed = state_fingerprint(state) != baseline if baseline is not None else (since_mtime is None or stat.st_mtime > since_mtime)
                if changed:
                    return state
                last_reason, last_detail = 'state_unchanged', f'valid state, no new observation: {candidate}'
                # A valid current save takes precedence over a stale legacy JSON.
                break
            except (OSError, ValueError, TypeError, KeyError) as exc:
                last_reason, last_detail = 'state_parse_failed', f'{candidate}: {exc}'
                break
        if not found:
            last_reason, last_detail = 'state_missing', f'{path} / {save_file}'
        if not wait or time.monotonic() >= deadline:
            raise StateReadError(last_reason, last_detail)
        time.sleep(min(0.05, max(0, deadline - time.monotonic())))


def compact_coord(unit: dict[str, Any]) -> str:
    bits = [f"({unit.get('x')},{unit.get('y')})"]
    if unit.get("dir") is not None:
        bits.append(f"dir={unit.get('dir')}")
    if unit.get("id") is not None:
        bits.append(f"id={unit.get('id')}")
    return " ".join(bits)


def text_word(unit: dict[str, Any]) -> str:
    word = str(unit.get("word") or "").strip().lower()
    if word:
        return word
    name = str(unit.get("name") or "").strip().lower()
    return name.removeprefix("text_") if name.startswith("text_") else name


def edge_text_warnings(meta: dict[str, Any], text_units: list[dict[str, Any]]) -> list[str]:
    width = to_int(str(meta.get("room_width") or ""))
    height = to_int(str(meta.get("room_height") or ""))
    if width is None or height is None:
        return []

    min_x = 1
    min_y = 1
    max_x = width - 2
    max_y = height - 2
    warnings: list[str] = []
    for unit in sorted(text_units, key=lambda item: (text_word(item), item.get("x") or 0, item.get("y") or 0)):
        x = unit.get("x")
        y = unit.get("y")
        word = text_word(unit)
        if x is None or y is None or not word:
            continue
        at_left = x == min_x
        at_right = x == max_x
        at_top = y == min_y
        at_bottom = y == max_y
        if not (at_left or at_right or at_top or at_bottom):
            continue
        locks: list[str] = []
        if at_left or at_right:
            locks.append("horizontal_locked")
        if at_top or at_bottom:
            locks.append("vertical_locked")
        if (at_left or at_right) and (at_top or at_bottom):
            locks.append("corner_locked")
        warnings.append(f"text_{word}@({x},{y}):{','.join(locks)}")
    return warnings


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def parse_coord(value: str) -> Coord:
    try:
        raw_x, raw_y = value.split(",", 1)
        return int(raw_x), int(raw_y)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("coordinates must be X,Y") from exc


def props_by_subject(rules: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = collections.defaultdict(set)
    for rule in rules:
        subject = norm(rule.get("target"))
        effect = norm(rule.get("effect"))
        if subject and effect:
            result[subject].add(effect)
    return result


def unit_subject(unit: dict[str, Any]) -> str:
    if unit.get("unit_type") == "text":
        return "text"
    return norm(unit.get("name"))


def unit_properties(unit: dict[str, Any], props: dict[str, set[str]]) -> list[str]:
    return sorted(props.get(unit_subject(unit), set()))


def hazard_break_opportunities(
    rules: list[dict[str, Any]],
    object_units: list[dict[str, Any]],
) -> list[str]:
    object_names = {norm(unit.get("name")) for unit in object_units if not unit.get("dead")}
    win_subjects = sorted(
        norm(rule.get("target"))
        for rule in rules
        if norm(rule.get("effect")) == "win" and norm(rule.get("target")) not in META_SUBJECTS
    )
    if not win_subjects:
        return []

    opportunities: list[str] = []
    for rule in rules:
        subject = norm(rule.get("target"))
        prop = norm(rule.get("effect"))
        if subject in META_SUBJECTS or prop not in HAZARD_PROPERTIES:
            continue
        if subject not in object_names:
            continue
        opportunities.append(
            f"remove {subject} is {prop} -> existing "
            + "/".join(f"{win_subject} is win" for win_subject in win_subjects)
            + " may become reachable"
        )
    return opportunities


def print_cell_details(
    units: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    cells: list[Coord],
) -> None:
    if not cells:
        return

    props = props_by_subject(rules)
    by_cell: dict[Coord, list[dict[str, Any]]] = collections.defaultdict(list)
    for unit in units:
        if unit.get("dead"):
            continue
        x = unit.get("x")
        y = unit.get("y")
        if x is None or y is None:
            continue
        by_cell[(x, y)].append(unit)

    print()
    print("Cells:")
    for cell in cells:
        print(f"  cell {cell[0]},{cell[1]}:")
        occupants = sorted(
            by_cell.get(cell, []),
            key=lambda item: (str(item.get("unit_type") or ""), str(item.get("name") or ""), item.get("id") or 0),
        )
        if not occupants:
            print("    <empty>")
            continue
        risks: list[str] = []
        for unit in occupants:
            properties = unit_properties(unit, props)
            property_suffix = f" props={','.join(properties)}" if properties else " props=<none>"
            word_suffix = f" word={text_word(unit)}" if unit.get("unit_type") == "text" else ""
            print(
                "    "
                f"{unit.get('name')} type={unit.get('unit_type')}{word_suffix}"
                f"{property_suffix} dir={unit.get('dir')} id={unit.get('id')}"
            )
            relevant = sorted(set(properties) & RISK_PROPERTIES)
            if relevant:
                risks.append(f"{unit.get('name')}:{'/'.join(relevant)}")
        if risks:
            print("    movement_risk=" + "; ".join(risks))
        else:
            print("    movement_risk=<none>")


def print_group(title: str, units: list[dict[str, Any]], *, limit: int) -> None:
    print(title + ":")
    if not units:
        print("  <none>")
        return

    grouped: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for unit in units:
        grouped[str(unit.get("name") or "<unknown>")].append(unit)

    printed = 0
    for name in sorted(grouped):
        coords = ", ".join(compact_coord(unit) for unit in grouped[name])
        print(f"  {name}: {coords}")
        printed += 1
        if limit and printed >= limit:
            remaining = len(grouped) - printed
            if remaining > 0:
                print(f"  ... {remaining} more groups")
            return


def summarize(
    state: dict[str, Any],
    path: Path | None,
    *,
    limit: int,
    cells: list[Coord] | None = None,
) -> None:
    meta = state.get("meta", {})
    units = state.get("units", [])
    rules = state.get("rules", [])
    text_units = [unit for unit in units if unit.get("unit_type") == "text"]
    object_units = [unit for unit in units if unit.get("unit_type") != "text"]
    storage_path = meta.get("storage_path") or path or "<save:[agent_state]>"
    save_dir = Path(storage_path).parent if str(storage_path).endswith(".ba") else None

    print(f"state_path={storage_path}")
    print(f"state_storage={meta.get('storage') or 'unknown'}")
    if save_dir is not None:
        try:
            slot, previous_world, previous_level = current_level(save_dir)
            print(f"save_previous={previous_world}/{previous_level} slot={slot}")
            if meta.get("world") != previous_world or meta.get("level") != previous_level:
                print(
                    "state_warning=agent_state level differs from save Previous; "
                    "the exporter snapshot may be stale, or the game may be inside a child level."
                )
        except Exception as exc:  # noqa: BLE001 - state summaries should stay readable.
            print(f"save_previous_error={type(exc).__name__}: {exc}")
    print(
        "event="
        f"{meta.get('source')} turn={meta.get('turn')} seq={meta.get('sequence')} "
        f"last_command={meta.get('last_command')}"
    )
    print(
        "level="
        f"{meta.get('world')}/{meta.get('level')} "
        f"name={meta.get('level_name') or '<unknown>'} "
        f"size={meta.get('room_width')}x{meta.get('room_height')}"
    )
    print(f"counts=units:{len(units)} text:{len(text_units)} rules:{len(rules)}")

    warnings = edge_text_warnings(meta, text_units)
    if warnings:
        print("edge_text_warnings:")
        for warning in warnings[:10]:
            print(f"  {warning}")
        if len(warnings) > 10:
            print(f"  ... {len(warnings) - 10} more")
        print(
            "edge_rule=locked-axis text cannot be pushed off that axis; "
            "verify edge/corner text plans with a 1-3 step baba_action_check segment"
        )
    opportunities = hazard_break_opportunities(rules, object_units)
    if opportunities:
        print("hazard_break_opportunities:")
        for opportunity in opportunities[:5]:
            print(f"  {opportunity}")
        print(
            "hazard_break_rule=when an existing WIN rule is active, prefer testing hazard-rule removal "
            "before rearranging WIN text"
        )
    print(
        "next_protocol=choose one 1-8 step baba_action_check.py segment with explicit --expect-*; "
        "if the plan moves text/rules, choose a 1-3 step segment before writing more than 5 lines of reasoning"
    )
    if cells:
        print("cell_protocol=use --at X,Y for exact blockers; do not infer blockers from truncated --limit groups")

    print_cell_details(units, rules, cells or [])

    print()
    print("Rules:")
    if not rules:
        print("  <none>")
    else:
        for rule in rules[: limit or None]:
            label = rule.get("text")
            flags = []
            if rule.get("base"):
                flags.append("base")
            if rule.get("visible"):
                flags.append("visible")
            suffix = f" [{' '.join(flags)}]" if flags else ""
            print(f"  {label}{suffix}")
        if limit and len(rules) > limit:
            print(f"  ... {len(rules) - limit} more rules")

    print()
    print_group("Objects", object_units, limit=limit)
    print()
    print_group("Text", text_units, limit=limit)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override JSON state path")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    parser.add_argument("--wait", action="store_true", help="Wait until the state file exists or changes")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait with --wait")
    parser.add_argument(
        "--since-mtime",
        type=float,
        help="With --wait, require the file mtime to become greater than this value",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit printed rule/object groups")
    parser.add_argument(
        "--at",
        action="append",
        default=[],
        type=parse_coord,
        metavar="X,Y",
        help="Print exact occupants and active properties for a cell. Repeat for multiple cells.",
    )
    parser.add_argument(
        "--ignore-loop-guard",
        action="store_true",
        help="Bypass the analysis/action loop guard for manual debugging.",
    )
    args = parser.parse_args()

    guard_enabled = not args.json and not args.at and not args.ignore_loop_guard
    if guard_enabled:
        decision = check_allowed("read_state", args.config)
        if not decision.allowed:
            decision.print_block()
            return 2

    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    path = args.path.expanduser().resolve() if args.path else None
    state = load_state(
        path,
        wait=args.wait,
        timeout=args.timeout,
        since_mtime=args.since_mtime,
        save_dir=save_dir,
    )
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        summarize(state, path, limit=args.limit, cells=args.at)
        if guard_enabled:
            guard_path = record_analysis("read_state", args.config, detail=f"limit={args.limit}")
            if guard_path:
                print(f"loop_guard=after_read path={guard_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
