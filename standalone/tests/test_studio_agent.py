"""CLI/MCP core: every write goes through the editor's save and keeps the story connected."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import studio_agent
import studio_mcp


def studio_for(store):
    studio = studio_agent.Studio.__new__(studio_agent.Studio)
    studio.store = store
    return studio


class StudioAgentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='studio-agent-test-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        env = {k: str(root / v) for k, v in [('STUDIO_USER_DATA_ROOT', 'User'), ('STUDIO_CACHE_ROOT', 'Cache'), ('STUDIO_BACKUP_ROOT', 'Backups'),
                                             ('STUDIO_DISPLAY_SETTINGS', 'display.json'), ('STUDIO_ERROR_LOG_ROOT', 'Logs')]}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = server.StudioStore(root / 'Mods', root / 'Workshop', root / 'Game', asset_settings_path=root / 'assets.json', migrate_cache=False)
        self.mod = self.store.create('代理测试')['id']
        self.studio = studio_for(self.store)

    def test_create_edit_insert_delete_keep_the_story_connected(self):
        s, mod = self.studio, self.mod
        preview = s.create_event(mod, '预览', [{'text': '只预览'}], event_id=1500000, dry_run=True)
        self.assertTrue(preview['dryRun'])
        self.assertNotIn('1500000', self.store.load(mod)['events'])

        created = s.create_event(mod, '放学后', [
            {'speaker': '旁白', 'text': '教室里只剩下两个人。'},
            {'speaker': '主角', 'text': '要不要说？', 'options': [
                {'text': '说', 'lines': [{'text': '你开口了。'}]},
                {'text': '不说', 'lines': [{'text': '你沉默了。'}]}]},
            {'text': '铃声响了。'}], event_id=1500000, map_id=2)
        self.assertTrue(created['saved'])
        first, choice, said, silent, bell = 1500000001, 1500000002, 1500000003, 1500000004, 1500000005
        self.assertEqual(created['lineIds'], [first, choice, said, silent, bell])
        event = s.event(mod, 1500000)
        self.assertEqual(event['title'], '放学后')
        self.assertEqual(event['mapId'], 2)
        by_id = {line['id']: line for line in event['lines']}
        self.assertEqual(by_id[first]['speakerId'], studio_agent.NARRATOR)
        self.assertEqual(by_id[choice]['speakerId'], studio_agent.PROTAGONIST)
        self.assertEqual([o['goto'] for o in by_id[choice]['options']], [[said], [silent]])
        self.assertEqual(by_id[said]['next'], [bell])
        self.assertEqual(by_id[silent]['next'], [bell])
        owners = self.store.load(mod)['talkOwners']
        self.assertTrue(all(owners.get(str(t)) == [1500000] for t in created['lineIds']))

        inserted = s.add_lines(mod, 1500000, [{'text': '（插入的一句）'}], after=first)
        new = inserted['lineIds'][0]
        self.assertEqual(s.event(mod, 1500000)['lines'][1]['id'], new)
        self.assertEqual(s.line(mod, new)['next'], [choice])

        s.edit_line(mod, first, text='教室里只剩下你们两个人。')
        self.assertEqual(s.line(mod, first)['text'], '教室里只剩下你们两个人。')

        s.update_event(mod, 1500000, {'title': '放学后（改）', 'maxcount': 2})
        self.assertEqual(s.event(mod, 1500000)['maxcount'], 2)

        removed = s.delete_lines(mod, [new])
        self.assertEqual(removed['relinked'], [first])
        self.assertEqual(s.line(mod, first)['next'], [choice])

        s.delete_event(mod, 1500000)
        doc = self.store.load(mod)
        self.assertNotIn('1500000', doc['events'])
        self.assertFalse({str(t) for t in created['lineIds']} & {str(k) for k in doc['localIds'].get('talks', [])})

    def test_staging_follows_the_game_rules(self):
        s, mod = self.studio, self.mod
        cfgs = self.store.project(mod).path / 'Cfgs' / 'zh-cn'
        cfgs.mkdir(parents=True, exist_ok=True)
        (cfgs / 'BgCfg.json').write_text(json.dumps({'900': {'id': 900, 'url': 'bg/img_tiantai', 'cloth': [0]}}), encoding='utf-8')
        (cfgs / 'AudioCfg.json').write_text(json.dumps({'91': {'id': 91, 'name': '心动足迹', 'url': 'bgm/xindong', 'type': 1},
                                                        '92': {'id': 92, 'name': '铃声', 'url': 'sfx/ring', 'type': 2}}), encoding='utf-8')
        created = s.create_event(mod, '演出', [
            {'speaker': '主角', 'text': '一', 'enter': '中', 'expression': '害羞', 'music': '心动足迹'},
            {'speaker': '主角', 'text': '二', 'enter': '中'},
            {'speaker': '旁白', 'text': '三', 'background': 'tiantai', 'sound': '铃声'},
            {'speaker': '主角', 'text': '四', 'expression': '高兴'},
            {'speaker': '主角', 'text': '五', 'exit': ['主角']}], event_id=1600000)
        one, two, three, four, five = created['lineIds']
        talks = self.store.load(mod)['talks']
        self.assertEqual(talks[str(one)]['roles'], [[0, 1002, 1, 3, 0], [0, 3000, 4]])  # 中 is native axis 3
        self.assertEqual(talks[str(two)]['roles'], [])  # already standing there: no second entrance
        self.assertEqual(talks[str(three)]['bg'], 900)
        # The new background cleared the stage; an expression on someone off stage brings them back in.
        self.assertEqual(talks[str(four)]['roles'], [[0, 3000, 1]])
        self.assertEqual(talks[str(five)]['roles'], [[0, 2002, 0]])
        cues = self.store.load(mod)['audioCues']
        self.assertEqual(cues['sfx'][str(three)], [{'audioId': 92, 'volume': 1}])
        self.assertEqual([(g['audioId'], g['talkIds']) for g in cues['bgm']], [(91, [one, two, three, four, five])])
        self.assertEqual(talks[str(one)]['audio'], 91)

        # Lines inserted later continue from the stage as it stands: the protagonist is already in the middle.
        inserted = s.add_lines(mod, 1600000, [{'speaker': '主角', 'text': '一点五', 'enter': '中', 'expression': '微笑'}], after=one)
        self.assertEqual(self.store.load(mod)['talks'][str(inserted['lineIds'][0])]['roles'], [[0, 3000, 10]])

        s.edit_line(mod, one, enter='左')
        self.assertEqual(self.store.load(mod)['talks'][str(one)]['roles'], [[0, 1002, 1, 1, 0], [0, 3000, 4]])
        s.edit_line(mod, one, enter='无', expression='')
        self.assertEqual(self.store.load(mod)['talks'][str(one)]['roles'], [])
        s.set_music(mod, [four, five], None)
        self.assertEqual(self.store.load(mod)['audioCues']['bgm'][0]['talkIds'], [one, two, three])
        view = s.event(mod, 1600000)['lines']
        self.assertEqual(view[0]['musicStarts'], 91)
        self.assertIn('background', next(l for l in view if l['id'] == three))
        with self.assertRaises(studio_agent.AgentError):
            s.edit_line(mod, one, enter='上')
        self.assertEqual([i['name'] for i in s.assets(mod, 'music')['items']], ['心动足迹'])
        self.assertEqual(s.assets(mod, 'expressions', person='主角')['items'][4]['name'], '害羞')

    def test_errors_are_explained(self):
        with self.assertRaises(studio_agent.AgentError) as missing:
            self.studio.event(self.mod, 1)
        self.assertIn('找不到事件', missing.exception.message)
        with self.assertRaises(studio_agent.AgentError):
            self.studio.create_event(self.mod, '', [{'text': 'x'}])
        with self.assertRaises(studio_agent.AgentError) as speaker:
            self.studio.create_event(self.mod, '人物', [{'speaker': '不存在的人', 'text': 'x'}])
        self.assertIn('找不到名为', speaker.exception.message)
        with self.assertRaises(studio_agent.AgentError):
            self.studio.update_event(self.mod, 1, {'unknownField': 1})


class McpProtocolTests(unittest.TestCase):
    def test_initialize_list_and_unknown_tool(self):
        lines = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
                 {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                 {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                 {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'nope', 'arguments': {}}},
                 {'jsonrpc': '2.0', 'id': 4, 'method': 'ping'}]
        stdin = io.StringIO('\n'.join(json.dumps(m) for m in lines) + '\n')
        out = io.StringIO()
        saved = sys.stdout
        try:
            studio_mcp.serve(studio_mcp.argparse.Namespace(mods=None, game=None, workshop=None), stdin=stdin, stdout=out)
        finally:
            sys.stdout = saved
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([r['id'] for r in replies], [1, 2, 3, 4])  # the notification gets no reply
        self.assertEqual(replies[0]['result']['protocolVersion'], '2025-06-18')
        names = {t['name'] for t in replies[1]['result']['tools']}
        self.assertTrue({'list_mods', 'get_event', 'create_event', 'add_lines', 'delete_lines'} <= names)
        self.assertTrue(all(t['inputSchema']['type'] == 'object' for t in replies[1]['result']['tools']))
        self.assertEqual(replies[2]['error']['code'], -32602)
        self.assertEqual(replies[3]['result'], {})

    def test_self_check_and_install_prompt(self):
        with patch('sys.stdout', io.StringIO()) as out:
            code = studio_mcp.check(studio_mcp.argparse.Namespace(mods=None, game='/nonexistent-game', workshop=None))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())['ok'])
        commands = studio_mcp.launch_commands(Path(studio_mcp.__file__).parent)
        self.assertIn('--check', commands['check'])
        self.assertIn('student-age-studio', commands['prompt'])
        self.assertIn(commands['claudeCode'], commands['prompt'])
        with tempfile.TemporaryDirectory() as folder:
            target = studio_mcp.write_install_prompt(folder, Path(studio_mcp.__file__).parent)
            self.assertIn('list_mods', target.read_text(encoding='utf-8-sig'))


if __name__ == '__main__':
    unittest.main()
