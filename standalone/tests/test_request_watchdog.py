"""A request that never finishes (the editor looks frozen) is written to slow-requests.log with where it waits."""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from error_logs import ErrorLogs


class RequestWatchdogTests(unittest.TestCase):
    def test_stuck_request_is_logged_with_its_stack(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = ErrorLogs(folder)
            watchdog = server.RequestWatchdog(logs)
            watchdog.LIMIT = 0.2
            release = threading.Event()

            def stuck_request():
                watchdog.begin('POST', '/api/save')
                watchdog.running()
                release.wait(15)  # stands in for a request that never returns
                watchdog.end()
            worker = threading.Thread(target=stuck_request)
            worker.start()
            path = Path(folder) / 'slow-requests.log'
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not path.exists():
                time.sleep(0.2)
            release.set(); worker.join()
            text = path.read_text(encoding='utf-8')
            self.assertIn('POST /api/save', text)
            self.assertIn('仍未完成', text)
            self.assertIn('执行中', text)
            self.assertIn('stuck_request', text)

    def test_slow_request_line(self):
        with tempfile.TemporaryDirectory() as folder:
            logs = ErrorLogs(folder)
            logs.slow('GET', '/api/project', 0.5, 3.2)
            text = (Path(folder) / 'slow-requests.log').read_text(encoding='utf-8')
            self.assertIn('GET /api/project', text)
            self.assertIn('排队 0.5s', text)
            self.assertIn('执行 3.2s', text)


if __name__ == '__main__':
    unittest.main()
