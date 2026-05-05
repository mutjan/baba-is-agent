# Agent TTS Integration

`scripts/agent_tts.py` is the TTS engine. Keep it agent-neutral: it accepts text
from argv, stdin, or a file, sends the text to Xiaomi MiMo TTS, and optionally
plays the generated WAV.

`scripts/agent_tts_tee.py` is the CLI adapter. It copies stdin to stdout as bytes
arrive, collects the same text, strips terminal ANSI sequences for speech, and
starts `agent_tts.py --background` after stdin closes.

## Decision Model

Use the smallest adapter that matches the host agent:

- Plain CLI output: pipe stdout through `scripts/agent_tts_tee.py`.
- TUI or desktop app with hooks: use a host-specific hook/plugin that calls
  `scripts/agent_tts.py --background --text-file ...`.
- Host with no output hook: instruct the agent to call `scripts/agent_tts.py
  --background` for the final user-facing answer.

Do not put `MIMO_API_KEY` in repo files. Load it from the shell environment.

## Generic CLI Adapter

For an agent command that writes assistant output to stdout:

```bash
some-agent-command 2>agent.stderr | python3 scripts/agent_tts_tee.py
```

For a dry-run that proves the adapter is collecting text without calling MiMo:

```bash
printf '根据第一性原理，CLI adapter test.\n' | python3 scripts/agent_tts_tee.py --dry-run --verbose
```

If the command streams progress logs and final answers to the same stdout, prefer
a host hook instead of the pipe. The pipe speaks whatever it receives.

## OpenCode

OpenCode supports project-level plugins in `.opencode/plugins/` and exposes
message/session events. The example plugin is intentionally not installed by
default, because a project plugin is automatically loaded when OpenCode starts.

Install the example:

```bash
mkdir -p .opencode/plugins
cp integrations/opencode/agent-tts-plugin.example.js .opencode/plugins/agent-tts.js
```

Then restart OpenCode from this repo. The plugin captures the latest assistant
message from `message.updated` and calls `scripts/agent_tts.py --background` on
`session.idle`, so it should speak once per completed response.

Useful environment overrides:

```bash
export MIMO_API_KEY="..."
export MIMO_TTS_STYLE="用清晰、冷静、简洁的中文助手语气朗读。"
export AGENT_TTS_REPO="/Users/mutjan/develop/baba-is-agent"
export AGENT_TTS_LOG="/tmp/baba_agent_tts.log"
```

If OpenCode changes event payload shapes, the plugin may need a small extractor
adjustment. The TTS engine remains reusable because the host-specific logic stays
outside `scripts/agent_tts.py`.

## Codex And Other Agents

Codex Desktop does not currently expose this repo script as an automatic
post-response hook from inside the project, so explicit calls still work:

```bash
python3 scripts/agent_tts.py --background "根据第一性原理，这条回答会被朗读。"
```

For any other agent environment, wire the last user-facing assistant text to one
of these two commands:

```bash
python3 scripts/agent_tts.py --background --text-file /path/to/response.txt
python3 scripts/agent_tts_tee.py
```
