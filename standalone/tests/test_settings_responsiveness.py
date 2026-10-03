"""A stalled update connection must not stall settings, editing, or policy changes."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class SettingsResponsivenessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='studio-settings-test-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = {key: str(root / name) for key, name in (
            ('STUDIO_USER_DATA_ROOT', 'User'), ('STUDIO_CACHE_ROOT', 'Cache'),
            ('STUDIO_BACKUP_ROOT', 'Backups'), ('STUDIO_ERROR_LOG_ROOT', 'Logs'),
            ('STUDIO_DISPLAY_SETTINGS', 'display.json'))}
        env['STUDIO_UPDATE_MANAGED'] = '1'
        env['STUDIO_BASE_WEB'] = str(Path(server.__file__).parent)
        context = patch.dict(os.environ, env)
        context.start()
        self.addCleanup(context.stop)
        store = server.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game',
                                  asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.app = server.StudioServer(('127.0.0.1', 0), store)
        thread = threading.Thread(target=self.app.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.app.server_close)
        self.addCleanup(self.app.shutdown)

    def request(self, route, payload=None, token=None):
        request = urllib.request.Request(self.app.origin + '/api/' + route,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'X-Studio-Token': self.app.token if token is None else token,
                     'Content-Type': 'application/json'})
        # Local sessions must not be sent through the user's system HTTP proxy.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
            return json.load(response)

    def test_settings_and_policy_gate_remain_available_during_stalled_update_check(self):
        entered, release = threading.Event(), threading.Event()

        def blocked_network(url):
            entered.set()
            if not release.wait(10):
                raise TimeoutError('isolated network timeout')
            raise urllib.error.URLError('isolated offline update')

        self.app.updates.opener = blocked_network
        with ThreadPoolExecutor(max_workers=1) as executor:
            check = executor.submit(self.request, 'updates/check', {})
            try:
                self.assertTrue(entered.wait(2), 'update check did not reach network')
                self.assertEqual(self.app.project_request_gate.readers, 0)
                self.assertIn('modsStatus', self.request('game-locations'))
                self.assertIn('path', self.request('cache-settings'))
                self.assertEqual(self.request('startup-preparation')['status'], 'idle')
                # Ignoring a mod needs the exclusive policy gate. Update networking
                # does not read mod files and must not delay that gate's acquisition.
                with self.app.project_request_gate.access(exclusive=True):
                    with self.app.location_lock:
                        self.assertEqual(self.request('updates')['status'], 'checking')
                self.assertFalse(check.done(), 'network stall ended before the checks')
            finally:
                release.set()
            self.assertEqual(check.result(timeout=4)['status'], 'error')

    def test_independent_update_requests_still_require_session_token(self):
        with patch.object(self.app.updates, 'check') as check:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request('updates/check', {}, token='incorrect')
            self.assertEqual(error.exception.code, 403)
            check.assert_not_called()


if __name__ == '__main__':
    unittest.main()
