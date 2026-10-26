# Study 2 燕麦饮DCE：Cloudflare Workers版

这是原平台的后端迁移版，保留原网页、问卷、两张PureOat广告、16道任务及两个区组。Cloudflare运行TypeScript Worker，使用D1；原Python文件保留用于本地旧版和历史数据核对，线上不再启动Python。迁移不会上传或改写电脑上的SQLite原始数据库。

## Cloudflare连接GitHub后的填写内容

| 设置 | 内容 |
| --- | --- |
| Worker项目名称 | `study2-dce-web` |
| Root directory | `GitHub_上传专用` |
| Build command | `npm run ci` |
| Deploy command | `npx wrangler deploy` |
| Node版本 | 22或更高；建议22 LTS |

Cloudflare构建环境通常会先安装依赖；如关闭了自动安装，请在Build command前加`npm ci &&`。`npm run ci`依次执行本地workerd/D1自动测试、TypeScript检查、题库和广告哈希校验、Wrangler部署预演。测试禁用全部外网请求。构建失败不应继续部署。不要选择GitHub Pages或静态Pages项目：它们不能运行本后端。

`wrangler.jsonc`已经指定名称、入口、静态资源、DB绑定和定时任务。只有`static`里的网页及广告允许作为公开资源；SQL、源码配置、答卷和备份不作为静态文件发布。

## 创建并绑定D1

推荐先在Cloudflare控制台 **Storage & databases → D1 SQL Database → Create database** 创建 `study2-dce-web-db`，复制它的Database ID。在本目录`wrangler.jsonc`的`d1_databases`唯一对象内，加入：

```json
"database_id": "这里填写刚创建的D1数据库UUID"
```

保留现有`binding: "DB"`、`database_name`及`migrations_dir`。在Worker的 **Bindings → Add binding → D1 database** 中确认变量名为`DB`、数据库为刚创建的库。UUID不是后台密码，可以提交配置。配置和控制台绑定必须指向同一个库，不要每次部署换库。

也可以在本目录终端执行：

```bash
npm ci
npx wrangler login
npx wrangler d1 create study2-dce-web-db
```

将命令输出的`database_id`填入配置，随后执行：

```bash
npm run db:remote
npm run ci
npm run deploy
```

