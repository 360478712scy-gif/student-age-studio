# 给 AI 助手：接入「拾光工坊」MCP（学生时代模组编辑器）

请为用户接入拾光工坊的 MCP 服务。编辑器已经自带这个服务，找到启动命令、写进客户端配置即可，一般几分钟内完成。

## 不要做
- 不要安装 Python、pip、Node 包，不要克隆仓库，也不要自己编写 MCP 服务。
- 不要用 npx、uvx、docker 或 HTTP/SSE 方式，它是 stdio 服务。
- 不要去掉环境变量 `STUDIO_UPDATE_MANAGED=1`：少了它，服务不会使用编辑器的最新版本。
- 自检失败时，不要换别的方法反复尝试，把报错原文告诉用户即可。

## 最快的方法：用编辑器生成的提示词
编辑器会按用户电脑上的实际路径生成一份完整提示词，照着做就行：
- **任何系统**：请用户打开编辑器的「工坊设置 → 外观与偏好 → AI 工具」，点「复制安装提示词」发给你。
- **Windows**：编辑器文件夹里（和「拾光工坊.exe」放在一起）有「AI安装MCP提示词.txt」。编辑器至少启动过一次才会生成，直接读取它即可。

拿到提示词后按它的步骤执行，下面的内容可以跳过。

## 自己找启动命令
### Windows
1. 找到用户解压的编辑器文件夹，也就是包含「拾光工坊.exe」和 `runtime` 文件夹的那一个。可以问用户放在哪里，或者搜索 `StudioEngine.exe`。
2. 启动命令是 `<编辑器文件夹>\runtime\StudioEngine.exe`，参数为 `--server-only --mcp`，环境变量为 `STUDIO_UPDATE_MANAGED=1`。
3. 在 PowerShell 中自检：
   ```powershell
   $env:STUDIO_UPDATE_MANAGED='1'; & "<编辑器文件夹>\runtime\StudioEngine.exe" --server-only --mcp --check
   ```

### Mac
1. 编辑器位于 `/Applications/拾光工坊.app` 或 `~/Applications/拾光工坊.app`。
2. 启动命令是 `<App>/Contents/Resources/python/bin/python3`，参数为 `-B <App>/Contents/Resources/standalone/update_bootstrap.py --mcp`，环境变量为 `STUDIO_UPDATE_MANAGED=1`、`PYTHONNOUSERSITE=1`。
3. 自检：
   ```bash
   STUDIO_UPDATE_MANAGED=1 PYTHONNOUSERSITE=1 "<App>/Contents/Resources/python/bin/python3" -B "<App>/Contents/Resources/standalone/update_bootstrap.py" --mcp --check
   ```

### 源码运行（开发者）
```bash
python3 -B standalone/studio_mcp.py --check
```

自检输出 `"ok": true` 表示服务正常。把自检命令里的 `--check` 换成 `--print-prompt`，会输出填好本机路径的完整提示词。

## 写进客户端配置
服务名写 `student-age-studio`，方式选 stdio，填入上面的命令、参数和环境变量。
- **Claude Code**：`claude mcp add student-age-studio -e STUDIO_UPDATE_MANAGED=1 -- <命令> <参数…>`
- **Codex**（`~/.codex/config.toml`）：
  ```toml
  [mcp_servers.student-age-studio]
  command = "<命令>"
  args = ["<参数1>", "<参数2>"]
  env = { STUDIO_UPDATE_MANAGED = "1" }
  ```
- **Cursor、Claude 桌面版、Cline、Roo Code、Windsurf、Cherry Studio、Gemini CLI 等**：在 `mcpServers` 中加入下面这一项。如果已有其他服务，只加这一项，不要覆盖。JSON 里 Windows 路径的反斜杠要写成 `\\`。
  ```json
  {"mcpServers": {"student-age-studio": {"command": "<命令>", "args": ["<参数…>"], "env": {"STUDIO_UPDATE_MANAGED": "1"}}}}
  ```
- **DeepSeek 桌面版（DSH）**：编辑 DSH 数据目录下的 `harness/profiles/web/cordis.patch.yml`，把这一项加入列表：
  ```yaml
  - insert:
      - id: student-age-studio-mcp
        name: '@deepseek-ai/dsh-mcp-client'
        config:
          transport: stdio
          serverName: student-age-studio
          command: "<命令>"
          args: ["<参数…>"]
          env: { STUDIO_UPDATE_MANAGED: '1' }
          toolCallTimeoutMs: 120000
  ```
  DSH 数据目录：Mac 为 `~/Library/Application Support/dsh-desktop/`，Windows 为 `%APPDATA%\dsh-desktop\`。

## 验证
重启或重新加载客户端，然后调用 `list_mods` 工具。能看到模组列表就完成了，告诉用户已经可以读写模组剧情。
