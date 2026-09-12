# 拾光工坊 · StudentAge Studio

《学生时代》的独立模组编辑器。使用本地 Python 服务与网页界面，桌面客户端分别使用 Windows WebView2 和 macOS WKWebView。

支持剧情与分支、人物、场景和 CG、条件与效果、配置编辑、JSON 侧栏、撤销和备份。模组及素材在本机处理。

## 从源码运行

需要 Python 3.12 或以上。Windows 桌面窗口另需 WebView2 Evergreen Runtime；Mac 原生窗口需要 Xcode Command Line Tools。

```sh
python -m venv .venv
# 激活 .venv 后：
python -m pip install -r requirements.txt
python -B standalone/server.py
```

服务会输出仅供本机访问的地址，包含本次会话令牌。在浏览器中打开该地址，在工坊设置里选择自己的游戏及模组目录。不要将会话令牌分享给其他人。

Mac 原生源码窗口：`python -B desktop/run-source.py`。
Windows 原生源码窗口：`python -B desktop/windows/main.py`。

公开源码不包含原游戏图片、字体和 Live2D SDK。`tools/prepare_game_ui.py --game 游戏目录` 可从本机游戏准备界面素材；这些文件保留在本机，勿提交到仓库。缺少可选 SDK 时，部分动态立绘功能不可用。参见 [第三方说明](THIRD_PARTY_NOTICES.md)。

## 在线更新

带更新能力的客户端在启动后检查 GitHub Releases，也可在 **工坊设置 → 版本与反馈** 手动检查。

1. 点击“下载更新”，下载期间可以继续编辑。
2. 下载完成后点击“保存并重启更新”。保存失败会取消重启。
3. 更新保存到固定用户数据目录的 `Updates/versions`，不覆盖模组、缓存或原安装目录。
4. 新版本启动失败时回退；也可在相同位置选择“恢复上一版本”。原安装目录仍保留内置版本。

现有 b1.2.3 及更早客户端没有更新引导程序，必须先安装一次新客户端。在线更新覆盖编辑器代码和界面，支持相同运行环境 ABI 的后续版本；Python、原生宿主或第三方运行库变化需要新的完整客户端。本仓库目前的自动发布产物是代码更新 ZIP，不是首次安装包。

默认更新源由内置 `standalone/update-channel.json` 固定。Fork 项目后应在构建客户端前改为自己的仓库。

## 发布与贡献

使用 GPL-3.0-only，允许使用、修改及商用；分发修改版本时须遵守 GPL 的源码提供等要求，见 [LICENSE](LICENSE)。

发布流程及首次客户端构建见 [发布说明](docs/open-source-release.md)。提交前至少运行：

```sh
python -B -m unittest discover -s standalone/tests -p test_app_updates.py
python -B tools/build_update.py --out release/student-age-studio-update.zip
```

请勿提交游戏原始数据、用户模组、机器路径、缓存、密钥或带私人内容的截图。报告问题时请删除私人内容，并描述操作步骤、版本、系统与主题。
