#!/usr/bin/env python3
"""Run the existing Mac WKWebView host against source; produces no app/package."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if sys.platform != 'darwin':
        raise SystemExit('此入口用于 Mac 原生源码预览。Windows 请使用现有 WebView2 开发入口。')
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='student-age-source-host-') as temporary:
        binary=Path(temporary)/'StudentAgeSource'
        subprocess.run(['swiftc',str(root/'desktop/StudioApp.swift'),'-o',str(binary),'-framework','AppKit','-framework','WebKit'],check=True)
        # The host strips PYTHONPATH and disables user site-packages; the source
        # tree's decoders (tools/asset-reader, built for python.org 3.14) and any
        # user-installed packages reach the server through this wrapper.
        wrapper=Path(temporary)/'python-with-source-libs.sh'
        extra=':'.join(str(d) for d in (root/'tools/asset-reader',root/'standalone/vendor') if d.is_dir())
        wrapper.write_text('#!/bin/sh\nexport PYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}"\nunset PYTHONNOUSERSITE\nexec "%s" "$@"\n'%(extra,sys.executable),encoding='utf-8')
        wrapper.chmod(0o755)
        env={**os.environ,'STUDIO_SOURCE_ROOT':str(root),'STUDIO_PYTHON':str(wrapper)}
        print('已启动源码预览；关闭窗口时仍会检查未保存草稿。',flush=True)
        subprocess.run([str(binary)],env=env,check=True)


if __name__=='__main__': main()
