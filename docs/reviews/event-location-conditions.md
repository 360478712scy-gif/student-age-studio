# 事件地点与非假期条件核查（2026-10-17）

基于 GitHub main `fc87171`（1.5.0）的修复，随 1.5.1 轻量更新交付；发布状态以对应 CI 与更新频道为准。

## 原因与修改

- `syncSocialEntry` 在社交事件指定地图和人物时额外加入 `[7,101,npc,mapId]`。原版这条条件检查人物当前所在地图，会额外限制事件；它并不是设置事件地点的必要步骤。删除自动生成，继续使用 `EvtCfg.mapId` 和闲聊的 `InteractCfg.map`。
- 同步时沿用自动指令归属记录，移除旧 `studioSocial.entryConditions` 中的自动位置条件。作者手写且无自动归属的位置条件保留；不会按指令编号全局删除。
- 非假期选择改为生成 `[2,8,-1]`；服务端为旧缓存中的选项同步该值，不要求用户删除缓存，也不批量改写已有条件。
- 原版源码快照中 `2,8,0` 与 `2,8,-1` 都走 `!IsHoliday()`，因此不能仅根据截图认定 `0` 导致事件不触发。仍需反馈者 Mod 与对应游戏版本验证触发失败原因。

## 证据范围

原版资源：`StudentAge-Decompiled-Resources/current/native-all.cs`，2026-09-20 快照；源码 SHA256 `c3b842f0d02ed53f483b1aac0b1aee5aac42936510a313b3eca33e1e416b8654`。未匹配反馈者当前 DLL，不代表其游戏版本已验证。

- `CommonEvtMgr.GenConditioner`，17375 行起：类型 7 分派到 `ConditionerRelation`。
- `ConditionerRelation`，195869 行起：101 从第 3 项读取人物、第 4 项起读取地图列表；196066 行起按 `GetMapByNpc` 判定。
- `CommonEvtMgr.GetEnableEvtId`，17974 行起：独立检查 `EvtCfg.mapId` 与条件。
- `ConditionerDate.OnIsMatch`，193455 行附近：假期参数等于 1 时检查假期，否则检查非假期。

## 验证

- 修复前 `event-location-conditions.cjs` 复现额外 `[7,101,3,12]`；修复后通过。覆盖换地点、已标记旧自动条件清理、手写条件保留、概率、重复同步、重开及闲聊地点。
- `automatic-command-removal.cjs`、`command-localization.cjs` 通过。
- `test_native_condition_integration.py` 共 6 项通过，包括旧缓存转换、原缓存不变、效果目录不受影响。
- `event-location-full-ui.cjs` 使用真实 StudioServer 与完整 Chrome 编辑器，通过选择地点、选择非假期、应用、HTTP 保存、重载重开。初次和旧缓存场景均通过；最终结果为 `output/event-location-fix/result.json`，复现入口为同目录 `run.py`。
- 合成数据验证；未复制实际 Mod、游戏安装或项目。未做 Windows 原生窗口、Unity 游戏或反馈者 Mod 验收。
