# 请求路径的无上限等待（Windows 卡死）

2026-09-22，基于 main `050d70e`（1.3.13）。本轮改动尚未发布；工作树 `/Users/yugonglian/Projects/student-age-studio-gh`。

## 原因

Windows 用户反馈最新版会永久卡死。请求路径上有两处等待没有任何截止时间，任一处触发，界面就停在原地而且不给任何提示：

- `platform_support.lock_file` 的阻塞分支是 `while True` + `time.sleep(.05)`，没有超时。保存 `/api/save`、模组备份、用户条件配置都走这把锁；只要另一个窗口或进程占着不放手，请求就永远不返回。
- `/api/portrait-dimensions` 在 HTTP 请求线程内同步 `UnityPy.load()` 整包解包（原版 role 包约 442 MB）并逐个解析 Texture2D/Sprite。内置种子只覆盖 2 个包（合计 0.47 GB），且必须文件长度与 SHA-256 完全一致才复用；游戏版本不同或装了其他 DLC 就必然整包解包。挂住期间前端 `portraitSizePending` 一直不清，立绘不安装。

这与同一仓库既有的设计约束冲突：`media_warmup.py` 明确写着不把 UnityPy 引进 HTTP 进程，而 `/api/portrait-dimensions` 走的正是这条路径。

## 改动

- `platform_support.py`：`lock_file` 增加 `LOCK_TIMEOUT=30s`，超时抛 `BlockingIOError`；POSIX 与 Windows 两条分支都改为带截止时间的重试循环。`timeout=float('inf')` 保留显式无限等待能力，`blocking=False` 行为不变。
- `server.py`：保存抢不到锁返回 `409 save_busy`「另一个窗口正在保存这个模组，暂时无法写入。请稍后重试。」，不再无声挂起；`backups.py`、`condition_library.py` 同样给出 `backup_busy` / `condition_busy`。
- `extract_game_assets.py`：请求路径只读缓存、绝不解包；需要测量时交给一条去重后台线程（总预算 300s），按包落盘，下次从断点继续；种子 JSON 进程内只读一次；同一包同一版本最多尝试 2 次；新增 `complete` / `tried` 标记，既不重复解包也不漏资源。
- `app.js`：后台补齐的尺寸用有限次（12 次）重试取回，不再"问过一次就永远不要"。

## 修改前失败证据

旧代码取 HEAD 副本，两版用同一探针：

| 探针 | 旧代码 | 新代码 |
| --- | --- | --- |
| 另一个句柄持锁时调用 `lock_file` | 8 秒未返回，进程需被杀死（exit 124） | 1.01 秒返回 `BlockingIOError` |
| `UnityPy.load` 卡住不返回时的 `/api/portrait-dimensions` | 8 秒未返回 | 0.00 秒返回 `{}`，请求线程内未调用 `load` |

复现方式（不依赖本机临时目录）：

```sh
# 旧代码副本：只把本轮改动的 5 个源文件还原到 HEAD
cp -R standalone /tmp/oldcheck-standalone
for f in platform_support.py server.py extract_game_assets.py backups.py condition_library.py; do
  git show HEAD:standalone/$f > /tmp/oldcheck-standalone/$f
done
python -B output/freeze-bounds/probe_lock.py /tmp/oldcheck-standalone     # 旧代码：8 秒不返回
python -B output/freeze-bounds/probe_lock.py standalone 1                # 新代码：1.0 秒 BlockingIOError
python -B output/freeze-bounds/probe_portrait.py /tmp/oldcheck-standalone # 旧代码：8 秒不返回
python -B output/freeze-bounds/probe_portrait.py standalone               # 新代码：0.00 秒返回 {}
```

实测记录见 `output/freeze-bounds/probes.txt`。

## 验证

- Python 全套：`295 → 303` 通过（4 项平台跳过）。新增 `standalone/tests/test_freeze_bounds.py` 6 项；`standalone/tests/test_picture_dimensions.py` 更新为增量缓存契约（请求不解包、后台补齐、已测包不重复解包、种子仍需完全哈希）。
- CI 列表 10 个 Node 用例全部通过；另跑仓库其余 6 个纯 Node 用例与 4 个浏览器渲染用例（Chrome）全部通过。
- `tools/build_update.py` 打包通过，190 文件，包内含本次修复。
- Windows 分支以打桩 `msvcrt` 覆盖：持锁时按截止时间报错，不再自旋（本机无 x64 Windows，未做实机运行）。

## 第二轮：独立复核后的修正（2026-09-22）

独立复核 agent 提出 4 项问题 + 细节项。逐条复现后的结论与处理：

