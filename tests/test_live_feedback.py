import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from baba_execution import ActionJournal, ExecutionError, action_status
from baba_search_budget import SearchBudget, BudgetExhausted
from baba_stream import stream_command
from read_baba_state import load_state, StateReadError


def state(turn=0):
    return {'meta': {'world': 'baba', 'level': 'test', 'turn': turn, 'sequence': turn}, 'units': [], 'rules': []}


class FeedbackTests(unittest.TestCase):
    def test_deadline_and_size(self):
        now = [0]
        budget = SearchBudget(clock=lambda: now[0], emit=lambda _: None)
        for phase in ['patterns', 'assignments', 'heuristic', 'reachable', 'solve']:
            now[0] = 6
            with self.assertRaises(BudgetExhausted):
                budget.check(phase)
        budget = SearchBudget(max_patterns=1, emit=lambda _: None)
        with self.assertRaises(BudgetExhausted):
            budget.check('patterns', 2)

    def test_confirmed_resume_and_uncertain_refusal(self):
        with tempfile.TemporaryDirectory() as temp, patch('baba_execution.ROOT', Path(temp)):
            config = SimpleNamespace(current_run_id='test')
            journal = ActionJournal(config, 'abc', ['right', 'up'], state())
            journal.dispatch(0, 'right')
            with self.assertRaisesRegex(ExecutionError, 'uncertain'):
                ActionJournal(config, 'abc', ['right', 'up'], state(), resume=True)
            journal.confirm(state(1), .1)
            with self.assertRaisesRegex(ExecutionError, 'state_mismatch'):
                ActionJournal(config, 'abc', ['right', 'up'], state(), resume=True)
            resumed = ActionJournal(config, 'abc', ['right', 'up'], state(1), resume=True)
            self.assertEqual(resumed.record['confirmed_steps'], 1)
            resumed.update('completed')
            self.assertFalse(action_status(config, 'abc')['resume_safe'])

    def test_output_arrives_before_child_exits(self):
        times = []
        start = time.monotonic()
        result = stream_command([sys.executable, '-u', '-c', 'import time; print("first"); time.sleep(.4); print("last")'], cwd='.', timeout=2,
                                emit=lambda data, **kw: times.append((time.monotonic()-start, data)))
        self.assertEqual(result.returncode, 0)
        self.assertLess(times[0][0], .35)
        self.assertIn('last', result.stdout)

    def test_mcp_background_query_without_game_input(self):
        import baba_mcp_server as server
        with tempfile.TemporaryDirectory() as temp, patch('baba_execution.ROOT', Path(temp)):
            config = Path(temp) / 'config.json'
            config.write_text(json.dumps({'current_run_id': 'test'}))
            args = {'config': str(config), 'moves': 'right', 'expect_moved': ['baba'],
                    'background': True, 'dry_run': True, 'action_id': 'dry'}
            text, error = server.check_moves(args)
            self.assertFalse(error)
            self.assertEqual(json.loads(text)['phase'], 'submitted')
            server.BACKGROUND['dry'].wait(timeout=3)
            status = json.loads(server.query_action({'config': str(config), 'action_id': 'dry'})[0])
            self.assertEqual(status['exit_code'], 0)
            self.assertIn('check=planned', status['output_tail'])
            with self.assertRaises(server.RpcError):
                server.check_moves(args)
            server.cancel_action({'config': str(config), 'action_id': 'dry'})
            self.assertTrue((Path(temp) / 'runs/test/actions/dry.cancel').exists())

    def test_cancel_stops_before_next_key(self):
        import baba_try
        from baba_execution import action_path
        with tempfile.TemporaryDirectory() as temp, patch('baba_execution.ROOT', Path(temp)):
            config = SimpleNamespace(current_run_id='test', app_name='Baba', input_delay=0)
            args = SimpleNamespace(resume=False, check_request='{}', no_activate=True,
                                   app_name=None, pre_delay=0, method='cgevent', delay=0,
                                   hold_ms=1, timeout=1)
            path = action_path(config, 'cancel')
            path.parent.mkdir(parents=True)
            path.with_suffix('.cancel').touch()
            with patch.object(baba_try, 'load_state', return_value=state()), \
                 patch.object(baba_try, 'validate_benchmark'), \
                 patch.object(baba_try, 'send_one') as send:
                baba_try.execute_segment(args, config, Path(temp), Path(temp)/'state', ['right'], 'cancel')
                send.assert_not_called()
            self.assertEqual(json.loads(path.read_text())['phase'], 'cancelled')

    def test_default_agent_save_and_incomplete_export(self):
        with tempfile.TemporaryDirectory() as temp:
            save_dir = Path(temp)
            save = save_dir / '0ba.ba'
            export = ('[agent_state]\nschema=baba-agent-state-export-v1\n'
                      'world=baba\nlevel=test\nturn=1\nsequence=2\n'
                      'unit_count=0\nrule_count=0\n')
            save.write_text(export)
            with patch('read_baba_state.current_save_file', return_value=save):
                observed = load_state(None, wait=False, timeout=0, since_mtime=None, save_dir=save_dir)
                self.assertEqual(observed['meta']['turn'], 1)
                self.assertEqual(observed['meta']['storage'], 'save')
                save.write_text(export.replace('unit_count=0', 'unit_count=1'))
                with self.assertRaises(StateReadError) as caught:
                    load_state(None, wait=False, timeout=0, since_mtime=None, save_dir=save_dir)
                self.assertEqual(caught.exception.reason, 'state_parse_failed')

    def test_search_keeps_you_and_solves_existing_goal(self):
        from baba_search_route import LevelData, SearchConfig, build_problem, solve
        level = LevelData('baba', 'synthetic', 'fixture', 7, 7, {
            'baba': [(1, 3, 0)], 'text_baba': [(1, 1, 0)],
            'text_is': [(2, 1, 0), (2, 5, 0)], 'text_you': [(3, 1, 0)],
            'text_flag': [(1, 5, 0)], 'text_win': [(3, 5, 0)],
        }, [('H', (1, 1), 'baba', 'is', 'you'),
            ('H', (1, 5), 'flag', 'is', 'win')])
        config = SearchConfig('flag', 'win', True, False, 100, 4, 0, (1, 5), 'right')
        problem = build_problem(level, config, extra_words=[], selected_text_at=[], all_is=True)
        self.assertNotIn((2, 1), [unit.coord for unit in problem.selected])
        route, _, _ = solve(problem)
        self.assertEqual(route, [])

    def test_stale_is_not_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'explicit.json'
            path.write_text(json.dumps(state()))
            with self.assertRaises(StateReadError) as caught:
                load_state(path, wait=True, timeout=.01, since_mtime=None, since_state=state(), save_dir=Path(temp))
            self.assertEqual(caught.exception.reason, 'state_unchanged')

if __name__ == '__main__':
    unittest.main()
