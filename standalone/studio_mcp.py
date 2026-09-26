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

SERVER_INFO = {'name': 'student-age-studio', 'title': '拾光工坊 · 学生时代模组编辑器', 'version': '1.2.0'}
PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')

INSTRUCTIONS = """拾光工坊（学生时代模组编辑器）的 MCP 工具，用编辑器自身的逻辑读写模组。
使用要点：
1. 先用 list_mods 找到模组（之后 mod 参数写编号或唯一名称即可）；订阅模组只读。
2. 修改剧情前先用 get_event / list_events / search_lines 了解现状；说话人可写人物名、编号、"旁白"(-1) 或 "主角"(0)，不确定时用 list_persons。
3. 写入工具都支持 dry_run 预览。保存由编辑器完成：会检查版本冲突、保存前自动备份；若返回 code=save_warnings，请把警告告诉用户，确认后把 warnings 原样放进 confirm 再调用一次。
4. 编写事件条件/效果前先用 list_commands 查模板：每条条件/效果是一个数组，按 template 与 parameters 填写。
5. 编辑器窗口开着时也能用；若编辑器里有未保存的修改，之后编辑器保存时会提示冲突，请提醒用户先保存或刷新。
6. 演出（立绘站位、表情、背景、音乐、音效）写在每句对话里，素材编号先用 list_assets 查：
   - enter 写 "左"/"中"/"右"：人物在这句登场或换位置。已经站在那里的人物不会重复登场，所以只在第一次出场或换位置时写。
   - expression 写表情名（如 "害羞"）或编号；exit 写要退场的人物。
   - background 换背景。按游戏规则，换背景会让所有人物退场，换背景后的第一句要重新写 enter。
   - music 从这句开始播放背景音乐，直到下一个写了 music 的句子；sound 在这句播放音效。
   - 已有的句子用 edit_line 修改演出，用 set_music 给一段对话设置背景音乐。
   - 没写任何动作的句子，游戏会让说话人自动登场；写了动作的句子只执行写出的动作，工具会自动补上说话人的登场。
7. 分支：set_options 增删改玩家选项；edit_line 的 next 改跳转、check + next_if_failed 做条件分支、cg 显示插图、effect 写本句效果。
8. 其他内容（物品、人物、目标、短信、企鹅动态、商店……）：describe_table 看字段含义，read_table 读，update_rows 改或删除。
9. 事件外对话（送礼、闲聊、小游戏开场、CG 回忆等）：list_assets(kind="dialogue_uses") 查用途，create_external_dialogue 新建。
10. 改完用 check_mod 检查断开的连接。其他工具都做不到的，最后才用 json_file 直接改 JSON 原文。
不确定怎么做时，调用 read_guide 读完整使用说明。"""

