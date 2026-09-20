"""Durable, exclusive execution records. A pending key is never replayed."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from read_baba_state import state_fingerprint

ROOT = Path(__file__).resolve().parents[1]


class ExecutionError(Exception):
    pass


def actions_dir(config):
    run = config.current_run_id
    if not run or not re.fullmatch(r'[A-Za-z0-9_-]+', run):
        raise ExecutionError('invalid_current_run_id')
    return ROOT / 'runs' / run / 'actions'


def action_path(config, action_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', action_id):
        raise ExecutionError('invalid_action_id')
    return actions_dir(config) / (action_id + '.json')


def read_action(config, action_id):
    try:
        return json.loads(action_path(config, action_id).read_text())
    except (OSError, ValueError) as exc:
        raise ExecutionError(f'action_unavailable: {action_id}') from exc


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + '-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def exclusive_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ExecutionError('execution_busy: query the existing action; do not restart it') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def game_lock_path(save_dir):
    key = hashlib.sha256(str(save_dir.resolve()).encode()).hexdigest()[:24]
    return Path(tempfile.gettempdir()) / f'baba-input-{os.getuid()}-{key}.lock'


def action_status(config, action_id):
    record = read_action(config, action_id)
    path = action_path(config, action_id).with_suffix('.lock')
    try:
        with exclusive_lock(path):
            busy = False
    except ExecutionError:
        busy = True
    return {k: v for k, v in record.items() if k not in ('before', 'after', 'request')} | {
        'worker_active': busy,
        'resume_safe': not busy and record.get('pending') is None and record.get('phase') != 'completed',
        'next': 'wait_or_query' if busy else ('inspect_uncertain_key' if record.get('pending') is not None else ('read_result' if record.get('phase') == 'completed' else 'verify_live_state_then_resume')),
    }


class ActionJournal:
    def __init__(self, config, action_id, moves, before, *, resume=False, request=None):
        self.path = action_path(config, action_id)
        if self.path.exists():
            self.record = read_action(config, action_id)
            if not resume:
                raise ExecutionError('action_already_exists: use status or resume with the same ID')
            if self.record.get('request', {}) != (request or {}):
                raise ExecutionError('resume_expectations_mismatch')
            if self.record['moves'] != moves:
                raise ExecutionError('resume_moves_mismatch')
            if self.record['phase'] == 'completed':
                return
            if self.record.get('pending') is not None:
                raise ExecutionError('action_uncertain: key was dispatched but not confirmed; automatic replay refused')
            if state_fingerprint(before) != state_fingerprint(self.record['after']):
                raise ExecutionError('resume_state_mismatch: inspect live state before choosing a new action')
        else:
            if resume:
                raise ExecutionError('action_not_found')
            self.record = {'action_id': action_id, 'moves': moves, 'before': before, 'after': before,
                           'confirmed_steps': 0, 'pending': None, 'request': request or {},
                           'phase': 'accepted', 'created_at': time.time(), 'events': []}
        self.update('accepted')

    def update(self, phase, **values):
        self.record.update(values, phase=phase, worker_pid=os.getpid(), updated_at=time.time())
        atomic_write(self.path, self.record)

    def dispatch(self, index, move):
        self.update('sending', pending={'index': index, 'move': move, 'before_fingerprint': state_fingerprint(self.record['after'])})

    def confirm(self, state, elapsed):
        pending = self.record['pending']
        self.record['events'].append({'index': pending['index'], 'move': pending['move'],
                                     'turn': state['meta'].get('turn'), 'sequence': state['meta'].get('sequence'),
                                     'elapsed_seconds': round(elapsed, 4)})
        self.update('confirmed', confirmed_steps=pending['index'] + 1, pending=None, after=state)


def new_action_id():
    return uuid.uuid4().hex[:16]
