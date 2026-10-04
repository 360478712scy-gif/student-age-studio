"""Read-only Windows startup probes; called only after failure or by explicit QA."""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

NETFX_URL = 'https://dotnet.microsoft.com/download/dotnet-framework/net48'
WEBVIEW_URL = 'https://developer.microsoft.com/microsoft-edge/webview2/'
WEBVIEW_KEYS = (
    '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    '{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}',
    '{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}',
    '{65C35B14-6C1D-4122-AC46-7148CC9D6497}',
)
EXIT_CODES = {'ok': 0, 'package_missing': 11, 'netfx_missing': 12, 'netfx_too_old': 12,
              'webview_missing': 13, 'runtime_config': 14, 'pythonnet_load': 15,
              'startup_unknown': 16}


def _registry_value(winreg, hive, key, name, view):
    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
        return winreg.QueryValueEx(handle, name)[0]


def probe_dependencies(registry=None, environment=None):
    env = os.environ if environment is None else environment
    result = {'netfx': 'unknown', 'webview': 'unknown'}
    if registry is None:
        try:
            import winreg as registry
        except ImportError:
            return result
    views = (registry.KEY_WOW64_64KEY, registry.KEY_WOW64_32KEY)
    errors = []
    releases = []
    for view in views:
        try:
            releases.append(int(_registry_value(registry, registry.HKEY_LOCAL_MACHINE,
                r'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', view)))
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as error:
            errors.append(str(error))
    if releases:
        result['netfxRelease'] = max(releases)
        # This is pywebview 6.2.1 WinForms' own minimum, not Python.NET's minimum.
        result['netfx'] = 'installed' if max(releases) >= 394802 else 'too_old'
    elif not errors:
        result['netfx'] = 'missing'
    if errors:
        result['registryErrors'] = errors
    if env.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'):
        result['webview'] = 'custom'
        return result
    versions, errors = [], []
    for hive in (registry.HKEY_CURRENT_USER, registry.HKEY_LOCAL_MACHINE):
        for view in views:
            for key in WEBVIEW_KEYS:
                try:
                    version = str(_registry_value(registry, hive,
                        r'SOFTWARE\Microsoft\EdgeUpdate\Clients' + '\\' + key, 'pv', view))
                    parts = tuple(int(part) for part in version.split('.'))
                    if parts >= (86, 0, 622, 0):
                        versions.append(version)
                except FileNotFoundError:
                    pass
                except (OSError, ValueError, TypeError) as error:
                    errors.append(str(error))
    if versions:
        result.update(webview='installed', webviewVersions=versions)
    elif not errors:
        result['webview'] = 'missing'
    return result


def classify_failure(error, install_root, *, dependencies=None, environment=None):
    root = Path(install_root)
    env = os.environ if environment is None else environment
    dependencies = probe_dependencies(environment=env) if dependencies is None else dependencies
    detail = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    report = {'code': 'startup_unknown', 'summary': '工作台启动失败，请查看详细日志。',
              'details': detail, 'dependencies': dependencies, 'installRoot': str(root)}
    dll = root / 'runtime/_internal/pythonnet/runtime/Python.Runtime.dll'
    packaged = (root / 'runtime').is_dir()
    if packaged and not dll.is_file():
        report.update(code='package_missing', summary='安装包缺少 Python.NET 运行库文件，请重新完整解压官方安装包。')
    elif dependencies.get('netfx') == 'missing':
        report.update(code='netfx_missing', summary='未检测到兼容的 .NET Framework，工作台无法创建 Windows 窗口。')
    elif dependencies.get('netfx') == 'too_old':
        report.update(code='netfx_too_old', summary='已安装的 .NET Framework 版本低于本客户端 WinForms 的要求（4.6.2）。')
    elif env.get('PYTHONNET_RUNTIME', 'netfx').lower() not in ('', 'netfx') or env.get('PYTHONNET_RUNTIME_CONFIG'):
        report.update(code='runtime_config', summary='Python.NET 运行环境被外部配置覆盖，请从完整安装包的顶层“拾光工坊.exe”启动。')
    elif dependencies.get('webview') == 'missing' and 'WEBVIEW_REQUIREMENT' in str(error):
        report.update(code='webview_missing', summary='未检测到可用的 Microsoft Edge WebView2 Runtime。')
    elif 'Python.Runtime' in detail or 'clr_loader' in detail or 'pythonnet' in detail or isinstance(error, ModuleNotFoundError) and error.name in ('clr', 'pythonnet', 'clr_loader'):
        report.update(code='pythonnet_load', summary='Windows 的 Python.NET 桥接运行库加载失败。诊断窗口将检查本安装包完整性与下载限制。')
    return report


def write_report(report, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def diagnostic_cli(argv=None):
    parser = argparse.ArgumentParser(description='Read-only native runtime diagnostics')
    parser.add_argument('--diagnose-runtime', action='store_true')
    parser.add_argument('--diagnostic-json')
    parser.add_argument('--install-root')
    args = parser.parse_args(argv)
    root = Path(args.install_root or os.environ.get('STUDIO_INSTALL_ROOT', Path(sys.executable).parent.parent))
    dependencies = probe_dependencies()
    try:
        # Exercise the actual frozen Python.NET import, rather than reflecting on a DLL alone.
        importlib.import_module('clr')
        guilib = importlib.import_module('webview.guilib')
        guilib.forced_gui_ = 'edgechromium'
        winforms = importlib.import_module('webview.platforms.winforms')
        if winforms.renderer != 'edgechromium':
            raise RuntimeError('WEBVIEW_REQUIREMENT: edgechromium unavailable')
        report = {'code': 'ok', 'summary': 'Python.NET 和 WebView2 窗口宿主导入通过。',
                  'dependencies': dependencies, 'installRoot': str(root), 'readOnly': True}
    except Exception as error:
        report = classify_failure(error, root, dependencies=dependencies)
        report['readOnly'] = True
    if args.diagnostic_json:
        write_report(report, args.diagnostic_json)
    print(json.dumps(report, ensure_ascii=False))
    return EXIT_CODES[report['code']]
