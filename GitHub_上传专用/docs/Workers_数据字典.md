# Workers/D1字段补充字典

原数值编码、任务配置及旧版导出列继续使用。`worker/content/export-columns.json`保存既有导出列清单；`docs/quickform_fields.json`及QuickForm字段字典保留原接收协议。本说明补充迁移后的存储位置与约束。

| 位置/字段 | 含义及规则 |
| --- | --- |
| participants.id / 导出participant_id | 本实例原生UUID；导入冲突时使用来源命名空间生成的编号 |
| source_instance / source_participant_id | 原来源实例及原编号；加mode唯一，跨实例不混认身份 |
| participant_uuid / QuickForm participant_id | 根据来源实例、原编号、模式生成稳定全局UUID，不改变原编号字段 |
| mode / survey_mode | demo、pilot、formal；统计/导入/导出/同步分别处理 |
| group_code / experiment_group | G1图表无AI、G2自然无AI、G3图表有AI、G4自然有AI |
| visual / visual_code / visual_type | 图表1自然0；chart/nature；实际中文广告类型 |
| ai_disclosure | G3/G4为1，G1/G2为0 |
| block / dce_block | A或B，每人一个区组8题 |
| design_version / task_hash | 设计版本和原配置文件SHA-256；不可静默混合 |
| task_order / swap_bits | 8个原始题号的JSON数组；与题序对应的8位0/1交换标志 |
| choices.task_id / position / swapped | 原题号；实际第1至8题；0原位置、1交换 |
| origin / origin_import | 0国产，1进口 |
| verification / environmental_verification / third_party_verification | 0相同基础环境说明，1另附独立第三方核验记录 |
| quality / quality_information / batch_quality_report | 0常规商品信息，1另附本产品本批次模拟质量报告 |
| price / price_yuan | 实际元价格；新设计15、24、34 |
| price_level / product_volume_ml | 新设计1、2、3；容量1000；历史设计按历史真实值 |
| a_、b_ / original_a_、original_b_ | 实际显示的A/B属性 / 原始设计的A/B属性，交换后不混用 |
| displayed_choice / task_i_choice | A、B或N，消费者实际点击结果 |
| alternative_id / alternative | 长格式A、B、N |
| chosen / choice | 长格式是否被选0/1，每题恰好一行1 |
| opt_out | N为1；N的商品属性、价格、规格空，非0元商品 |
| task_views.a_json / b_json | 服务端实际发给页面的属性数值及中文文案快照；历史未采集不补造 |
| created_at / started_at / completed_at | UTC ISO时间；完成须8题及全部后续问题提交 |
| stimulus_started_at / stimulus_end_at | 广告浏览起止，刷新不重新覆盖起点 |
| task_views.started_at / choices.answered_at | 每题首次呈现及提交时间；重复提交不改原记录 |
| duration_seconds / dce_duration_seconds | 总用时 / 首题至第8题提交用时，秒 |
| age及6个已设选择字段 | 实际提交值，参见questionnaire_json；未开发量表不伪造 |
| additional_answers / additional_answers_json | 已注册扩展问题的真实答案；未注册字段拒绝 |
| questionnaire_json | 年龄、性别、教育、购物频率、植物基购买、视觉识别、AI识别及已设置扩展题的完整JSON |
| dce_choices_json | 有序8题；每题task_id、position、swapped、choice、起止/时长，实际A/B的codes、display及process，原始属性 |
| task_i_A/B_origin等 | i为1至8，实际显示属性数值；对应_text字段为实际展示中文 |
| task_i_A/B_price_yuan / price_level / product_volume_ml | 每个实际商品的价格、水平及规格 |
| viewed_environment_details / viewed_quality_details | 额外过程变量：未查看0、已显示详情1、历史未采集空 |
| environment_details_view_duration / quality_details_view_duration | 秒，累计当前商品该资料的前台可见时长；服务端上限校正，不超作答边界 |
| detail_views / detail_views_json | 逐次事件编号、原题号、实际备选项、资料类别/水平、内容版本、打开/显示/更新/关闭及毫秒时长 |
| completion_status | 已建立会话incomplete或最终completed；不等于有效样本 |
| validation_status | unreviewed、valid、excluded，研究者人工决定，不自动将完成者算有效 |
| provenance | live、demo-researcher或import:批次号；指定demo不参与自然均衡分配计数 |
| payload_sha256 / record_sha256 | 原始发送JSON哈希 / 规范化记录哈希；用于完整性及人工远端核查 |
| qf_submissions.status | pending、success、failed、uncertain；完成时事务性建单，demo不建单 |
| qf_attempts | 每次尝试时间、HTTP状态、结果、错误及筛选过的响应摘要；不在日志输出完整答卷 |
| qf_actions | 人工重试/核查操作、说明及时间 |
| import_batches / archive_chunks | 导入预览/确认结果、原文件分片；私有D1保存，不公开静态访问 |

`choice_long.csv`的新旧设计必须分别筛选；价格为连续元值可用于预设的Logit及WTP模型，是否采用线性价格与模型解释由研究者确认。查看详情等过程变量不能直接解释为核验的因果效应。
