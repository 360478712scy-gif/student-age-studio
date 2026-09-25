"""拾光工坊 MCP server (stdio). Lets AI assistants read and edit mods through the editor's own logic.

Register it with an MCP client, for example:
    claude mcp add student-age-studio -- python3 /path/to/standalone/studio_mcp.py
Optional: --mods / --game / --workshop override the editor's saved locations.

Protocol: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP stdio transport). stdout carries protocol
messages only; any library output is redirected to stderr. No third-party dependency.
"""
import argparse
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SERVER_INFO = {'name': 'student-age-studio', 'title': '拾光工坊 · 学生时代模组编辑器', 'version': '1.0.0'}
PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')

INSTRUCTIONS = """拾光工坊（学生时代模组编辑器）的 MCP 工具，用编辑器自身的逻辑读写模组。
使用要点：
1. 先用 list_mods 找到模组（之后 mod 参数写编号或唯一名称即可）；订阅模组只读。
2. 修改剧情前先用 get_event / list_events / search_lines 了解现状；说话人可写人物名、编号、"旁白"(-1) 或 "主角"(0)，不确定时用 list_persons。
3. 写入工具都支持 dry_run 预览。保存由编辑器完成：会检查版本冲突、保存前自动备份；若返回 code=save_warnings，请把警告告诉用户，确认后把 warnings 原样放进 confirm 再调用一次。
4. 编写事件条件/效果前先用 list_commands 查模板：每条条件/效果是一个数组，按 template 与 parameters 填写。
5. 编辑器窗口开着时也能用；若编辑器里有未保存的修改，之后编辑器保存时会提示冲突，请提醒用户先保存或刷新。"""

LINE_SCHEMA = {
    'type': 'object', 'required': ['text'],
    'properties': {
        'speaker': {'description': '说话人：人物名称、人物编号、"旁白"(-1) 或 "主角"(0)。省略即旁白。', 'type': ['string', 'integer']},
        'text': {'type': 'string', 'description': '台词或旁白文字'},
        'displayName': {'type': 'string', 'description': '可选：覆盖显示的名字'},
        'enter': {'type': 'integer', 'enum': [1, 2, 3], 'description': '可选：该人物在这句登场，位置 1 左 / 2 中 / 3 右'},
        'options': {'type': 'array', 'description': '可选：这句之后出现玩家选项。各分支结束后默认接回下一句主线',
                    'items': {'type': 'object', 'required': ['text'], 'properties': {
                        'text': {'type': 'string', 'description': '选项文字'},
                        'lines': {'type': 'array', 'description': '选择后的对话（同本结构，可嵌套选项）', 'items': {'type': 'object'}},
                        'condition': {'type': 'array', 'description': '可选：选项出现条件（条件数组）'},
                        'effect': {'type': 'array', 'description': '可选：选择后执行的效果（效果数组）'}}}},
        'rejoin': {'type': 'boolean', 'description': '有选项时，分支结束后是否接回下一句主线（默认 true）'},
    }}
MOD = {'type': 'string', 'description': '模组编号或唯一名称（见 list_mods）'}
WRITE = {'dry_run': {'type': 'boolean', 'description': '只预览，不写入'},
         'confirm': {'type': 'array', 'items': {'type': 'string'}, 'description': '确认保存警告：传回上次返回的 warnings'}}


def tool(name, description, properties, required=(), read_only=True):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
            'annotations': {'readOnlyHint': read_only, 'destructiveHint': not read_only and name.startswith('delete'), 'idempotentHint': read_only}}


