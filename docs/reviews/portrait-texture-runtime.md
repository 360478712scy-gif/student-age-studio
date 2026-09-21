# 人物放大修复与全量尺寸核对

2026-09-21；版本 1.3.13。

## 根因与实现

1. 原版 TalkRoleItem.SetData → UISprite.SetTextureUrl → ResInfo.GetSpriteAsync 实际通过 Addressables.LoadAssetAsync<Texture2D> 读取纹理，再 Sprite.Create，使用默认 PPU 100。旧实现误用了导入 Sprite 的 PPU；女老师 306 原图 423×2048 被换算为约 690×3341，叠加 urlParm2 的 .85 后从应有 1740.8 高变成约 2839.6。
2. 新读取器优先使用同资源的 Texture2D 尺寸，只有没有独立 Texture 的图集 Sprite 才保留 Sprite 原生单位。内置元数据版本 2，磁盘尺寸缓存 v5，防止已有 v4 错误值继续生效；不修改用户 Mod、作者位置和缩放。
3. DLC 混合 textures 包原先因为名称不含 role 被跳过，现在按 bundleOutputs 的实际目标资源筛选。已知包仍必须匹配完整 SHA-256 才使用内置元数据。
4. Windows 完整界面又复现肖清雅模型就绪前使用静态备用图，高度从 2048 跳到约 1554.6。模型正常读取期间不安装尺寸不同的静态备用图，保留已显示图片；实际模型错误仍允许静态备用。主舞台、人物动作及闲聊共享相同行为。

## 验证

- 读取本机原版和 DLC 共 1658 条图片尺寸。主资源包 1625 条中有 265 条旧值与游戏加载方式不符；DLC 另补 33 条。
- 遍历 394 个人物配置：296 个有可核对静态图，600 组学段／性别／服装组合通过尺寸、缩放和锚点检查；另识别 22 组模型学段／性别配置。没有把未逐一原生渲染的全部模型称为游戏验收。
- 原版 400 篮球、500 羽毛球、700 跑步三个特殊角色的占位图片本机不存在，两个学段共 6 条未计作图片通过，不伪造素材。
- Windows 11 完整编辑器，白雨／肖清雅／女老师三人同屏，4 次鼠标拖动、3 次编辑切句、2 次预览切句，进入/退出全屏均尺寸稳定。女老师游戏单位高度约 1740.8，舞台/全屏误差低于 0.02；对话动作仍由作者数据控制。
- Windows Unity 游戏隔离进程使用原版 UISprite 加载女老师，测得 Image rect 423×2048、Sprite PPU 100、Texture 423×2048。隔离副本跳过第三方订阅 Mod，原版人物/素材加载函数未修改；未改真实游戏、存档或订阅内容。
- 回归：图片尺寸/缓存/DLC/图集与保存竞争 5 项；浏览器 scene-portrait-readiness、scene-retained-geometry。缺失模型、延迟模型、静态备用回退、同图不同参数分别覆盖。三平台发布 CI 再运行现有完整套件。

私有证据（不分发游戏图片）：公开工作树 output/portrait-all/ 的 dimension-audit.json、all-roles-results.json、native-texture-metrics.json、windows-full-results.json、windows-full-stage.png、windows-full-preview.png。
