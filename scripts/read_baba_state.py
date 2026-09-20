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
from parse_baba_level import current_level, read_ini_like


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


def load_save_state(save_file: Path) -> dict[str, Any] | None:
    sections = read_ini_like(save_file)
    raw = sections.get("codex_state")
    if not raw or raw.get("schema") != "codex-baba-state-export-v1":
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
    path: Path,
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
        explicit_json = path.resolve() != (config_save_dir / 'codex_state.json').resolve()
        candidates = [(path, 'json')] if explicit_json else [(save_file, 'save'), (path, 'json')]
        found = False
        for candidate, storage in candidates:
            if not candidate.exists():
                continue
            found = True
            try:
                stat = candidate.stat()
                state = json.loads(candidate.read_text(encoding='utf-8')) if storage == 'json' else load_save_state(candidate)
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


def summarize(state: dict[str, Any], path: Path, *, limit: int) -> None:
    meta = state.get("meta", {})
    units = state.get("units", [])
    rules = state.get("rules", [])
    text_units = [unit for unit in units if unit.get("unit_type") == "text"]
    object_units = [unit for unit in units if unit.get("unit_type") != "text"]

    print(f"state_path={meta.get('storage_path') or path}")
    print(f"state_storage={meta.get('storage') or 'unknown'}")
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
    parser.add_argument("--path", type=Path, help="Override legacy JSON state path")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    parser.add_argument("--wait", action="store_true", help="Wait until the state file exists or changes")
    parser.add_argument("--timeout", type=float, default=3.0, help="Seconds to wait with --wait")
    parser.add_argument(
        "--since-mtime",
        type=float,
        help="With --wait, require the file mtime to become greater than this value",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit printed rule/object groups")
    args = parser.parse_args()

    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    path = args.path.expanduser().resolve() if args.path else (save_dir / "codex_state.json").resolve()
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
        summarize(state, path, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
