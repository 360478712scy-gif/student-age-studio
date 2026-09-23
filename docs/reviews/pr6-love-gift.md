# PR #6 审查与前端集成

PR: https://github.com/360478712scy-gif/student-age-studio/pull/6
作者：若心知（ruoxingzhi），原提交 72f8bb76f43dad068c5794aecc025a6980842480。保留合并祖先。

## 修正

1. LoveVindicateCfg.target 是成功率档位，txt 是概率提示；并非好感度阈值和表白台词。
2. LoveData.GetVindicateSuccessRate 按人物 ID 读取两组五项参数。新增选择所属人物，参数用五个固定输入；人物改号同时维护这两类配置。
3. LoveActionCfg 的键是解锁恋爱值，不能用普通百万段新增；界面修改原有条目。
4. LoveDrawCfg 同时包含画笔颜色与人物画作。补齐画作字段，并保留 GetNewLovePaint 按人物编号连续查找的现有身份。
5. LoveGreetingCfg 尚无已确认调用，不宣传为可触发的问候功能。
6. GiftEvtCfg.npc/talkId 按下标关联；type 缺省或 0 会消耗礼物，非零只触发。界面按收礼人分组，删除同步维护三组列表。一项入口通用，两项为男、女主角。
7. “ItemCfg / BookCfg”是联合引用，不能直接用作表接口名称。前端分别读取合并供选择，保存仍是原始整数 ID。

## 保存与安全

复用现有鉴权、只读订阅保护、路径限定、实时修订校验及事务备份。未增加上传、命令执行或新的无鉴权接口。提示/台词经转义，颜色仅允许六位十六进制值进入预览样式；可疑原值继续保留。概率参数或送礼关联不完整走现有保存确认，未确认前不写盘。扩展字段不丢弃。

## 验证入口

- standalone/tests/test_love_gift.py：新表保存重开、完整字段/未知字段保留、原版身份、确认后保存、非法路径和过期修订。
- standalone/tests/love-gift-ui.cjs：生产工坊组件，隔离 API 夹具；收礼人关联、可省略赠送方式、撤销、物品/书籍选择、编辑保存重开、五项参数、画笔/画作分流、HTML 转义。
- output/pr6-review/gift-events.png、love-breakfast.png：上述真实工坊组件界面截图。
- 发布 CI 执行 Windows/macOS/Linux 回归。截图及夹具不替代原生游戏恋爱自然流程验收，不宣称绝对无漏洞。
