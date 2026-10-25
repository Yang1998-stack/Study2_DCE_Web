# QuickForm及DCE编码字典（1 L三价格候选设计）

设计版本study2-1l-3price-v2；提交结构study2-qf-v2。保留现有接口与旧列别名。未开发量表仍为not_collected/null。

## DCE属性与长表

|字段|数值/含义|
|---|---|
|origin_import / origin|0国产燕麦；1进口燕麦|
|third_party_verification / environmental_verification|0基础环境说明；1相同说明另附独立核验记录|
|batch_quality_report / quality_information|0常规资料；1相同资料另附本批次检测报告|
|price_yuan / price|人民币15、24、34；购买备选项按实际售价保存|
|price_level|1=15、2=24、3=34，价格水平标签仅供研究编码|
|product_volume_ml|购买备选项1000；不购买留空|
|alternative / alternative_id|实际显示A、B、N|
|choice / chosen|0未选，1被选；每个选择集恰有一行1|
|opt_out|N为1；N的价格、价格水平、容量和产品属性为空|
|design_version|study2-1l-3price-v2；历史数据另选其版本导出|

WTP应使用实际元单位price_yuan；若按(价格-24)/10建模，需将价格系数除以10再计算属性系数与价格系数之比。price_level为非等间隔的类别编码，不能直接代替元价格。分类价格模型用于检查线性价格假设。

## 全部QuickForm固定扁平字段