STAGE = {
    'enter': {'type': 'string', 'description': '可选：说话人在这句登场或移动到 "左"/"中"/"右"。已站在该位置时不会重复登场'},
    'expression': {'type': 'string', 'description': '可选：说话人的表情，写名称（如 "害羞"、"微笑"）或编号，见 list_assets(kind="expressions")'},
    'expressions': {'type': 'object', 'description': '可选：其他在场人物的表情，如 {"小雅": "高兴"}'},
    'exit': {'type': 'array', 'items': {'type': 'string'}, 'description': '可选：在这句退场的人物（名称或编号）'},
    'background': {'type': 'string', 'description': '可选：从这句起换成的背景（编号或名称，见 list_assets）。换背景会让在场人物全部退场'},
    'sound': {'type': 'string', 'description': '可选：这句播放的音效（编号或名称，见 list_assets(kind="sounds")）'},
    'actions': {'type': 'array', 'items': {'type': 'array'}, 'description': '高级：原版动作数组 [人物, 动作编号, 参数…]。如 [["小雅", 3001, 1, 0, 1]] 跳跃；[["小雅", 3012]] 变成黑影、[["小雅", 3013]] 取消黑影；[["小雅", 3003, 1.5, 0]] 调整为当前的 1.5 倍大小（需玩家安装 UP 非官方补丁，否则原版固定放大 1.1 倍）'},
}
LINE_SCHEMA = {
    'type': 'object', 'required': ['text'],
    'properties': {
        'speaker': {'type': 'string', 'description': '说话人：人物名称、人物编号（如 "3"）、"旁白" 或 "主角"。省略即旁白。'},
        'text': {'type': 'string', 'description': '台词或旁白文字'},
        'displayName': {'type': 'string', 'description': '可选：覆盖显示的名字'},
        **STAGE,
        'music': {'type': 'string', 'description': '可选：从这句开始播放的背景音乐（编号或名称，见 list_assets(kind="music")），持续到下一个写了 music 的句子'},
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
            'inputSchema': {'type': 'object', 'properties': properties, **({'required': list(required)} if required else {})},
            'annotations': {'readOnlyHint': read_only, 'destructiveHint': not read_only and name.startswith('delete'), 'idempotentHint': read_only}}


TOOLS = [
    tool('read_guide', '读取拾光工坊 AI 使用说明：工作流程、剧情结构、演出规则、各工具用法与常见错误。第一次使用或不确定怎么做时先读。', {}),
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
         {'mod': MOD, 'name': {'type': 'string'}, 'ids': {'type': 'array', 'items': {'type': 'string'}, 'description': '记录编号列表'}, 'query': {'type': 'string'},
          'include_original': {'type': 'boolean'}, 'limit': {'type': 'integer', 'default': 50}}, ['mod', 'name']),
    tool('create_event', '新建剧情事件及其全部对话（可含选项分支）。编号自动分配，对话编号为 事件号×1000+序号。',
         {'mod': MOD, 'title': {'type': 'string'}, 'lines': {'type': 'array', 'items': LINE_SCHEMA},
          'type': {'type': 'integer', 'default': 1, 'description': '事件类型编号'}, 'npc': {'type': 'string', 'description': '关联人物：名称或编号'},
          'map_id': {'type': 'integer', 'default': 0, 'description': '地点编号，0 为不限'}, 'rate': {'type': 'number', 'default': 1, 'description': '触发概率 0–1'},
          'maxcount': {'type': 'integer', 'default': 1}, 'condition': {'type': 'array'}, 'effect': {'type': 'array'},
          'event_id': {'type': 'integer', 'description': '可选：指定事件编号'}, **WRITE}, ['mod', 'title', 'lines'], False),
    tool('add_lines', '在事件中插入对话（默认接在主线末尾；after 指定插在某句之后）。',
         {'mod': MOD, 'event_id': {'type': 'integer'}, 'lines': {'type': 'array', 'items': LINE_SCHEMA}, 'after': {'type': 'integer'}, **WRITE},
         ['mod', 'event_id', 'lines'], False),
    tool('edit_line', '修改一句对话：文字、说话人、显示名、演出（登场位置、表情、退场、背景、音效、CG）、跳转、条件分支和本句效果。只改传入的项。'
         'enter 写 "无" 取消登场；expression 写空字符串取消表情；sound 写 "无" 取消音效；actions 会整体替换这句的动作。',
         {'mod': MOD, 'talk_id': {'type': 'integer'}, 'text': {'type': 'string'}, 'speaker': {'type': 'string', 'description': '新的说话人：名称、编号、旁白或主角'},
          'display_name': {'type': 'string'}, **{k: v for k, v in STAGE.items() if k != 'expressions'},
          'cg': {'type': 'string', 'description': '从这句显示 CG（编号或名称，见 list_assets(kind="cgs")）；"end" 结束 CG；"无" 去掉'},
          'next': {'type': 'integer', 'description': '这句之后跳到哪句（对话编号）；0 表示到此结束'},
          'check': {'type': 'array', 'items': {'type': 'array'}, 'description': '判定条件（条件数组，见 list_commands）：显示这句后判定，满足走 next，不满足走 next_if_failed；传 [] 取消'},
          'next_if_failed': {'type': 'integer', 'description': '判定不满足时跳到的对话编号'},
          'effect': {'type': 'array', 'items': {'type': 'array'}, 'description': '这句执行的效果（效果数组，见 list_commands）；传 [] 清空'}, **WRITE}, ['mod', 'talk_id'], False),
    tool('set_options', '设置一句对话之后的玩家选项（整体替换）。每个选项写 text，并用 goto 跳到已有对话，或用 lines 新写选择后的对话；'
         '保留原有选项时带上它的 id。options 传空数组表示去掉选项。新写的分支对话结束后接到 rejoin_to（默认是这句原来的下一句）。',
         {'mod': MOD, 'talk_id': {'type': 'integer'}, 'options': {'type': 'array', 'items': {'type': 'object', 'required': ['text'], 'properties': {
             'id': {'type': 'integer', 'description': '已有选项编号（保留并修改）'}, 'text': {'type': 'string'},
             'goto': {'type': 'integer', 'description': '跳到已有对话编号'}, 'lines': {'type': 'array', 'items': LINE_SCHEMA, 'description': '新写的分支对话'},
             'condition': {'type': 'array', 'description': '选项出现条件'}, 'effect': {'type': 'array', 'description': '选择后的效果'}}}},
          'rejoin_to': {'type': 'integer', 'description': '新分支对话结束后接到的对话编号'}, **WRITE}, ['mod', 'talk_id', 'options'], False),
    tool('set_music', '给一段对话设置背景音乐（覆盖这些句子原来的音乐范围）；不写 music 则清除。通常传从开始到结束的连续对话编号。',
         {'mod': MOD, 'line_ids': {'type': 'array', 'items': {'type': 'integer'}}, 'music': {'type': 'string', 'description': '音乐编号或名称'},
          'loop': {'type': 'boolean', 'default': True}, 'volume': {'type': 'number', 'default': 1, 'description': '0–1'}, **WRITE}, ['mod', 'line_ids'], False),
    tool('list_assets', '查编号：背景（backgrounds）、背景音乐（music）、音效（sounds）、人物表情（expressions，需 person）、CG（cgs）、地点（maps）、事件类型（event_types）、事件外对话用途（dialogue_uses）。',
         {'mod': MOD, 'kind': {'type': 'string', 'enum': ['backgrounds', 'music', 'sounds', 'expressions', 'cgs', 'maps', 'event_types', 'dialogue_uses']}, 'query': {'type': 'string'},
          'person': {'type': 'string', 'description': '查表情时的人物名称或编号'}, 'limit': {'type': 'integer', 'default': 40}}, ['mod', 'kind']),
    tool('delete_lines', '删除对话，并把前后自动接上，事件不会断开。', {'mod': MOD, 'talk_ids': {'type': 'array', 'items': {'type': 'integer'}}, **WRITE}, ['mod', 'talk_ids'], False),
    tool('update_event', '修改事件字段：title、type、npc、mapId、rate、maxcount、condition、effect 等。',
         {'mod': MOD, 'event_id': {'type': 'integer'}, 'fields': {'type': 'object'}, **WRITE}, ['mod', 'event_id', 'fields'], False),
    tool('delete_event', '删除模组自己的事件；只属于它的对话由编辑器一并清理。原版事件不能删除。', {'mod': MOD, 'event_id': {'type': 'integer'}, **WRITE}, ['mod', 'event_id'], False),
    tool('update_rows', '新增、修改或删除配置表记录（对话、选项、事件请用剧情工具）。rows 为 {编号: {字段: 值}}，只需写要改的字段；'
         'delete 为要删除的本模组记录编号。字段含义先用 describe_table 查。短信（PhoneMsgCfg）会按短信界面的规则检查。',
         {'mod': MOD, 'name': {'type': 'string'}, 'rows': {'type': 'object'}, 'delete': {'type': 'array', 'items': {'type': 'integer'}}, **WRITE}, ['mod', 'name'], False),
    tool('describe_table', '不写 name：列出游戏的全部配置表及中文名。写 name：每个字段的含义、类型、默认值和引用的表。', {'mod': MOD, 'name': {'type': 'string'}}, ['mod']),
    tool('create_mod', '新建一个空的本地模组；写 copy_from 则复制已有模组（包括订阅模组）为本地副本。', {'name': {'type': 'string'}, 'copy_from': {'type': 'string', 'description': '要复制的模组编号或名称'}}, ['name'], False),
    tool('import_asset', '把本机的图片或音频导入模组：背景（background）、CG（cg）、人物立绘（portrait）、背景音乐（music）、音效（sound）。返回新素材编号。',
         {'mod': MOD, 'kind': {'type': 'string', 'enum': ['background', 'cg', 'portrait', 'music', 'sound']}, 'file_path': {'type': 'string', 'description': '本机文件的完整路径'},
          'name': {'type': 'string'}, 'person': {'type': 'string', 'description': '立绘：人物名称或编号；不写则新建人物'}, 'face': {'type': 'integer', 'description': '立绘：表情编号，默认 0'},
          'cloth': {'type': 'integer', 'description': '立绘：服装编号 0–9'}, 'grade': {'type': 'integer', 'description': '立绘：1 小学、2 中学'}}, ['mod', 'kind', 'file_path'], False),
    tool('check_mod', '检查模组：JSON 语法错误、指向不存在对话的跳转和选项、不存在的说话人、没有首句的事件。改完后建议运行一次。', {'mod': MOD}, ['mod']),
    tool('json_file', '最后手段：不写 path 列出模组的 JSON 文件；写 path 读取原文；再写 text 与 confirm_overwrite=true 则整体替换该文件（会备份、检查版本冲突）。',
         {'mod': MOD, 'path': {'type': 'string', 'description': '如 Cfgs/zh-cn/ItemCfg.json'}, 'text': {'type': 'string'}, 'confirm_overwrite': {'type': 'boolean'}}, ['mod'], False),
    tool('list_external_dialogues', '列出事件外对话夹：名称、句数、首句和绑定的用途（送礼、闲聊、小游戏开场等）。', {'mod': MOD}, ['mod']),
    tool('create_external_dialogue', '新建事件外对话夹（不属于任何事件的连续对话），并可绑定游戏里的播放位置。用途种类与所需参数见 list_assets(kind="dialogue_uses")，'
         '如 {"kind": "gift", "npc": "肖清雅", "item": 1000001}。',
         {'mod': MOD, 'name': {'type': 'string'}, 'lines': {'type': 'array', 'items': LINE_SCHEMA},
          'uses': {'type': 'array', 'items': {'type': 'object', 'required': ['kind'], 'properties': {
              'kind': {'type': 'string'}, 'npc': {'type': 'string'}, 'item': {'type': 'integer'}, 'level': {'type': 'integer'}, 'giftMode': {'type': 'integer'},
              'recordId': {'type': 'integer'}, 'answer': {'type': 'string'}, 'gender': {'type': 'string', 'enum': ['both', 'male', 'female']}, 'params': {'type': 'object'}}}},
          **WRITE}, ['mod', 'name', 'lines'], False),
    tool('backup_mod', '立即完整备份模组（与编辑器“手动备份”相同）。', {'mod': MOD}, ['mod'], False),
]


