# 单视频事实提取

Prompt version: `video-fact-extraction-v2`

只提取标题、描述和转写中明确可观察的事实，不添加外部知识或输入中没有的画面、声音细节。
缺失信息使用 `null` 或写入 `unknowns`；每条事实必须引用输入中真实存在的 `segment_id`。
除 JSON 字段名、Schema 固定枚举值和证据 ID 外，所有面向读者的文本必须使用简体中文，
不得输出英文分类名称或英文说明。只返回符合响应 Schema 的 JSON 对象。

## 内容包

{{ bundle_json }}

## 响应 Schema

{{ schema_json }}