|字段|类型|定义|来源|可空|
|---|---|---|---|---|
|payload_version|string|study2-qf-v2；历史study2-qf-v1只按其原设计读取|常量|否|
|record_type|string|study2_dce_completed|常量|否|
|participant_id|uuid|QuickForm全局UUID，命名空间按来源实例/原编号/模式生成|quickform_payload.participant_uuid|否|
|participant_uuid|uuid|与QuickForm participant_id相同；本地CSV连接键|同上|否|
|local_participant_id|string|本库原参与编号，不重写旧编号|participants.id|否|
|source_instance|string|最初来源实例|participants.source_instance|否|
|source_participant_id|string|最初来源参与编号|participants.source_participant_id|否|
|submission_key|string|全局UUID:设计版本，用于核查，不是远端幂等保证|派生标识|否|
|experiment_group|enum|G1图表无AI；G2自然无AI；G3图表有AI；G4自然有AI|participants.group_code|否|
|visual_type|enum|环境数据图表型 / 自然场景型|按广告组映射|否|
|visual_code|enum|chart / nature|按广告组映射|否|
|visual|integer|1图表 / 0自然，保留原统计定义|按广告组映射|否|
|ai_disclosure|integer|0无AI披露 / 1有AI披露|按广告组映射|否|
|dce_block|enum|A / B，原区组|participants.block|否|
|design_version|string|study2-1l-3price-v2；不同版本禁止无标识混合|participants.design_version|否|
|task_design_sha256|sha256|原题目配置文件哈希|participants.task_hash|否|
|survey_mode|enum|demo / pilot / formal；demo不会发送|participants.mode|否|
|started_at|iso_datetime|实验开始时间，带时区UTC|participants.created_at|否|
|completed_at|iso_datetime|全部DCE及后续问卷提交时间|participants.completed_at|否|
|duration_seconds|number|完整实验经过秒数，包含暂停|completed_at-started_at|否|
|dce_duration_seconds|number|DCE经过秒数；旧未采集为空|dce_completed_at-dce_started_at|是|
|completion_status|enum|completed；不提交未完成答卷|本地完成校验|否|
|n_choice_tasks|integer|8，固定当前区组完整题数|实际记录数校验|否|
|stimulus_started_at|iso_datetime|广告浏览开始；旧未采集为空|participants.stimulus_started_at|是|
|stimulus_end_at|iso_datetime|广告浏览结束时间|participants.stimulus_end_at|是|
|stimulus_versions_json|json_string|当时广告哈希；历史未知为空|participants.stimulus_versions|是|
|consent_version|string|实际同意说明版本；旧未知为空|participants.consent_version|是|
|questionnaire_json|json_string|所有实际采集的背景/回忆题及已注册扩展答案|participants+questionnaire_answers|否|
|green_consumption_values_json|json_string|当前为字符串null；不生成未开发量表答案|实际扩展答案，当前无|否|
|green_consumption_values_status|enum|当前not_collected；开发并实际采集后才可为collected|是否实际存在该扩展答案|否|
|oat_drink_purchase_experience|json_value|单独燕麦饮经验题，当前未开发，为null|实际扩展答案，当前无|是|
|oat_drink_purchase_experience_status|enum|当前not_collected，不冒充植物基购买经验|是否实际存在该扩展答案|否|
|age|integer|18至100周岁|participants.age|否|
|gender|enum|female/male/other/undisclosed|participants.gender|否|
|education|enum|highschool/college/bachelor/masterplus/undisclosed|participants.education|否|
|online_purchase|enum|monthly1/monthly2to3/weekly1plus/undisclosed|participants.online_purchase|否|
|plant_based_purchase|enum|yes/no/unsure：植物基饮品购买经验|participants.plant_based_purchase|否|
|manip_visual|enum|chart/nature/unsure：广告类型回忆|participants.manip_visual|否|
|manip_ai|enum|yes/no/unsure：AI披露回忆|participants.manip_ai|否|
|dce_choices_json|json_string|按实际呈现顺序保存8道完整选择，不补造记录|choices+固定题目+显示快照+过程记录|否|
|detail_views_json|json_string|实际逐次详情日志；无日志为空数组|detail_views|否|
|record_sha256|sha256|除本字段之外、按键排序的UTF-8 JSON的SHA256，用于远端核查|确定性序列化|否|
|task_1_A_origin|number|第1个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_1_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_A_environmental_verification|number|第1个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_1_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_A_quality_information|number|第1个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_1_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_1_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_B_origin|number|第1个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_1_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_B_environmental_verification|number|第1个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_1_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_B_quality_information|number|第1个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_1_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_1_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_1_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_1_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_1_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_1_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_1_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_1_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_1_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_2_A_origin|number|第2个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_2_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_A_environmental_verification|number|第2个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_2_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_A_quality_information|number|第2个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_2_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_2_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_B_origin|number|第2个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_2_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_B_environmental_verification|number|第2个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_2_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_B_quality_information|number|第2个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_2_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_2_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_2_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_2_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_2_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_2_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_2_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_2_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_2_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_3_A_origin|number|第3个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_3_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_A_environmental_verification|number|第3个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_3_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_A_quality_information|number|第3个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_3_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_3_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_B_origin|number|第3个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_3_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_B_environmental_verification|number|第3个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_3_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_B_quality_information|number|第3个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_3_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_3_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_3_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_3_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_3_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_3_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_3_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_3_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_3_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_4_A_origin|number|第4个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_4_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_A_environmental_verification|number|第4个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_4_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_A_quality_information|number|第4个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_4_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_4_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_B_origin|number|第4个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_4_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_B_environmental_verification|number|第4个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_4_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_B_quality_information|number|第4个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_4_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_4_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_4_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_4_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_4_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_4_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_4_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_4_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_4_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_5_A_origin|number|第5个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_5_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_A_environmental_verification|number|第5个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_5_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_A_quality_information|number|第5个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_5_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_5_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_B_origin|number|第5个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_5_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_B_environmental_verification|number|第5个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_5_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_B_quality_information|number|第5个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_5_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_5_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_5_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_5_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_5_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_5_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_5_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_5_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_5_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_6_A_origin|number|第6个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_6_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_A_environmental_verification|number|第6个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_6_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_A_quality_information|number|第6个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_6_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_6_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_B_origin|number|第6个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_6_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_B_environmental_verification|number|第6个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_6_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_B_quality_information|number|第6个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_6_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_6_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_6_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_6_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_6_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_6_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_6_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_6_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_6_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_7_A_origin|number|第7个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_7_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_A_environmental_verification|number|第7个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_7_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_A_quality_information|number|第7个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_7_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_7_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_B_origin|number|第7个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_7_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_B_environmental_verification|number|第7个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_7_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_B_quality_information|number|第7个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_7_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_7_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_7_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_7_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_7_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_7_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_7_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_7_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_7_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|task_8_A_origin|number|第8个实际呈现题，显示商品A：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_8_A_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_A_environmental_verification|number|第8个实际呈现题，显示商品A：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_8_A_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_A_quality_information|number|第8个实际呈现题，显示商品A：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_8_A_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_A_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_8_A_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_B_origin|number|第8个实际呈现题，显示商品B：0国产/1进口|实际A/B交换后的tasks.json origin|否|
|task_8_B_origin_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_B_environmental_verification|number|第8个实际呈现题，显示商品B：0基础环境说明/1另附独立核验记录|实际A/B交换后的tasks.json verification|否|
|task_8_B_environmental_verification_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_B_quality_information|number|第8个实际呈现题，显示商品B：0常规质量信息/1另附本批次报告|实际A/B交换后的tasks.json quality|否|
|task_8_B_quality_information_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_B_price|number|1 L单盒售价，数值15、24或34元|实际A/B交换后的tasks.json price|否|
|task_8_B_price_text|string|上述数值对应的实际显示文字；旧未记录时为空|choice_display_snapshots|是|
|task_8_id|string|原始任务编号T01至T16|choices/task_views/participants分配记录|否|
|task_8_position|integer|实际页面呈现序号1至8|choices/task_views/participants分配记录|否|
|task_8_choice|enum|A/B/N；N独立不购买|choices/task_views/participants分配记录|否|
|task_8_swapped|integer|0未交换/1已交换A/B位置|choices/task_views/participants分配记录|否|
|task_8_started_at|iso_datetime|该题首次提供时间，旧未采集为空|choices/task_views/participants分配记录|是|
|task_8_completed_at|iso_datetime|实际提交时间|choices/task_views/participants分配记录|否|
|task_8_duration_seconds|number|该题经过秒数，旧未采集为空|choices/task_views/participants分配记录|是|
|product_volume_ml|integer|本设计商品规格1000 mL；不把旧数据改记为此规格|锁定设计配置|否|
|task_1_A_price_yuan|number|第1个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_1_A_price_level|number|第1个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_1_A_product_volume_ml|number|第1个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_1_B_price_yuan|number|第1个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_1_B_price_level|number|第1个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_1_B_product_volume_ml|number|第1个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_2_A_price_yuan|number|第2个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_2_A_price_level|number|第2个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_2_A_product_volume_ml|number|第2个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_2_B_price_yuan|number|第2个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_2_B_price_level|number|第2个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_2_B_product_volume_ml|number|第2个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_3_A_price_yuan|number|第3个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_3_A_price_level|number|第3个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_3_A_product_volume_ml|number|第3个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_3_B_price_yuan|number|第3个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_3_B_price_level|number|第3个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_3_B_product_volume_ml|number|第3个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_4_A_price_yuan|number|第4个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_4_A_price_level|number|第4个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_4_A_product_volume_ml|number|第4个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_4_B_price_yuan|number|第4个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_4_B_price_level|number|第4个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_4_B_product_volume_ml|number|第4个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_5_A_price_yuan|number|第5个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_5_A_price_level|number|第5个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_5_A_product_volume_ml|number|第5个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_5_B_price_yuan|number|第5个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_5_B_price_level|number|第5个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_5_B_product_volume_ml|number|第5个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_6_A_price_yuan|number|第6个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_6_A_price_level|number|第6个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_6_A_product_volume_ml|number|第6个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_6_B_price_yuan|number|第6个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_6_B_price_level|number|第6个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_6_B_product_volume_ml|number|第6个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_7_A_price_yuan|number|第7个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_7_A_price_level|number|第7个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_7_A_product_volume_ml|number|第7个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_7_B_price_yuan|number|第7个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_7_B_price_level|number|第7个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_7_B_product_volume_ml|number|第7个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_8_A_price_yuan|number|第8个实际呈现题，商品A：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_8_A_price_level|number|第8个实际呈现题，商品A：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_8_A_product_volume_ml|number|第8个实际呈现题，商品A：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|
|task_8_B_price_yuan|number|第8个实际呈现题，商品B：实际人民币元，15/24/34，与price相同|当前锁定设计与实际A/B交换位置|否|
|task_8_B_price_level|number|第8个实际呈现题，商品B：1=15元、2=24元、3=34元；非等间隔金额，不作为连续价格代替price_yuan|当前锁定设计与实际A/B交换位置|否|
|task_8_B_product_volume_ml|number|第8个实际呈现题，商品B：1000，1 L单盒|当前锁定设计与实际A/B交换位置|否|

## 完整任务JSON

dce_choices_json每题保留task_id、position、swapped、choice、started_at、completed_at、duration_seconds、原始A/B组合，以及实际显示A/B。每个商品codes包含origin、environmental_verification、quality_information、price、price_yuan、price_level、product_volume_ml；display来自实际展示快照。过程变量仍是观察记录，不直接识别核验因果效应。

历史QuickForm快照不重写。还原脚本须按同一design_version运行；旧版元数据从旧设计解释，绝不把旧价格或规格改成新版。不同版本不能无标识合并。

record_sha256用于核查，不是QuickForm原生幂等保证；全局participant_uuid与原local_participant_id规则不变。
