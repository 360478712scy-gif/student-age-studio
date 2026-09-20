# PR #5 发布功能修复验收

日期：2026-09-21。分支：`codex/pr5-publish`，工作树 `student-age-studio-pr5`。

保留若心知（ruoxingzhi）原提交；先合并主线 `578f284`，再修复审查问题。没有合入 main、发布新版本或创建真实 Steam 工坊条目。

## 已通过

- 29 项 Python 回归：macOS 4.275 秒，Windows 11 11.661 秒。覆盖原校验、素材暂存变化、保存锁、重复提交、取消后的任务槽、关闭期间 native 生命周期、损坏绑定、创建结果不明、创建失败重试、成功后绑定恢复、缓存封面、64 位 ID、提交成功回调完成语义及 DLL 哈希/回调结构。
- Windows 11 原生 WebView2 完整编辑器：从实际工坊主页按钮进入；预检、填写信息、更换封面、创建模拟条目、显示上传进度、成功结果、恢复为更新已有条目；17 位 ID 未被 JS 截断，页面无 JS 异常。
- 原生窗口三种配色（glass / glass-dusk / glass-moon）截图；窄窗口无横向溢出。封面采用 contain，保留完整图片；窗口底色不透出主页文字。
- Windows 实际已安装游戏的 Valve DLL + 解码后的 MIT DLL 加载成功，所需导出/签名声明与回调注册成功。没有调用真实 CreateItem/SubmitItemUpdate。
- 轻量更新包 190 个文件，使用 origin/main 的旧 `app_updates.py` 验证并解压通过；含完整 DLL 资源、MIT 许可证和固定 SHA-256。包 SHA-256：`74a41d75d7c393801df90fdc31c0cdd20f3de30b3a61a4247b4fe74e532fec96`。
- Python 编译、改动 JS 语法和 git diff 空白检查通过。

## 必须区分的验证边界

真实 Steam 只做只读加载/初始化探测：首次初始化成功，后续部分启动返回 steam_init_failed，因此不认定真实会话稳定或真实上传通过。最终独立 DLL 加载检查通过。

UI 验收只在隔离的 Windows QA 源码副本注入假远端 bridge，使用真实前端、HTTP API、暂存和状态机。仓库产品代码没有模拟开关。截图的「Steam 已连接」「上传完成」是模拟接口状态，不是真实工坊发布证据。

合入前仍需要有权发布的真实测试账号/模组完成新建私密条目、更新、法律协议、断网和退出时上传等远端验证。此次没有构建新的 Windows 安装包或 macOS 完整包；构建规则已修复，运行库交付链通过轻量包及 Windows 源码原生窗口验证。

## 证据入口

本地 `output/pr5/`：

- `windows-qa.py`：原生窗口验收入口，环境隔离在 `C:\StudentAgePR5QA`；不会修改用户模组或实际发布。
- `windows-ui-results.json`、`windows-native-load.json`、`package-results.json`。
- `windows-publish-ready.png`、`windows-publish-uploading.png`、`windows-publish-done.png`。
- `windows-publish-glass.png`、`windows-publish-glass-moon.png`、`windows-publish-narrow.png`。

这些 QA 输出未作为产品资源打包。
