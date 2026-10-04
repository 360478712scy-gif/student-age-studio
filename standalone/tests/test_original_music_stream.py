"""A paused original-music stream must not hold the lock used by editing APIs."""
import json
import http.client
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class OriginalMusicStreamTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='studio-original-music-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = {key: str(root / name) for key, name in (
            ('STUDIO_USER_DATA_ROOT', 'User'), ('STUDIO_CACHE_ROOT', 'Cache'),
            ('STUDIO_BACKUP_ROOT', 'Backups'), ('STUDIO_ERROR_LOG_ROOT', 'Logs'),
            ('STUDIO_DISPLAY_SETTINGS', 'display.json'))}
        env['STUDIO_UPDATE_MANAGED'] = '1'
        context = patch.dict(os.environ, env)
        context.start()
        self.addCleanup(context.stop)
        store = server.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game',
                                  asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.project = store.create('音乐流测试')['id']
        self.audio = store.project(self.project).path / 'Audios' / 'stream.wav'
        size = 32 * 1024 * 1024
        with self.audio.open('wb') as stream:
            stream.write(b'RIFF' + struct.pack('<I', 36 + size) + b'WAVEfmt '
                         + struct.pack('<IHHIIHH', 16, 1, 1, 44100, 88200, 2, 16)
                         + b'data' + struct.pack('<I', size))
            stream.truncate(44 + size)  # Valid silent PCM, without a large allocation.
        self.app = server.StudioServer(('127.0.0.1', 0), store)
        threading.Thread(target=self.app.serve_forever, daemon=True).start()
        self.addCleanup(self.app.server_close)
        self.addCleanup(self.app.shutdown)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def url(self):
        return self.app.origin + '/api/social-image?' + urllib.parse.urlencode(
            {'projectId': self.project, 'path': 'Audios/stream.wav'})

    def test_paused_stream_does_not_block_editor_settings(self):
        entered, held = threading.Event(), []
        send_file = server.StudioHandler.send_file

        def observe(handler, path):
            held.append(handler.server.location_lock._is_owned())
            entered.set()
            return send_file(handler, path)

        with patch.object(server.StudioHandler, 'send_file', observe):
            with socket.socket() as client:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
                client.settimeout(2)
                client.connect(('127.0.0.1', self.app.server_port))
                target = self.url().split(self.app.origin, 1)[1]
                client.sendall((f'GET {target} HTTP/1.1\r\n'
                                f'Host: 127.0.0.1:{self.app.server_port}\r\n'
                                f'X-Studio-Token: {self.app.token}\r\n'
                                'Range: bytes=0-\r\nConnection: close\r\n\r\n').encode())
                header = b''
                while b'\r\n\r\n' not in header:
                    header += client.recv(1024)
                self.assertIn(b'206 Partial Content', header)
                self.assertTrue(entered.wait(1))
                # Keep the client open without reading the remaining 32 MiB.
                request = urllib.request.Request(self.app.origin + '/api/display-settings',
                    headers={'X-Studio-Token': self.app.token})
                with self.opener.open(request, timeout=2) as response:
                    self.assertIn('theme', json.load(response))
                self.assertEqual(held, [False])

    def test_original_music_range_still_returns_only_requested_bytes(self):
        request = urllib.request.Request(self.url(),
            headers={'X-Studio-Token': self.app.token, 'Range': 'bytes=0-43'})
        with self.opener.open(request, timeout=2) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers['Content-Range'], 'bytes 0-43/' + str(self.audio.stat().st_size))
            self.assertEqual(len(response.read()), 44)

    def test_unreadable_audio_returns_json_error_before_media_headers(self):
        original = Path.open

        def open_file(path, *args, **kwargs):
            if path == self.audio and args and args[0] == 'rb':
                raise PermissionError(13, 'isolated audio read denial', str(path))
            return original(path, *args, **kwargs)

        request = urllib.request.Request(self.url(),
            headers={'X-Studio-Token': self.app.token, 'Range': 'bytes=0-43'})
        with patch.object(Path, 'open', open_file):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                self.opener.open(request, timeout=2)
            self.assertEqual(raised.exception.code, 403)
            self.assertIn('application/json', raised.exception.headers['Content-Type'])
            self.assertNotIn('Content-Range', raised.exception.headers)
            self.assertEqual(json.load(raised.exception)['code'], 'file_permission')
            raised.exception.close()

    def test_cancelled_windows_media_connection_is_not_logged_as_app_failure(self):
        send_file = server.StudioHandler.send_file

        class CancelledBody:
            def __init__(self, stream):
                self.stream = stream

            def write(self, data):
                if data.startswith(b'RIFF'):
                    raise ConnectionAbortedError(10053, 'isolated cancelled media stream')
                return self.stream.write(data)

            def __getattr__(self, name):
                return getattr(self.stream, name)

        def stream(handler, path):
            handler.wfile = CancelledBody(handler.wfile)
            return send_file(handler, path)

        request = urllib.request.Request(self.url(),
            headers={'X-Studio-Token': self.app.token, 'Range': 'bytes=0-43'})
        with patch.object(server.StudioHandler, 'send_file', stream), patch.object(self.app.error_logs, 'response') as log:
            with self.opener.open(request, timeout=2) as response:
                with self.assertRaises(http.client.IncompleteRead):
                    response.read()
            log.assert_not_called()

    def test_original_music_stream_still_requires_session_token(self):
        request = urllib.request.Request(self.url(),
            headers={'X-Studio-Token': 'incorrect', 'Range': 'bytes=0-43'})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.opener.open(request, timeout=2)
        self.assertEqual(raised.exception.code, 403)
        raised.exception.close()


if __name__ == '__main__':
    unittest.main()
