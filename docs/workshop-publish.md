# Mod 一键上传创意工坊：设计与实现说明

> 范围：**仅后端**（`standalone/` Python）。前端（`*.js/*.css/*.html`）本次不动，
> 发布向导 UI 后续按本文第 7 节的接口契约实现。
> 基线版本：`1.3.12-beta.1`。Steam AppId：`1991040`（见 `game_locator.py:15`）。

## 1. 背景与参考实现

| 参考 | 位置 | 结论 |
|---|---|---|
| 游戏本体编辑器 | `D:\desktop\游戏反编译\View\Mod\ModPageUploadView.cs:301`、`Sdk\PlatformAPI\SteamPlatform.cs:637-731` | `Steamworks.NET`，`CreateItem` 新建 / `SubmitItemUpdate` 更新；更新说明写死；无进度条；`preview.jpg` ≤ 1MB；可见性 `0=Private/1=Friends/2=Public`，新建默认公开 |
| 星云/若心知编辑器 | `D:\desktop\学生时代编辑器_by星云11 - 副本\src\editor\app.py:381-974` | 自带 `steamworks/` 源码绑定 + `SteamworksPy64.dll` + 复用 Valve `steam_api64.dll`；有预检、150ms 进度轮询、被删自动重建、`.modstudio_workshop.json` 存 `published_id`；整目录原样上传 |
| 本编辑器现状 | `workshop.js:320`、`help.js` | 文档与 UI 明示"去游戏内发布"；`manifest.json` 已有 `title/description/visible/tags/metadata{id,version,packageId}`，与游戏 `ModManifestData` 子集兼容，无需改 Mod 格式 |

## 2. 核心选型（已定）

1. **绑定层自己写，不抄整包**：`standalone/steam_bridge.py`，只覆盖 UGC 发布必需的约 12 个桥接函数，
   并显式声明全部 `argtypes`（星云版缺了 `StartItemUpdate` 等的 `argtypes`，大 FileId 有截断风险，
   我们不继承这个坑）。ABI 事实（函数名/结构体布局）来自 Valve 公开 SDK 与 MIT 的 SteamworksPy，
   实现为原创代码。
2. **桥接 DLL 直接复用 MIT 产物**：`standalone/vendor-steamworks/SteamworksPy64.dll`
   取自 SteamworksPy-1.6.3 官方包（MIT，GP Garcia），附带 `LICENSE.SteamworksPy`，
   并在 `THIRD_PARTY_NOTICES.md` 登记。**不**复用星云改过的 `steamworks/` Python 包。
3. **Valve 的 `steam_api64.dll` 绝不随包分发**：运行时按序查找——游戏目录
   `StudentAge_Data/Plugins/x86_64/steam_api64.dll` → Steam 客户端根目录
   （`game_locator.steam_roots()`）→ 系统 PATH。找不到则接口报 503 并指引。
   （Valve 分发条款要求合作方身份才能再分发该 DLL；只用用户磁盘已有文件法务风险最小。）
4. **AppId 上下文用环境变量**：游戏根目录没有 `steam_appid.txt`，工作进程在 `SteamInit`
   前置 `SteamAppId=1991040`（Steam 官方支持的工具链机制）。
5. **仅 Windows x64**：Mac/CrossOver 下预检直接说明不支持（`steam_api` 的 dylib/转译链未验证）。
6. **发布默认值**：可见性默认私密（游戏默认公开太激进，星云默认私密）；更新说明每次由调用方传入；
   标签白名单 `{"剧情","其他"}`（与游戏 `ModCtrl.cs:579` 一致，防 Steam 拒收未知 tag）；
   暂存拷贝排除 `StudentAgeStudio/Backups/`、发布身份 sidecar、`*.lock/*.tmp/*.log`
   及 `mod_copy.excluded_entry` 原有项；其余编辑器 JSON（如 `deleted-talks.json`，游戏语义
   相关）原样上传，最接近游戏整目录上传，仅去掉备份/锁/日志/身份文件。

## 3. 总体架构

```
调用方（未来前端向导 / curl）
  │ POST /api/publish {projectId, revision, title?, description?, visibility?, tags?, changeNote?, previewPath?} → 202 {jobId}
  │ GET  /api/publish-status?jobId → {state, phase, percent, processedBytes, totalBytes, log[], publishedFileId?, itemUrl?, error?}
  │ POST /api/publish-cancel {jobId}   → 停止轮询并标记 cancelled（见 §5.6：UGC 无真取消语义）
  │ GET  /api/publish-prereq?projectId → 预检清单（不启动任务）
  ▼
standalone/workshop_publish.py
  ├─ Publisher（单例，常驻）：SteamClient 生命周期 + jobs 注册表（threading.Lock）+ 后台工作线程/任务
  ├─ SteamBridge（standalone/steam_bridge.py）：CDLL 装配、回调泵线程、CFUNCTYPE 持有（防 GC）
  ├─ staging：store.lock 下 revision 校验 → 安全拷贝到 temp → 写 preview.jpg → manifest 校验
  └─ sidecar：<mod>/StudentAgeStudio/workshop.json {publishedFileId,itemUrl,lastPublishedAt,lastChangeNote,appId}
```

