#!/usr/bin/env python3
"""Suggest small Baba hypotheses from the current live state.

This is intentionally not a solver. It narrows the next search/experiment to a
few functional rule templates: break out, make a tool open, define a win target,
or change control. The output is meant to feed the short check_moves loop.
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


META_SUBJECTS = {"cursor", "level", "text"}
HAZARD_PROPERTIES = {"defeat", "sink", "hot", "melt"}
Coord = tuple[int, int]


@dataclass
class Candidate:
    score: int
    title: str
    rules: list[tuple[str, str]]
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)

    def sort_key(self) -> tuple[int, str]:
        return (-self.score, self.title)


def norm(value: Any) -> str:
    return str(value or "").strip().lower()


def rule_text(subject: str, prop: str) -> str:
    return f"{subject} is {prop}"


def turn_int(meta: dict[str, Any]) -> int:
    try:
        return int(meta.get("turn") or 0)
    except (TypeError, ValueError):
        return 0


def search_command(subject: str, prop: str, *, from_live_state: bool) -> str:
    live_flag = "--from-live-state " if from_live_state else ""
    return (
        "python3 scripts/baba_search_route.py "
        f"{live_flag}"
        f"--make-rule {subject} is {prop} "
        f"--select-text {subject} --select-text {prop} --all-is --no-touch-win "
        "--timeout 20 --max-target-assignments 50000"
    )


def load_current_state(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    path = args.path.expanduser().resolve() if args.path else None
    return load_state(
        path,
        wait=args.wait,
        timeout=args.timeout,
        since_mtime=None,
        save_dir=save_dir,
    )


def int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def text_word(unit: dict[str, Any]) -> str:
    word = norm(unit.get("word"))
    if word:
        return word
    name = norm(unit.get("name"))
    return name.removeprefix("text_") if name.startswith("text_") else name


def add_candidate(
    candidates: list[Candidate],
    *,
    score: int,
    title: str,
    rules: list[tuple[str, str]],
    reasons: list[str],
    risks: list[str] | None = None,
    active_rules: set[tuple[str, str]],
    text_words: set[str],
    from_live_state: bool,
) -> None:
    missing = [(subject, prop) for subject, prop in rules if (subject, prop) not in active_rules]
    commands = [
        search_command(subject, prop, from_live_state=from_live_state)
        for subject, prop in missing
        if subject in text_words and prop in text_words and "is" in text_words
    ]
    candidates.append(
        Candidate(
            score=score,
            title=title,
            rules=rules,
            reasons=reasons,
            risks=risks or [],
            commands=commands,
        )
    )


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    units = state.get("units", [])
    rules = state.get("rules", [])

    objects: collections.Counter[str] = collections.Counter()
    text_counts: collections.Counter[str] = collections.Counter()
    for unit in units:
        if unit.get("dead"):
            continue
        name = norm(unit.get("name"))
        if unit.get("unit_type") == "text":
            word = text_word(unit)
            if word:
                text_counts[word] += 1
        elif name:
            objects[name] += 1

    active_rules: set[tuple[str, str]] = set()
    visible_rules: set[tuple[str, str]] = set()
    props_by_subject: dict[str, set[str]] = collections.defaultdict(set)
    text_positions: dict[str, list[Coord]] = collections.defaultdict(list)
    for rule in rules:
        subject = norm(rule.get("target"))
        prop = norm(rule.get("effect"))
        if not subject or not prop:
            continue
        active_rules.add((subject, prop))
        props_by_subject[subject].add(prop)
        if rule.get("visible"):
            visible_rules.add((subject, prop))

    for unit in units:
        if unit.get("dead") or unit.get("unit_type") != "text":
            continue
        word = text_word(unit)
        x = int_value(unit.get("x"))
        y = int_value(unit.get("y"))
        if word and x is not None and y is not None:
            text_positions[word].append((x, y))

    return {
        "meta": state.get("meta", {}),
        "objects": objects,
        "text_counts": text_counts,
        "text_positions": {word: sorted(coords) for word, coords in text_positions.items()},
        "text_words": set(text_counts),
        "active_rules": active_rules,
        "visible_rules": visible_rules,
        "props_by_subject": props_by_subject,
    }


def edge_text_warnings(summary: dict[str, Any]) -> list[str]:
    meta = summary["meta"]
    width = int_value(meta.get("room_width"))
    height = int_value(meta.get("room_height"))
    if width is None or height is None:
        return []
    min_x = 1
    min_y = 1
    max_x = width - 2
    max_y = height - 2
    warnings: list[str] = []
    for word, coords in sorted(summary["text_positions"].items()):
        for x, y in coords:
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


def score_open_shut_pair(
    *,
    tool: str,
    blocker: str,
    props_by_subject: dict[str, set[str]],
    objects: collections.Counter[str],
) -> tuple[int, list[str], list[str]]:
    tool_props = props_by_subject.get(tool, set())
    blocker_props = props_by_subject.get(blocker, set())
    score = 45
    reasons = [f"{blocker} currently blocks movement", "OPEN+SHUT can remove both objects on contact"]
    risks: list[str] = []

    if "push" in tool_props:
        score += 35
        reasons.append(f"{tool} is already pushable")
    else:
        score -= 15
        risks.append(f"{tool} is not currently push")

    if "open" in tool_props:
        score += 12
        reasons.append(f"{tool} is already open")

    if blocker == "wall":
        score += 14
        reasons.append("wall is a common enclosure blocker")
    elif blocker == "door":
        score += 10
        reasons.append("door is a local exit blocker")

    if objects.get(tool):
        score += 8
    if objects.get(blocker):
        score += 8

    hazards = sorted(tool_props & HAZARD_PROPERTIES)
    if hazards:
        penalty = 35 if "defeat" in hazards else 20
        score -= penalty
        risks.append(f"{tool} is {'/'.join(hazards)}")

    if "stop" not in blocker_props:
        score -= 12
        risks.append(f"{blocker} is not currently stop")

    return score, reasons, risks


def mechanic_warnings(summary: dict[str, Any]) -> list[str]:
    props_by_subject: dict[str, set[str]] = summary["props_by_subject"]
    push_sink = sorted(
        subject
        for subject, props in props_by_subject.items()
        if subject not in META_SUBJECTS and {"push", "sink"} <= props
    )
    stop_subjects = sorted(
        subject
        for subject, props in props_by_subject.items()
        if subject not in META_SUBJECTS and "stop" in props
    )
    if push_sink and stop_subjects:
        return [
            "PUSH+SINK objects cannot be pushed through STOP blockers; use them on non-STOP objects/hazards, "
            "or first remove/bypass STOP with a rule delta such as SHUT+OPEN or breaking X IS STOP. "
            f"push_sink={','.join(push_sink)} stop={','.join(stop_subjects)}"
        ]
    return []


def build_candidates(summary: dict[str, Any]) -> list[Candidate]:
    objects: collections.Counter[str] = summary["objects"]
    text_words: set[str] = summary["text_words"]
    active_rules: set[tuple[str, str]] = summary["active_rules"]
    visible_rules: set[tuple[str, str]] = summary["visible_rules"]
    props_by_subject: dict[str, set[str]] = summary["props_by_subject"]
    from_live_state = turn_int(summary["meta"]) > 0
    candidates: list[Candidate] = []

    stop_subjects = sorted(
        subject
        for subject, props in props_by_subject.items()
        if "stop" in props and subject not in META_SUBJECTS
    )
    push_subjects = sorted(
        subject
        for subject, props in props_by_subject.items()
        if "push" in props and subject not in META_SUBJECTS
    )
    open_subjects = sorted(
        subject
        for subject, props in props_by_subject.items()
        if "open" in props and subject not in META_SUBJECTS
    )
    you_subjects = sorted(
        subject
        for subject, props in props_by_subject.items()
        if "you" in props and subject not in META_SUBJECTS
    )

    possible_tools = sorted(set(push_subjects) | set(open_subjects))
    for blocker in stop_subjects:
        if blocker not in text_words or "shut" not in text_words:
            continue
        for tool in possible_tools:
            if tool not in text_words or "open" not in text_words:
                continue
            score, reasons, risks = score_open_shut_pair(
                tool=tool,
                blocker=blocker,
                props_by_subject=props_by_subject,
                objects=objects,
            )
            rules = [(blocker, "shut"), (tool, "open")]
            title = f"breakout: {rule_text(blocker, 'shut')} + {rule_text(tool, 'open')}"
            add_candidate(
                candidates,
                score=score,
                title=title,
                rules=rules,
                reasons=reasons,
                risks=risks,
                active_rules=active_rules,
                text_words=text_words,
                from_live_state=from_live_state,
            )

    for subject in sorted(set(you_subjects) | set(push_subjects) | set(objects)):
        if subject in META_SUBJECTS or subject not in text_words or "win" not in text_words:
            continue
        score = 44
        reasons = ["direct WIN rule can end the level if the object is reachable"]
        risks: list[str] = []
        props = props_by_subject.get(subject, set())
        if "you" in props:
            score += 28
            reasons.append(f"{subject} is already you")
        if "push" in props:
            score += 10
            reasons.append(f"{subject} is pushable")
        if props & HAZARD_PROPERTIES:
            score -= 18
            risks.append(f"{subject} has hazard property: {'/'.join(sorted(props & HAZARD_PROPERTIES))}")
        add_candidate(
            candidates,
            score=score,
            title=f"direct win: {rule_text(subject, 'win')}",
            rules=[(subject, "win")],
            reasons=reasons,
            risks=risks,
            active_rules=active_rules,
            text_words=text_words,
            from_live_state=from_live_state,
        )

    for subject in sorted(set(objects) | set(text_words)):
        if subject in META_SUBJECTS or subject in you_subjects or subject not in text_words:
            continue
        if "you" not in text_words:
            continue
        score = 28
        reasons = ["control shift can bypass a body-position bottleneck"]
        risks = ["high risk: losing current YOU can strand the attempt"]
        if subject in push_subjects:
            score += 10
        if subject in stop_subjects:
            score += 8
        add_candidate(
            candidates,
            score=score,
            title=f"control shift: {rule_text(subject, 'you')}",
            rules=[(subject, "you")],
            reasons=reasons,
            risks=risks,
            active_rules=active_rules,
            text_words=text_words,
            from_live_state=from_live_state,
        )

    win_subjects = sorted(
        subject
        for subject, props in props_by_subject.items()
        if "win" in props and subject not in META_SUBJECTS
    )
    for subject in win_subjects:
        if subject not in text_words or "move" not in text_words or (subject, "move") in active_rules:
            continue
        subject_objects = objects.get(subject, 0)
        score = 62
        reasons = [
            f"{subject} is already WIN",
            "adding MOVE can make the WIN object leave an enclosure or deliver itself without first reaching it",
        ]
        risks = [
            "MOVE direction matters; verify the first tick with --expect-moved-delta or --expect-position before chasing it",
            "MOVE can send the WIN object away, into a pocket, or into a hazard",
        ]
        if subject_objects:
            score += 20
            reasons.append(f"{subject} objects are present")
        if "push" in props_by_subject.get(subject, set()):
            score += 8
            reasons.append(f"{subject} is already pushable, so the same object may be a manipulable phase target")
        add_candidate(
            candidates,
            score=score,
            title=f"animate win object: {rule_text(subject, 'move')}",
            rules=[(subject, "move")],
            reasons=reasons,
            risks=risks,
            active_rules=active_rules,
            text_words=text_words,
            from_live_state=from_live_state,
        )

    for subject, prop in sorted(visible_rules):
        if subject in META_SUBJECTS or prop not in {"stop"} | HAZARD_PROPERTIES:
            continue
        score = 36
        reasons = [f"breaking visible {rule_text(subject, prop)} may open movement"]
        risks = ["verify immediately; removing a blocker/hazard can also change puzzle assumptions"]
        if prop in HAZARD_PROPERTIES:
            score += 34
            reasons.append(f"{subject} objects stop being {prop} after the rule is broken")
            if win_subjects:
                score += 22
                reasons.append(
                    "existing WIN rule already present: "
                    + "; ".join(rule_text(win_subject, "win") for win_subject in win_subjects)
                )
                risks.append("after breaking the hazard, immediately test a route to the existing WIN object")
            if subject in objects:
                score += 6
                reasons.append(f"{subject} objects are present on the map")
        elif prop == "stop":
            risks.append("removing STOP can open movement but may also remove useful structure")
        add_candidate(
            candidates,
            score=score,
            title=f"break rule: remove {rule_text(subject, prop)}",
            rules=[],
            reasons=reasons,
            risks=risks,
            active_rules=active_rules,
            text_words=text_words,
            from_live_state=from_live_state,
        )

    unique: dict[tuple[str, tuple[tuple[str, str], ...]], Candidate] = {}
    for candidate in candidates:
        key = (candidate.title, tuple(candidate.rules))
        previous = unique.get(key)
        if previous is None or candidate.score > previous.score:
            unique[key] = candidate
    return sorted(unique.values(), key=Candidate.sort_key)


def as_json(summary: dict[str, Any], candidates: list[Candidate], top: int, *, show_search: bool) -> str:
    meta = summary["meta"]
    payload = {
        "level": {
            "world": meta.get("world"),
            "level": meta.get("level"),
            "name": meta.get("level_name"),
            "turn": meta.get("turn"),
        },
        "post_hypothesis_protocol": {
            "max_analyze_runs": 1,
            "required_next_action": "choose one 1-8 step baba_action_check.py segment with explicit --expect-*; use 1-3 steps for text/rule pushes",
            "search_target_scope": "if a solution needs multiple rule changes, each baba_search_route.py call should target only the next immediate rule/prefix objective, not the final pass condition",
            "forbidden": "do not write more than 5 lines of rule-arrangement reasoning after hypotheses/analyze output",
            "push_chain_rule": "chain pushes require free space after the far end; corner/edge/pocket pushes are high-risk and must be verified with short action_check segments",
            "search_state": (
                "current turn > 0, so search_next commands include --from-live-state"
                if turn_int(meta) > 0
                else "current turn is 0/unknown, so search_next commands use the initial level file"
            ),
        },
        "edge_text_warnings": edge_text_warnings(summary),
        "signals": {
            "you": sorted(
                subject for subject, props in summary["props_by_subject"].items() if "you" in props
            ),
            "push": sorted(
                subject for subject, props in summary["props_by_subject"].items() if "push" in props
            ),
            "open": sorted(
                subject for subject, props in summary["props_by_subject"].items() if "open" in props
            ),
            "move": sorted(
                subject for subject, props in summary["props_by_subject"].items() if "move" in props
            ),
            "stop": sorted(
                subject for subject, props in summary["props_by_subject"].items() if "stop" in props
            ),
            "hazards": sorted(
                f"{subject}:{prop}"
                for subject, props in summary["props_by_subject"].items()
                for prop in props & HAZARD_PROPERTIES
            ),
        },
        "mechanic_warnings": mechanic_warnings(summary),
        "candidates": [
            {
                "score": item.score,
                "title": item.title,
                "rules": [rule_text(subject, prop) for subject, prop in item.rules],
                "reasons": item.reasons,
                "risks": item.risks,
                "commands": item.commands if show_search else [],
                "commands_suppressed": bool(item.commands and not show_search),
            }
            for item in candidates[:top]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def print_human(summary: dict[str, Any], candidates: list[Candidate], top: int, *, show_search: bool) -> None:
    meta = summary["meta"]
    props_by_subject: dict[str, set[str]] = summary["props_by_subject"]
    print(
        "level="
        f"{meta.get('world')}/{meta.get('level')} "
        f"name={meta.get('level_name') or '<unknown>'} "
        f"turn={meta.get('turn')}"
    )
    if turn_int(meta) > 0:
        print("search_state=current live board has already changed; search_next includes --from-live-state")
    print("signals:")
    for prop in ("you", "push", "open", "shut", "move", "stop", "defeat", "win"):
        subjects = sorted(subject for subject, props in props_by_subject.items() if prop in props)
        if subjects:
            print(f"  {prop}: {', '.join(subjects)}")
    edge_warnings = edge_text_warnings(summary)
    if edge_warnings:
        print("edge_text_warnings:")
        for warning in edge_warnings[:10]:
            print(f"  {warning}")
        if len(edge_warnings) > 10:
            print(f"  ... {len(edge_warnings) - 10} more")
        print("edge_rule=locked-axis text cannot be pushed off that axis; build around it or move other words instead of planning a blocked push")
    warnings = mechanic_warnings(summary)
    if warnings:
        print("mechanic_warnings:")
        for warning in warnings:
            print(f"  {warning}")
    print()
    print("hypotheses:")
    if not candidates:
        print("  <none>")
        return
    for index, item in enumerate(candidates[:top], 1):
        print(f"{index}. score={item.score} {item.title}")
        if item.rules:
            print("   target_rules=" + "; ".join(rule_text(subject, prop) for subject, prop in item.rules))
        print("   why=" + "; ".join(item.reasons))
        if item.risks:
            print("   risk=" + "; ".join(item.risks))
        if item.commands and show_search:
            print("   search_next:")
            for command in item.commands:
                print(f"     {command}")
            print("   search_rule=run at most one --analyze if the text layout is unclear; then immediately choose one 1-8 step baba_action_check.py segment with explicit --expect-*; use 1-3 steps for text/rule pushes")
            print("   search_target_scope=one search call should aim at the next immediate rule/prefix delta only; if the level needs multiple rule changes, verify this delta first, then call search again")
            print("   narrow_rule=if --analyze is too broad, add --target-start/--target-dir or --select-text-at before any larger search")
        elif item.commands:
            print("   search_next_suppressed=default output hides route-search commands; use --show-search only after choosing one candidate")
            print("   search_target_scope=when revealing a command, use it as one immediate rule/prefix target, not as a full-solution search")
        print("   push_safety=before pushing text/object, check the whole chain and the far-end cell; avoid corners, edges, STOP/DEFEAT, and one-cell pockets unless the next action_check proves it is safe")
        print("   verify=after any route, run baba_action_check.py with --expect-rule-added, --expect-moved-delta, or --expect-position plus --expect-rule-kept for current YOU if control must remain")
    print()
    print("post_hypothesis_protocol=max_analyze_runs=1; next=choose one 1-8 step baba_action_check.py segment with explicit --expect-*; text/rule push next segment must be 1-3 steps")
    print("search_target_protocol=do not aim search_route at the final win if that requires several rule changes; split into one immediate rule/prefix target, verify, then search again")
    if turn_int(meta) > 0:
        print("post_hypothesis_search_rule=keep --from-live-state for route analysis/search until the level is restarted")
    print("push_chain_rule=chain pushes require free space after the far end; corner/edge/pocket pushes are high-risk and should be verified by a short action_check, not prose")
    print("forbidden_after_hypotheses=do not write more than 5 lines of rule-arrangement reasoning before the next action_check; do not continue prose after identifying a 1-3 step text/rule test")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override JSON state path")
    parser.add_argument("--wait", action="store_true", help="Wait for state to appear")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--top", type=int, default=8, help="Number of hypotheses to print")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument("--show-search", action="store_true", help="Also print search_next commands. Hidden by default to discourage search loops.")
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
    summary = summarize_state(state)
    candidates = build_candidates(summary)
    guard_path = None
    if not args.ignore_loop_guard:
        guard_path = record_analysis("suggest", args.config, detail=f"top={args.top}")
    if args.json:
        print(as_json(summary, candidates, args.top, show_search=args.show_search))
    else:
        print_human(summary, candidates, args.top, show_search=args.show_search)
        if guard_path:
            print(f"loop_guard=after_suggest path={guard_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