- **P1 成立，且是本轮引入的回归。** 请求改成快速返回部分结果后，`/api/portrait-dimensions` 原有的导出图兜底从"极少触发"变成"冷缓存几乎必然触发"。导出预览按统一高度缩放（本机真实缓存 1625 条里 540 条与原生尺寸不同，例如 `role_full/role_afang` 导出 262×1200、原生 447×2048），而 `scene.js` 的 `portraitBox` 用**绝对像素高**乘 `urlParm` 计算几何，前端拿到兜底值后又不再重问 → 整场会话立绘尺寸偏小约 0.59 倍。命中人群正是报卡死的那批：他们 1.3.13 的请求没跑完、v5 缓存没写。
  **修正**：新增 `native_portrait_paths()`；原生贴图路径不再用导出图像素兜底，保持未回答让前端继续重问（12 次上限），非原生图片（模组自备 PNG）仍按原逻辑兜底。用例 `test_native_portrait_keeps_asking_instead_of_using_exported_pixels`（真实 HTTP + 冷缓存 + 可解析导出图）。
- **P2 成立。** 每进程"最多 2 次"的硬上限会在两次瞬时读失败后整场不再测量。改为前两次立即重试、之后 30/60/120…300s 退避，成功后清零；单个包失败不再中断整趟。用例 `test_a_transient_read_failure_recovers_after_the_delay`（假时钟推进验证自愈）。
- **P3 成立。** 请求预算只在两个包之间检查，种子校验的整文件 SHA-256 在请求线程上不可中断。改为分块读取并在截止时间放弃。
- **P4 成立，按复核意见只出方案。** 版本号未升 → 客户端按 `key<=current` 判定"已是最新"，修复到不了用户；`latest.json` 的 sha256/size 也与新包不一致。已验证 `1.3.13.1` 会被 `version_key` 直接抛 `无法识别的版本号`，四段版本号在现有更新器下不可行。
- **P5.1 成立（比复核描述更严重）。** 另有 5 处 `lock_file` 未处理：`error_logs.write` 在锁超时时会**静默丢弃诊断日志**（`except Exception: return None`），用户报障时恰好丢掉唯一证据；已改为超时后仍写（文件名唯一，旁写安全），`_prune` 容忍已被删除的文件。`error_logs.configure`、`ui_resources.resource_manifest` 给出中文 409；`storage_paths.prepare_game_cache` 用 300s 长超时 + 中文报错（启动期迁移可能合理地超过 30s）；`native_portraits.__main__` 是工作进程，保持快速失败由父进程重试。
- **P5.2 成立。** `complete` 在所有写路径恒为真、`tried` 为死代码，已删除；缓存条目回到 `{stamp, sizes}`，指纹一致即"该版本已完整测量"。
- **P5.3 成立。** 已补 P1 的兜底路径用例与 P5.1 的日志锁用例。
- 另外自行发现并修复：上一轮新写的 `load.assert_not_called()` 与刚启动的后台线程存在竞态，约 1/15 概率失败；已改为断言"解包发生在非主线程"。`test_portrait_save_priority.py` 的桩件同步补上 `native_portrait_paths`（路由新增导入导致桩件漂移）。

### 复核自身的两条断言与它的建议矛盾

- P3 用例在 200MB / `budget=0.05` 下同时要求"请求返回种子尺寸"和"请求留在预算内"，这两者不可能同时成立；它自己的建议（种子校验放后台、请求先返回）就意味着请求不该返回种子尺寸。反证：新代码 `budget=2.0` 时 0.072s 同步返回尺寸（快路径保留），`budget=0.05` 时 0.050s 截止返回 `{}`。旧代码则无视预算，0.076s 把整个哈希跑在请求线程上。
- P2 用例要求 6 次紧凑迭代里解包尝试 `>2` 次，任何带退避的实现都做不到。改成"前两次立即重试"后该断言通过（3 次），但真正验证"自愈"的是上面那条假时钟用例。

### 第二轮回归

- Python 全套 **307 项通过**（4 项平台跳过）。
- CI 10 项 Node 用例 + 其余可运行的 6 项纯 Node + 4 项浏览器渲染用例全部通过（3 项需 Electron/自带内核的未运行）。
- 复核探针（仅把 `module._portrait_unpack_attempts.clear()` 改为 `_portrait_retry.clear()`，其余不动）：**8/9 通过**；唯一失败项即上面那条自相矛盾的值断言。原始探针直接跑会有 6 项报错，因为它引用了本轮删除的私有属性，不是产品缺陷。
- 稳定性：全量套件连跑 10 次全部通过。

## 第三轮：加载慢（用户反馈"切换页面/事件/对话要十几秒到几十秒"）

用户补充症状：不是页面渲染卡，而是加载慢，切页/切事件/切句要十几秒到几十秒，内存正常。用他们自己的基准 + 真实游戏数据在**同一台机器**上做了逐项测量。

### 没有找到"变慢"的回归

`standalone/tests/benchmark_large_mod.py`，上一版 1.3.11.11（`v1.3.12-beta.11`）对当前：

