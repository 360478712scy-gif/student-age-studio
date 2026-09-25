# AI 工具：命令行与 MCP

拾光工坊提供命令行工具（`standalone/studio_cli.py`）和 MCP 服务（`standalone/studio_mcp.py`），让 Claude、Codex 等 AI 助手直接读取和修改模组剧情。

两者在进程内调用编辑器自己的后端逻辑，不单独写配置文件，所以保存行为和在编辑器里手动编辑完全一致：

- 读取的是和编辑器相同的数据（模组内容加原版内容）。
- 每次写入都基于当前版本：如果模组在此期间被编辑器、游戏或其他窗口修改过，会拒绝保存，而不是覆盖。
- 保存前自动备份，并沿用编辑器的编号规则、对话归属和前提整理。
- 编辑器检查出警告时不会直接写入，而是先把警告交给调用方，确认后才保存。
- 所有写入命令都可以先用预览（`--dry-run` / `dry_run`）查看会改哪些表。
- 订阅模组只读，只有本地模组可以修改。

## 接入 AI 助手

最简单的方法：打开编辑器的「工坊设置 → 外观与偏好 → AI 工具」，复制为本机生成的命令或配置。更新编辑器后路径可能变化，届时重新复制即可。

- **Claude Code**：在终端运行一次设置页里的 `claude mcp add student-age-studio -- …`。
- **Claude 桌面版等支持 `mcpServers` 的客户端**：把设置页里的 JSON 合并到客户端的 MCP 配置中。
- **Codex**：把设置页里的内容粘贴到 `~/.codex/config.toml`。

设置页生成的命令会通过安装版自带的固定入口启动，编辑器更新后仍然有效：

- Windows 安装版：`StudioEngine.exe --server-only --mcp`，需要设置环境变量 `STUDIO_UPDATE_MANAGED=1`（设置页复制的配置已包含），不需要另装 Python。
- Mac 安装版：App 自带的 Python 运行 App 内的 `update_bootstrap.py --mcp`，同样需要设置 `STUDIO_UPDATE_MANAGED=1`。
- 源码运行：`python3 -B /path/to/standalone/studio_mcp.py`。

任何支持 MCP（stdio 方式，即填写一条启动命令）的 AI 客户端都可以使用，例如 Claude、Codex、Cursor、Cline、Gemini CLI、Cherry Studio 等。

默认使用编辑器保存的游戏与模组目录；`--mods`、`--game`、`--workshop` 可以覆盖。

## MCP 工具

| 工具 | 作用 |
|---|---|
| `list_mods` | 列出模组（编号、名称、是否只读） |
| `mod_summary` | 模组概况与当前版本 |
| `list_events` / `get_event` | 列出事件；查看事件设置与按阅读顺序排列的对话、选项 |
| `get_line` / `search_lines` | 查看一句对话；按文字搜索 |
| `list_persons` | 人物与编号（旁白 = -1，主角 = 0） |
| `list_commands` | 条件/效果模板，用于编写 condition 和 effect |
| `read_table` | 读取任意配置表 |
| `create_event` | 新建事件及全部对话，可包含选项分支 |
| `add_lines` | 在事件中插入对话 |
| `edit_line` | 修改台词、说话人或显示名 |
| `delete_lines` | 删除对话并自动接上前后 |
| `update_event` / `delete_event` | 修改或删除事件 |
| `update_rows` | 新增或修改配置表记录（对话与选项请用剧情工具） |
| `backup_mod` | 立即完整备份 |

### 对话写法

```json
[
  {"speaker": "旁白", "text": "放学后，教室里只剩下你们两个人。"},
  {"speaker": "梁超杰", "text": "喂，你周末有空吗？", "enter": 3},
  {"speaker": "主角", "text": "（要答应他吗？）", "options": [
    {"text": "答应", "lines": [{"speaker": "梁超杰", "text": "太好了！"}]},
    {"text": "拒绝", "lines": [{"speaker": "梁超杰", "text": "……好吧。"}]}
  ]},
  {"speaker": "旁白", "text": "上课铃响了。"}
]
```

- `speaker` 可以写人物名称、人物编号、`旁白` 或 `主角`。省略时默认为旁白。
- `enter` 表示该人物在这句登场，取值 1 左 / 2 中 / 3 右。
- 带 `options` 的句子之后出现玩家选项。每个分支的对话结束后，默认接回下一句主线；设置 `"rejoin": false` 时，分支结束即事件结束。
- 事件编号自动分配；对话编号为 `事件号×1000+序号`，按阅读顺序排列。

## 命令行

输出均为 JSON。退出码：0 表示成功，1 表示出错，2 表示有保存警告需要确认（把返回的 `warnings` 用 `--confirm` 传回即可）。

```
python3 studio_cli.py mods
python3 studio_cli.py events "我的模组" -q 放学
python3 studio_cli.py event "我的模组" 1234567
python3 studio_cli.py create-event "我的模组" --title 放学后 --lines @lines.json --map 2 --dry-run
python3 studio_cli.py add-lines "我的模组" 1234567 --lines '[{"speaker":"旁白","text":"……"}]' --after 1234567002
python3 studio_cli.py edit-line "我的模组" 1234567001 --text "新的台词"
python3 studio_cli.py delete-lines "我的模组" 1234567003
python3 studio_cli.py commands "我的模组" condition -q 好感
```

`--lines`、`--set`、`--rows`、`--condition`、`--effect` 都接受三种写法：直接写 JSON、`@文件`、或 `-`（从标准输入读取）。

## 与编辑器同时使用

编辑器开着时也可以使用这些工具。如果编辑器里还有未保存的修改，之后在编辑器里保存时会提示「模组已被其他窗口修改」，不会悄悄覆盖。建议先在编辑器里保存，再让 AI 修改；AI 改完后，在编辑器里重新打开模组即可看到结果。
