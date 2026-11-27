# 单视频语义标注

Prompt version: `video-semantic-labeling-v2`

按响应分类体系标注输入内容。所有非未知的钩子、结构、情绪、行动引导和内容方向判断，
都必须引用真实存在的 `segment_id`。不得虚构画面特征、受众意图、因果解释或账号级规律；
置信度应保守，不确定项写入 `unknowns`。

除 JSON 字段名、Schema 固定枚举值和证据 ID 外，所有面向读者的自由文本必须使用简体中文。
例如内容方向应写“餐饮与美食”，不能写 `Food & Dining`；说明原因时也不要夹杂英文状态词。
只返回符合响应 Schema 的 JSON 对象。

## 内容包

{{ bundle_json }}

## 已验证事实

{{ facts_json }}

## 响应 Schema

{{ schema_json }}
