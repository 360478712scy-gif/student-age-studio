# 原版音乐播放阻塞修复

Codex，2026-10-04，1.4.9.4。

## 原因与修复

播放器中的原版空间音乐通过 `/api/social-image` 获取，该媒体路由此前未排除全局 location_lock。音频请求暂停读取时，整个媒体流一直占锁，其他编辑、设置与保存请求需要等待。该路由现在沿用既有媒体流独立处理方式，不改变令牌验证、路径检查、Range 或文件读取限制。

实际 HTTP：32 MiB 合法 PCM WAV，请求收到 206 头后停止读正文并保持连接。修前 location_lock 仍占用，设置读取约 1,004 ms 超时；修后同样的慢读连接仍在，设置读取约 2 ms 完成。证据 output/original-music-freeze/baseline-stall.json 与 fixed-stall.json。

另外，文件无法打开时旧代码先发出 200/206 音频头，再拼接 JSON 错误，浏览器因此误报音频格式错误。现在先打开文件，再发送成功响应；PermissionError 回归确认得到完整 403 JSON。Windows 切歌正常取消旧连接产生的 WinError 10053，按正常连接关闭处理，不记录为程序内部错误。

## 验证范围

- 新音频流回归 5 项通过：慢读不阻塞、Range 正确、令牌验证、无法读取的完整错误响应、切歌取消不写内部错误。既有音乐库回归 2 项通过；更新器回归 29 项通过。
- Windows 11 ARM64 / x64 Python 模拟 / 实际 WebView2：白日、水星前两首及播放时间推进已通过，见 docs/reviews/editor-music-1494.md。
- 原版曲目的 Windows 原生完整播放本轮未完成：最终隔离窗口已进入工坊，QA 脚本用于抑制新歌自动播放的 interrupted 断言失败，未点击原版 101。未出现页面错误、crash 或 ProcessFailed，已正常关闭自有 PID 476；记录保留 windows-native-original-final-results.json=ok false。两首新歌此前原生播放与真实原版媒体路由 HTTP 慢读结果仍独立有效。
- 原暖 QA 缓存的 13 首 WAV 均 stat 可见但无法读取，Win32 ERROR_ACCESS_DENIED 5；普通 NTFS 目录，无 junction/reparse/encryption。没有改 ACL 或清缓存。该环境限制不能当作反馈者原 Mod 的已确认原因。最终原版验证使用既有外置资源包中可读的同轨道 101「Find Your Heart」AAC 副本，仅在本次 QA 映射；音频不随发布包提供。

首次原版验证失败和隔离 catalog hook 可选参数缺失导致的 QA 启动失败均保留于 output/original-music-freeze/，不将它们当成生产实现的通过证据。后续仅对同一环境的对应原版曲目定向复测。

最终生产 server.py SHA256：74ce406698f5d8cda9895d1d408a68bc9c903bbbcee90d0dc3786525be000c13。版本、下载包与旧更新器启用/回退见 output/release-1494/publication.json。
