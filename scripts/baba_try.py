#!/usr/bin/env python3
"""Send a short Baba move segment and print the meaningful state delta."""

from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Any

from baba_config import load_config
from baba_send_keys import activate_game, frontmost_process, parse_moves
from baba_step import current_state_mtime, send_one, state_path
from parse_baba_level import read_ini_like
from read_baba_state import current_save_file, load_state
from read_baba_state import StateReadError, state_fingerprint
from baba_execution import (ActionJournal, ExecutionError, actions_dir, action_path,
                            exclusive_lock, game_lock_path, new_action_id)


def rule_text(rule: dict[str, Any]) -> str:
    target = rule.get("target") or "?"
    verb = rule.get("verb") or "is"
    effect = rule.get("effect") or "?"
    suffix = " [base]" if rule.get("base") else ""
    return f"{target} {verb} {effect}{suffix}"


def ruleset(state: dict[str, Any]) -> set[str]:
    return {rule_text(rule) for rule in state.get("rules", [])}


def unit_label(unit: dict[str, Any]) -> str:
    name = str(unit.get("name") or "<unknown>")
    unit_id = unit.get("id")
    if unit_id is None:
        return name
    return f"{name}#{unit_id}"


def unit_key(unit: dict[str, Any]) -> tuple[str, int | str]:
    unit_id = unit.get("id")
    if unit_id is not None:
        return ("id", int(unit_id))
    runtime_id = unit.get("runtime_id")
    if runtime_id is not None:
        return ("runtime", int(runtime_id))
    return ("label", unit_label(unit))


def visible_units(state: dict[str, Any]) -> dict[tuple[str, int | str], dict[str, Any]]:
    result: dict[tuple[str, int | str], dict[str, Any]] = {}
    for unit in state.get("units", []):
        if unit.get("dead") or not unit.get("visible", True):
            continue
        result[unit_key(unit)] = unit
    return result


def coord(unit: dict[str, Any]) -> tuple[int | None, int | None]:
    return (unit.get("x"), unit.get("y"))