* 路由风格沿用 `server.py` 现有模式：`X-Studio-Token` 鉴权、`ApiError` 错误码、长任务 202 + 轮询
  （仿 `ResourceJobs`），绝不同步 POST 等上传完成（`socket timeout 30s`）。
* 只允许 `local:` 工程（`workshop:` 只读，沿用 `store.project(..., writable=True)` 即 403）。
* `ThreadingHTTPServer` 下所有共享状态（jobs、bridge 单例）各自持锁；`store.lock` 只在 staging 与
  sidecar 读写时持有，绝不在等待 Steam 回调时持有。

## 4. 状态机与接口契约

### 4.1 任务状态

`queued → preflight → staging → creating → updating → uploading → done | error | cancelled`

* `creating` 仅无绑定 id 时出现；`updating` 覆盖组装参数 + `SubmitItemUpdate`。
* `uploading` 按 150ms 轮询 `GetItemUpdateProgress` 更新 `processedBytes/totalBytes/percent`
  与 `phase`（`PREPARING_CONFIG/PREPARING_CONTENT/UPLOADING_CONTENT/UPLOADING_PREVIEW_FILE/COMMITTING_CHANGES`）。
* 终端态保留在注册表（内存，重启丢失；sidecar 才是持久身份）。`GET` 未知 jobId → 404。

### 4.2 `POST /api/publish` 请求体

```json
{
  "projectId": "local:<hex>",
  "revision": "<store.revision>",
  "title": "标题（可选，缺省用 manifest.title）",
  "description": "简介（可选，缺省用 manifest.description）",
  "visibility": 2,
  "tags": ["剧情"],
  "changeNote": "v1.1 新增结局（可选，缺省 '通过拾光工坊上传'）",
  "previewPath": "preview.jpg（可选，缺省 <mod>/preview.jpg；绝对路径或 Mod 内相对路径）"
}
```

校验（失败全部 4xx，不建任务）：`revision` 失配 409；标题去空后 1..128 字符；
简介 ≤ 8000 字符；`visibility ∈ {0,1,2}`；tags 须为白名单子集（否则 422 并列出非法项）；
封面存在、可解码、≤ 1MB（沿用 `normalize_image` 的 Pillow 门）；`previewPath` 不得越界
（`safe_path` 语义，绝对路径必须落在 Mod 目录或本机缓存内）。

### 4.3 `GET /api/publish-prereq?projectId=` 返回

```json
{"ready": false, "steam": {"available": false, "reason": "未检测到 Steam 客户端…"},
 "manifest": {"ok": true}, "preview": {"ok": false, "reason": "缺少 preview.jpg"},
 "binding": {"publishedFileId": 0}, "warnings": ["Cfgs/zh-cn 为空…"]}
```

* `steam.available=false` 时其余照常检查，让向导一次展示全部问题。

## 5. 关键流程细节

### 5.1 Steam 运行时装配（`steam_bridge.py`）

1. 定位桥接 DLL：`sys._MEIPASS`（冻结包）→ 本文件同级 `vendor-steamworks/`（源码运行）。
   缺失 → `SteamUnavailable('编辑器缺少 Steam 桥接组件…')`。
2. 定位官方 DLL：`<game>/StudentAge_Data/Plugins/x86_64/steam_api64.dll` →
   `steam_roots()` 下的 `steam_api64.dll` → `PATH`。缺失 → 同上类错误。
3. `os.add_dll_directory(官方 DLL 所在目录)`（Python 3.8+ Windows），再 `CDLL(桥接 DLL)`。
4. `SteamInit()` 前置 `os.environ['SteamAppId']='1991040'`（仅工作进程内设置，不污染用户环境则更好：
   实现里用 `try/finally` 还原旧值）。
5. `IsSteamRunning()` 为假 → `SteamNotRunning('请先启动并登录 Steam 客户端…')`。
6. 回调：`CFUNCTYPE(None, CreateItemResult_t)` / `CFUNCTYPE(None, SubmitItemUpdateResult_t)`
   实例必须被桥接对象强引用（否则 GC 后 Steam 回调写野指针崩溃——星云版同样这么持有）。
   泵线程 `RunCallbacks()` 每 50ms 一次，只在任务活跃期跑。
7. `Shutdown()` 在 server 关闭与进程退出时调用（幂等）。

### 5.2 新建 vs 更新

* sidecar `publishedFileId > 0` → `StartItemUpdate(appId, id)`；`= 0` → `CreateItem(appId, COMMUNITY=1)`，
  回调成功后写 sidecar 再走更新（与游戏/星云一致）。
