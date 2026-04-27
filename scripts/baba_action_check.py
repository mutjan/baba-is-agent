#!/usr/bin/env python3
"""Run a short Baba move segment and verify the expected observable delta.

This is a guardrail for benchmark agents: do not validate a route in hidden
reasoning. Name the expected rule/object/completion change, run the move
segment, and let this script decide whether the observation happened.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from baba_send_keys import parse_moves


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


DELTA_KEYS = (
    "rules_added",
    "rules_removed",
    "moved",
    "appeared",
    "disappeared",
)


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


def parse_try_stdout(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {key: [] for key in DELTA_KEYS}
    parsed["completion_status"] = ""
    parsed["completion_value"] = None
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
    variants = {label, name}
    if target.startswith("text_"):
        candidates = {target, target.removeprefix("text_")}
    else:
        candidates = {target, "text_" + target}
    return any(candidate in variants or label.startswith(candidate + "#") for candidate in candidates)


def rule_matches(items: list[str], expected: str) -> bool:
    target = normalize_rule(expected)
    return target in {normalize_rule(item) for item in items}


def expectation_count(args: argparse.Namespace) -> int:
    total = 0
    for key in (
        "expect_rule_added",
        "expect_rule_removed",
        "expect_moved",
        "expect_appeared",
        "expect_disappeared",
    ):
        total += len(getattr(args, key) or [])
    if args.expect_completion or args.expect_completion_status is not None:
        total += 1
    return total


def expected_summary(args: argparse.Namespace) -> str:
    parts: list[str] = []
    for value in args.expect_rule_added:
        parts.append(f"rule_added:{value}")
    for value in args.expect_rule_removed:
        parts.append(f"rule_removed:{value}")
    for value in args.expect_moved:
        parts.append(f"moved:{value}")
    for value in args.expect_appeared:
        parts.append(f"appeared:{value}")
    for value in args.expect_disappeared:
        parts.append(f"disappeared:{value}")
    if args.expect_completion:
        parts.append("completion_status:3")
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
        focus_names = sorted(
            {
                *args.expect_moved,
                *args.expect_appeared,
                *args.expect_disappeared,
            }
        )
        if focus_names:
            command.extend(["--focus", ",".join(focus_names)])
    if args.limit is not None:
        command.extend(["--limit", str(args.limit)])


def build_try_command(args: argparse.Namespace) -> list[str]:
    command = [sys.executable, str(SCRIPTS_DIR / "baba_try.py"), args.moves]
    append_common_args(command, args)
    return command


def evaluate(parsed: dict[str, Any], args: argparse.Namespace) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for value in args.expect_rule_added:
        if not rule_matches(parsed["rules_added"], value):
            failures.append(f"missing rule_added:{value}")
    for value in args.expect_rule_removed:
        if not rule_matches(parsed["rules_removed"], value):
            failures.append(f"missing rule_removed:{value}")
    for value in args.expect_moved:
        if not any(unit_matches(item, value) for item in parsed["moved"]):
            failures.append(f"missing moved:{value}")
    for value in args.expect_appeared:
        if not any(unit_matches(item, value) for item in parsed["appeared"]):
            failures.append(f"missing appeared:{value}")
    for value in args.expect_disappeared:
        if not any(unit_matches(item, value) for item in parsed["disappeared"]):
            failures.append(f"missing disappeared:{value}")

    expected_status = args.expect_completion_status
    if args.expect_completion:
        expected_status = 3
    if expected_status is not None and parsed["completion_value"] != expected_status:
        failures.append(
            f"completion_status:{expected_status} not reached "
            f"(observed {parsed['completion_status'] or '<missing>'})"
        )
    return not failures, failures


def print_observed(parsed: dict[str, Any]) -> None:
    print("observed_rules_added=" + ("; ".join(parsed["rules_added"]) or "<none>"))
    print("observed_rules_removed=" + ("; ".join(parsed["rules_removed"]) or "<none>"))
    print("observed_moved=" + ("; ".join(parsed["moved"]) or "<none>"))
    print("observed_appeared=" + ("; ".join(parsed["appeared"]) or "<none>"))
    print("observed_disappeared=" + ("; ".join(parsed["disappeared"]) or "<none>"))
    print("observed_completion_status=" + (parsed["completion_status"] or "<none>"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("moves", help="Comma-separated moves, e.g. 'left*3,up'")
    parser.add_argument("--expect-rule-added", action="append", default=[], help="Rule expected to be newly formed.")
    parser.add_argument("--expect-rule-removed", action="append", default=[], help="Rule expected to be broken.")
    parser.add_argument("--expect-moved", action="append", default=[], help="Unit/text expected to move, e.g. text_is.")
    parser.add_argument("--expect-appeared", action="append", default=[], help="Unit/text expected to appear.")
    parser.add_argument("--expect-disappeared", action="append", default=[], help="Unit/text expected to disappear.")
    parser.add_argument("--expect-completion", action="store_true", help="Expect completion status 3.")
    parser.add_argument("--expect-completion-status", type=int, help="Expect a specific completion status value.")
    parser.add_argument("--allow-no-expectation", action="store_true", help="Permit running without expected delta.")
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

    moves = parse_moves(args.moves)
    if not moves:
        print("check=error")
        print("reason=moves must expand to at least one key")
        return 2
    if len(moves) > args.max_moves and not args.allow_long:
        print("check=error")
        print(f"reason=expanded move count {len(moves)} exceeds max_moves {args.max_moves}")
        print("next=split the action into a shorter observable segment or pass --allow-long intentionally")
        return 2
    if expectation_count(args) == 0 and not args.allow_no_expectation:
        print("check=error")
        print("reason=declare at least one expected observable delta")
        print("examples=--expect-moved text_is | --expect-rule-added 'rock is win' | --expect-completion")
        return 2

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
    if failures:
        print("missing=" + "; ".join(failures))
        print("next=do not repair this in thought; shorten, restart, or choose a target the delta actually touched")
    else:
        print("next=continue from the observed delta")
    print("--- baba_try stdout ---")
    print(proc.stdout.rstrip())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
