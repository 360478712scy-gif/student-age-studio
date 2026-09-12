# 发布与在线更新

## 首次客户端

1. 使用 Python 3.12 准备 requirements.txt 中的依赖（含 certifi 根证书集合），按照 README 从自己的游戏安装目录提取本地界面素材。可选 SDK 需按其自身许可另行准备。
2. Windows：`desktop/windows/build.ps1` 使用 `$env:STUDIO_BUILD_ROOT` 下的 `venv\Scripts\python.exe` 和 PyInstaller 打包，输出 WebView2 客户端。启动器需使用新 `Launcher.cs`：它在后端以退出码 42 结束时重启，并为客户端启用更新。直接运行旧版 `StudioEngine.exe` 不支持在线重启。
3. Mac：`desktop/package.py` 需要 `STUDIO_MAC_PYTHON_ROOT`、`STUDIO_MAC_DEPENDENCIES` 和新的 `STUDIO_APP_PATH`，生成 Apple Silicon 应用。WKWebView 宿主通过内置的 `update_bootstrap.py` 启动后端。运行环境升级时另建完整客户端，不复用旧客户端的 ABI。
4. 完整客户端含本机准备的第三方组件及游戏素材。公开仓库的 GPL 只覆盖原创编辑器代码；未经相应权利人许可，不应将这些私有素材随公开安装包再分发。公开自动构建使用不含这些素材的源码；客户端在用户选定游戏后于本机缓存准备界面素材。Releases 同时提供 Windows x64、Mac arm64 完整运行环境客户端与代码更新包。

首次 Windows 构建可在源码目录用 PowerShell 准备运行环境：

```powershell
$env:STUDIO_BUILD_ROOT = Join-Path $env:LOCALAPPDATA 'StudentAgeStudioBuild'
py -3.12 -m venv "$env:STUDIO_BUILD_ROOT\venv"
& "$env:STUDIO_BUILD_ROOT\venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
& "$env:STUDIO_BUILD_ROOT\venv\Scripts\python.exe" tools/prepare_game_ui.py --game '自己的游戏目录'
& ./desktop/windows/build.ps1
```

## 发布常规更新

1. 更新 `standalone/error_logs.py` 的 `APP_VERSION`，例如 `1.3.0-beta.4`。
2. 测试后将版本改动提交并推送到 main，工作流会为该版本生成标签并发布；也可手动推送匹配的 `v1.3.0-beta.4` 标签，或在 Actions 页面运行 `Publish code update`。
3. 工作流验证版本、运行更新器测试，生成 `student-age-studio-update.zip` 和 SHA-256 文本，并创建对应 GitHub Release。预发布后缀标为 prerelease；已有 Release 保持不变，修复时递增版本号。
4. 客户端通过发布列表寻找版本号更高的版本，包括 beta 通道的 prerelease；不能用仅返回正式版的 latest 接口。客户端强制检查 GitHub 附件的 `sha256:` digest、大小、下载仓库路径与包内逐文件清单。
5. 原生宿主、Python 或第三方依赖变化时，提升内置更新引导程序的 `RUNTIME_ABI`，先提供相应新客户端；旧客户端拒绝安装不兼容代码更新。

GitHub API 参考：[Releases](https://docs.github.com/en/rest/releases/releases)、[Release assets](https://docs.github.com/en/rest/releases/assets)。

## 更新边界与回退

- 更新只包含 standalone 顶层编辑器代码与自有图标，不包含游戏素材、运行库、更新引导程序或更新源配置。
- 更新目录为固定用户数据目录下的 `Updates`，与素材缓存和 Mods 分开。
- 下载、文件清单及校验全部完成后才建立新版本目录；保存所有草稿成功后才切换 active 指针并请求原生宿主重启。
- 上一版保留。启动抛出异常会回退后重启；未完成页面加载就异常退出，下次启动会回退。已成功打开但遇到功能问题，可手动回退。
- 不自动删除历史版本或覆盖安装目录；失败下载的临时目录会清理。
- 多窗口使用同一更新数据。另一窗口已切换版本时，旧窗口不能再次覆盖激活状态。
- 源码预览不会安装远程代码。仅客户端的稳定启动器启用该能力。

## 当前验证范围

更新器本地隔离测试包含版本排序、完整校验、目录穿越／链接／重复文件拒绝、运行环境兼容性、暂存与启用、实际子进程启动失败回退、旧在线版本不覆盖新安装包、用户数据保留。原生 Swift 通过类型检查；Windows 和 macOS 安装版升级仍须用实际客户端验收，不能把源码或浏览器测试当作发行应用验收。

## 自动打包客户端

`Build desktop clients` 在版本变更时使用 GitHub 的 Windows x64 与 macOS 14 arm64 环境构建。两端先检查打包后端启动、首页静态文件及在线更新接口，再压缩上传；Mac 另验证代码签名。Mac 使用 uv 管理的可搬移 Python 3.12，Windows 使用 PyInstaller 与原生启动器。Release 顶部提供两端下载入口，代码更新 ZIP 保留供程序读取。原生窗口完整交互和游戏联调需另行验收。
