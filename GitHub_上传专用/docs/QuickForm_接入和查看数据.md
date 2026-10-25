# QuickForm接入、同步与数据恢复

本版继续使用现有Study2_DCE_Web、原SQLite答卷、4个广告组、16题双区组及每人8题设计。环境核验和质量信息仍为0/1，广告素材不变，收集接口按用户最新指定更新；当前运行设计已更新为1 L单盒、15/24/34元（study2-1l-3price-v2），旧版另行保存。购物界面、详情面板、查看过程记录、研究者认证、导入汇总和备份功能保留。

## 先分清：实验网址和QuickForm收集任务

当前代码已包含QuickForm后端同步功能，按用户最新指定，正式任务地址为 `https://quickform.cn/api/kajm9wjasx`；仅配置地址不代表已开启发送。当前demo不上传，新设计的正式收集仍锁定。

受访者打开实验网址 → Python后端保存完整答卷到SQLite → 后端按模式同步QuickForm → 研究者登录QuickForm查看对应任务的数据。

### 先测试QuickForm连接

1. 登录 https://quickform.cn ，为预测试单独新建一个收集任务，复制该任务的API地址。不要复用正式任务kajm9wjasx。
2. 将「管理工具/quickform.env.example.cmd」复制到项目根目录，命名为「quickform.env.cmd」。保留正式地址和正式开关关闭，只填写自己的独立预测试地址，将 `QUICKFORM_PILOT_ENABLED` 设为 `YES`。
3. 停止当前演示服务，再运行「管理工具/启动_预测试.bat」。用浏览器完整完成8题及后续问卷。
4. 在本平台/admin的「QuickForm数据同步」检查状态，并在QuickForm中打开刚建立的预测试任务查看数据。成功需确认HTTP 200且JSON status=success；若为uncertain先查重，不能连续重发。

### 再发布可供他人访问的实验网址

本项目同时需要Python服务和可持久保存的SQLite文件。应将不含私有数据的「dist/Study2_DCE_Web_升级源码.zip」部署到能持续运行Python且有持久磁盘的服务器，再绑定公网HTTPS网址。先以demo或pilot上线；收集接口和设计审批保持原样。

QuickForm官方上传入口接收单个HTML/HTM（最大4 MB），可生成该HTML的访问链接。直接上传本项目static/index.html不能运行完整实验：页面仍要请求Python后端的/api/state、/api/answer、/api/finish等接口，且需要其随机分配、恢复和保存逻辑。HTML上传不能替代本项目后端部署。

部署需要确定服务器/托管环境、域名或HTTPS访问地址、研究者后台账号。后台密码应在服务器上设置，不在聊天或源码中公开。数据库、导出、备份及凭据不得放在公开静态目录中。

正式上线仍需确认新设计并完成预测试、填写研究者联系方式及数据保留/撤回说明、设置后台账号、HTTPS、安全Cookie及邀请码。此说明不会代替研究者确认，也不会自动打开正式收数。

QuickForm官方参考：https://quickform.cn/cli （第6节HTML上传、第7节数据接口）。

## 1. 默认地址与显式开关

2026-10-25：用户将kajm9wjasx指定为正式任务。原9lnrb0a8hn不再作为默认发送目标。两个曾指定正式的任务均不可用于pilot；现有待发快照不自动重定向。预测试地址已清空、发送开关已关闭；正式设计审批保持原样。

正式接口默认值是 `https://quickform.cn/api/kajm9wjasx`，通过环境变量 `QUICKFORM_API_URL`覆盖。**仅设置地址不会启用真实上传。**

| 模式 | 建单与发送 |
| --- | --- |
| demo | 不建同步任务，永不发送 |
| pilot | 完成后建立独立pilot任务；设置独立QUICKFORM_PILOT_API_URL和QUICKFORM_PILOT_ENABLED=YES才发送 |
| formal | 完成后建立formal任务；DCE_MODE=formal、DCE_ALLOW_FORMAL=YES、QUICKFORM_FORMAL_ENABLED=YES才发送 |

