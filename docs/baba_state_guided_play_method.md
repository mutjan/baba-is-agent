# Baba State-Guided Play Method

This method is for solving a live Baba Is You level with local state reads and
short move experiments. It is intentionally different from full route search:
the goal is to reduce uncertainty while keeping the game visibly moving.

## First Principles

The agent does not need to know the full solution before acting. It needs to:

1. Know the real current state.
2. Name one hypothesis about the next useful state change.
3. Execute the shortest move segment that should test that hypothesis.
4. Read the state delta.
5. Continue, revise, or reset based on file evidence.

The success standard is not a command exit code or `frontmost=Chowdren`. A level
is complete only when the save field for that level becomes `3`.

## What Belongs In Scripts

Write a script when the task is mechanical, repeatable, and safer when exact:

- read current level, rules, object positions, and save completion status;
- send key input through the verified CGEvent path;
- wait for fresh exporter output after each move;
- compare before/after states for rules added, rules removed, moved units, and
  disappeared units;
- infer map routes from saved map/cursor data;
- run constrained text-rule search when the state model is known to match the
  level.

Do not put level-specific solved routes into generic scripts. Known solved
routes live in `runs/baba_level_notes.md` and, when useful for replay, in
`runs/baba_play_known_route.py`.

## What Belongs In Markdown

Write Markdown when the information needs judgment or context:

- the current operating method and risk boundaries;
- generic rules learned from play, such as what counts as reliable evidence;
- level-specific hypotheses, key coordinates, failed branches, and final routes;
- when to prefer interactive experiments over route search;
- human-facing notes for live play, such as why a move segment is interesting.

Use `docs/` for reusable method. Use `runs/baba_learned_rules.md` for generic
play lessons. Use `runs/baba_level_notes.md` for per-level facts and routes.

## Interactive Loop

Start every new level with:

```bash
python3 scripts/read_baba_state.py
python3 scripts/parse_baba_level.py --rules-only
```

Then choose one hypothesis. Good hypotheses have a visible or state-readable
effect, for example:

- break `FLAG IS STOP`;
- move `WIN` next to an existing `IS`;
- push a key onto a door and remove both;
- move the current `YOU` actor to a staging coordinate;
- form `BABA IS WIN` while preserving `BABA IS YOU`.

Run the shortest move segment that should reach that effect:

```bash
python3 scripts/baba_try.py 'left*3'
```

Read the delta:

- `rules_added` and `rules_removed` answer whether a text rule changed.
- `moved` answers whether the intended object or text moved to the expected
  coordinate.
- `disappeared` can confirm `OPEN`/`SHUT`, `SINK`, or defeat interactions.
- `completion_status=<level>=3` confirms a finished level.

## Segment Size

Do not force one move per read. Stop at the next meaningful checkpoint.

Use a one-step segment when testing contact behavior, such as whether a wall is
really passable or a key can be pushed.

Use a short multi-step segment when the expected result is clear, such as:

```bash
python3 scripts/baba_try.py 'left*3'
```

Use a longer segment only when every step is navigation through already-proven
space and the next checkpoint is still unambiguous.

## When To Avoid Heavy Search

Avoid route search when:

- the model would need moving non-text objects, `OPEN/SHUT`, `SINK`, `MOVE`, or
  multiple `YOU` actors that the current searcher does not model completely;
- the level can be reduced with a small number of readable state changes;
- the user wants the game to move for live viewing;
- a failed route would leave the board in an unclear state.

Prefer route search when:

- the task is mostly arranging text;
- the relevant words are known;
- the searcher analysis shows the needed text is pushable;
- the printed route can be checked before execution.

## Example: 189level / Now What Is This?

The useful decomposition was not "find the route." It was:

1. Break `FLAG IS STOP` by pushing the middle `IS` left.
2. Walk through flags now that they are not stop.
3. Move `WIN` to the right of a fixed upper `IS`.
4. Move `FLAG` to the left of that `IS`.
5. Touch a real flag after `FLAG IS WIN` appears.

The key checkpoints were:

```bash
python3 scripts/baba_try.py 'left*3'
python3 scripts/baba_try.py 'up*7,right*3'
python3 scripts/baba_try.py 'down,right*2,up,left*3,down,left,up*2'
python3 scripts/baba_try.py 'left,down,left,up,left'
```

The final checkpoint should show `rules_added=flag is win` and
`completion_status=189level=3`.
