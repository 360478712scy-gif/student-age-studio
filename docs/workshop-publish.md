# 创意工坊发布：PR #5 修订说明

贡献人：若心知（ruoxingzhi）。原 PR 的后端实现与提交归属保留；本分支补充审查修复、前端和验证。

## 使用入口

工坊主页右上角「发布到创意工坊」。订阅模组不提供发布按钮，先创建本地副本。

一个窗口完成封面、标题、简介、可见范围、剧情/其他标签与更新说明。发布前检查未保存内容及 Steam 状态；提交后显示进度和条目链接。更换封面只改上传副本，不覆盖模组原图。

「关联已有的工坊条目」折叠在表单下方，仅在已有条目、损坏绑定或恢复发布时使用。正常首次发布不需要进入。已有绑定自动上传更新；条目不存在时停止并提示核实，不自动另建条目。

## 审查问题与修复

| 问题 | 当前行为 |
|---|---|
| 轻量更新漏带 DLL | `steamworks-runtime.json` 内含 MIT 桥接 DLL、许可证及固定 SHA-256；旧更新器支持此顶层 JSON，Windows 首次使用时校验并解码到缓存 |
| 完整包/公开源码导出 | Windows 完整包携带 JSON，并在有 vendor 目录时复制原 DLL；公开导出的顶层 JSON 同样支持运行时解码；Mac 完整包跳过此 Windows 运行库 |
| DLL 搜索目录句柄过早释放 | 保留目录句柄与两个库对象，工作线程退出后才关闭；桥接校验固定哈希，Valve DLL 仅从游戏/已知 Steam 目录定位 |
| 原生接口不匹配 | `SteamInit` 使用 int 返回值，0 为成功；community 类型为 0；提交回调补齐 uint64 条目编号 |
| 并发任务共享回调 | 一个 Publisher 仅允许一个活跃 worker，重复提交返回 409；取消期间仍占用任务槽 |
| 关闭时卸载正在调用的库 | 先停止新任务、标记取消并等待 worker；未退出则由 worker 最终清理 native session |
| 素材复制不一致 | 在保存锁内校验 revision、散列所有发布文件、稳定复制并比较源/副本；图片、音频变化也返回 conflict |
| 上传成功后一直等进度 | 提交成功回调即完成，不再等待已失效的进度句柄 |
| 上传后本地绑定失败 | ID 和链接保留，提供「重试保存绑定」；不重复上传或新建 |
| 创建成功但进程中断 | 创建前持久化 pending intent，得到 ID 后立即保存绑定；未知结果保留 pending，要求先核实 |
| 损坏绑定被当成首次发布 | 返回 409，保留文件；手动关联时备份旧绑定 |
| 覆盖缓存封面/锁文件规则 | 预检使用提交的 previewPath；统一排除所有 `*.lock/*.tmp/*.log`、备份及发布侧文件 |
| 注册表清理丢活跃任务 | 仅淘汰已终结且无需绑定恢复的任务 |

不分发 Valve 的 `steam_api64.dll`。只支持 Windows 64 位；其他平台预检给出原因。

原生接口依据：[SteamworksPy C++](https://github.com/philippj/SteamworksPy/blob/master/library/SteamworksPy.cpp)、[回调结构](https://github.com/philippj/SteamworksPy/blob/master/steamworks/structs.py)、[ISteamUGC](https://partner.steamgames.com/doc/api/ISteamUGC)。

## 数据与接口

- `POST /api/publish`：projectId、revision、title、description、visibility、tags、changeNote、previewPath。返回 202 任务。
- `GET /api/publish-status?jobId=`：状态、进度、错误、警告、bindingPending、条目链接。`publishedFileId` 使用字符串，避免 JS 丢失 64 位精度。
- `POST /api/publish-cancel`：取消尚未提交的后续步骤；已提交的 Steam 上传不能撤回，继续等回调后报告真实结果。
- `GET/POST /api/publish-prereq`：默认信息/当前填写内容的检查。不会创建条目。
- `POST /api/publish-preview`：上传不超过 1 MB 的封面，转换 JPEG 到编辑器缓存；GET 用于预览。
- `POST /api/publish-recover`：按 jobId 重写本地绑定，不重新上传。
- `POST /api/publish-bind`：按当前 revision 关联用户填写的已有条目编号；Steam 在上传时检查归属。

Steam visibility：0 所有人、1 好友、2 自己。标题 1–128 字，简介最多 8000 字，更新说明 1–2000 字。标签为剧情/其他。

状态：queued → preflight → creating/updating → uploading → done/error/cancelled/unconfirmed。取消等待阶段为 cancelling。超时/进度长时间不变不等于远端失败，记为 unconfirmed，保留暂存内容并阻止再次发布，提示用户核实后重启。

`StudentAgeStudio/workshop.json` 保存绑定；`workshop-pending.json` 保存未确认创建意图；重新关联前保存 `workshop-binding-backup.json`。这些文件不上传到工坊。游戏配置 JSON 不增加编辑器发布字段。

## 验证

验证证据、截图和边界见 [PR #5 验收记录](reviews/pr5-publish-acceptance.md)。

本分支用于用户审阅，未合并主线、未更新发行版本。原 PR 的 19 项假桥接测试不是实际 Steam 上传证明；真实账号创建/更新条目仍需单独验收。
