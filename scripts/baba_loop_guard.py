#!/usr/bin/env python3
"""Shared loop guard for Baba benchmark agents.

The guard is intentionally small and stateful. Observation/search tools may
advance the guard, but only a concrete action_check resets it. This makes the
short feedback loop a tool-level contract instead of a prompt-only request.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from baba_config import load_config


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
GUARD_NAME = "baba_loop_guard.json"
VALID_RUN_RE = re.compile(r"\d{3}_[A-Za-z0-9][A-Za-z0-9_.-]*")

OPEN = "open"
AFTER_READ = "after_read"
AFTER_SUGGEST = "after_suggest"
AFTER_ANALYZE = "after_analyze"

ALLOWED_NEXT: dict[str, set[str]] = {
    OPEN: {"read_state", "suggest", "search", "search_analyze", "action_check"},
    AFTER_READ: {"suggest", "action_check"},
    AFTER_SUGGEST: {"search_analyze", "action_check"},
    AFTER_ANALYZE: {"action_check"},
}

NEXT_HINTS: dict[str, str] = {
    OPEN: "read_state, rule_goal_scan, suggest_hypotheses, one analyze/search, or action_check",
    AFTER_READ: "run baba_rule_goal_scan.py or baba_suggest_hypotheses.py once, or run baba_action_check.py with an explicit --expect-*",
    AFTER_SUGGEST: "run at most one baba_search_route.py --analyze for one rule delta, or run baba_action_check.py with an explicit --expect-*",
    AFTER_ANALYZE: "run baba_action_check.py with a 1-8 step segment and explicit --expect-*",
}

STATE_AFTER_KIND: dict[str, str] = {
    "read_state": AFTER_READ,
    "suggest": AFTER_SUGGEST,
    "search": AFTER_ANALYZE,
    "search_analyze": AFTER_ANALYZE,
}


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    path: Path | None
    state: str
    reason: str = ""

    def print_block(self) -> None:
        print("loop_guard=action_required")
        print(f"loop_guard_state={self.state}")
        if self.path:
            print(f"loop_guard_path={self.path}")
        print(f"reason={self.reason}")
        print("allowed_next=python3 scripts/baba_action_check.py '<1-8 moves>' --expect-moved-delta '<unit-or-text>:<dir>'")
        print("allowed_next=python3 scripts/baba_action_check.py '<1-3 text/rule push moves>' --expect-moved-delta text_<word>:<dir>")
        print("forbidden_next=more read/rule_goal_scan/suggest/search/analyze before action_check; more than 5 lines of rule-arrangement prose")


def stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def guard_path(config_path: Path | None = None) -> Path | None:
    try:
        config = load_config(config_path, refresh_status=False)
    except SystemExit:
        return None
    run_id = (config.current_run_id or "").strip()
    if not run_id or not VALID_RUN_RE.fullmatch(run_id):
        return None
    return RUNS_ROOT / run_id / GUARD_NAME


def default_guard() -> dict[str, Any]:
    return {
        "version": 1,
        "state": OPEN,
        "updated_at": stamp(),
        "events": [],
    }


def read_guard(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return default_guard()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_guard()
    return payload if isinstance(payload, dict) else default_guard()


def write_guard(path: Path | None, guard: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(guard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event_entry(kind: str, detail: str = "") -> dict[str, str]:
    entry = {"at": stamp(), "kind": kind}
    if detail:
        entry["detail"] = detail
    return entry


def append_event(guard: dict[str, Any], kind: str, detail: str = "") -> None:
    events = guard.get("events")
    if not isinstance(events, list):
        events = []
    events.append(event_entry(kind, detail))
    guard["events"] = events[-20:]
    guard["updated_at"] = stamp()


def check_allowed(kind: str, config_path: Path | None = None, *, ignore: bool = False) -> GuardDecision:
    path = guard_path(config_path)
    guard = read_guard(path)
    state = str(guard.get("state") or OPEN)
    if ignore or path is None:
        return GuardDecision(True, path, state)
    allowed = ALLOWED_NEXT.get(state, ALLOWED_NEXT[OPEN])
    if kind in allowed:
        return GuardDecision(True, path, state)
    return GuardDecision(
        False,
        path,
        state,
        reason=f"{kind} is blocked after {state}; next must be {NEXT_HINTS.get(state, NEXT_HINTS[AFTER_ANALYZE])}",
    )


def record_analysis(kind: str, config_path: Path | None = None, *, detail: str = "") -> Path | None:
    path = guard_path(config_path)
    if path is None:
        return None
    guard = read_guard(path)
    guard["state"] = STATE_AFTER_KIND.get(kind, AFTER_ANALYZE)
    append_event(guard, kind, detail)
    write_guard(path, guard)
    return path


def record_action(kind: str = "action_check", config_path: Path | None = None, *, detail: str = "") -> Path | None:
    path = guard_path(config_path)
    if path is None:
        return None
    guard = read_guard(path)
    guard["state"] = OPEN
    append_event(guard, kind, detail)
    write_guard(path, guard)
    return path


def status(config_path: Path | None = None) -> dict[str, Any]:
    path = guard_path(config_path)
    guard = read_guard(path)
    state = str(guard.get("state") or OPEN)
    return {
        "path": str(path) if path else "",
        "state": state,
        "required_next": NEXT_HINTS.get(state, NEXT_HINTS[AFTER_ANALYZE]),
        "events": guard.get("events", []),
    }
