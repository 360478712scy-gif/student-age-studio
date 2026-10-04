import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[2] / 'desktop/windows/startup_diagnostics.py'
SPEC = importlib.util.spec_from_file_location('windows_startup_diagnostics', PATH)
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


class Registry:
    KEY_READ, KEY_WOW64_64KEY, KEY_WOW64_32KEY = 1, 2, 4
    HKEY_LOCAL_MACHINE, HKEY_CURRENT_USER = 'machine', 'user'
    def __init__(self, values=None, denied=False):
        self.values = values or {}
        self.denied = denied
    def OpenKey(self, hive, key, reserved, view):
        if self.denied:
            raise PermissionError('registry access denied')
        if key not in self.values:
            raise FileNotFoundError(key)
        class Handle:
            def __enter__(self):
                return key
            def __exit__(self, *args):
                pass
        return Handle()
    def QueryValueEx(self, key, name):
        return self.values[key], 1


class StartupDiagnosticsTests(unittest.TestCase):
    def failure(self, message='Failed to resolve Python.Runtime.Loader.Initialize'):
        return RuntimeError(message)

    def test_verified_absence_is_distinct_from_registry_denied(self):
        missing = diagnostics.probe_dependencies(Registry(), {})
        self.assertEqual(missing['netfx'], 'missing')
        denied = diagnostics.probe_dependencies(Registry(denied=True), {})
        self.assertEqual(denied['netfx'], 'unknown')
        self.assertEqual(denied['webview'], 'unknown')

    def test_installed_dependencies_use_pywebview_registry_locations(self):
        registry = Registry({
            r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full': 533320,
            r'SOFTWARE\Microsoft\EdgeUpdate\Clients' + '\\' + diagnostics.WEBVIEW_KEYS[0]: '140.0.1000.0',
        })
        result = diagnostics.probe_dependencies(registry, {})
        self.assertEqual(result['netfx'], 'installed')
        self.assertEqual(result['webview'], 'installed')

    def test_old_framework_is_not_reported_missing(self):
        registry = Registry({r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full': 394254})
        result = diagnostics.probe_dependencies(registry, {})
        self.assertEqual(result['netfx'], 'too_old')

    def test_custom_webview_is_not_reported_missing(self):
        result = diagnostics.probe_dependencies(Registry(), {'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER': r'C:\custom'})
        self.assertEqual(result['webview'], 'custom')

    def test_generic_clr_error_does_not_claim_framework_missing(self):
        result = diagnostics.classify_failure(self.failure(), '.', dependencies={'netfx': 'installed'}, environment={})
        self.assertEqual(result['code'], 'pythonnet_load')
        self.assertIn('Python.Runtime.Loader.Initialize', result['details'])

    def test_confirmed_missing_framework_offers_only_its_classification(self):
        result = diagnostics.classify_failure(self.failure(), '.', dependencies={'netfx': 'missing'}, environment={})
        self.assertEqual(result['code'], 'netfx_missing')

    def test_missing_package_file_takes_priority_over_system_install(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'runtime').mkdir()
            result = diagnostics.classify_failure(self.failure(), directory, dependencies={'netfx': 'missing'}, environment={})
            self.assertEqual(result['code'], 'package_missing')

    def test_external_runtime_override_is_not_an_installer_failure(self):
        result = diagnostics.classify_failure(self.failure(), '.', dependencies={'netfx': 'installed'}, environment={'PYTHONNET_RUNTIME': 'coreclr'})
        self.assertEqual(result['code'], 'runtime_config')

    def test_webview_install_requires_explicit_renderer_failure_and_absence(self):
        result = diagnostics.classify_failure(self.failure('WEBVIEW_REQUIREMENT: unavailable'), '.', dependencies={'netfx': 'installed', 'webview': 'missing'}, environment={})
        self.assertEqual(result['code'], 'webview_missing')
        result = diagnostics.classify_failure(self.failure(), '.', dependencies={'netfx': 'installed', 'webview': 'missing'}, environment={})
        self.assertEqual(result['code'], 'pythonnet_load')


if __name__ == '__main__':
    unittest.main()