def launch_commands(web_root):
    """Commands that start the CLI and MCP server with this installation's own runtime.

    Installed clients go through their stable launcher, which picks the current update, so the
    command survives editor updates. A source checkout runs the scripts directly."""
    import os
    web_root = Path(web_root).resolve()
    managed = os.environ.get('STUDIO_UPDATE_MANAGED') == '1'
    env = {'STUDIO_UPDATE_MANAGED': '1'} if managed else {}
    if getattr(sys, 'frozen', False):  # Windows client engine
        base = [sys.executable, '--server-only']
    elif managed:  # Mac client: bundled Python + the app's own update bootstrap
        env['PYTHONNOUSERSITE'] = '1'
        base = [sys.executable, '-B', str(Path(os.environ.get('STUDIO_BASE_WEB') or web_root) / 'update_bootstrap.py')]
    else:
        base = None
    mcp = base + ['--mcp'] if base else [sys.executable, '-B', str(web_root / 'studio_mcp.py')]
    cli = base + ['--cli'] if base else [sys.executable, '-B', str(web_root / 'studio_cli.py')]

    def shell(parts):
        return ' '.join(f'"{p}"' if (' ' in p or not p) else p for p in parts)
    env_flags = ''.join(f' -e {k}={v}' for k, v in env.items())
    codex = '[mcp_servers.student-age-studio]\ncommand = ' + json.dumps(mcp[0]) + '\nargs = ' + json.dumps(mcp[1:], ensure_ascii=False)
    if env:
        codex += '\nenv = { ' + ', '.join(f'{k} = {json.dumps(v)}' for k, v in env.items()) + ' }'
    server = {'command': mcp[0], 'args': mcp[1:], **({'env': env} if env else {})}
    env_prefix = (' '.join(f'{k}={v}' for k, v in env.items()) + ' ') if env and os.name != 'nt' else ''
    if os.name == 'nt':  # agents on Windows usually run PowerShell; cmd needs its own form
        check = ''.join(f"$env:{k}='{v}'; " for k, v in env.items()) + '& ' + shell(mcp + ['--check'])
        check_cmd = ''.join(f'set {k}={v}&& ' for k, v in env.items()) + shell(mcp + ['--check'])
    else:
        check = check_cmd = env_prefix + shell(mcp + ['--check'])
    result = {'mcp': mcp, 'cli': cli, 'env': env,
              'claudeCode': 'claude mcp add student-age-studio' + env_flags + ' -- ' + shell(mcp),
              'codex': codex, 'json': {'mcpServers': {'student-age-studio': server}},
              'cliExample': env_prefix + shell(cli) + ' mods', 'check': check, 'checkCmd': check_cmd}
    result['prompt'] = install_prompt(result)
    result['promptFile'] = bool(getattr(sys, 'frozen', False) and os.name == 'nt')
    return result