pilot地址不能等于正式地址，也不能指向正式任务的同一路径，即使域名不同也拒绝。HTTP重定向不跟随，防止重新路由到其他任务。生产外部地址必须是HTTPS；测试开关QUICKFORM_ALLOW_LOCAL_TEST=YES只允许127.0.0.1/localhost/::1环回模拟接口，若仍指向真实地址则配置报错。测试时绕过系统代理，不会借代理把模拟答卷发到外网。

旧quickform.local.json和QUICKFORM_ENDPOINT/QUICKFORM_MODES不再用于启用收集，避免沿用旧配置意外上传。原私有文件已有data/backups校验备份，旧归档已按用户要求移至Windows回收站，迁移前源代码也已备份。旧quickform_outbox保留原样；如有旧任务，其状态统一置于新的“需人工核查”队列，不自动重发或把旧sent/202当作成功。本次原库旧队列为空。

## 2. Windows一键启动

1. 先运行 `管理工具/设置_研究者账号.bat` 设置后台账号（需停止现有服务）。
2. 演示：双击 `一键启动_本地演示.bat`，不上传。入口http://127.0.0.1:8000；后台/admin。
3. 把 `管理工具/quickform.env.example.cmd` 复制到项目根目录并命名为 **quickform.env.cmd**。该文件为私有可执行批处理配置，只能填写自己信任的命令，不进源码包/版本库。
4. 预测试：在私有配置填写独立测试地址与QUICKFORM_PILOT_ENABLED=YES，双击 `管理工具/启动_预测试.bat`。未启用时本地保存及待同步任务仍保留。
5. 正式调查：完成config/study_config.json伦理、联系、保留/撤回说明，设置ready_for_formal=true；配置HTTPS反向代理，再在私有配置有意设置DCE_ALLOW_FORMAL=YES、DCE_SECURE_COOKIE=1、QUICKFORM_FORMAL_ENABLED=YES，双击 `管理工具/启动_正式调查.bat`。正式模式强制一次性邀请码。本版还有config/design_approval.json硬锁：researcher_approved和pilot_completed均为false，未获用户确认及预测试完成记录前，任何正式启动或发送均被拒绝；环境变量不能绕过。

当前新版为study2-1l-3price-v2，1 L单盒15/24/34元。默认配置模板全部关闭收集开关。本次没有为研究者开启正式收集，也没有向真实QuickForm提交测试答卷。后台账号存放在所选DCE_DATA_DIR下；切换私有数据目录后需在该目录重新设置账号。Cookie的Secure配置不等于已经架设HTTPS，正式访问应通过反向代理的HTTPS地址。

PowerShell正式配置示例（须先完成上述前置工作）：

```powershell
$env:DCE_MODE='formal'
$env:DCE_ALLOW_FORMAL='YES'
$env:DCE_SECURE_COOKIE='1'
$env:QUICKFORM_API_URL='https://quickform.cn/api/kajm9wjasx'
$env:QUICKFORM_FORMAL_ENABLED='YES'
python server.py invitations --count 100
python server.py
```

预测试只设置独立地址：

```powershell
$env:DCE_MODE='pilot'
$env:QUICKFORM_PILOT_API_URL='https://quickform.cn/api/替换为独立测试任务编号'
$env:QUICKFORM_PILOT_ENABLED='YES'
python server.py
```

不同数据模式及设计版本在本地查询、发送和导出时均独立筛选。后台的“设计版本”选择器可读取旧版，默认使用新的候选设计；不合并版本。可继续设置DCE_DATA_DIR做物理隔离；本次不拆分或丢弃原数据库。

## 3. 提交顺序与成功定义

前7题及第8题都不向QuickForm发记录。消费者完成8题、提交全部必填后续问卷后，后端在同一SQLite事务中保存完成状态、真实答案及一条不可变的待发JSON快照，然后提交事务，再作第一次POST。网络失败不会撤销本地完成，也不会要求消费者重填。第一次尝试有超时上限，随后显示完成及统一研究说明。

