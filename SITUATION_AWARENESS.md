# Baba Is You Situation Awareness

This repo lets Codex read local Baba Is You files and send local macOS key events. Use this file first when taking over a play session.

## Current Goal

Continue playing the current save, one level at a time:

1. Confirm the real current state from save files.
2. Enter the next level from the map only after verifying the real cursor.
3. Solve by combining parser output with short in-game feedback loops.
4. Verify success from save status, not from command exit codes.

## Important User Preferences

- Start answers with `根据第一性原理...`.
- Do not use web search for solutions. Think locally and use game feedback.
- Use screenshots only when local parsing and game behavior conflict; screenshots are token-expensive.
- Use file coordinates only. The file coordinate system includes an outer border; the actual movable range is `x=1..width-2`, `y=1..height-2`.
- Keep `runs/baba_learned_rules.md` generic. Put level-specific routes and notes in `runs/baba_level_notes.md`.

## Key Commands

Read current level:

```bash
python3 scripts/parse_baba_level.py
```

Read a specific level:

```bash
python3 scripts/parse_baba_level.py --world baba --level 6level
```

Detect map route:

```bash
python3 scripts/baba_map_route.py
python3 scripts/baba_map_route.py 6level
```

Send keys:

```bash
python3 scripts/baba_send_keys.py 'right,left,up' --delay 0.12
```

Restart current level when stuck:

```bash
python3 scripts/baba_send_keys.py 'r,down,enter' --delay 0.12
```

Known route lookup:

```bash
PYTHONPATH=scripts python3 runs/baba_play_known_route.py --list
PYTHONPATH=scripts python3 runs/baba_play_known_route.py --level 2level
```

## Current Save Snapshot

At the time this handoff was written:

- `slot=2`
- `world=baba`
- `Previous=5level`
- Completed: `0level=3`, `1level=3`, `2level=3`, `3level=3`, `5level=3`
- Uncompleted/unlocked seen in save: `6level=2`, `177level=2`, `189level=2`

The player has just completed `5level / off limits` and is back on the world map according to the user. Before executing any map route, re-run:

```bash
python3 scripts/baba_map_route.py
```

If it reports `source=selector fallback`, do not blindly execute it. The map cursor inference may be stale or underdetermined; use a short key probe or user observation to confirm the real cursor first.

## Files To Know

- `README.md`: repo overview.
- `scripts/parse_baba_level.py`: static parser for current/specific levels.
- `scripts/baba_send_keys.py`: verified CGEvent key sender.
- `scripts/baba_map_route.py`: map route detector; good but still verify cursor source.
- `runs/baba_learned_rules.md`: generic rules only.
- `runs/baba_level_notes.md`: level-specific routes and notes.
- `docs/baba_level_parsing_method.md`: parser method and coordinate notes.
- `dev/baba_control_handoff.md`: longer historical handoff.

## Critical Rules

- `frontmost=Chowdren` only proves the game process is focused; it does not prove movement or success.
- A level is complete only when its save field becomes `3`.
- Text blocks are pushable by default.
- `B` in parser output means real `baba`; `M` means `brick`.
- Do not treat the outer border as walkable.
- If a route fails, restart with `r,down,enter`, then try a shorter or corrected route.

## Recent Proven Routes

See `runs/baba_level_notes.md` for details. Most recent:

```text
5level / off limits:
right*3,down*2,right*2,down,left*5,up,left,down,left,down,right,up*2
```

The previous attempt missed the final second `up`; the user pressed it and the level completed.