def install_prompt(c):
    """Step-by-step instructions an AI agent can follow to connect itself, with this computer's exact commands."""
    server = c['json']['mcpServers']['student-age-studio']
    yaml_env = ''.join(f"\n        env: {{ {k}: '{v}' }}" for k, v in c['env'].items())
    yaml = ("- insert:\n    - id: student-age-studio-mcp\n      name: '@deepseek-ai/dsh-mcp-client'\n      config:\n        transport: stdio\n"
            f"        serverName: student-age-studio\n        command: {json.dumps(server['command'], ensure_ascii=False)}\n"
            f"        args: {json.dumps(server['args'], ensure_ascii=False)}{yaml_env}\n        toolCallTimeoutMs: 120000")
    return f"""# 给 AI 助手：接入「拾光工坊」MCP（学生时代模组编辑器）

请为用户接入拾光工坊的 MCP 服务。下面的命令和配置已经按这台电脑生成好，直接照做即可，一般两分钟内完成。

## 不要做
- 不要安装 Python、pip、Node 包，不要克隆仓库，也不要自己编写 MCP 服务：编辑器已经自带，下面的命令就是它。
- 不要改动命令路径和参数，不要去掉环境变量（如果有）。
- 不要用 npx、uvx、docker 或 HTTP/SSE 方式，它是 stdio 服务。
- 第 1 步失败时，不要换别的方法反复尝试，把报错原文告诉用户即可。

## 第 1 步：确认服务能启动
在终端运行下面这条命令，几秒内会输出一段 JSON 并自动退出：

{c['check']}
{'''
（上面是 PowerShell 写法；如果终端是 cmd，用这一条：）
''' + c['checkCmd'] + '''
''' if c['checkCmd'] != c['check'] else ''}
输出里有 "ok": true 就说明服务正常。

## 第 2 步：写进你所在客户端的 MCP 配置
- 服务名：student-age-studio
- 方式：stdio
- 命令：{server['command']}
- 参数：{json.dumps(server['args'], ensure_ascii=False)}
- 环境变量：{json.dumps(c['env'], ensure_ascii=False) if c['env'] else '无'}

按你自己是哪个客户端，只做其中一种：

**Claude Code**：在终端运行
{c['claudeCode']}

**Codex**：追加到 ~/.codex/config.toml 末尾
{c['codex']}

**Cursor、Claude 桌面版、Cline、Roo Code、Windsurf、Cherry Studio、Gemini CLI 等使用 mcpServers 的客户端**：把下面的 JSON 合并进客户端的 MCP 配置文件（已有 mcpServers 时只加入 student-age-studio 这一项，不要覆盖其他服务）。Windows 路径里的反斜杠已经转义好，请原样复制：
{json.dumps(c['json'], ensure_ascii=False, indent=2)}

常见配置文件位置：Cursor 为 ~/.cursor/mcp.json；Claude 桌面版为「设置 → 开发者 → 编辑配置」打开的 claude_desktop_config.json；Gemini CLI 为 ~/.gemini/settings.json；Cline、Roo Code、Cherry Studio 在各自的 MCP 设置界面中编辑。

**DeepSeek 桌面版（DSH）**：编辑 DSH 数据目录下的 harness/profiles/web/cordis.patch.yml（Mac 为 ~/Library/Application Support/dsh-desktop/，Windows 为 %APPDATA%\\dsh-desktop\\）。文件里只有 [] 时整行替换为下面内容；已有其他条目时把这一项加进列表：
{yaml}

## 第 3 步：重启客户端并验证
重启或重新加载客户端后，调用 student-age-studio 的 list_mods 工具，能看到模组列表就完成了。告诉用户：已接入，可以让你读写模组剧情了。

## 之后怎么用
服务连接后会带使用说明，先调用 list_mods、get_event 了解模组，再修改。写入前可用 dry_run 预览；遇到 save_warnings 先把警告告诉用户，用户确认后再传 confirm。
"""


