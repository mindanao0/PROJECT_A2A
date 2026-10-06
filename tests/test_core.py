import tempfile
import unittest
from pathlib import Path

from navis.core import ControlError, Runtime, normalize_scope, overlap


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.now = 1000
        self.runtime = Runtime(Path(self.folder.name) / 'state.sqlite3', lambda: self.now)

    def tearDown(self):
        self.runtime.close()
        self.folder.cleanup()

    def create(self, scenario='success', spec='A task', scope='src/'):
        result = self.runtime.command(dict(action='create_task', project_id='project-vela', title='Test task', spec=spec, scope=scope, scenario=scenario))
        return self.runtime.task(result['task_id'])

    def control(self, task, action, **extra):
        return self.runtime.command(dict(action=action, task_id=task['id'], attempt_id=task['attempt_id'], **extra))

    def tick(self, seconds=3):
        self.now += seconds
        self.runtime.tick()

    def test_result_cannot_complete_before_verification(self):
        task = self.create()
        self.runtime.tick()
        self.tick()
        self.assertEqual(task['state'], 'VERIFY')
        self.tick()
        self.assertEqual(task['state'], 'COMPLETED')
        self.assertEqual(task['artifacts'][-1]['exit_code'], 0)
        self.assertTrue(task['artifacts'][-1]['simulated'])

    def test_verifier_failure(self):
        task = self.create('verify_failure')
        self.runtime.tick()
        self.tick()
        self.tick()
        self.assertEqual(task['state'], 'FAILED')
        self.assertEqual(task['artifacts'][-1]['exit_code'], 1)

    def test_pause_does_not_stop_running_attempt(self):
        first = self.create()
        second = self.create(spec='Second task')
        self.runtime.tick()
        self.runtime.command({'action':'pause'})
        self.tick()
        self.tick()
        self.assertEqual(first['state'], 'COMPLETED')
        self.assertEqual(second['state'], 'QUEUED')
        self.runtime.command({'action':'resume'})
        self.runtime.tick()
        self.assertEqual(second['state'], 'RUNNING')

    def test_stop_requires_ack_and_kill_revokes(self):
        task = self.create('hang')
        self.runtime.tick()
        self.control(task, 'stop')
        self.assertEqual(task['state'], 'CANCELLING')
        self.tick(1)
        self.assertEqual(task['state'], 'CANCELLED')
        self.control(task, 'retry')
        self.runtime.tick()
        self.control(task, 'kill')
        self.assertEqual(task['state'], 'CANCELLED')
        self.tick(100)
        self.assertEqual(task['state'], 'CANCELLED')

    def test_pending_request_bound_to_payload_attempt_and_expiry(self):
        task = self.create('approval')
        self.runtime.tick()
        self.tick()
        pending = task['pending']['id']
        with self.assertRaises(ControlError):
            self.control(task, 'approve', pending_id='wrong')
        task = self.runtime.task(task['id'])
        self.assertEqual(task['state'], 'WAITING_APPROVAL')
        self.control(task, 'approve', pending_id=pending)
        task = self.runtime.task(task['id'])
        self.assertEqual(task['state'], 'RUNNING')
        with self.assertRaises(ControlError):
            self.control(task, 'approve', pending_id=pending)
        expired = self.create('approval', spec='Expired request')
        self.tick()
        self.tick()
        self.tick()
        self.tick(601)
        self.assertEqual(self.runtime.task(expired['id'])['state'], 'BLOCKED')

    def test_input_and_rejection(self):
        task = self.create('input')
        self.runtime.tick()
        self.tick()
        self.control(task, 'answer', pending_id=task['pending']['id'], text='Use contract tests')
        self.assertEqual(task['state'], 'RUNNING')
        self.control(task, 'kill')
        second = self.create('approval', spec='Another task')
        self.runtime.tick()
        self.tick()
        self.control(second, 'reject', pending_id=second['pending']['id'])
        self.assertEqual(second['state'], 'BLOCKED')
        self.assertFalse(second['artifacts'])

    def test_quota_releases_slot_and_does_not_fail(self):
        task = self.create('quota')
        other = self.create(spec='Second')
        self.runtime.tick()
        self.tick()
        self.assertEqual(task['state'], 'WAITING_QUOTA')
        self.assertEqual(other['state'], 'RUNNING')
        self.tick(15)
        self.assertEqual(task['state'], 'QUEUED')
        self.assertEqual(len(task['attempts']), 1)

    def test_scope_and_dedup(self):
        first = self.create(spec='Do THE task', scope='src/, tests')
        duplicate = self.create(spec=' do  the TASK ', scope='tests/, src')
        self.assertEqual(first['id'], duplicate['id'])
        self.assertTrue(overlap(['src'], ['src/index']))
        self.assertFalse(overlap(['src'], ['src2']))
        for path in ['/tmp', '../secret', 'src/../../tmp', '']:
            with self.assertRaises(ControlError):
                normalize_scope(path)

    def test_restart_does_not_replay_and_rejects_stale_control(self):
        task = self.create('hang')
        self.runtime.tick()
        old_attempt = task['attempt_id']
        self.runtime.close()
        self.runtime = Runtime(Path(self.folder.name) / 'state.sqlite3', lambda: self.now)
        task = self.runtime.task(task['id'])
        self.assertEqual(task['state'], 'BLOCKED')
        self.tick(100)
        self.assertEqual(task['state'], 'BLOCKED')
        self.control(task, 'retry')
        self.runtime.tick()
        self.assertNotEqual(task['attempt_id'], old_attempt)
        with self.assertRaises(ControlError):
            self.runtime.command(dict(action='kill', task_id=task['id'], attempt_id=old_attempt))
        self.assertEqual(self.runtime.task(task['id'])['state'], 'RUNNING')

    def test_retry_preserves_evidence_of_previous_attempt(self):
        task = self.create('verify_failure')
        self.runtime.tick()
        self.tick()
        self.tick()
        old = task['attempt_id']
        hashes = [a['hash'] for a in task['artifacts']]
        self.control(task, 'retry')
        self.runtime.tick()
        self.assertNotEqual(task['attempt_id'], old)
        self.assertEqual([a['hash'] for a in task['artifacts']], hashes)
        self.assertTrue(all(a['attempt_id'] == old for a in task['artifacts']))
        self.assertEqual(task['attempts'][0]['state'], 'FAILED')

    def test_cursor_and_atomic_invalid_commands(self):
        self.create()
        snapshot = self.runtime.snapshot()
        self.assertEqual(len(snapshot['events']), 1)
        self.assertEqual(self.runtime.snapshot(snapshot['cursor'])['events'], [])
        with self.assertRaises(ControlError):
            self.runtime.command(dict(action='create_task', project_id='missing',title='t',spec='s',scope='src'))
        self.assertEqual(len(self.runtime.snapshot()['tasks']), 1)
        self.assertEqual(len(self.runtime.snapshot()['events']), 1)

    def test_task_evidence_is_excluded_from_poll_and_available_on_demand(self):
        task = self.create()
        task['artifacts'].append({'id':'artifact-test','kind':'diff','name':'Patch','attempt_id':'attempt-test','content':'+full patch'})
        self.runtime.save()
        summary = next(t for t in self.runtime.snapshot()['tasks'] if t['id']==task['id'])
        self.assertNotIn('content',summary['artifacts'][-1])
        detail = self.runtime.task_detail(task['id'])
        self.assertEqual(detail['task']['artifacts'][-1]['content'],'+full patch')

    def test_queue_reasons_report_pause_scope_slot_and_cooldown(self):
        first = self.create('hang')
        self.runtime.tick()
        queued = self.create(spec='Blocked queue', scope='src/nested')
        self.runtime.command({'action': 'pause'})
        task = next(t for t in self.runtime.snapshot()['tasks'] if t['id'] == queued['id'])
        self.assertEqual([r['code'] for r in task['queue_reasons']], ['paused', 'scope', 'slot'])
        self.assertEqual(task['queue_reasons'][1]['task_id'], first['id'])
        self.control(first, 'kill')
        self.runtime.command({'action': 'resume'})
        quota = self.create('quota', spec='Cooldown')
        self.control(queued, 'stop')
        self.runtime.tick()
        self.tick()
        task = next(t for t in self.runtime.snapshot()['tasks'] if t['id'] == quota['id'])
        self.assertEqual(task['queue_reasons'][0]['code'], 'cooldown')
        self.assertEqual(task['queue_reasons'][0]['until'], quota['due'])
        self.assertFalse(self.runtime.snapshot()['resources']['memory_available'])

    def test_source_task_is_bound_to_completed_attempt_and_saved_artifacts(self):
        source = self.create()
        self.runtime.tick(); self.tick(); self.tick()
        request = dict(action='create_task', project_id='project-vela', title='Follow up', spec='Review previous result', scope='src/', source_task_id=source['id'], source_attempt_id=source['attempt_id'])
        result = self.runtime.command(request)
        following = self.runtime.task(result['task_id'])
        self.assertEqual(following['source']['attempt_id'], source['attempt_id'])
        self.assertEqual(following['source']['artifacts'], source['artifacts'])
        source['artifacts'][0]['content'] = 'Changed later'
        self.assertNotEqual(following['source']['artifacts'][0]['content'], 'Changed later')
        with self.assertRaises(ControlError):
            self.runtime.command(dict(request, source_attempt_id='stale'))
        running = self.create('hang', spec='Not completed')
        with self.assertRaises(ControlError):
            self.runtime.command(dict(request, source_task_id=running['id'], source_attempt_id=None))


if __name__ == '__main__':
    unittest.main()