| 指标（1 万句模组） | 1.3.11.11 | 当前 | 变化 |
| --- | --- | --- | --- |
| 首次打开项目 coldSegmentOpen | 1203.9 ms | 1207.5 ms | +0% |
| 全表 load | 276.1 ms | 281.1 ms | +2% |
| 素材列表（首次） | 884.4 ms | 887.8 ms | +0% |
| 保存一句 | 338.8 ms | 341.7 ms | +1% |
| 100 次头像读取 | 199.3 ms | 195.4 ms | -2% |

2000 句档同样全部在 ±5% 内。真实游戏侧（120 包 / 32057 条素材）暖启动资源 worker 0.43 秒；原版目录首次 92.7 ms；原版素材列表 44–177 ms；素材预热冷 84.1 秒、暖 7.8 秒（一次性）。

### 真正贵的是"读整包"

强制种子未命中后单独量 422 MB 的 role 包：

| 步骤 | 耗时 |
| --- | --- |
| `UnityPy.load` 整包 | **3.5 s** |
| 解析全部 1625 条 role_* 资源 | 0.1 s |
| 只解析要用的 3 个资源 | 0.0 s |

结论：成本几乎全在"读 + 解压整包"，**"只解析所需资源"这个方向无价值，已否决**（避免了一次没必要的改动）。慢盘 / 杀软下这一步从 3.5 秒放大到几十秒，正是用户描述的"切页十几秒"。

### 本轮两处优化

- **优化 A：测量改到独立进程。** 原先整包测量跑在服务进程的后台线程里：虽然请求不再被阻塞，但解压与解析会持续占用本进程的 GIL，其它请求在这段时间里一起变慢。现在改为 `--portrait-measure` 工作进程（复用既有 `worker_command`，冻结版走 `--extract extract_game_assets`，Windows 下 `BELOW_NORMAL_PRIORITY_CLASS`），父进程 0.002 秒返回、子进程 0.6 秒跑完并写缓存；HTTP 进程不再需要打开游戏包。
- **更正（2026-09-22，复核方实测）**：上一版这里写的是"`needs_unpack` 只在包存在且尚未测量时置位，所以不会出现每个请求拉一个进程"。**这句不成立**：`needs_unpack=True` 只说明有候选包且缓存里没有它这个版本，**不保证测得出来**。包存在但读不出来（杀软占用、权限不足），或缓存目录不可写（只读、满盘、盘掉线）时，子进程测不出也写不进 manifest，而按包退避只存在于子进程里、跨进程永不触发，于是每次请求都会再起一个进程——实测 4 次请求 = 4 个子进程。
  **正确表述**：只有成功测量才会推进缓存；始终测不出来的包需要父进程侧限流。
- **优化 A2：父进程侧限流（按同一退避曲线）。** 父进程用"这趟有没有推进 manifest"判断成败：推进则清零，未推进则计数并按与按包重试相同的曲线等待（前 `PORTRAIT_RETRY_FREE`=2 次不等待，之后 30/60/120…300s），退避期间不再起进程。自愈契约保留：实测 4 次请求的子进程数由 4 降为 3（前两次按契约立即重试，第三次建立退避，第四次被挡住）。
- **优化 B：素材列表的指纹复用。** 一次列表渲染原本要对模组里每个素材做一次文件指纹（400 图 = 512 次调用，**再取一次仍然 452 次**）；Windows 上每次指纹就是一次 `CreateFileW`，杀软会过滤。现在在"廉价 stat（大小、mtime、inode）未变"的前提下复用 15 秒内的结果：**再取 452 → 52 次**。写盘前的冲突校验、读取期间的变更校验、像素哈希、目录监视仍然使用新鲜指纹，不受影响。

### 验证

- Python 全套 **311 项通过**（4 项平台跳过）；CI 10 项 Node 与其余可运行的 Node/浏览器用例全部通过。
- worker 端到端：父进程 0.002 秒返回；子进程退出码 0、写入 v5 缓存；真实游戏 + 种子命中路径复验通过。
- 私有维护源已同步，定向用例通过。

### 未验证

- 未在 x64 Windows 真机测量；上面是 macOS + 真实游戏数据 + 隔离临时模组的数字。慢盘与杀软的放大倍数仍是推断。
- 优化 A/B 的收益在 macOS 上是"少读文件、少占 GIL"，具体到用户机器的秒数需要现场数据。



- 未在 x64 Windows 真机复现用户现场。上面是代码级可重复证据，不声称已复现用户那条具体触发链；若修复后仍出现卡死，下一步在真机取 `--qa-debug-port` 现场与错误日志。
- 未测量完整冷缓存整包解包的实机时长。新逻辑下它已不在请求路径上，只在后台进行。
- 本轮只处理"永久卡死"。用户同时反馈的"整体比旧版更卡"未在本轮范围内：液态玻璃 WebGL 层按用户要求暂不处理，其余候选（`ui-controls.js` 的全文档 MutationObserver 与 400ms 轮询、每次启动全量扫描 `.bundle` 头、杀软实时扫描）尚未验证。