后台线程只处理已启用模式、原目标地址及当前设计版本的到期任务。本版正式发送另受设计确认与预测试硬锁约束。最终提交、刷新、并发重复提交均不会再次发送已确认成功的答卷；本地每参与者只有一条同步任务。已完成但以前没有同步任务的历史答卷，不自动补发；研究者可审查后单独建单。导入的其他实例答卷不在本实例自动再次上传，以免集中汇总后重复收集。

严格成功条件：**HTTP 200且JSON对象中status为success，并且不是queued=true**。官方公开说明见[QuickForm接口说明第7节](https://quickform.cn/cli)。HTTP 202可能是排队，不能等同于已持久化。

| 状态 | 处理 |
| --- | --- |
| pending | 等待发送、未显式启用或等待有限退避重试 |
| success | 收到约定成功确认，或研究者已核实远端收到；后台会区分两种确认来源 |
| failed | 明确拒绝或已证明未建立连接；达到自动重试上限后保留，可人工修复后重试 |
| uncertain | 超时、断连、202排队、未知2xx/确认格式、非明确拒绝的5xx或发送期间进程中断；不自动重发 |

默认自动最多3次尝试（含第一次），可通过QUICKFORM_MAX_ATTEMPTS设置1–5。仅明确可重试的连接未建立、429及带retry_after的503进行重试；普通字段/权限拒绝需先修复再人工重试。基础退避默认10秒，后续按4倍增加，尊重更长的Retry-After/retry_after。可设置QUICKFORM_BACKOFF_SECONDS（1–3600），超时QUICKFORM_TIMEOUT_SECONDS（0.1–30，默认8）。达到上限不会无限循环。

单纯配置变化不会静默把已建单答卷改发另一个任务。队列保留原target_url、payload_sha256及每次尝试。未配置地址的pilot待发任务，在研究者明确启用独立测试地址后可用“重新同步尚未发送记录”绑定；已尝试/已绑定的其他目标必须先核查。

## 4. 后台查看、失败重试与不确定核查

登录/admin，找到“QuickForm数据同步”。上方模式选择同时控制此区：

- 查看本地完成数、成功/待同步/失败/需核查数、未建单数、最近尝试时间及单条状态。
- 用本地编号或全局UUID查找；“查看记录”仅向已认证研究者显示不可变待发快照、每次响应摘要及人工操作日志。
- 明确失败：排查字段/权限/网络原因，点“准备重试”，填写至少5字原因后执行。原始选择和待发快照不变。
- 不确定：先在QuickForm后台按participant_id全局UUID和record_sha256核查。确认已收到可人工标记成功；确认未收到，勾选风险确认并记录依据后才重新排队。
- 已安排退避的pending不允许用手动按钮绕过间隔；已成功记录不允许重试。
- 只有当前服务器模式可执行相应队列的写操作，demo始终禁用。查看其他模式的数据不会导致发送。

**UUID及本地唯一键不能保证远端绝对不重复。** 本次没有证据表明QuickForm支持原生幂等键。超时后可能已写入、202以后可能异步落库；即使人工核查时尚未看到，仍有延迟/重复风险。不要删除本地原始答卷，不能凭一次查询未发现就声称绝对安全重发。人工确认及重试均有日志，不会自动改写论文结论。

“导出同步日志”下载每次尝试的CSV，包括本地编号、全局UUID、模式、设计版本、次数、开始/结束时间、HTTP状态、outcome、错误及响应摘要、快照哈希。单条页面另含人工核查/重试说明。普通消费者没有这些接口的权限。

本地命令（状态/导出可在服务运行时读取；重试/处理队列需先停止同库服务，文件锁防止多进程重复处理）：

```powershell
python server.py quickform-status
python server.py quickform-logs
python server.py quickform-sync
python server.py quickform-retry --participant-id '本地编号' --note '已核实失败原因并完成修复'
```

不带编号/原因运行quickform-retry会在Python中提示输入，避免把输入拼成shell命令。`管理工具/查看QuickForm同步状态.bat`、`管理工具/重试QuickForm同步.bat`和`管理工具/导出数据_当前模式.bat`读取私有quickform.env.cmd中的模式。后台仍是日常管理入口。

## 5. 字段、身份与展示内容

完整字段定义见 [数据字典](QuickForm_字段字典.md) 和 [机器可读字段表](quickform_fields.json)。一个QuickForm记录对应一个完整参与者，扁平字段task_1_至task_8_按该人的实际页面呈现顺序编号，并非固定T01至T08。

- QuickForm participant_id/participant_uuid使用稳定的全局命名空间UUID，按来源实例、来源原编号及模式生成；本地旧participant_id不改写。QuickForm另有local_participant_id、source_instance和source_participant_id。本地CSV新增participant_uuid，可据此连接QuickForm记录。
- 新建本地参与编号为UUID4；旧编号原样保留。全局UUID不会与参与者Cookie、管理员账号或权限凭据混用。
- 每个task_i_A/B属性包含数值及_text文案，另有选择、真实任务编号、呈现顺序、交换位、开始/提交时间与每题时长。
- dce_choices_json为8道实际选择的JSON字符串，含显示A/B数值、实际展示文案、原始组合、交换位、时间及四项查看过程变量。服务器首次展示该题时保存文案快照；之后的同步重试使用同一快照，避免文案更新造成历史错配。
- 历史未采集的题目开始时间、文案或广告版本保持空值，并注明not_recorded_legacy，不能拿当前文案冒充过去实际所见。
- questionnaire_json及原字段保留年龄、性别、学历、线上食品购物频率、植物基饮品购买经验、广告类型/AI披露回忆。当前没有单独燕麦饮购买经验题及绿色消费价值观量表，其字段状态为not_collected，值为null，不把植物基经验冒充燕麦饮经验。
- questionnaire_schema.json的fields为空；未来需由研究者开发对应题目并注册扩展字段后，才能接收additional_answers。未配置字段被服务端拒绝，不能代填量表。

过程变量只描述自主查看行为，不直接当作第三方核验的因果效应。

## 6. 原始CSV、长表与QuickForm还原

后台原有“导出CSV及清单”和同步区“导出原始与长格式CSV”均下载participants.csv、choices.csv、choice_long.csv、detail_views.csv及manifest.json。命令行 `python server.py export` 也按DCE_MODE导出到私有exports目录。

原建模字段全部保留。新版购买备选项另有product_volume_ml=1000、price_level=1/2/3，以及price_yuan=15/24/34；原有price与price_yuan一致。长表新增同义字段alternative_id、chosen、origin、environmental_verification、quality_information、price、visual_type、dce_block，数值与原alternative/choice/origin_import/third_party_verification/batch_quality_report/price_yuan一致。每题三行，N的opt_out=1，属性和price为空，不是0元商品。

从QuickForm下载CSV或JSON后，可以在本机还原长表：

```powershell
python scripts/restore_quickform_export.py 'QuickForm导出的答卷.csv' --mode formal --output-dir 'exports\quickform_restored_formal'
```

支持普通JSON数组、带submissions的JSON及带data包装的任务迁移记录。逐条验证当前设计哈希、模式、区组、8题、交换位、显示属性与扁平选择一致性，再展开为每人24行。重复UUID、缺题、异版本或异模式报错，不补造、不覆盖已有输出文件，也不自动删远端重复记录。还原不向任何接口发送请求。请保留QuickForm原文件及还原清单。

## 7. 本地测试与部署边界

测试入口：`python -m unittest discover -s tests -v`。QuickForm相关测试仅使用环回HTTP模拟服务，覆盖一次完整提交、UTF-8、A/B交换、成功、明确拒绝、退避上限、超时/202不确定、刷新与并发防重复、后台重试及日志、模式隔离、进程中断、后台线程重试及远端导出还原。

原数据库、导入原件、备份、同步快照和凭据均在私有data中，不在静态白名单内。代码包排除data、exports、测试截图、私有quickform.env.cmd及旧quickform.local.json。正式上线仍须完成原README中的伦理说明、广告核查、HTTPS、邀请码、访问控制与备份恢复要求。QuickForm不取代本地原始研究数据库或正式统计分析。
