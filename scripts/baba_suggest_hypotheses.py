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
from read_baba_state import load_state


META_SUBJECTS = {"cursor", "level", "text"}
HAZARD_PROPERTIES = {"defeat", "sink", "hot", "melt"}


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


def search_command(subject: str, prop: str) -> str:
    return (
        "python3 scripts/baba_search_route.py "
        f"--make-rule {subject} is {prop} "
        f"--select-text {subject} --select-text {prop} --all-is --no-touch-win"
    )


def load_current_state(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    save_dir = args.save_dir or config.save_dir
    path = args.path.expanduser().resolve() if args.path else (save_dir / "codex_state.json").resolve()
    return load_state(
        path,
        wait=args.wait,
        timeout=args.timeout,
        since_mtime=None,
        save_dir=save_dir,
    )


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
) -> None:
    missing = [(subject, prop) for subject, prop in rules if (subject, prop) not in active_rules]
    commands = [
        search_command(subject, prop)
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
    for rule in rules:
        subject = norm(rule.get("target"))
        prop = norm(rule.get("effect"))
        if not subject or not prop:
            continue
        active_rules.add((subject, prop))
        props_by_subject[subject].add(prop)
        if rule.get("visible"):
            visible_rules.add((subject, prop))

    return {
        "meta": state.get("meta", {}),
        "objects": objects,
        "text_counts": text_counts,
        "text_words": set(text_counts),
        "active_rules": active_rules,
        "visible_rules": visible_rules,
        "props_by_subject": props_by_subject,
    }


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


def build_candidates(summary: dict[str, Any]) -> list[Candidate]:
    objects: collections.Counter[str] = summary["objects"]
    text_words: set[str] = summary["text_words"]
    active_rules: set[tuple[str, str]] = summary["active_rules"]
    visible_rules: set[tuple[str, str]] = summary["visible_rules"]
    props_by_subject: dict[str, set[str]] = summary["props_by_subject"]
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
        )

    for subject, prop in sorted(visible_rules):
        if subject in META_SUBJECTS or prop != "stop":
            continue
        score = 36
        reasons = [f"breaking visible {rule_text(subject, prop)} may open movement"]
        risks = ["verify immediately; removing STOP can also change puzzle assumptions"]
        add_candidate(
            candidates,
            score=score,
            title=f"break rule: remove {rule_text(subject, prop)}",
            rules=[],
            reasons=reasons,
            risks=risks,
            active_rules=active_rules,
            text_words=text_words,
        )

    unique: dict[tuple[str, tuple[tuple[str, str], ...]], Candidate] = {}
    for candidate in candidates:
        key = (candidate.title, tuple(candidate.rules))
        previous = unique.get(key)
        if previous is None or candidate.score > previous.score:
            unique[key] = candidate
    return sorted(unique.values(), key=Candidate.sort_key)


def as_json(summary: dict[str, Any], candidates: list[Candidate], top: int) -> str:
    meta = summary["meta"]
    payload = {
        "level": {
            "world": meta.get("world"),
            "level": meta.get("level"),
            "name": meta.get("level_name"),
            "turn": meta.get("turn"),
        },
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
            "stop": sorted(
                subject for subject, props in summary["props_by_subject"].items() if "stop" in props
            ),
            "hazards": sorted(
                f"{subject}:{prop}"
                for subject, props in summary["props_by_subject"].items()
                for prop in props & HAZARD_PROPERTIES
            ),
        },
        "candidates": [
            {
                "score": item.score,
                "title": item.title,
                "rules": [rule_text(subject, prop) for subject, prop in item.rules],
                "reasons": item.reasons,
                "risks": item.risks,
                "commands": item.commands,
            }
            for item in candidates[:top]
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def print_human(summary: dict[str, Any], candidates: list[Candidate], top: int) -> None:
    meta = summary["meta"]
    props_by_subject: dict[str, set[str]] = summary["props_by_subject"]
    print(
        "level="
        f"{meta.get('world')}/{meta.get('level')} "
        f"name={meta.get('level_name') or '<unknown>'} "
        f"turn={meta.get('turn')}"
    )
    print("signals:")
    for prop in ("you", "push", "open", "shut", "stop", "defeat", "win"):
        subjects = sorted(subject for subject, props in props_by_subject.items() if prop in props)
        if subjects:
            print(f"  {prop}: {', '.join(subjects)}")
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
        if item.commands:
            print("   search_next:")
            for command in item.commands:
                print(f"     {command}")
        print("   verify=after any route, run baba_action_check.py with --expect-rule-added or --expect-moved")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Path to baba_config.json")
    parser.add_argument("--save-dir", type=Path, help="Override configured save directory")
    parser.add_argument("--path", type=Path, help="Override legacy JSON state path")
    parser.add_argument("--wait", action="store_true", help="Wait for state to appear")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--top", type=int, default=8, help="Number of hypotheses to print")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    state = load_current_state(args)
    summary = summarize_state(state)
    candidates = build_candidates(summary)
    if args.json:
        print(as_json(summary, candidates, args.top))
    else:
        print_human(summary, candidates, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
