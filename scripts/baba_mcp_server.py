#!/usr/bin/env python3
"""Dependency-free stdio MCP wrapper for the Baba Is You scripts.

This server intentionally keeps the existing scripts as the source of truth.
Each MCP tool validates a small argument set, runs one fixed script, and returns
the command, exit code, stdout, and stderr.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SERVER_NAME = "baba-is-you-scripts"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"


class RpcError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def tool_schema(
    *,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


COMMON_CONFIG = {
    "config": {
        "type": "string",
        "description": "Optional path to baba_config.json.",
    },
    "command_timeout_seconds": {
        "type": "number",
        "description": "Wrapper subprocess timeout. Defaults to 30 seconds.",
        "minimum": 0.1,
        "maximum": 600,
    },
}


TOOLS: dict[str, dict[str, Any]] = {
    "config_status": tool_schema(
        description="Inspect local config, game file detection, exporter status, current_run_id, and input_delay.",
        properties={**COMMON_CONFIG},
    ),
    "set_current_run_id": tool_schema(
        description="Write current_run_id into the local ignored baba_config.json.",
        properties={
            **COMMON_CONFIG,
            "run_id": {
                "type": "string",
                "description": "Run directory name, e.g. 001_codex_gpt55 or 002_claude_sonnet.",
            },
        },
        required=["run_id"],
    ),
    "start_benchmark": tool_schema(
        description="Start or resume a from-zero benchmark attempt using scripts/baba_benchmark.py.",
        properties={
            **COMMON_CONFIG,
            "run_id": {"type": "string", "description": "Optional runs/<run_id> directory name."},
            "force_new": {"type": "boolean", "description": "Start a new attempt even if one is active."},
            "enter_next": {"type": "boolean", "description": "Enter the next map level before starting."},
            "dry_run": {"type": "boolean", "description": "Print planned action without writing files or sending keys."},
        },
    ),
    "read_state": tool_schema(
        description="Read the latest live state emitted by the Lua exporter.",
        properties={
            **COMMON_CONFIG,
            "save_dir": {"type": "string", "description": "Optional save directory override."},
            "path": {"type": "string", "description": "Optional legacy JSON state path override."},
            "raw_json": {"type": "boolean", "description": "Return raw state JSON instead of a compact summary."},
            "wait": {"type": "boolean", "description": "Wait for state to exist or change."},
            "timeout": {"type": "number", "description": "Seconds to wait with wait=true."},
            "limit": {"type": "integer", "description": "Limit printed rule/object groups."},
        },
    ),
    "parse_rules": tool_schema(
        description="Read static level files and print level identity plus active initial rules.",
        properties={
            **COMMON_CONFIG,
            "game_root": {"type": "string", "description": "Optional Worlds directory override."},
            "save_dir": {"type": "string", "description": "Optional save directory override."},
            "world": {"type": "string", "description": "Optional world folder."},
            "level": {"type": "string", "description": "Optional level id without extension."},
            "rules_only": {
                "type": "boolean",
                "description": "When true, pass --rules-only. Defaults to true.",
            },
            "all_layers": {"type": "boolean", "description": "Print every map layer."},
        },
    ),
    "try_moves": tool_schema(
        description="Send a short move segment and return the meaningful state delta. This makes the game move.",
        properties={
            **COMMON_CONFIG,
            "moves": {"type": "string", "description": "Comma-separated moves, e.g. left*3,up."},
            "save_dir": {"type": "string", "description": "Optional save directory override."},
            "app_name": {"type": "string", "description": "Optional macOS app name override."},
            "timeout": {"type": "number", "description": "Seconds to wait after each move."},
            "delay": {"type": "number", "description": "Delay after each key press."},
            "hold_ms": {"type": "integer", "description": "Milliseconds to hold each key."},
            "method": {"type": "string", "enum": ["cgevent", "applescript"]},
            "no_activate": {"type": "boolean", "description": "Do not activate Baba before sending."},
            "pre_delay": {"type": "number", "description": "Delay after activating Baba."},
            "focus": {"type": "string", "description": "Comma-separated unit names to show."},
            "limit": {"type": "integer", "description": "Limit printed changed units per category."},
        },
        required=["moves"],
    ),
    "restart_level": tool_schema(
        description="Restart the current level or map position using scripts/baba_restart.py.",
        properties={
            **COMMON_CONFIG,
            "delay": {"type": "number", "description": "Delay between keys."},
            "app_name": {"type": "string", "description": "Optional macOS app name override."},
            "no_activate": {"type": "boolean", "description": "Do not activate Baba before sending."},
            "dry_run": {"type": "boolean", "description": "Print command without sending keys."},
        },
    ),
    "map_route": tool_schema(
        description="Infer a map route to a level, optionally execute it, and optionally print entered rules.",
        properties={
            **COMMON_CONFIG,
            "target": {"type": "string", "description": "Optional target level id, e.g. 1level."},
            "game_root": {"type": "string", "description": "Optional Worlds directory override."},
            "save_dir": {"type": "string", "description": "Optional save directory override."},
            "enter_key": {"type": "string", "enum": ["enter", "confirm"]},
            "execute": {"type": "boolean", "description": "Send the detected route."},
            "hold_ms": {"type": "integer", "description": "Key hold passed to baba_send_keys.py with execute=true."},
            "no_rules_summary": {
                "type": "boolean",
                "description": "Do not print the entered level's initial rules after execute=true.",
            },
        },
    ),
    "play_known_route": tool_schema(
        description=(
            "Print, list, or execute known routes from the current run's JSON. "
            "Do not use this as a benchmark solution source."
        ),
        properties={
            **COMMON_CONFIG,
            "routes": {"type": "string", "description": "Optional known-routes JSON path override."},
            "save_dir": {"type": "string", "description": "Optional save directory override."},
            "level": {"type": "string", "description": "Optional level id. Defaults to save Previous."},
            "list_routes": {"type": "boolean", "description": "List known routes."},
            "execute": {"type": "boolean", "description": "Send the known route."},
            "delay": {"type": "number", "description": "Override configured input_delay."},
            "hold_ms": {"type": "integer", "description": "Override route/default key hold."},
        },
    ),
    "record_pass": tool_schema(
        description="Record an interactively solved level, stop the active timer, and update run files.",
        properties={
            **COMMON_CONFIG,
            "moves": {"type": "string", "description": "Verified full route."},
            "note": {"type": "string", "description": "Short summary for run notes."},
            "run_id": {"type": "string", "description": "Optional runs/<run_id> directory name."},
            "world": {"type": "string", "description": "Optional world override."},
            "level": {"type": "string", "description": "Optional level id override."},
            "name": {"type": "string", "description": "Optional level name."},
            "hold_ms": {"type": "integer", "description": "Route key hold value to record."},
            "allow_without_status": {
                "type": "boolean",
                "description": "Allow recording without completion status 3. Use only for repair.",
            },
            "no_run_updates": {"type": "boolean", "description": "Do not append run Markdown records."},
        },
        required=["moves"],
    ),
}


def as_bool(args: dict[str, Any], key: str) -> bool:
    return bool(args.get(key))


def command_timeout(args: dict[str, Any]) -> float:
    raw = args.get("command_timeout_seconds", 30)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RpcError(-32602, f"command_timeout_seconds must be numeric: {raw!r}") from exc
    return max(0.1, min(value, 600.0))


def add_value(command: list[str], args: dict[str, Any], key: str, flag: str) -> None:
    value = args.get(key)
    if value is not None and value != "":
        command.extend([flag, str(value)])


def add_bool(command: list[str], args: dict[str, Any], key: str, flag: str) -> None:
    if as_bool(args, key):
        command.append(flag)


def script_command(script_name: str, script_args: list[str]) -> tuple[list[str], list[str]]:
    actual = [sys.executable, str(SCRIPTS_DIR / script_name), *script_args]
    display = ["python3", f"scripts/{script_name}", *script_args]
    return actual, display


def run_script(script_name: str, script_args: list[str], args: dict[str, Any]) -> tuple[str, bool]:
    actual, display = script_command(script_name, script_args)
    payload: dict[str, Any] = {
        "command": shlex.join(display),
        "cwd": str(ROOT),
    }
    try:
        proc = subprocess.run(
            actual,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=command_timeout(args),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        payload.update(
            {
                "timed_out": True,
                "timeout_seconds": command_timeout(args),
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
            }
        )
        return json.dumps(payload, ensure_ascii=False, indent=2), True

    payload.update(
        {
            "exit_code": proc.returncode,
            "stdout": proc.stdout.rstrip(),
            "stderr": proc.stderr.rstrip(),
        }
    )
    return json.dumps(payload, ensure_ascii=False, indent=2), proc.returncode != 0


def config_status(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    add_value(command, args, "config", "--config")
    return run_script("baba_config.py", command, args)


def set_current_run_id(args: dict[str, Any]) -> tuple[str, bool]:
    run_id = args.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise RpcError(-32602, "set_current_run_id requires a non-empty run_id string")
    command = ["--set-current-run-id", run_id]
    add_value(command, args, "config", "--config")
    return run_script("baba_config.py", command, args)


def start_benchmark(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    add_value(command, args, "config", "--config")
    add_value(command, args, "run_id", "--run-id")
    add_bool(command, args, "force_new", "--force-new")
    add_bool(command, args, "enter_next", "--enter-next")
    add_bool(command, args, "dry_run", "--dry-run")
    return run_script("baba_benchmark.py", command, args)


def read_state(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    add_value(command, args, "config", "--config")
    add_value(command, args, "save_dir", "--save-dir")
    add_value(command, args, "path", "--path")
    add_bool(command, args, "raw_json", "--json")
    add_bool(command, args, "wait", "--wait")
    add_value(command, args, "timeout", "--timeout")
    add_value(command, args, "limit", "--limit")
    return run_script("read_baba_state.py", command, args)


def parse_rules(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    add_value(command, args, "config", "--config")
    add_value(command, args, "game_root", "--game-root")
    add_value(command, args, "save_dir", "--save-dir")
    add_value(command, args, "world", "--world")
    add_value(command, args, "level", "--level")
    if args.get("rules_only", True):
        command.append("--rules-only")
    add_bool(command, args, "all_layers", "--all-layers")
    return run_script("parse_baba_level.py", command, args)


def try_moves(args: dict[str, Any]) -> tuple[str, bool]:
    moves = args.get("moves")
    if not isinstance(moves, str) or not moves.strip():
        raise RpcError(-32602, "try_moves requires a non-empty moves string")
    command: list[str] = [moves]
    add_value(command, args, "config", "--config")
    add_value(command, args, "save_dir", "--save-dir")
    add_value(command, args, "app_name", "--app-name")
    add_value(command, args, "timeout", "--timeout")
    add_value(command, args, "delay", "--delay")
    add_value(command, args, "hold_ms", "--hold-ms")
    add_value(command, args, "method", "--method")
    add_bool(command, args, "no_activate", "--no-activate")
    add_value(command, args, "pre_delay", "--pre-delay")
    add_value(command, args, "focus", "--focus")
    add_value(command, args, "limit", "--limit")
    return run_script("baba_try.py", command, args)


def restart_level(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    add_value(command, args, "config", "--config")
    add_value(command, args, "delay", "--delay")
    add_value(command, args, "app_name", "--app-name")
    add_bool(command, args, "no_activate", "--no-activate")
    add_bool(command, args, "dry_run", "--dry-run")
    return run_script("baba_restart.py", command, args)


def map_route(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    target = args.get("target")
    if target:
        command.append(str(target))
    add_value(command, args, "config", "--config")
    add_value(command, args, "game_root", "--game-root")
    add_value(command, args, "save_dir", "--save-dir")
    add_value(command, args, "enter_key", "--enter-key")
    add_bool(command, args, "execute", "--execute")
    add_value(command, args, "hold_ms", "--hold-ms")
    add_bool(command, args, "no_rules_summary", "--no-rules-summary")
    return run_script("baba_map_route.py", command, args)


def play_known_route(args: dict[str, Any]) -> tuple[str, bool]:
    command: list[str] = []
    add_value(command, args, "config", "--config")
    add_value(command, args, "routes", "--routes")
    add_value(command, args, "save_dir", "--save-dir")
    add_value(command, args, "level", "--level")
    add_bool(command, args, "list_routes", "--list")
    add_bool(command, args, "execute", "--execute")
    add_value(command, args, "delay", "--delay")
    add_value(command, args, "hold_ms", "--hold-ms")
    return run_script("baba_play_known_route.py", command, args)


def record_pass(args: dict[str, Any]) -> tuple[str, bool]:
    moves = args.get("moves")
    if not isinstance(moves, str) or not moves.strip():
        raise RpcError(-32602, "record_pass requires a non-empty moves string")
    command: list[str] = ["--record-pass", "--moves", moves]
    add_value(command, args, "config", "--config")
    add_value(command, args, "run_id", "--run-id")
    add_value(command, args, "world", "--world")
    add_value(command, args, "level", "--level")
    add_value(command, args, "name", "--name")
    add_value(command, args, "note", "--note")
    add_value(command, args, "hold_ms", "--hold-ms")
    add_bool(command, args, "allow_without_status", "--allow-without-status")
    add_bool(command, args, "no_run_updates", "--no-run-updates")
    return run_script("baba_benchmark.py", command, args)


TOOL_HANDLERS = {
    "config_status": config_status,
    "set_current_run_id": set_current_run_id,
    "start_benchmark": start_benchmark,
    "read_state": read_state,
    "parse_rules": parse_rules,
    "try_moves": try_moves,
    "restart_level": restart_level,
    "map_route": map_route,
    "play_known_route": play_known_route,
    "record_pass": record_pass,
}


def tool_list() -> list[dict[str, Any]]:
    return [
        {"name": name, **schema}
        for name, schema in TOOLS.items()
    ]


def call_tool(params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    if name not in TOOL_HANDLERS:
        raise RpcError(-32602, f"Unknown tool: {name}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise RpcError(-32602, "Tool arguments must be an object")
    text, is_error = TOOL_HANDLERS[name](arguments)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    if message.get("jsonrpc") != "2.0":
        raise RpcError(-32600, "Expected JSON-RPC 2.0")

    method = message.get("method")
    request_id = message.get("id")

    if method and method.startswith("notifications/"):
        return None

    if request_id is None:
        return None

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise RpcError(-32602, "tools/call params must be an object")
        return call_tool(params)
    if method in {"resources/list", "prompts/list"}:
        key = "resources" if method == "resources/list" else "prompts"
        return {key: []}

    raise RpcError(-32601, f"Method not found: {method}")


def send_response(response: Any) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def response_for_message(message: Any) -> dict[str, Any] | None:
    request_id = message.get("id") if isinstance(message, dict) else None
    if not isinstance(message, dict):
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32600, "message": "Invalid request"},
        }
    try:
        result = handle_request(message)
        if result is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except RpcError as exc:
        error: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.data is not None:
            error["data"] = exc.data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32603, "message": "Internal error", "data": str(exc)},
        }


def serve_stdio() -> int:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if isinstance(message, list):
                responses = [response for item in message if (response := response_for_message(item)) is not None]
                if responses:
                    send_response(responses)
                continue
            response = response_for_message(message)
            if response is not None:
                send_response(response)
        except json.JSONDecodeError as exc:
            send_response(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error", "data": str(exc)},
                }
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list-tools", action="store_true", help="Print tool names and exit")
    args = parser.parse_args()

    if args.list_tools:
        for tool in tool_list():
            print(tool["name"])
        return 0
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
