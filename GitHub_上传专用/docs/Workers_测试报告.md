# Workers迁移验收记录

日期：2026-10-26。环境：Windows、本地Node 24.22.1、Wrangler 4.152.0、Miniflare/workerd、真实本地D1 SQLite存储、Chromium Playwright。未部署到Cloudflare生产账户，未向真实QuickForm发送任何测试记录。

`npm run ci`通过：14项自动测试全部通过，TypeScript检查通过，原始题库/广告SHA-256检查通过，`wrangler deploy --dry-run`通过。全部测试外网请求被禁用，QuickForm使用隔离模拟HTTP响应。

| 自动测试 | 结果 |
| --- | --- |
| 原始16题、两个8题区组、价格和两张广告字节哈希、Worker名称、正式开关 | 通过 |
| 实际workerd运行、D1初始化、前台与广告、源码/数据库私有路径404、后台未认证401 | 通过 |
| 完整8题和后续问卷、最终重复提交不改答案、24行长格式、不购买属性留空 | 通过 |
| G1—G4刺激物、仅G3/G4披露、相同属性解释；16题各在交换/未交换两种位置核对 | 通过 |
| 16名并发入组，8个组别×区组单元各2人，禁止参与者指定组别 | 通过 |
| 环境/质量详情独立随编码变化，基础内容完全相同，32次资料查看、服务器限制时长 | 通过 |
| 同题并发幂等、已答改选409、重建Worker后同一持久化D1恢复下一题 | 通过 |
| 管理认证、CSRF、跨站请求拒绝、人数和人工有效样本区分、模式分开 | 通过 |
| CSV预览不写答卷、确认后跨实例导入、重复跳过、错误拒绝、原件下载、备份下载 | 通过 |
| 模拟HTTP200/status success；只发送一条完整UTF-8答卷，中文与实际A/B属性正确，刷新不重发；从完整QuickForm JSON及扁平CSV还原24行 | 通过 |
| 模拟网络中断uncertain，8题仍保存，禁止盲目重试；明确400失败后人工重试不改选择 | 通过 |
| 正式同步即使误开变量也锁定；一次性邀请码并发只成功一次；演示不混入formal | 通过 |
| 429按退避最多3次、快照不变；HTTP202标记uncertain且Cron不自动重发 | 通过 |
| XLSX中文、公式/重复字段拒绝；长格式同题两行choice=1拒绝 | 通过 |

另运行 `python worker/tests/browser_e2e.py`：G1—G4各完成一次，覆盖390px手机和1440px桌面、后台登录及指定demo组别、广告与披露、统一说明、详情面板、选择前按钮禁用、每人8题、途中刷新、最终问卷和完成后刷新。四组全部通过，无JavaScript页面异常，无横向溢出。

离线命令`node worker/scripts/quickform-to-long.mjs .worker-build/quickform-export.csv .worker-build/choice-long-recovered.csv`通过：1份实际模拟接收的完整答卷恢复24行，原文件未改。测试样本、本地库和截图位于Git忽略目录，没有放入交付或生产数据。

原始活动题库SHA-256：`13f951b8e1b28c00fde362b54df8d9fdbaa47d9a912a09ba0025d36f2a338136`。旧版题库：`e695ba4d0098f5b17938cd121d7f4205893e4b627b5de655ae32fbeb3572d834`。图表广告：`21292f60ad8ab7d4120a73fde93d6050728768c82ac2bc06dc2bfd56614f445f`；自然广告：`6dfe23fb124ccd4912cc3ee35c7519bd9975d2da3b6a6c270bfba73961ef2148`。

验证边界：Cloudflare账户数据库权限/实际绑定、发布域名、Secrets、线上Cron与套餐限额尚须部署后在demo验收。测试不是实际受访者预测试，也不证明正式QuickForm任务已收到数据。正式通道保持关闭。