def parse_focus(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def focused(name: str, focus: set[str] | None) -> bool:
    if focus is None:
        return True
    bare = name.removeprefix("text_")
    return name in focus or bare in focus


def print_header(state: dict[str, Any], label: str) -> None:
    meta = state.get("meta", {})
    world = meta.get("world")
    level = meta.get("level")
    name = meta.get("level_name")
    print(
        f"{label}=world:{world} level:{level} name:{name} "
        f"turn:{meta.get('turn')} seq:{meta.get('sequence')} "
        f"event:{meta.get('source')} command:{meta.get('last_command')}"
    )


def print_delta(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    focus: set[str] | None,
    limit: int,
) -> None:
    before_rules = ruleset(before)
    after_rules = ruleset(after)
    added_rules = sorted(after_rules - before_rules)
    removed_rules = sorted(before_rules - after_rules)

    if added_rules:
        print("rules_added=" + "; ".join(added_rules))
    if removed_rules:
        print("rules_removed=" + "; ".join(removed_rules))
    if not added_rules and not removed_rules:
        print("rules_delta=<none>")

    before_units = visible_units(before)
    after_units = visible_units(after)
    moved: list[str] = []
    appeared: list[str] = []
    disappeared: list[str] = []

    for key, after_unit in sorted(after_units.items(), key=lambda item: unit_label(item[1])):
        name = str(after_unit.get("name") or "")
        if not focused(name, focus):
            continue
        before_unit = before_units.get(key)
        if before_unit is None:
            appeared.append(f"{unit_label(after_unit)}@{coord(after_unit)}")
            continue
        if coord(before_unit) != coord(after_unit):
            moved.append(f"{unit_label(after_unit)}:{coord(before_unit)}->{coord(after_unit)}")

    for key, before_unit in sorted(before_units.items(), key=lambda item: unit_label(item[1])):
        name = str(before_unit.get("name") or "")
        if key not in after_units and focused(name, focus):
            disappeared.append(f"{unit_label(before_unit)}@{coord(before_unit)}")

    def print_items(title: str, items: list[str]) -> None:
        if not items:
            print(f"{title}=<none>")
            return
        shown = items[:limit]
        print(f"{title}=" + "; ".join(shown))
        if len(items) > len(shown):
            print(f"{title}_remaining={len(items) - len(shown)}")

    print_items("moved", moved)
    print_items("appeared", appeared)
    print_items("disappeared", disappeared)


def level_status(save_dir: Path, world: str | None, level: str | None) -> str | None:
    if not world or not level:
        return None
    save_file = current_save_file(save_dir)
    section = read_ini_like(save_file).get(world, {})
    value = section.get(level)
    if value is None:
        return None
    return f"{level}={value}"


def validate_benchmark(config, state, save_dir):
    names = {u.get('name') for u in state.get('units', [])}
    if {'cursor', 'level'} <= names:
        return
    active_path = actions_dir(config).parent / 'baba_benchmark_active.json'
    try:
        active = json.loads(active_path.read_text())
    except (OSError, ValueError) as exc:
        raise ExecutionError('benchmark_not_started: start_benchmark before moving') from exc
    meta = state['meta']
    if (active.get('world'), active.get('level')) != (meta.get('world'), meta.get('level')):
        raise ExecutionError('active_state_mismatch: inspect and start_benchmark --force-new')
    if level_status(save_dir, meta.get('world'), meta.get('level')) == f"{meta.get('level')}=3":
        raise ExecutionError('level_already_complete: record_pass before further moves')


def wait_move(path, save_dir, before, move, timeout):
    deadline = time.monotonic() + timeout
    observed = before
    while True:
        latest = load_state(path, wait=True, timeout=max(0, deadline-time.monotonic()),
                            since_mtime=None, since_state=observed, save_dir=save_dir)
        meta = latest['meta']
        if meta.get('source') in ('effect_once', 'level_win_after', 'undoed_after', 'level_start', 'level_restart'):
            if meta.get('world') != before['meta'].get('world'):
                raise ExecutionError('unexpected_world_change')
            if meta.get('level') != before['meta'].get('level') and meta.get('source') != 'level_win_after':
                raise ExecutionError('unexpected_level_change')
            if move in ('up', 'down', 'left', 'right') and meta.get('turn') != before['meta'].get('turn') + 1:
                raise ExecutionError('unexpected_turn_delta: inspect input before continuing')
            return latest
        observed = latest
        if time.monotonic() >= deadline:
            raise StateReadError('state_incomplete_turn', 'only intermediate exports observed')


def execute_segment(args, config, save_dir, path, moves, action_id):
    journal = None
    with exclusive_lock(game_lock_path(save_dir)), exclusive_lock(action_path(config, action_id).with_suffix('.lock')):
        before = load_state(path, wait=False, timeout=0, since_mtime=None, save_dir=save_dir)
        journal = ActionJournal(config, action_id, moves, before, resume=args.resume,
                                request=json.loads(args.check_request))
        if journal.record['phase'] == 'completed':
            print('phase=cached_result', flush=True)
            return journal.record['before'], journal.record['after']
        try:
            validate_benchmark(config, before, save_dir)
            journal.update('focusing')
            print(f'phase=focusing action_id={action_id}', flush=True)
            if not args.no_activate:
                activate_game(args.app_name or config.app_name)
                time.sleep(args.pre_delay)
            latest = journal.record['after']
            for index in range(journal.record['confirmed_steps'], len(moves)):
                if action_path(config, action_id).with_suffix('.cancel').exists():
                    journal.update('cancelled', stop_reason='cancel_requested')
                    break
                move = moves[index]
                current = load_state(path, wait=False, timeout=0, since_mtime=None, save_dir=save_dir)
                if state_fingerprint(current) != state_fingerprint(latest):
                    raise ExecutionError('live_state_drift: inspect state before continuing')
                if frontmost_process() not in {args.app_name or config.app_name, 'Chowdren'}:
                    raise ExecutionError('window_unfocused: no key sent')
                journal.dispatch(index, move)
                started = time.monotonic()
                print(f'phase=sending action_id={action_id} step={index+1}/{len(moves)} move={move}', flush=True)
                send_one(move, method=args.method, delay=args.delay if args.delay is not None else config.input_delay, hold_ms=args.hold_ms)
                journal.update('waiting_state')
                print(f'phase=waiting_state action_id={action_id} step={index+1}', flush=True)
                new_state = wait_move(path, save_dir, latest, move, args.timeout)
                journal.confirm(new_state, time.monotonic()-started)
                meta = new_state['meta']
                print(f"sent={index+1}/{len(moves)} move={move} turn={meta.get('turn')} seq={meta.get('sequence')} event={meta.get('source')} command={meta.get('last_command')}", flush=True)
                changed = ruleset(latest) != ruleset(new_state)
                latest = new_state
                if meta.get('source') == 'level_win_after':
                    journal.update('completed', stop_reason='win')
                    break
                if changed and index+1 < len(moves):
                    journal.update('checkpoint', stop_reason='rule_change')
                    print(f'phase=checkpoint confirmed_steps={index+1} remaining_steps={len(moves)-index-1}', flush=True)
                    break
            else:
                journal.update('completed', stop_reason='moves_finished')
            return journal.record['before'], latest
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            reason = getattr(exc, 'reason', str(exc) or type(exc).__name__)
            journal.update('interrupted' if isinstance(exc, KeyboardInterrupt) else 'error', error=reason)
            print(f'phase={journal.record["phase"]} action_id={action_id} confirmed_steps={journal.record["confirmed_steps"]} pending={json.dumps(journal.record["pending"])} reason={reason}', flush=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("moves", nargs="?", default="", help="Comma-separated moves, e.g. 'left*3,up'")
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--app-name", help="Override configured macOS app name")
    parser.add_argument("--state-path", type=Path, help="Override legacy JSON state path")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait after each move")
    parser.add_argument(
        "--delay",
        type=float,
        help="Delay after each key press. Defaults to input_delay in baba_config.json.",
    )
    parser.add_argument("--hold-ms", type=int, default=90, help="Milliseconds to hold each cgevent key")
    parser.add_argument(
        "--method",
        choices=["cgevent", "applescript"],
        default="cgevent",
        help="Key injection method. cgevent is the verified Baba input path.",
    )
    parser.add_argument("--no-activate", action="store_true", help="Do not activate Baba before sending")
    parser.add_argument("--pre-delay", type=float, default=0.15, help="Delay after activating Baba")
    parser.add_argument(
        "--focus",
        help="Comma-separated unit names to show, such as wall,text_is,flag,win. Defaults to all changed units.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Limit printed changed units per category")
    parser.add_argument('--action-id', help='Stable action identifier for status/resume')
    parser.add_argument('--resume', action='store_true', help='Resume only a confirmed prefix with an exact state match')
    parser.add_argument('--check-request', default='{}', help=argparse.SUPPRESS)
    parser.add_argument('--status', metavar='ACTION_ID', help='Read durable progress without sending keys')
    args = parser.parse_args()

    config = load_config(args.config)
    if args.status:
        from baba_execution import action_status
        print(json.dumps(action_status(config, args.status), ensure_ascii=False))
        return 0
    save_dir = args.save_dir or config.save_dir
    app_name = args.app_name or config.app_name
    delay = args.delay if args.delay is not None else config.input_delay
    live_state_path = state_path(save_dir, args.state_path)

    moves = parse_moves(args.moves) if args.moves else []
    if moves:
        action_id = args.action_id or new_action_id()
        print(f'phase=accepted action_id={action_id}', flush=True)
        try:
            before, after = execute_segment(args, config, save_dir, live_state_path, moves, action_id)
        except (ExecutionError, StateReadError) as exc:
            print(f'check=error reason={exc}', flush=True)
            return 1
    else:
        before = load_state(live_state_path, wait=False, timeout=0, since_mtime=None, save_dir=save_dir)
        after = before

    print_header(before, "before")
    print_header(after, "after")
    focus = parse_focus(args.focus)
    print_delta(before, after, focus=focus, limit=args.limit)

    before_meta = before.get("meta", {})
    status = level_status(save_dir, before_meta.get("world"), before_meta.get("level"))
    if status is not None:
        print("completion_status=" + status)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
