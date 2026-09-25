"""拾光工坊命令行：读取和修改模组剧情，供脚本与 AI 使用。

    python studio_cli.py mods
    python studio_cli.py event "我的模组" 1234567
    python studio_cli.py create-event "我的模组" --title 放学后 --lines lines.json --dry-run

Output is JSON. Writes go through the editor's own save (revision check, warnings, backup);
add --dry-run to preview what would change. Exit code 0 = ok, 1 = error, 2 = warnings need --confirm.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _json_arg(value, label):
    """Inline JSON, @file, or - for stdin."""
    if value is None:
        return None
    text = sys.stdin.read() if value == '-' else Path(value[1:]).expanduser().read_text(encoding='utf-8') if value.startswith('@') else value
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise SystemExit(json.dumps({'error': f'{label} 不是有效的 JSON：{error}'}, ensure_ascii=False))


def parser():
    p = argparse.ArgumentParser(prog='studio_cli', description='拾光工坊命令行：读取和修改模组剧情。输出为 JSON。')
    p.add_argument('--mods', help='模组目录（默认使用编辑器保存的设置）')
    p.add_argument('--game', help='游戏目录（默认使用编辑器保存的设置）')
    p.add_argument('--workshop', help='创意工坊目录（默认使用编辑器保存的设置）')
    p.add_argument('--compact', action='store_true', help='单行 JSON 输出')
    sub = p.add_subparsers(dest='command', required=True)

    def cmd(name, help_text):
        c = sub.add_parser(name, help=help_text, description=help_text)
        return c

    def writes(c):
        c.add_argument('--dry-run', action='store_true', help='只预览会修改哪些表，不写入')
        c.add_argument('--confirm', help='确认保存警告：传回上一次返回的 warnings（JSON 数组，或 @文件）')

    cmd('mods', '列出所有模组（编号、名称、是否只读）')
    c = cmd('summary', '模组概况：自有内容数量与当前版本'); c.add_argument('mod')
    c = cmd('events', '列出事件（默认只列模组自己的）'); c.add_argument('mod'); c.add_argument('-q', '--query')
    c.add_argument('--all', action='store_true', help='包含原版事件'); c.add_argument('--limit', type=int, default=50); c.add_argument('--offset', type=int, default=0)
    c = cmd('event', '查看一个事件：设置与按阅读顺序排列的全部对话、选项'); c.add_argument('mod'); c.add_argument('event_id')
    c = cmd('line', '查看一句对话的完整记录'); c.add_argument('mod'); c.add_argument('talk_id')
    c = cmd('search', '按文字搜索对话'); c.add_argument('mod'); c.add_argument('text'); c.add_argument('--all', action='store_true', help='包含原版对话'); c.add_argument('--limit', type=int, default=50)
    c = cmd('persons', '列出人物（旁白 = -1，主角 = 0）'); c.add_argument('mod'); c.add_argument('-q', '--query'); c.add_argument('--limit', type=int, default=100)
    c = cmd('commands', '条件/效果模板目录，用来编写事件的 condition 与 effect'); c.add_argument('mod'); c.add_argument('kind', choices=['condition', 'effect']); c.add_argument('-q', '--query'); c.add_argument('--limit', type=int, default=60)
    c = cmd('table', '读取任意配置表（物品、行动、人物成长……）'); c.add_argument('mod'); c.add_argument('name'); c.add_argument('--ids', nargs='*'); c.add_argument('-q', '--query')
    c.add_argument('--all', action='store_true', help='包含原版记录'); c.add_argument('--limit', type=int, default=50)

    c = cmd('create-event', '新建事件及其对话。--lines 为对话数组 JSON：[{"speaker":"人物名|编号|旁白|主角","text":"…","enter":1-3,"options":[{"text":"选项","lines":[…]}]}]')
    c.add_argument('mod'); c.add_argument('--title', required=True); c.add_argument('--lines', required=True, help='JSON、@文件或 -（标准输入）')
    c.add_argument('--type', type=int, default=1, help='事件类型编号（默认 1）'); c.add_argument('--npc', default='0', help='关联人物（名称或编号）')
    c.add_argument('--map', type=int, default=0, help='地点编号（0 = 不限）'); c.add_argument('--rate', type=float, default=1); c.add_argument('--maxcount', type=int, default=1)
    c.add_argument('--condition', help='触发条件 JSON 数组'); c.add_argument('--effect', help='事件效果 JSON 数组'); c.add_argument('--event-id', help='指定事件编号（默认自动分配）'); writes(c)
    c = cmd('add-lines', '在事件中插入对话（默认接在主线末尾）'); c.add_argument('mod'); c.add_argument('event_id'); c.add_argument('--lines', required=True)
    c.add_argument('--after', help='插在这句对话之后'); writes(c)
    c = cmd('edit-line', '修改一句对话的文字或说话人'); c.add_argument('mod'); c.add_argument('talk_id'); c.add_argument('--text'); c.add_argument('--speaker'); c.add_argument('--display-name'); writes(c)
    c = cmd('delete-lines', '删除对话，并把前后自动接上'); c.add_argument('mod'); c.add_argument('talk_ids', nargs='+'); writes(c)
    c = cmd('update-event', '修改事件字段，--set 为 JSON 对象，如 {"title":"新名称","maxcount":2}'); c.add_argument('mod'); c.add_argument('event_id'); c.add_argument('--set', required=True, dest='fields'); writes(c)
    c = cmd('delete-event', '删除模组自己的事件（仅属于它的对话一并删除）'); c.add_argument('mod'); c.add_argument('event_id'); writes(c)
    c = cmd('update-rows', '新增或修改配置表记录，--rows 为 {编号: {字段: 值}}'); c.add_argument('mod'); c.add_argument('name'); c.add_argument('--rows', required=True); writes(c)
    c = cmd('backup', '立即完整备份模组'); c.add_argument('mod')
    return p


def run(args):
    import studio_agent
    studio = studio_agent.Studio(mods=args.mods, game=args.game, workshop=args.workshop)
    w = lambda: {'dry_run': getattr(args, 'dry_run', False), 'confirm': _json_arg(getattr(args, 'confirm', None), 'confirm')}
    c = args.command
    if c == 'mods': return studio.mods()
    if c == 'summary': return studio.summary(args.mod)
    if c == 'events': return studio.events(args.mod, args.query, args.all, args.limit, args.offset)
    if c == 'event': return studio.event(args.mod, args.event_id)
    if c == 'line': return studio.line(args.mod, args.talk_id)
    if c == 'search': return studio.search(args.mod, args.text, args.all, args.limit)
    if c == 'persons': return studio.persons(args.mod, args.query, args.limit)
    if c == 'commands': return studio.commands(args.mod, args.kind, args.query, args.limit)
    if c == 'table': return studio.table(args.mod, args.name, args.ids, args.query, not args.all, args.limit)
    if c == 'create-event':
        return studio.create_event(args.mod, args.title, _json_arg(args.lines, 'lines'), args.type, args.npc, args.map, args.rate, args.maxcount,
                                   _json_arg(args.condition, 'condition'), _json_arg(args.effect, 'effect'), args.event_id, **w())
    if c == 'add-lines': return studio.add_lines(args.mod, args.event_id, _json_arg(args.lines, 'lines'), args.after, **w())
    if c == 'edit-line': return studio.edit_line(args.mod, args.talk_id, args.text, args.speaker, args.display_name, **w())
    if c == 'delete-lines': return studio.delete_lines(args.mod, args.talk_ids, **w())
    if c == 'update-event': return studio.update_event(args.mod, args.event_id, _json_arg(args.fields, 'set'), **w())
    if c == 'delete-event': return studio.delete_event(args.mod, args.event_id, **w())
    if c == 'update-rows': return studio.update_rows(args.mod, args.name, _json_arg(args.rows, 'rows'), **w())
    if c == 'backup': return studio.backup(args.mod)
    raise SystemExit('未知命令：' + c)


def main(argv=None):
    args = parser().parse_args(argv)
    # Library code may print diagnostics; keep stdout for the JSON result only.
    real_stdout, sys.stdout = sys.stdout, sys.stderr
    try:
        import studio_agent
        try:
            result, code = run(args), 0
        except studio_agent.AgentError as error:
            result = {'error': error.message, 'code': error.code, **({'warnings': error.warnings} if error.warnings else {})}
            code = 2 if error.code == 'save_warnings' else 1
        except Exception as error:  # still answer in JSON so scripts and agents can read it
            import traceback
            traceback.print_exc(file=sys.stderr)
            result, code = {'error': f'{type(error).__name__}: {error}', 'code': 'internal_error'}, 1
    finally:
        sys.stdout = real_stdout
    print(json.dumps(result, ensure_ascii=False, indent=None if args.compact else 2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