* `SubmitItemUpdate` 返回 `FileNotFound(9)`（物品在工坊被删）→ 清 sidecar id → 自动重建一次
  （仿星云 `result==8` 逻辑；以 Valve `EResult` 为准）。
* `userNeedsToAcceptWorkshopLegalAgreement` → 任务进 `error`，错误体带
  `https://steamcommunity.com/sharedfiles/workshopagreement`（与两处参考一致）。

### 5.3 EResult 错误映射（节选，余者透出原文）

`1 OK / 2 Fail("上传失败…看 Steam/logs/workshop_log.txt") / 3 NoConnection("网络未连接…") /
8 InvalidParam / 9 FileNotFound(见 5.2) / 15 AccessDenied / 25 LimitExceeded`。
`NotLoggedOn` 单独提示"请在 Steam 客户端登录拥有游戏的账号"。

### 5.4 预览图处理

 staging 内固定写 `preview.jpg`：若调用方给了 `previewPath`（任意可解码图片），用 Pillow
 转 JPEG（quality 85，逐级降采样保证 ≤ 1MB，与 `headshots.preview_image` 同策略）；
 否则直接采用 Mod 内 `preview.jpg`（须已 ≤ 1MB，否则 422 拒绝，不静默压缩用户原图的分发意图——
 注：此处是"拒绝"而非"压缩"，避免用户以为原图已传）。

### 5.5 大小与超时

* 暂存前 `os.walk` 统计：总量 > 900MB 警告（沿用星云阈值，进 `warnings` 不阻止）；
  单文件 > 100MB 逐项警告。Steam 工坊对大物品另有服务端限制，透出原文。
* 任务级超时 30 分钟；上传进度 10 分钟零进展判 stall 进 `error`（取值见 `workshop_publish.py` 头部常量）。

### 5.6 取消语义（诚实设计）

ISteamUGC 没有取消接口。`POST /api/publish-cancel` 只做到：停泵轮询、任务标 `cancelled`、
不再写 sidecar。**服务端可能已收录本次提交**，`status` 返回 `note` 字段明示，
并给出物品链接让用户去工坊确认/删除。文档与未来 UI 文案必须一字不差地传达这一点。

## 6. 打包与分发（本次不改构建脚本，只定契约）

* 轻量更新包（`tools/build_update.py`）：只收 `standalone/` 顶层代码文件，
  `vendor-steamworks/` 子目录与 `docs/` **自动不进包**——行为正确：轻量更新不碰 Steam 能力。
* 完整客户端需维护者加两行（Windows `build.ps1` PyInstaller `datas`、Mac `package.py`
  Resources 拷贝）：`standalone/vendor-steamworks/SteamworksPy64.dll`（MIT，可分发），
  **不要**加 `steam_api64.dll`（Valve 专有，运行时从用户游戏目录加载）。
* 缺桥接 DLL 的客户端（旧完整包/纯源码未放 DLL）：`/api/publish*` 报 503，
  `reason` 指引下载新完整客户端。Mac：预检直接 `available=false`。

## 7. 给未来前端向导的契约（供 UI 实现对照）

1. 三步：①预检页调 `publish-prereq` 全量展示；②表单（标题/简介/可见性三档/标签多选/更新说明/封面选择复用 asset-picker）调 `publish`；
   ③进度页轮询 `publish-status`（1s），成功展示物品链接，失败展示 `error.message + error.code` 与重试。
2. 可见性默认选中**私密**；更新说明默认文案 `通过拾光工坊上传`。
3. 封面选择器 accept 沿用图片类型；<=1MB 由后端校验，前端只做大小提示。
4. 所有文案保留"取消≠撤回服务端提交"的说明（§5.6）。

## 8. 测试策略

* `standalone/tests/test_workshop_publish.py`：全部经可注入的假桥接（`bridge_factory` 参数），
  覆盖：字段校验矩阵、revision 失配、只读工程拒绝、暂存排除集、sidecar 读写、新建/更新/被删重建
  状态机、进度推进、超时/stall、取消标记、错误映射、回调对象持有（防 GC）。
* 真 Steam 链路不在 CI（无客户端、无账号），`publish-prereq` 的 `steam.available` 在 CI 恒 false，
  相关断言只覆盖"不可用时的错误体"。
* 人工 QA 矩阵（发布前）：新建公开/私密、更新、删后重建、离线、未同意协议、900MB+、无封面、
  标题 129 字符、并发二次提交。

## 9. 未决事项（需产品拍板，均已给默认值）

1. 可见性默认私密（§2.6）——拍板：是。
2. 暂存排除范围（§2.6）：实现为"排除 Backups/sidecar/锁/日志，保留其余编辑器 JSON
   （如 deleted-talks.json 以保游戏语义）"——拍板：是。
3. 是否回写 `manifest.json` 的 `metadata.id` 以兼容游戏内"已发布"显示：默认**否**
   （sidecar 足够；回写会触 `manifest_save` 的 id 锁死规则，需另开特例）。
4. Mac 支持：默认关闭，待验证。
