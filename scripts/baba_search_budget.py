"""Cooperative deadline and size limits shared by every search phase."""
from __future__ import annotations

import json
import math
import sys
import time


class BudgetExhausted(Exception):
    pass


class SearchBudget:
    def __init__(self, seconds=5.0, max_patterns=20000, max_assignments=40000,
                 clock=time.monotonic, emit=None):
        if not math.isfinite(seconds) or seconds <= 0 or max_patterns <= 0 or max_assignments <= 0:
            raise ValueError('Search budgets must be positive')
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + seconds
        self.last_report = -float('inf')
        self.phase = 'starting'
        self.reported_phases = set()
        self.counts = {}
        self.limits = {'patterns': max_patterns, 'assignments': max_assignments}
        self.candidate_moves = []
        self.emit = emit or (lambda value: print('search_progress=' + json.dumps(value), file=sys.stderr, flush=True))

    def check(self, phase, count=None):
        now = self.clock()
        self.phase = phase
        if count is not None:
            self.counts[phase] = count
        if phase not in self.reported_phases or now - self.last_report >= 1:
            self.emit(self.status(now))
            self.last_report = now
            self.reported_phases.add(phase)
        if count is not None and phase in self.limits and count > self.limits[phase]:
            raise BudgetExhausted(f'{phase}_limit')
        if now >= self.deadline:
            raise BudgetExhausted('time_limit')

    def status(self, now=None):
        return {'phase': self.phase, 'elapsed_seconds': round((self.clock() if now is None else now) - self.started, 3), **self.counts}
