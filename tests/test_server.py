import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from axon.core import Runtime
from axon.server import ControlServer


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Path(self.folder.name) / 'test.sqlite3')
        self.server = ControlServer(self.runtime)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.runtime.close()
        self.folder.cleanup()

    def request(self, method='GET', path='/api/snapshot', headers=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        result = (response.status, data, response.headers)
        connection.close()
        return result

    def auth(self):
        return {'Authorization':'Bearer '+self.server.token, 'Origin':self.server.origin,'Content-Type':'application/json'}

    def test_authenticated_reads_and_writes(self):
        self.assertEqual(self.request()[0], 401)
        self.assertEqual(self.request(headers=self.auth())[0], 200)
        status, body, headers = self.request('POST','/api/command',self.auth(),json.dumps({'action':'pause'}))
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['ok'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertTrue(self.runtime.snapshot()['paused'])

    def test_origin_and_host_rejected(self):
        for headers in [dict(self.auth(),Origin='https://attacker.example'), dict(self.auth(),Host='attacker.example')]:
            self.assertEqual(self.request('POST','/api/command',headers,'{"action":"pause"}')[0],403)
        missing_origin = self.auth()
        missing_origin.pop('Origin')
        self.assertEqual(self.request('POST','/api/command',missing_origin,'{"action":"pause"}')[0],403)
        self.assertFalse(self.runtime.snapshot()['paused'])

    def test_invalid_payload_and_cursor(self):
        for body in ['[1]', 'null', '{', '"string"', '{"action":[]}', '{"action":{}}']:
            self.assertEqual(self.request('POST','/api/command',self.auth(),body)[0],400)
        self.assertEqual(self.request(path='/api/snapshot?cursor=-1',headers=self.auth())[0],400)
        self.assertEqual(self.request(path='/api/snapshot?cursor=999999999999999999999',headers=self.auth())[0],400)
        self.assertEqual(self.request('POST','/api/command',self.auth(),'x'*17000)[0],413)

    def test_static_allowlist_csp_and_no_remote_bind(self):
        status, _, headers = self.request(path='/')
        self.assertEqual(status,200)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(self.server.server_address[0],'127.0.0.1')
        status, logo, headers = self.request(path='/axon-wordmark.svg')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/svg+xml')
        self.assertIn(b'<svg', logo)
        status, icon, headers = self.request(path='/axon-icon.svg')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/svg+xml')
        self.assertIn(b'<svg', icon)
        for path in ['/../core.py','/core.py','/api/token']:
            self.assertEqual(self.request(path=path,headers=self.auth())[0],404)

    def test_browser_session_survives_reload_without_exposing_bearer(self):
        status, _, headers = self.request('POST', '/api/session', self.auth(), '{}')
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        self.assertIn('Path=/api/', cookie)
        self.assertNotIn(self.server.token, cookie)
        session = {'Cookie': cookie.split(';')[0]}
        self.assertEqual(self.request(headers=session)[0], 200)
        self.assertEqual(self.request('POST', '/api/command', dict(session, Origin=self.server.origin, **{'Content-Type':'application/json'}), '{"action":"pause"}')[0], 200)

    def test_cookie_does_not_bypass_origin_or_allow_session_bootstrap(self):
        _, _, headers = self.request('POST', '/api/session', self.auth(), '{}')
        session = {'Cookie': headers['Set-Cookie'].split(';')[0], 'Content-Type':'application/json'}
        self.assertEqual(self.request('POST', '/api/command', dict(session, Origin='https://attacker.example'), '{"action":"pause"}')[0], 403)
        self.assertEqual(self.request('POST', '/api/command', session, '{"action":"pause"}')[0], 403)
        self.assertEqual(self.request('POST', '/api/session', dict(session, Origin=self.server.origin), '{}')[0], 401)
        self.assertEqual(self.request(headers=dict(session, Authorization='Bearer wrong'))[0], 401)
        self.server.session_token = 'new-session-after-restart'
        self.assertEqual(self.request(headers=session)[0], 401)

    def test_full_task_evidence_is_loaded_only_for_selected_task(self):
        project = self.runtime.command({'action':'create_project','name':'Example'})
        created = self.runtime.command({'action':'create_task','project_id':project['id'],'title':'Evidence','spec':'Review output','scope':'src/'})
        task = self.runtime.task(created['task_id'])
        task['artifacts'].append({'id':'artifact-test','kind':'diff','name':'Patch','attempt_id':'attempt-test','content':'+safe test payload','files':[]})
        self.runtime.save()
        status, body, _ = self.request(headers=self.auth())
        self.assertEqual(status,200)
        self.assertNotIn(b'+safe test payload',body)
        self.assertEqual(self.request(path=f"/api/tasks/{task['id']}")[0],401)
        status, body, _ = self.request(path=f"/api/tasks/{task['id']}",headers=self.auth())
        self.assertEqual(status,200)
        self.assertIn(b'+safe test payload',body)
        self.assertEqual(self.request(path='/api/tasks/unknown-task',headers=self.auth())[0],404)


class LoginAndRemoteTests(unittest.TestCase):
    """Password sign-in, and a proxy's host name (tailscale serve) allowed only once a password is set."""
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.runtime = Runtime(Path(self.folder.name) / 'test.sqlite3')
        self.pw = Path(self.folder.name) / 'password'
        self.server = ControlServer(self.runtime, hosts=['box.tail1.ts.net'], password_file=self.pw)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.runtime.close()
        self.folder.cleanup()

    def request(self, method, path, headers, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        result = (response.status, json.loads(response.read() or b'null'), response.headers)
        connection.close()
        return result

    def test_password_hash_round_trip(self):
        from axon.server import check_password, hash_password
        stored = hash_password('correct horse', iterations=1000)
        self.assertTrue(check_password('correct horse', stored))
        self.assertFalse(check_password('wrong', stored))
        self.assertFalse(check_password('x', 'garbage'))

    def test_remote_needs_a_password_then_sign_in_works(self):
        from axon.server import hash_password
        remote = {'Host': 'box.tail1.ts.net', 'Origin': 'https://box.tail1.ts.net', 'Content-Type': 'application/json'}
        self.assertEqual(self.request('GET', '/', {'Host': 'box.tail1.ts.net'})[0], 403)  # no password: remote closed
        self.assertEqual(self.request('GET', '/', {'Host': 'other.example'})[0], 403)
        self.pw.write_text(hash_password('correct horse', iterations=1000))
        status, body, _ = self.request('GET', '/api/snapshot', remote)
        self.assertEqual((status, body['login']), (401, True))
        self.assertEqual(self.request('POST', '/api/login', remote, '{"password":"wrong"}')[0], 401)
        self.assertEqual(self.request('POST', '/api/login', dict(remote, Origin='https://evil.example'), '{"password":"correct horse"}')[0], 403)
        status, _, headers = self.request('POST', '/api/login', remote, '{"password":"correct horse"}')
        self.assertEqual(status, 200)
        self.assertIn('Secure', headers['Set-Cookie'])
        cookie = {'Cookie': headers['Set-Cookie'].split(';')[0]}
        self.assertEqual(self.request('GET', '/api/snapshot', dict(remote, **cookie))[0], 200)
        # A proxy that rewrites Host to loopback still counts as remote by the browser's Origin.
        local_host = {'Host': f'127.0.0.1:{self.server.server_port}', 'Origin': 'https://box.tail1.ts.net', 'Content-Type': 'application/json'}
        self.assertEqual(self.request('POST', '/api/command', dict(local_host, **cookie), '{"action":"pause"}')[0], 200)
        self.pw.unlink()
        self.assertEqual(self.request('POST', '/api/command', dict(local_host, **cookie), '{"action":"resume"}')[0], 403)


if __name__ == '__main__':
    unittest.main()