初始化SQL位于`migrations/0001_initial.sql`，使用`IF NOT EXISTS`，不会删除旧表。Worker首次访问也会执行同一套幂等初始化，支持Wrangler首次部署自动创建D1的流程。当前配置没有伪造的数据库ID；若依靠自动创建，请在首次部署日志确认实际库名/UUID，并将它固定回配置。已有同名D1时优先采用上面的显式UUID方式。[Cloudflare自动配置说明](https://developers.cloudflare.com/workers/wrangler/configuration/#automatic-provisioning)

部署后访问Worker真实网址的`/health`，应显示`platform: cloudflare-workers`、`database: D1`、`mode: demo`、`formal_quickform_enabled: false`。发布网址以控制台实际显示为准。

## 后台账号与本地启动

在Worker **Settings → Variables and Secrets** 新建两个 **Secret**：

- `ADMIN_USERNAME`：自己设置的研究者账号。
- `ADMIN_PASSWORD`：自己设置、至少12字符的强密码。

密码不要发到聊天或提交GitHub。保存并按控制台要求重新部署。打开`https://你的Worker网址/admin`登录。后台有模式/版本筛选、人数与进度、人工样本审核、导入导出、备份、QuickForm同步和邀请码管理。改密码会使旧后台登录失效；普通受访者Cookie不具有管理权限。

Windows本地双击`启动_Workers本地演示.cmd`；先安装Node.js 22+。也可在本目录执行`npm ci`、`npm run dev`。本地管理账号需复制`.dev.vars.example`为`.dev.vars`并填写自己的密码；该文件被Git忽略。本地D1放在`.wrangler`，与线上D1分开。`npm run db:local`可显式初始化本地库。

## 模式及QuickForm：本次正式接口仍禁用

默认`DCE_MODE=demo`，演示永不建QuickForm任务、不上传。网页可重新体验，后台可指定广告组/区组，每次建立新记录。demo、pilot、formal分别统计、导入、导出。

现有正式配置地址仍为`https://quickform.cn/api/kajm9wjasx`。`QUICKFORM_API_URL`保留此默认值；**本迁移验收版有服务端发布锁，正式QuickForm通道强制关闭**。即使误设`QUICKFORM_FORMAL_ENABLED=YES`也不会向正式接口发送。不要通过修改模式将演示记录转换为正式记录。

测试同步应单独创建预测试任务，再显式设置：

```text
DCE_MODE=pilot
QUICKFORM_PILOT_ENABLED=YES
QUICKFORM_PILOT_API_URL=https://quickform.cn/api/独立测试任务编号
QUICKFORM_FORMAL_ENABLED=NO
DCE_ALLOW_FORMAL=NO
```

预测试接口可设为Secret，不能与当前正式任务`kajm9wjasx`或原正式任务`9lnrb0a8hn`相同。配置中的vars会随部署应用，长期修改请同步修改`wrangler.jsonc`，避免只在控制台临时修改而被下次部署还原。正式收集需另行审查并显式解锁发布代码；本次部署不启用正式收数。

只有8道题及后续问卷全部验证通过，最终提交事务才保存问卷并为非demo原生答卷创建一份不可变的待同步快照。导入记录不自动上传。Worker异步发送POST JSON UTF-8，不依赖浏览器访问QuickForm。受访者完成页只表示本地D1已保存，远端状态在后台查看。

- `pending`：待发送，或明确拒绝后的有限退避等待。
- `success`：仅HTTP 200且JSON `status=success`、未标记queued，或研究者核查确认。
- `failed`：明确失败；后台填原因后可重新同步。
- `uncertain`：超时、网络异常、HTTP 202或其他未明确确认的响应。不会自动重发，先到QuickForm按全局UUID及哈希核查；后台选择“收到”或“未收到”并记录依据。

429或带明确`retry_after`的503按间隔有限重试，默认最多3次；每次保留时间、HTTP状态、摘要及快照哈希。每分钟Cron处理队列与中断恢复。UUID仅用于身份和核查，不能保证QuickForm远端绝对不重复。原始答卷不会因失败而删除或重写。

## 导入、导出和旧数据

后台先选择目标模式和设计版本。在“导入实验数据”中上传原平台导出的`participants.csv`及`choices.csv`，或`participants.csv`及`choice_long.csv`；也可同时上传三份进行一致性校验，附`detail_views.csv`保留逐次日志。支持UTF-8 CSV及单工作表XLSX，拒绝公式；单文件8 MiB、合计原始文件9 MiB、JSON请求12 MiB。过大的数据按参与者拆成完整批次。

先预览字段、行数、重复、错误和模式/版本，再勾选确认、执行导入。原件和日志私下存入D1，可从导入日志下载原始文件。不同实例采用来源命名空间；同来源同身份必须逐项一致才跳过，冲突拒绝，不覆盖、不补造作答。设计版本/哈希、区组、原题号、题序、A/B交换及实际属性必须匹配。旧文件缺少必要溯源字段会明确拒绝，不能猜测补齐。原电脑SQLite请继续保留；迁移前先从原后台导出，再在新后台按原模式/版本导入。

“导出CSV”下载ZIP，包含：

- `participants.csv`：一人一行，分组/区组/来源/版本/背景/完成状态/人工审核/总时长。
- `choices.csv`：一人每题一行，原题号、位置交换、实际显示A/B与原始属性、选择和时间。
- `choice_long.csv`：每题A、B、N三行；`chosen`和`choice`为0/1，保留原数值编码及分析别名。
- `detail_views.csv`：逐次查看资料及服务器校正时长。
- `manifest.json`：导出时间、模式、版本、题库/广告哈希、来源及说明。

N行`opt_out=1`，商品属性、价格、规格留空，不把不购买当0元商品。新设计1 L、价格15/24/34、price_level1/2/3，原三个二水平属性编码不变。历史设计单独保存，导出真实历史规格/价格。详情查看行为是额外过程变量，不作为核验的因果效应。完成答卷仍为待审核，“有效”须研究者人工标记。

QuickForm导出含`dce_choices_json`的完整CSV或JSON后，在本目录执行：

```bash
npm run recover:quickform -- quickform-export.csv choice_long-recovered.csv
```

离线脚本核对设计、任务、交换与实际属性后还原长格式；不覆盖原文件或已经存在的输出文件，不生成缺失选择。完整字段见`docs/Workers_数据字典.md`及`docs/QuickForm_字段字典.md`。

## 备份和恢复

后台“创建备份”按当前模式/版本生成ZIP并提供下载。Cron每6小时分别生成各模式/版本快照，原件和哈希存入私有D1。它们与业务库同处D1，**还需要定期下载到研究者独立存储**，不能把同库副本当成独立灾备。查看Cloudflare D1控制台的Time Travel/Export功能，按自己的套餐确认保留窗口；恢复生产库前先导出当前库，优先恢复到单独测试库核对。Worker不提供公开恢复接口。

CSV恢复可在新建空D1后通过后台预览确认导入，保留真实来源和历史版本；或使用Cloudflare D1 Time Travel恢复整个库。批量数据超过应用导出/备份限制时使用Cloudflare D1原生导出，不要关闭校验硬塞大文件。研究结束后按知情同意期限清理业务记录、导入原件、快照及外部副本；当前联系邮箱为`230259627@seu.edu.cn`，政策保留位置在`config/study_config.json`。

## 验证与上线边界

`npm test`运行真实本地workerd和D1，外网全禁，模拟QuickForm，覆盖四广告组/全部任务/交换、8题、重复提交、并发均衡、刷新持久化、过程详情、CSV/XLSX、导入去重/错误留档、权限/CSRF、统计审核、邀请码、同步状态/退避/模式隔离及QuickForm长格式还原。`npm run build`再做类型检查、设计和广告原始字节哈希校验、Wrangler预演。

可选浏览器验证：先安装Python Playwright及Chromium，终端1执行`node worker/tests/serve-browser.mjs`，终端2执行`python worker/tests/browser_e2e.py`；此服务只绑定127.0.0.1，使用专门测试账号和隔离本地库，无任何真实上传。生产运行不需要Python。

本次通过的是本地Cloudflare运行时及浏览器验证，不能替代你账户上的D1权限、绑定、HTTPS域名、Secrets、Cron、套餐限额及真实多设备验收。部署后先保留demo，核对`/health`、广告与后台导出。正式QuickForm保持关闭；不要把演示或自动化样本送进正式任务。