class Handler:
    def __init__(self, options):
        self.options, self.studio = options, None

    def get_studio(self):
        if self.studio is None:
            import studio_agent
            self.studio = studio_agent.Studio(mods=self.options.mods, game=self.options.game, workshop=self.options.workshop)
        return self.studio

    def call(self, name, a):
        s = None if name == 'read_guide' else self.get_studio()
        w = {'dry_run': bool(a.get('dry_run')), 'confirm': a.get('confirm')}
        if name == 'read_guide':  # needs no mod data
            import ai_guide
            return {'guide': ai_guide.GUIDE}
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
            'edit_line': lambda: s.edit_line(a['mod'], a['talk_id'], a.get('text'), a.get('speaker'), a.get('display_name'), **w,
                                             **{k: a.get(k) for k in ('background', 'enter', 'expression', 'exit', 'sound', 'actions', 'effect', 'cg', 'check', 'next_if_failed')},
                                             goto=a.get('next')),
            'set_options': lambda: s.set_options(a['mod'], a['talk_id'], a['options'], a.get('rejoin_to'), **w),
            'describe_table': lambda: s.describe_table(a['mod'], a.get('name')),
            'create_mod': lambda: s.create_mod(a['name'], a.get('copy_from')),
            'import_asset': lambda: s.import_asset(a['mod'], a['kind'], a['file_path'], a.get('name'), a.get('person'), a.get('face', 0), a.get('cloth', 0), a.get('grade', 1)),
            'check_mod': lambda: s.check_mod(a['mod']),
            'json_file': lambda: s.json_file(a['mod'], a.get('path'), a.get('text'), bool(a.get('confirm_overwrite'))),
            'list_external_dialogues': lambda: s.external_dialogues(a['mod']),
            'create_external_dialogue': lambda: s.create_external_dialogue(a['mod'], a['name'], a['lines'], a.get('uses'), **w),
            'set_music': lambda: s.set_music(a['mod'], a['line_ids'], {'id': a['music'], 'loop': a.get('loop', True), 'volume': a.get('volume', 1)}
                                             if a.get('music') not in (None, '') else None, **w),
            'list_assets': lambda: s.assets(a['mod'], a['kind'], a.get('query'), a.get('person'), a.get('limit', 40)),
            'delete_lines': lambda: s.delete_lines(a['mod'], a['talk_ids'], **w),
            'update_event': lambda: s.update_event(a['mod'], a['event_id'], a['fields'], **w),
            'delete_event': lambda: s.delete_event(a['mod'], a['event_id'], **w),
            'update_rows': lambda: s.update_rows(a['mod'], a['name'], a.get('rows'), **w, delete=a.get('delete')),
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
        if method in ('resources/list', 'resources/templates/list', 'prompts/list'):
            # Some clients ask regardless of the advertised capabilities; answer with nothing.
            return {method.split('/')[0] if method != 'resources/templates/list' else 'resourceTemplates': []}
        if method == 'tools/call':
            import studio_agent
            name, arguments = params.get('name'), params.get('arguments') or {}
            if name not in {t['name'] for t in TOOLS}:  # before touching any mod data
                raise JsonRpcError(-32602, f'未知工具：{name}')
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
    for stream in (sys.stdin, sys.stdout):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', newline='\n' if stream is sys.stdout else None)  # Windows defaults to the ANSI code page
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
        batch = isinstance(message, list)  # JSON-RPC batches (protocol 2025-03-26)
        replies = [reply for reply in (respond(handler, item) for item in (message if batch else [message])) if reply is not None]
        if replies:
            out.write(json.dumps(replies if batch else replies[0], ensure_ascii=False) + '\n'); out.flush()


