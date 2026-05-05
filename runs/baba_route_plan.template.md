# Baba Route Plan

Temporary scratchpad for planned short route segments.

Rules:

- This file is not a solution source. It only records the current run's short
  hypotheses and their observed outcomes.
- Keep pending plans to 1-3 segments, and each normal segment to 1-8 steps.
- Every segment must include the move string and expected observable delta.
- Segments that rely on an existing control/win rule should include a rule
  invariant such as `--expect-rule-kept 'wall is you'`; segments near dangerous
  text should forbid bad rules such as `--forbid-rule-added 'wall is stop'`.
- After `check=fail`, discard pending segments. The next action must be
  `python3 scripts/baba_undo.py --steps <failed-expanded-step-count>`,
  `python3 scripts/read_baba_state.py --limit 60`, or
  `python3 scripts/baba_restart.py`.
- Completed routes belong in `baba_benchmark_log.md`, `baba_level_notes.md`, and
  `baba_known_routes.json` only after completion status is verified as `3`.
