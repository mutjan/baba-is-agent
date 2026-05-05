#!/usr/bin/env python3
"""Echo an agent response and speak it through Xiaomi MiMo TTS.

The response text is sent as an assistant message because MiMo-V2.5-TTS
documents require synthesized text to live in the assistant role.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
DEFAULT_MODEL = "mimo-v2.5-tts"
DEFAULT_VOICE = "mimo_default"
DEFAULT_LOG_PATH = Path(tempfile.gettempdir()) / "baba_agent_tts.log"


def positive_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid float value: {raw}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return value


def read_text(args: argparse.Namespace) -> str:
    if args.text and args.text_file is not None:
        raise SystemExit("Provide response text from only one source: args or --text-file.")

    if args.text:
        text = " ".join(args.text)
    elif args.text_file is not None:
        text = args.text_file.read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise SystemExit("Provide response text as args, --text-file, or stdin.")

    if not text.strip():
        raise SystemExit("Response text is empty; nothing to speak.")
    return text


def echo_text(text: str) -> None:
    print(text, end="" if text.endswith("\n") else "\n", flush=True)


def build_payload(args: argparse.Namespace, text: str) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if args.style:
        messages.append({"role": "user", "content": args.style})
    messages.append({"role": "assistant", "content": text})

    audio: dict[str, str] = {"format": args.audio_format}
    if not args.no_voice:
        audio["voice"] = args.voice

    return {
        "model": args.model,
        "messages": messages,
        "audio": audio,
    }


def require_api_key(env_name: str) -> str:
    api_key = os.environ.get(env_name, "")
    if not api_key:
        raise SystemExit(
            f"Missing {env_name}. Export it first, e.g. `export {env_name}=...`."
        )
    return api_key


def default_ca_file() -> str:
    try:
        import certifi  # type: ignore[import-not-found]
    except Exception:
        return ""
    return str(certifi.where())


def ssl_context(ca_file: str) -> ssl.SSLContext | None:
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    return None


def request_audio(
    payload: dict[str, Any],
    api_key: str,
    base_url: str,
    timeout: float,
    ca_file: str,
) -> bytes:
    url = f"{base_url.rstrip('/')}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "api-key": api_key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
            context=ssl_context(ca_file),
        ) as response:
            raw_body = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"TTS request failed: HTTP {exc.code}: {body[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"TTS request failed: {exc}") from exc

    try:
        body = json.loads(raw_body.decode("utf-8"))
        audio_data = body["choices"][0]["message"]["audio"]["data"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        decoded = raw_body.decode("utf-8", errors="replace")
        raise SystemExit(f"TTS response did not contain audio data: {decoded[:1200]}") from exc

    try:
        return base64.b64decode(audio_data)
    except ValueError as exc:
        raise SystemExit("TTS audio data was not valid base64.") from exc


def output_path_for(args: argparse.Namespace) -> tuple[Path, bool]:
    if args.output is not None:
        return args.output.expanduser().resolve(), False

    suffix = f".{args.audio_format}"
    fd, raw_path = tempfile.mkstemp(prefix="baba-agent-tts-", suffix=suffix)
    os.close(fd)
    return Path(raw_path), True


def play_audio(path: Path, player: str) -> None:
    executable = shutil.which(player)
    if executable is None:
        raise SystemExit(f"Audio player not found: {player}")
    subprocess.run([executable, str(path)], check=True)


def dry_run(args: argparse.Namespace, payload: dict[str, Any]) -> int:
    print("tts_dry_run=true", file=sys.stderr)
    print(f"model={args.model}", file=sys.stderr)
    print(f"base_url={args.base_url.rstrip('/')}", file=sys.stderr)
    print(f"audio_format={args.audio_format}", file=sys.stderr)
    print(f"voice={'<omitted>' if args.no_voice else args.voice}", file=sys.stderr)
    print(f"ca_file={args.ca_file or '<python default>'}", file=sys.stderr)
    print(f"assistant_chars={len(payload['messages'][-1]['content'])}", file=sys.stderr)
    print(f"style_present={bool(args.style)}", file=sys.stderr)
    return 0


def background_command(args: argparse.Namespace, text_file: Path) -> list[str]:
    script = Path(__file__).resolve()
    command = [
        sys.executable,
        str(script),
        "--text-file",
        str(text_file),
        "--no-echo",
        "--cleanup-text-file",
        "--api-key-env",
        args.api_key_env,
        "--base-url",
        args.base_url,
        "--model",
        args.model,
        "--audio-format",
        args.audio_format,
        "--timeout",
        str(args.timeout),
        "--ca-file",
        args.ca_file,
        "--player",
        args.player,
    ]
    if args.style:
        command.extend(["--style", args.style])
    if args.no_voice:
        command.append("--no-voice")
    else:
        command.extend(["--voice", args.voice])
    if args.output is not None:
        command.extend(["--output", str(args.output)])
    if args.no_play:
        command.append("--no-play")
    if args.keep_audio:
        command.append("--keep-audio")
    if args.dry_run:
        command.append("--dry-run")
    if args.verbose:
        command.append("--verbose")
    return command


def spawn_background(args: argparse.Namespace, text: str) -> int:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        prefix="baba-agent-tts-text-",
        suffix=".txt",
    ) as handle:
        handle.write(text)
        text_file = Path(handle.name)

    log_path = args.background_log.expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = background_command(args, text_file)
    with log_path.open("a", encoding="utf-8") as log:
        subprocess.Popen(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    if args.verbose:
        print(f"tts_background_log={log_path}", file=sys.stderr)
    return 0


def cleanup_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def speak_foreground(args: argparse.Namespace, text: str) -> int:
    payload = build_payload(args, text)
    if args.dry_run:
        return dry_run(args, payload)

    api_key = require_api_key(args.api_key_env)
    audio_bytes = request_audio(payload, api_key, args.base_url, args.timeout, args.ca_file)
    output_path, temporary_output = output_path_for(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    if args.verbose:
        print(f"tts_audio_path={output_path}", file=sys.stderr)

    try:
        if not args.no_play:
            play_audio(output_path, args.player)
    finally:
        if temporary_output and not args.keep_audio:
            cleanup_file(output_path)

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "text",
        nargs="*",
        help="Response text to echo and speak. Omit to read stdin.",
    )
    parser.add_argument(
        "--text-file",
        type=Path,
        help="Read response text from this UTF-8 file instead of args/stdin.",
    )
    parser.add_argument(
        "--style",
        default=os.environ.get("MIMO_TTS_STYLE", ""),
        help="Optional natural-language speech style instruction for the user message.",
    )
    parser.add_argument(
        "--voice",
        default=os.environ.get("MIMO_TTS_VOICE", DEFAULT_VOICE),
        help="Built-in voice ID, e.g. mimo_default, built-in Chinese names, Mia, Chloe.",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Omit audio.voice, useful for voice-design models.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("MIMO_TTS_MODEL", DEFAULT_MODEL),
        help="MiMo TTS model ID.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MIMO_BASE_URL", DEFAULT_BASE_URL),
        help="MiMo API base URL.",
    )
    parser.add_argument(
        "--api-key-env",
        default="MIMO_API_KEY",
        help="Environment variable containing the MiMo API key.",
    )
    parser.add_argument(
        "--ca-file",
        default=os.environ.get("MIMO_CA_FILE", default_ca_file()),
        help="CA bundle path for HTTPS. Defaults to certifi when available.",
    )
    parser.add_argument(
        "--audio-format",
        default="wav",
        choices=["wav"],
        help="Requested output audio format. WAV is directly playable by afplay.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write audio to this path. Defaults to a temporary WAV file.",
    )
    parser.add_argument(
        "--keep-audio",
        action="store_true",
        help="Keep the temporary audio file when --output is not set.",
    )
    parser.add_argument(
        "--no-play",
        action="store_true",
        help="Do not play audio after synthesis.",
    )
    parser.add_argument(
        "--player",
        default=os.environ.get("MIMO_TTS_PLAYER", "afplay"),
        help="Audio player command. Defaults to macOS afplay.",
    )
    parser.add_argument(
        "--background",
        action="store_true",
        help="Echo now, then synthesize/play in a detached background process.",
    )
    parser.add_argument(
        "--background-log",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help="Append background process output to this log file.",
    )
    parser.add_argument(
        "--no-echo",
        action="store_true",
        help="Do not print the response text before synthesis.",
    )
    parser.add_argument(
        "--timeout",
        type=positive_float,
        default=120.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print request metadata without calling the API.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print audio/log paths to stderr.",
    )
    parser.add_argument(
        "--cleanup-text-file",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    text = read_text(args)

    if not args.no_echo:
        echo_text(text)

    try:
        if args.background:
            return spawn_background(args, text)
        return speak_foreground(args, text)
    finally:
        if args.cleanup_text_file:
            cleanup_file(args.text_file)


if __name__ == "__main__":
    raise SystemExit(main())