def respond(handler, message):
    if not isinstance(message, dict):
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': '无效的请求'}}
    if 'id' not in message:  # notification (e.g. notifications/initialized)
        return None
    try:
        return {'jsonrpc': '2.0', 'id': message['id'], 'result': handler.handle(message)}
    except JsonRpcError as error:
        return {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': error.code, 'message': error.message}}
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        return {'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32603, 'message': str(error)}}


def check(options):
    """One-shot self test for installers: start like a client would, list mods, report, exit."""
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        handler = Handler(options)
        init = handler.handle({'method': 'initialize', 'params': {'protocolVersion': PROTOCOLS[0]}})
        mods = handler.call('list_mods', {})
        report = {'ok': True, 'server': init['serverInfo']['version'], 'tools': len(TOOLS), 'mods': len(mods),
                  'message': '服务正常。把启动命令写进 AI 客户端的 MCP 配置后重启客户端即可。'}
    except Exception as error:
        message = getattr(error, 'message', None) or f'{type(error).__name__}: {error}'
        report = {'ok': False, 'error': message, 'message': '服务未能读取模组。请先打开一次编辑器完成设置，或用 --game/--mods 指定目录。'}
    finally:
        sys.stdout = real_stdout
    for stream in (sys.stdout,):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


def write_install_prompt(directory, web_root):
    """Keep an up-to-date install prompt and usage guide next to the installed client, for users to hand to their AI."""
    import ai_guide
    written = None
    for name, text in (('AI安装MCP提示词.txt', launch_commands(web_root)['prompt']), ('AI使用说明.md', ai_guide.GUIDE)):
        try:
            target = Path(directory) / name
            data = text.replace('\n', '\r\n' if sys.platform == 'win32' else '\n').encode('utf-8-sig')
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
            written = written or target
        except OSError:
            pass
    return written


def main(argv=None):
    p = argparse.ArgumentParser(description='拾光工坊 MCP 服务（stdio）')
    p.add_argument('--mods'); p.add_argument('--game'); p.add_argument('--workshop')
    p.add_argument('--check', action='store_true', help='自检：像客户端一样启动并列出模组，输出结果后退出')
    p.add_argument('--print-config', action='store_true', help='输出本机的接入命令与配置（JSON）')
    p.add_argument('--print-prompt', action='store_true', help='输出给 AI 助手看的安装提示词')
    options = p.parse_args(argv)
    if options.check:
        raise SystemExit(check(options))
    if options.print_config or options.print_prompt:
        commands = launch_commands(Path(__file__).resolve().parent)
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print(commands['prompt'] if options.print_prompt else json.dumps(commands, ensure_ascii=False, indent=2))
        return
    serve(options)


if __name__ == '__main__':
    main()