TOOLS = [
    tool('list_mods', '列出所有模组：编号、名称、来源、是否只读。', {}),
    tool('mod_summary', '模组概况：各类自有内容数量、当前版本号、读取警告。', {'mod': MOD}, ['mod']),
    tool('list_events', '列出事件（默认只列模组自己的），含名称、类型、关联人物、地点和首句。',
         {'mod': MOD, 'query': {'type': 'string', 'description': '按编号、名称或首句过滤'}, 'include_original': {'type': 'boolean'},
          'limit': {'type': 'integer', 'default': 50}, 'offset': {'type': 'integer', 'default': 0}}, ['mod']),
    tool('get_event', '查看一个事件的设置（类型、条件、效果、次数等）和按阅读顺序排列的全部对话与选项分支。', {'mod': MOD, 'event_id': {'type': 'integer'}}, ['mod', 'event_id']),
    tool('get_line', '查看一句对话的完整记录与所属事件。', {'mod': MOD, 'talk_id': {'type': 'integer'}}, ['mod', 'talk_id']),
    tool('search_lines', '按文字搜索对话。', {'mod': MOD, 'text': {'type': 'string'}, 'include_original': {'type': 'boolean'}, 'limit': {'type': 'integer', 'default': 50}}, ['mod', 'text']),
    tool('list_persons', '列出可用人物及编号（旁白 = -1，主角 = 0）。', {'mod': MOD, 'query': {'type': 'string'}, 'limit': {'type': 'integer', 'default': 100}}, ['mod']),
    tool('list_commands', '条件/效果模板目录。编写事件或选项的 condition/effect 前先查这里。',
         {'mod': MOD, 'kind': {'type': 'string', 'enum': ['condition', 'effect']}, 'query': {'type': 'string'}, 'limit': {'type': 'integer', 'default': 60}}, ['mod', 'kind']),
    tool('read_table', '读取任意配置表（如 ItemCfg、ActionCfg、PersonGrowCfg），默认只返回模组自己的记录。',
         {'mod': MOD, 'name': {'type': 'string'}, 'ids': {'type': 'array', 'items': {'type': ['string', 'integer']}}, 'query': {'type': 'string'},
          'include_original': {'type': 'boolean'}, 'limit': {'type': 'integer', 'default': 50}}, ['mod', 'name']),
    tool('create_event', '新建剧情事件及其全部对话（可含选项分支）。编号自动分配，对话编号为 事件号×1000+序号。',
         {'mod': MOD, 'title': {'type': 'string'}, 'lines': {'type': 'array', 'items': LINE_SCHEMA},
          'type': {'type': 'integer', 'default': 1, 'description': '事件类型编号'}, 'npc': {'type': ['string', 'integer'], 'description': '关联人物'},
          'map_id': {'type': 'integer', 'default': 0, 'description': '地点编号，0 为不限'}, 'rate': {'type': 'number', 'default': 1, 'description': '触发概率 0–1'},
          'maxcount': {'type': 'integer', 'default': 1}, 'condition': {'type': 'array'}, 'effect': {'type': 'array'},
          'event_id': {'type': 'integer', 'description': '可选：指定事件编号'}, **WRITE}, ['mod', 'title', 'lines'], False),
    tool('add_lines', '在事件中插入对话（默认接在主线末尾；after 指定插在某句之后）。',
         {'mod': MOD, 'event_id': {'type': 'integer'}, 'lines': {'type': 'array', 'items': LINE_SCHEMA}, 'after': {'type': 'integer'}, **WRITE},
         ['mod', 'event_id', 'lines'], False),
    tool('edit_line', '修改一句对话的文字、说话人或显示名。',
         {'mod': MOD, 'talk_id': {'type': 'integer'}, 'text': {'type': 'string'}, 'speaker': {'type': ['string', 'integer']},
          'display_name': {'type': 'string'}, **WRITE}, ['mod', 'talk_id'], False),
    tool('delete_lines', '删除对话，并把前后自动接上，事件不会断开。', {'mod': MOD, 'talk_ids': {'type': 'array', 'items': {'type': 'integer'}}, **WRITE}, ['mod', 'talk_ids'], False),
    tool('update_event', '修改事件字段：title、type、npc、mapId、rate、maxcount、condition、effect 等。',
         {'mod': MOD, 'event_id': {'type': 'integer'}, 'fields': {'type': 'object'}, **WRITE}, ['mod', 'event_id', 'fields'], False),
    tool('delete_event', '删除模组自己的事件；只属于它的对话由编辑器一并清理。原版事件不能删除。', {'mod': MOD, 'event_id': {'type': 'integer'}, **WRITE}, ['mod', 'event_id'], False),
    tool('update_rows', '新增或修改配置表记录（不含对话与选项，它们请用剧情工具）。rows 为 {编号: {字段: 值}}，只需写要改的字段。',
         {'mod': MOD, 'name': {'type': 'string'}, 'rows': {'type': 'object'}, **WRITE}, ['mod', 'name', 'rows'], False),
    tool('backup_mod', '立即完整备份模组（与编辑器“手动备份”相同）。', {'mod': MOD}, ['mod'], False),
]


def launch_commands(web_root):
    """Commands that start the CLI and MCP server with this installation's own runtime."""
    web_root = Path(web_root).resolve()
    if getattr(sys, 'frozen', False):  # Windows client: the engine runs bundled scripts as workers
        mcp, cli = [sys.executable, '--extract', 'studio_mcp'], [sys.executable, '--extract', 'studio_cli']
    else:
        mcp, cli = [sys.executable, '-B', str(web_root / 'studio_mcp.py')], [sys.executable, '-B', str(web_root / 'studio_cli.py')]
    def shell(parts):
        return ' '.join(f'"{p}"' if (' ' in p or not p) else p for p in parts)
    return {'mcp': mcp, 'cli': cli,
            'claudeCode': 'claude mcp add student-age-studio -- ' + shell(mcp),
            'codex': '[mcp_servers.student-age-studio]\ncommand = ' + json.dumps(mcp[0]) + '\nargs = ' + json.dumps(mcp[1:], ensure_ascii=False),
            'json': {'mcpServers': {'student-age-studio': {'command': mcp[0], 'args': mcp[1:]}}},
            'cliExample': shell(cli) + ' mods'}


