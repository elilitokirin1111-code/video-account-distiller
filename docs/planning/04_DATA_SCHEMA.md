# 数据模型与字段字典

## 1. 通用规则

所有核心记录包含：

```text
schema_version
record_id
source_platform
source_type
source_uri
source_record_id
collected_at
ingested_at
run_id
raw_hash
data_quality_flags
```

未知字段使用 `null`，禁止将未知值写成 0、空字符串或 false。

## 2. Account

```text
account_id: string
platform: enum
platform_account_id: string
handle: string|null
display_name: string|null
bio: string|null
profile_url: string|null
verified: bool|null
follower_count_current: int|null
following_count_current: int|null
total_likes_current: int|null
video_count_current: int|null
category_raw: string|null
country_or_region: string|null
language: string|null
created_at: datetime|null
snapshot_at: datetime
```

## 3. Account Snapshot

```text
account_snapshot_id
account_id
snapshot_at
followers
following
total_likes
video_count
profile_views
source
```

## 4. Video

```text
video_id
account_id
platform
platform_video_id
url
title
description
published_at
duration_seconds
content_type
language
is_ad
is_pinned
is_deleted
is_repost
music_title
music_author
hashtags[]
mentions[]
cover_path
media_path
transcript_path
follower_count_at_publish
```

`follower_count_at_publish` 与当前粉丝数必须分开。

## 5. Metric Snapshot

```text
metric_snapshot_id
video_id
snapshot_at
age_hours
views
impressions
likes
comments
shares
saves
favorites
follows_gained
profile_visits
avg_watch_time_seconds
completion_rate
three_second_view_rate
five_second_view_rate
clicks
leads
orders
revenue
is_promoted
promotion_spend
metric_source
```

## 6. Derived Metrics

```text
video_id
snapshot_at
like_rate_by_view
comment_rate_by_view
share_rate_by_view
save_rate_by_view
engagement_rate_by_view
engagement_rate_by_follower
follow_conversion_rate
profile_conversion_rate
completion_efficiency
view_velocity_1h
view_velocity_24h
viral_index_account
viral_index_peer
performance_score
performance_band
outlier_flags[]
```

## 7. Transcript Segment

```text
segment_id
video_id
start_ms
end_ms
text
speaker
confidence
language
source
```

## 8. Shot Segment

```text
shot_id
video_id
start_ms
end_ms
shot_type
camera_motion
scene
subject
face_count
text_density
visual_change_score
keyframe_paths[]
```

## 9. Audio Features

```text
video_id
speech_ratio
music_ratio
silence_ratio
estimated_speech_wpm
beat_bpm
loudness_mean
loudness_variance
sound_effect_count
```

## 10. Video Content Analysis

```text
analysis_id
video_id
analysis_version
model_provider
model_name
prompt_version

primary_pillar
secondary_topics[]
audience_tasks[]
content_goal
funnel_stage

hook:
  primary_type
  secondary_types[]
  hook_text
  hook_start_ms
  hook_end_ms
  promise
  curiosity_gap
  visual_hook
  evidence

structure_segments[]
narrative_type
information_density
emotion_timeline[]
cta:
  type
  text
  alignment_score

persona_signals[]
language_signals[]
visual_signals[]
production_cost_level
replicability_score
risk_flags[]
unknowns[]
```

## 11. Comment

```text
comment_id
video_id
platform_comment_id
parent_comment_id
author_hash
text
created_at
like_count
is_creator_reply
is_pinned
language
```

## 12. Comment Signal

```text
comment_signal_id
comment_id
sentiment
intent_labels[]
pain_points[]
questions[]
objections[]
purchase_intent
identity_signal
content_opportunities[]
spam_probability
confidence
```

## 13. Pattern

```text
pattern_id
account_id|null
benchmark_group_id|null
pattern_type
name
description
feature_conditions
target_metrics[]
support_video_ids[]
counterexample_video_ids[]
support_count
counterexample_count
effect_summary
confounders[]
scope:
  platforms[]
  pillars[]
  account_stages[]
  duration_range
confidence
maturity_level
created_at
last_validated_at
version
```

## 14. Rule

```text
rule_id
source_pattern_ids[]
name
instruction
scope
required_conditions[]
forbidden_conditions[]
expected_effect
target_metric
confidence
evidence_count
experiment_count
status
version
approved_by
approved_at
```

状态：

- candidate
- experimental
- validated
- deprecated
- rejected

## 15. Rubric

```text
rubric_id
account_id
version
dimensions:
  - dimension_id
    name
    weight
    scoring_guide
    evidence_rule_ids[]
created_at
```

## 16. Content Candidate

```text
candidate_id
account_id
title
topic
script_path
shot_plan_path
target_platform
target_pillar
target_metric
created_at
```

## 17. Score Result

```text
score_id
candidate_id
rubric_id
total_score
dimension_scores[]
strengths[]
weaknesses[]
required_fixes[]
risk_flags[]
evidence[]
created_at
```

## 18. Prediction

```text
prediction_id
candidate_id
account_id
rubric_id
rule_versions[]
created_at
target_snapshot_age_hours
target_metrics:
  views:
    p25
    p50
    p75
  engagement_rate:
    p25
    p50
    p75
confidence
positive_factors[]
negative_factors[]
uncertainties[]
input_hash
immutable: true
```

## 19. Publication

```text
publication_id
candidate_id
prediction_id|null
video_id
published_at
url
platform
notes
```

## 20. Retro

```text
retro_id
publication_id
prediction_id|null
evaluated_snapshot_at
actual_metrics
prediction_errors
supported_rule_ids[]
counterexample_rule_ids[]
external_factors[]
lessons[]
rubric_change_proposals[]
next_experiments[]
created_at
```

## 21. 数据质量标志

建议枚举：

- `missing_views`
- `missing_publish_time`
- `unknown_follower_at_publish`
- `current_follower_used_as_proxy`
- `suspected_paid_traffic`
- `suspected_repost`
- `deleted_content`
- `metric_snapshot_inconsistent`
- `transcript_low_confidence`
- `comment_sample_partial`
- `platform_metric_not_comparable`
- `small_sample`
- `outlier`
- `manual_override`

## 22. 平台字段映射

每个平台参考文件必须明确：

- 播放/阅读字段定义。
- 收藏与喜欢区别。
- 分享是否可见。
- 粉丝增长是否可见。
- 完播率定义。
- 指标更新时间。
- 商业投流标记。
- 无法获取的字段。
- 合法采集方式。
- 跨平台不可比字段。

## 23. ID 规则

内部 ID 使用稳定前缀：

- `acc_`
- `vid_`
- `ms_`
- `cmt_`
- `pat_`
- `rule_`
- `rub_`
- `cand_`
- `pred_`
- `pub_`
- `retro_`
- `run_`

推荐 UUIDv7 或内容哈希加平台 ID。
