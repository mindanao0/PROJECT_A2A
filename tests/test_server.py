import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from navis.core import Runtime
from navis.server import ControlServer


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
        for path in ['/../core.py','/core.py','/api/token']:
            self.assertEqual(self.request(path=path,headers=self.auth())[0],404)


if __name__ == '__main__':
    unittest.main()
