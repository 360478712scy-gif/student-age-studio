import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
import backups

class BackupLocationTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='studio-backup-test-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.store=server.StudioStore(self.root/'Mods',self.root/'Workshop',self.root/'Game',asset_settings_path=self.root/'assets.json',backup_root=self.root/'Backups',migrate_cache=False)
        self.project=self.store.project(self.store.create('备份测试')['id'])
    def test_move_and_restart_preserves_old_and_new_snapshots(self):
        manager=self.store.backups
        manager.fixed_root=None
        manager.location_path=self.root/'user/backup-location.json'
        original=manager.create({'projectId':self.project.id,'requestId':'before_move'})
        manager.configure({'autoCleanup':False})
        target=(self.root/'新备份').resolve()
        result=manager.configure({'path':str(target)})
        self.assertFalse(result['autoCleanup'])
        self.assertTrue(Path(original['modPath']).is_dir())
        newer=manager.create({'projectId':self.project.id,'requestId':'after_move'})
        self.assertTrue(Path(newer['modPath']).is_relative_to(target))
        with patch.object(backups,'settings_path',return_value=self.root/'user/game.json'),patch.dict(os.environ,{'STUDIO_BACKUP_ROOT':''}):
            restarted=backups.ModBackups(self.store,manager.api)
            self.assertEqual(restarted.root,target)
            self.assertFalse(restarted.settings()['autoCleanup'])
        self.assertEqual(len(manager.status(self.project.id)['backups']),1)

    def test_invalid_destination_keeps_current_location_and_backup(self):
        manager=self.store.backups;old=manager.root
        original=manager.create({'projectId':self.project.id,'requestId':'safe_backup'})
        file=self.root/'file';file.write_text('keep')
        for target in ['', 'relative',str(self.root),str(self.store.mods),str(self.project.path/'Nested'),str(file),original['modPath']]:
            with self.assertRaises(Exception):manager.configure({'path':target})
            self.assertEqual(manager.root,old)
            self.assertTrue(Path(original['modPath']).is_dir())
        self.assertEqual(file.read_text(),'keep')

if __name__=='__main__':unittest.main()
