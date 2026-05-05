#!/usr/bin/env python3
"""Copy stdin to stdout in real time, then speak the collected response.

This is the agent-agnostic adapter: any CLI agent that writes its final response
to stdout can be piped through this script without changing the agent itself.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ANSI_RE = re.compile(
    r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))"
)


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def read_and_echo_stdin() -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = sys.stdin.buffer.read(4096)
        if not chunk:
            break
        chunks.append(chunk)
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()
    return b"".join(chunks)


def write_temp_text(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        prefix="baba-agent-tts-tee-",
        suffix=".txt",
    )
    with handle:
        handle.write(text)
    return Path(handle.name)


def build_tts_command(args: argparse.Namespace, text_file: Path) -> list[str]:
    script = args.tts_script.expanduser().resolve()
    command = [
        args.python,
        str(script),
        "--background",
        "--no-echo",
        "--text-file",
        str(text_file),
        "--cleanup-text-file",
        "--api-key-env",
        args.api_key_env,
        "--base-url",
        args.base_url,
        "--model",
        args.model,
        "--voice",
        args.voice,
        "--audio-format",
        args.audio_format,
        "--timeout",
        str(args.timeout),
        "--player",
        args.player,
        "--background-log",
        str(args.background_log.expanduser()),
    ]
    if args.style:
        command.extend(["--style", args.style])
    if args.no_play:
        command.append("--no-play")
    if args.output is not None:
        command.extend(["--output", str(args.output.expanduser())])
    if args.dry_run:
        command.append("--dry-run")
    if args.verbose:
        command.append("--verbose")
    return command


def spawn_tts(args: argparse.Namespace, text: str) -> int:
    if not text.strip():
        return 0

    if args.max_speech_chars and len(text) > args.max_speech_chars:
        text = text[: args.max_speech_chars].rstrip() + "\n[朗读内容已截断]"

    text_file = write_temp_text(text)
    command = build_tts_command(args, text_file)
    log_path = args.background_log.expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=args.cwd.expanduser().resolve() if args.cwd else None,
            start_new_session=True,
            env=os.environ.copy(),
        )
    if args.verbose:
        print(f"tts_background_log={log_path}", file=sys.stderr)
    return 0


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tts-script",
        type=Path,
        default=root / "scripts" / "agent_tts.py",
        help="Path to agent_tts.py.",
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable.")
    parser.add_argument(
        "--style",
        default=os.environ.get("MIMO_TTS_STYLE", ""),
        help="Optional natural-language speech style instruction.",
    )
    parser.add_argument(
        "--voice",
        default=os.environ.get("MIMO_TTS_VOICE", "mimo_default"),
        help="Built-in MiMo voice ID.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MIMO_TTS_MODEL", "mimo-v2.5-tts"),
        help="MiMo TTS model ID.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        help="MiMo API base URL.",
    )
    parser.add_argument(
        "--api-key-env",
        default="MIMO_API_KEY",
        help="Environment variable containing the MiMo API key.",
    )
    parser.add_argument(
        "--audio-format",
        default="wav",
        choices=["wav"],
        help="Requested output audio format.",
    )
    parser.add_argument(
        "--player",
        default=os.environ.get("MIMO_TTS_PLAYER", "afplay"),
        help="Audio player command.",
    )
    parser.add_argument(
        "--background-log",
        type=Path,
        default=Path(tempfile.gettempdir()) / "baba_agent_tts.log",
        help="Append background process output to this log file.",
    )
    parser.add_argument("--output", type=Path, help="Write audio to this path.")
    parser.add_argument("--no-play", action="store_true", help="Synthesize without playback.")
    parser.add_argument("--timeout", type=float, default=120.0, help="HTTP timeout seconds.")
    parser.add_argument(
        "--max-speech-chars",
        type=int,
        default=0,
        help="Optionally truncate text sent to TTS; 0 means no truncation.",
    )
    parser.add_argument(
        "--keep-ansi",
        action="store_true",
        help="Do not strip ANSI control sequences from the spoken text.",
    )
    parser.add_argument(
        "--cwd",
        type=Path,
        help="Working directory for the background TTS process.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not call the TTS API.")
    parser.add_argument("--verbose", action="store_true", help="Print log path to stderr.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw = read_and_echo_stdin()
    text = raw.decode("utf-8", errors="replace")
    if not args.keep_ansi:
        text = strip_ansi(text)
    return spawn_tts(args, text)


if __name__ == "__main__":
    raise SystemExit(main())
