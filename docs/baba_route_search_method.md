# Baba Route Search Method

`scripts/baba_search_route.py` is a generic text-rule macro searcher. It should
not store per-level solved coordinates. Machine-readable solved routes belong
in `scripts/baba_known_routes.json`; route explanations and failed-branch notes
belong in `runs/baba_level_notes.md`.

## What Level 6 Taught Us

The reusable lessons from `6level / grass yard` are:

1. Derive blockers from active rules, not sprites. `wall` without
   `WALL IS STOP` is empty for pathfinding.
2. Keep the search state small. Start with the current `YOU` rule text plus the
   words needed for the target rule, for example `FLAG`, `IS`, `WIN`.
3. Treat unselected text as fixed blockers. This keeps the model conservative
   and avoids accidentally breaking unrelated rules.
4. Search macro actions instead of raw moves: walk to the back of a text block,
   push one text chain one tile, then re-evaluate rules.
5. Preserve the active `YOU` rule after every push unless explicitly exploring a
   controlled handoff.
6. Build target-rule patterns in a small window around relevant text first.
   If no route is found, widen the window with `--pattern-margin`.
7. Precompile target patterns into text assignments so every A* state only pays
   a cheap Manhattan-distance heuristic.

## Typical Workflow

Analyze the current derived search problem. This prints initial rules plus
rule mobility: which initial rule text can be pushed, and whether each push
keeps the current `YOU` rule alive.

```bash
python3 scripts/baba_search_route.py --analyze
```

Read mobility markers as:

```text
right*  # push right and current YOU remains active
down!   # push down but current YOU breaks
fixed   # no currently reachable legal push for this rule text
```

Try the default target, `FLAG IS WIN`:

```bash
python3 scripts/baba_search_route.py
```

Try another target rule:

```bash
python3 scripts/baba_search_route.py --make-rule rock is win
```

If the first search is too narrow:

```bash
python3 scripts/baba_search_route.py --pattern-margin 6
```

If a needed `IS` or other word was kept fixed:

```bash
python3 scripts/baba_search_route.py --all-is
python3 scripts/baba_search_route.py --select-text wall
```

Only execute after reading the printed route:

```bash
python3 scripts/baba_search_route.py --execute
```

## Current Limits

- It models text movement and active `STOP` blockers.
- It does not yet search with moving non-text `PUSH` objects such as rocks.
- It assumes a single initial `YOU` actor object.
- It is a fast route-generation helper, not a complete Baba Is You theorem
  prover.
