import io
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_updates import AppUpdates, unpack_archive, version_key
from update_bootstrap import select_web, mark_healthy, read_state, write_json, rollback_failed_start


def archive(version='1.3.1-beta.1',extra=None,abi=1):
    files={'standalone/server.py':b'print("ready")','standalone/index.html':b'<html>test</html>',
           'standalone/error_logs.py':('APP_VERSION = '+repr(version)).encode()}
    if extra:files.update(extra)
    manifest={'format':1,'version':version,'runtimeAbi':abi,'files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()}}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('update.json',json.dumps(manifest))
    return output.getvalue()


class UpdatesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.base=self.root/'base';self.base.mkdir()
        self.env=patch.dict(os.environ,{'STUDIO_UPDATE_MANAGED':'1','STUDIO_ACTIVE_UPDATE':'','STUDIO_BASE_WEB':str(self.base)},clear=False);self.env.start();self.addCleanup(self.env.stop);os.environ.pop('STUDIO_ACTIVE_UPDATE',None)
        (self.base/'update-channel.json').write_text(json.dumps({'repository':'owner/repo','channel':'beta','asset':'student-age-studio-update.zip'}), encoding='utf-8')
        (self.base/'update_bootstrap.py').write_text('# stable bootstrap', encoding='utf-8')
        (self.base/'ui-assets').mkdir();(self.base/'ui-assets/private.png').write_bytes(b'private installed artwork')
        (self.base/'obsolete.js').write_text('old', encoding='utf-8')
        (self.base/'error_logs.py').write_text("APP_VERSION='1.3.0-beta.1'", encoding='utf-8')
        self.payload=archive();self.release={'tag_name':'v1.3.1-beta.1','draft':False,'prerelease':True,'assets':[{'name':'student-age-studio-update.zip','size':len(self.payload),'digest':'sha256:'+hashlib.sha256(self.payload).hexdigest(),'browser_download_url':'https://github.com/owner/repo/releases/download/v1.3.1-beta.1/student-age-studio-update.zip'}]}
        self.calls=[]
        def opener(url):
            self.calls.append(url)
            return io.BytesIO(json.dumps([self.release]).encode() if 'api.github.com' in url else self.payload)
        self.updater=AppUpdates(self.base,'1.3.0-beta.1',self.root/'Updates',opener,True)

    def stage(self):
        self.assertEqual(self.updater.check()['status'],'available');self.updater.download()
        for _ in range(300):
            status=self.updater.status()
            if status['status']!='downloading':break
            time.sleep(.01)
        self.assertEqual(status['status'],'ready',status)

    def test_13111_uses_legacy_compatible_version_order_and_display(self):
        from error_logs import display_version
        self.assertGreater(version_key('v1.3.12-beta.1'), version_key('1.3.11'))
        self.assertLess(version_key('v1.3.12-beta.1'), version_key('1.3.12'))
        self.assertEqual(display_version('v1.3.12-beta.1'), '1.3.11.1')
        self.assertGreater(version_key('v1.3.12-beta.2'), version_key('v1.3.12-beta.1'))
        self.assertEqual(display_version('v1.3.12-beta.2'), '1.3.11.2')
        self.assertGreater(version_key('v1.3.12-beta.3'), version_key('v1.3.12-beta.2'))
        self.assertEqual(display_version('v1.3.12-beta.3'), '1.3.11.3')

    def test_beta135_hotfix_sorts_after_installed_beta135(self):
        self.assertGreater(version_key('v1.3.5-beta.2'), version_key('v1.3.5-beta.1'))
        self.assertGreater(version_key('v1.3.5-beta.1'), version_key('beta-1.3.5'))
        self.assertLess(version_key('v1.3.5-beta.1'), version_key('beta-1.3.6'))
        self.assertEqual(version_key('v1.3.5-beta.1'), version_key('1.3.5-beta.1'))

    def test_source_feed_download_uses_immutable_commit(self):
        self.updater.config['sourceUpdates']=True
        commit='a'*40
        feed={'format':1,'runtimeAbi':1,'version':'v1.3.1-beta.1','commit':commit,'size':len(self.payload),'sha256':hashlib.sha256(self.payload).hexdigest()}
        def opener(url):
            self.calls.append(url)
            if url.endswith('/updates/latest.json'):return io.BytesIO(json.dumps(feed).encode())
            self.assertEqual(url,'https://raw.githubusercontent.com/owner/repo/'+commit+'/student-age-studio-update.zip')
            return io.BytesIO(self.payload)
        self.updater.opener=opener
        self.stage()
        self.assertFalse(any('/releases' in u for u in self.calls))
        self.updater.activate();self.assertTrue(read_state(self.updater.root)['active'])

    def test_official_fallback_recovers_blocked_raw_and_interrupted_download(self):
        import urllib.error
        self.updater.config['sourceUpdates']=True
        feed={'format':1,'runtimeAbi':1,'version':'v1.3.1-beta.1','commit':'a'*40,
              'size':len(self.payload),'sha256':hashlib.sha256(self.payload).hexdigest()}
        payload_calls=[]
        def opener(url):
            self.calls.append(url)
            if 'raw.githubusercontent.com' in url:raise urllib.error.URLError('blocked raw')
            if '/contents/latest.json?ref=updates' in url:return io.BytesIO(json.dumps(feed).encode())
            self.assertIn('/contents/student-age-studio-update.zip?ref='+'a'*40,url)
            payload_calls.append(url)
            return io.BytesIO(self.payload[:70] if len(payload_calls)==1 else self.payload)
        self.updater.opener=opener
        self.assertEqual(self.updater.check()['status'],'available')
        with patch('app_updates.time.sleep'):self.updater._download(self.updater.asset,self.release['tag_name'])
        self.assertEqual(self.updater.status()['status'],'ready')
        self.assertEqual(len(payload_calls),2)
        self.assertFalse(any('/releases?' in url for url in self.calls))

    def test_transfer_never_retries_integrity_failure(self):
        self.updater.check()
        self.updater.opener=lambda url:io.BytesIO(b'x'*len(self.payload))
        with patch.object(self.updater,'opener',wraps=self.updater.opener) as opener:
            self.updater._download(self.updater.asset,self.release['tag_name'])
            self.assertEqual(opener.call_count,1)
        self.assertEqual(self.updater.status()['status'],'error')
        self.assertFalse(read_state(self.updater.root).get('active'))

    def test_missing_fallback_does_not_hide_network_failure(self):
        import urllib.error
        self.updater.config['sourceUpdates']=True
        def opener(url):
            if 'raw.githubusercontent.com' in url:raise urllib.error.URLError('offline')
            raise urllib.error.HTTPError(url,404,'missing',{},None)
        self.updater.opener=opener
        with patch('app_updates.time.sleep'):result=self.updater.check()
        self.assertEqual(result['status'],'error')
        self.assertIn('已重试',result['message'])

    def test_source_feed_rejects_bad_commit_and_runtime(self):
        self.updater.config['sourceUpdates']=True
        feed={'format':1,'runtimeAbi':1,'version':'v1.3.1-beta.1','commit':'../main','size':10,'sha256':'a'*64}
        self.updater.opener=lambda url:io.BytesIO(json.dumps(feed).encode())
        self.assertEqual(self.updater.check()['status'],'error')
        feed.update(commit='a'*40,runtimeAbi=200)
        self.assertEqual(self.updater.check()['status'],'error')

    def test_newer_installer_cannot_be_downgraded_by_old_overlay(self):
        self.stage();self.updater.activate();(self.base/'error_logs.py').write_text("APP_VERSION='1.4.0'", encoding='utf-8')
        self.assertEqual(select_web(self.base,self.updater.root),self.base)
        self.assertFalse(read_state(self.updater.root).get('active'))

    def test_real_bootstrap_failure_restarts_into_builtin_version(self):
        import subprocess
        import update_bootstrap
        (self.base/'update_bootstrap.py').write_text(Path(update_bootstrap.__file__).read_text(encoding='utf-8'), encoding='utf-8')
        (self.base/'server.py').write_text("print('BUILTIN_BOOT_OK')", encoding='utf-8')
        self.stage();self.updater.activate()
        web=self.updater.root/'versions'/self.updater.staged/'standalone'
        (web/'server.py').write_text("raise RuntimeError('simulated startup failure')", encoding='utf-8')
        env={**os.environ,'STUDIO_USER_DATA_ROOT':str(self.root)}
        first=subprocess.run([sys.executable,'-B',str(self.base/'update_bootstrap.py')],env=env,capture_output=True,text=True)
        self.assertEqual(first.returncode,42,first.stderr)
        second=subprocess.run([sys.executable,'-B',str(self.base/'update_bootstrap.py')],env=env,capture_output=True,text=True)
        self.assertEqual(second.returncode,0,second.stderr);self.assertIn('BUILTIN_BOOT_OK',second.stdout)


    def test_automatic_recheck_preserves_downloaded_update(self):
        self.stage();identifier=self.updater.staged;calls=len(self.calls)
        self.assertEqual(self.updater.check()['status'],'ready')
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(self.updater.staged,identifier)
        self.updater.activate()
        self.assertEqual(read_state(self.updater.root)['active'],identifier)

    def test_license_notices_are_verified_and_preserved(self):
        destination=self.root/'unpacked'
        unpack_archive(io.BytesIO(archive(extra={'LICENSE':b'license notice','THIRD_PARTY_NOTICES.md':b'credit'})),destination,'1.3.1-beta.1')
        self.assertEqual((destination/'LICENSE').read_bytes(),b'license notice')
        self.assertEqual((destination/'THIRD_PARTY_NOTICES.md').read_bytes(),b'credit')

    def test_tls_context_keeps_verification_and_has_trust_roots(self):
        import ssl
        from app_updates import tls_context
        context=tls_context()
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()['x509_ca'],0)

    def test_versions(self):
        self.assertLess(version_key('beta-1.2.3'),version_key('v1.3.0-beta.1'))
        self.assertLess(version_key('1.3.0-beta.2'),version_key('1.3.0-rc.1'))
        self.assertLess(version_key('1.3.0-rc.1'),version_key('1.3.0'))
        self.assertLess(version_key('1.9.0'),version_key('1.10.0'))
        with self.assertRaises(ValueError):version_key('../../etc')

    def test_stage_activate_boot_health_and_rollback(self):
        mods=self.root/'Mods';mods.mkdir();(mods/'draft.json').write_text('keep me', encoding='utf-8')
        self.stage();self.assertEqual(read_state(self.updater.root),{})
        self.updater.activate();web=select_web(self.base,self.updater.root)
        self.assertNotEqual(web,self.base);self.assertEqual((web/'ui-assets/private.png').read_bytes(),b'private installed artwork')
        self.assertEqual((web/'update_bootstrap.py').read_text(encoding='utf-8'),'# stable bootstrap');self.assertFalse((web/'obsolete.js').exists())
        mark_healthy(self.updater.root);self.assertFalse(read_state(self.updater.root)['pending'])
        self.updater.running_id=os.environ['STUDIO_ACTIVE_UPDATE'];self.updater.activate(rollback=True)
        self.assertEqual(select_web(self.base,self.updater.root),self.base);self.assertEqual((mods/'draft.json').read_text(encoding='utf-8'),'keep me')

    def test_failed_boot_rolls_back(self):
        self.stage();self.updater.activate();select_web(self.base,self.updater.root)
        self.assertTrue(rollback_failed_start(self.updater.root));self.assertEqual(select_web(self.base,self.updater.root),self.base)

    def test_dead_pending_boot_rolls_back_on_next_launch(self):
        self.stage();self.updater.activate();select_web(self.base,self.updater.root)
        with patch('update_bootstrap.process_alive',return_value=False):self.assertEqual(select_web(self.base,self.updater.root),self.base)

    def test_other_live_pending_process_does_not_roll_back(self):
        self.stage();self.updater.activate();web=select_web(self.base,self.updater.root)
        with patch('update_bootstrap.process_alive',return_value=True):self.assertEqual(select_web(self.base,self.updater.root),web)

    def test_source_preview_never_selects_update(self):
        self.stage();self.updater.activate()
        with patch.dict(os.environ,{'STUDIO_UPDATE_MANAGED':'0'}):self.assertEqual(select_web(self.base,self.updater.root),self.base)
        self.updater.managed=False
        with self.assertRaises(ValueError):self.updater.activate()

    def test_hash_mismatch_never_activates(self):
        self.release['assets'][0]['digest']='sha256:'+'0'*64
        self.assertEqual(self.updater.check()['status'],'available');self.updater.download()
        for _ in range(200):
            if self.updater.status()['status']!='downloading':break
            time.sleep(.01)
        self.assertEqual(self.updater.status()['status'],'error');self.assertEqual(read_state(self.updater.root),{})

    def test_untrusted_asset_url_rejected(self):
        self.release['assets'][0]['browser_download_url']='https://evil.example/payload.zip'
        self.assertEqual(self.updater.check()['status'],'error');self.assertEqual(len(self.calls),1)

    def test_absent_digest_rejected(self):
        self.release['assets'][0]['digest']=None
        self.assertEqual(self.updater.check()['status'],'error')

    def test_prerelease_not_selected_for_stable(self):
        self.updater.config['channel']='stable';self.assertEqual(self.updater.check()['status'],'current')

    def test_path_traversal_and_bootstrap_replacement_rejected(self):
        for name in ['../escape.py','standalone/../escape.py','standalone/C:evil.py','standalone/update_bootstrap.py','standalone/update-channel.json','standalone/Mods/data.json','standalone/CON.py','standalone//evil.py']:
            with self.subTest(name=name),self.assertRaises(ValueError):unpack_archive(io.BytesIO(archive(extra={name:b'bad'})),self.root/'out','1.3.1-beta.1')
        self.assertFalse((self.root/'escape.py').exists())

    def test_incompatible_runtime_rejected(self):
        with self.assertRaises(ValueError):unpack_archive(io.BytesIO(archive(abi=2)),self.root/'out','1.3.1-beta.1')

    def test_duplicate_and_symlink_rejected(self):
        for symlink in (True,False):
            out=io.BytesIO(archive())
            with zipfile.ZipFile(out,'a') as z:
                info=zipfile.ZipInfo('standalone/link.py' if symlink else 'standalone/server.py');info.external_attr=(stat.S_IFLNK|0o777)<<16 if symlink else 0
                z.writestr(info,b'ignored')
            with self.assertRaises(ValueError):unpack_archive(io.BytesIO(out.getvalue()),self.root/'out','1.3.1-beta.1')

    def test_manifest_and_runtime_version_must_match_tag(self):
        with self.assertRaises(ValueError):unpack_archive(io.BytesIO(archive()),self.root/'out','1.3.2')

    def test_stale_window_cannot_override_activated_update(self):
        self.stage();self.updater.activate()
        with self.assertRaises(ValueError):self.updater.activate(rollback=True)


if __name__=='__main__':unittest.main()