class Handler:
    def __init__(self, options):
        self.options, self.studio = options, None

    def get_studio(self):
        if self.studio is None:
            import studio_agent
            self.studio = studio_agent.Studio(mods=self.options.mods, game=self.options.game, workshop=self.options.workshop)
        return self.studio

    def call(self, name, a):
        s = self.get_studio()
        w = {'dry_run': bool(a.get('dry_run')), 'confirm': a.get('confirm')}
        table = {
            'list_mods': lambda: s.mods(),
            'mod_summary': lambda: s.summary(a['mod']),
            'list_events': lambda: s.events(a['mod'], a.get('query'), bool(a.get('include_original')), a.get('limit', 50), a.get('offset', 0)),
            'get_event': lambda: s.event(a['mod'], a['event_id']),
            'get_line': lambda: s.line(a['mod'], a['talk_id']),
            'search_lines': lambda: s.search(a['mod'], a['text'], bool(a.get('include_original')), a.get('limit', 50)),
            'list_persons': lambda: s.persons(a['mod'], a.get('query'), a.get('limit', 100)),
            'list_commands': lambda: s.commands(a['mod'], a['kind'], a.get('query'), a.get('limit', 60)),
            'read_table': lambda: s.table(a['mod'], a['name'], a.get('ids'), a.get('query'), not a.get('include_original'), a.get('limit', 50)),
            'create_event': lambda: s.create_event(a['mod'], a['title'], a['lines'], a.get('type', 1), a.get('npc', 0), a.get('map_id', 0),
                                                   a.get('rate', 1), a.get('maxcount', 1), a.get('condition'), a.get('effect'), a.get('event_id'), **w),
            'add_lines': lambda: s.add_lines(a['mod'], a['event_id'], a['lines'], a.get('after'), **w),
            'edit_line': lambda: s.edit_line(a['mod'], a['talk_id'], a.get('text'), a.get('speaker'), a.get('display_name'), **w),
            'delete_lines': lambda: s.delete_lines(a['mod'], a['talk_ids'], **w),
            'update_event': lambda: s.update_event(a['mod'], a['event_id'], a['fields'], **w),
            'delete_event': lambda: s.delete_event(a['mod'], a['event_id'], **w),
            'update_rows': lambda: s.update_rows(a['mod'], a['name'], a['rows'], **w),
            'backup_mod': lambda: s.backup(a['mod']),
        }
        if name not in table:
            raise KeyError(name)
        return table[name]()

    def handle(self, message):
        method, ident, params = message.get('method'), message.get('id'), message.get('params') or {}
        if method == 'initialize':
            requested = params.get('protocolVersion')
            return {'protocolVersion': requested if requested in PROTOCOLS else PROTOCOLS[0],
                    'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': SERVER_INFO, 'instructions': INSTRUCTIONS}
        if method == 'ping':
            return {}
        if method == 'tools/list':
            return {'tools': TOOLS}
        if method == 'tools/call':
            import studio_agent
            name, arguments = params.get('name'), params.get('arguments') or {}
            try:
                result = self.call(name, arguments)
                return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}],
                        'structuredContent': result if isinstance(result, dict) else {'items': result}, 'isError': False}
            except KeyError as error:
                if name not in [t['name'] for t in TOOLS]:
                    raise JsonRpcError(-32602, f'未知工具：{name}')
                text = f'缺少参数：{error}'
            except studio_agent.AgentError as error:
                payload = {'error': error.message, 'code': error.code, **({'warnings': error.warnings} if error.warnings else {})}
                return {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}], 'structuredContent': payload, 'isError': True}
            except Exception as error:  # report, never crash the session
                traceback.print_exc(file=sys.stderr)
                text = f'操作未完成：{type(error).__name__}: {error}'
            return {'content': [{'type': 'text', 'text': text}], 'isError': True}
        raise JsonRpcError(-32601, f'不支持的方法：{method}')


class JsonRpcError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def serve(options, stdin=None, stdout=None):
    stdin = stdin or sys.stdin
    out = stdout or sys.stdout
    sys.stdout = sys.stderr  # protocol channel stays clean
    handler = Handler(options)
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            out.write(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': '无法解析的 JSON'}}) + '\n'); out.flush()
            continue
        if 'id' not in message:  # notification (e.g. notifications/initialized)
            continue
        try:
            response = {'jsonrpc': '2.0', 'id': message['id'], 'result': handler.handle(message)}
        except JsonRpcError as error:
            response = {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': error.code, 'message': error.message}}
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            response = {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32603, 'message': str(error)}}
        out.write(json.dumps(response, ensure_ascii=False) + '\n'); out.flush()


def main(argv=None):
    p = argparse.ArgumentParser(description='拾光工坊 MCP 服务（stdio）')
    p.add_argument('--mods'); p.add_argument('--game'); p.add_argument('--workshop')
    serve(p.parse_args(argv))


if __name__ == '__main__':
    main()
