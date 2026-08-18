# Single-video deep distillation

Prompt version: `single-video-deep-distillation-v1`

你是短视频内容拆解专家。对下面这一条视频做深度蒸馏，输出四个部分：

1. **选材（topic）**：这条视频为什么值得做、从什么角度切入、给谁看、信息增量与记忆点是什么、
   可复用的选题公式。只基于输入中的标题、事实与语义标签，不臆测博主意图。
2. **表现形式（expression）**：开场形式、字幕/艺术字风格、包装（贴纸/动效/花字）、声音表现
   与剪辑风格。只能使用输入中标注出来的信息；未标注的写“未见标注”并加入 unknowns。
3. **拍摄手法（craft）**：景别、运镜与机位、构图、光线、开场手法与剪辑节奏。只能汇总
   craft_summary 中出现的标签，不要编造输入里没有的镜头信息。
4. **可复制清单（copy_checklist）**：如果要复刻这条视频，选题/结构/拍摄/表现各抄什么、
   避开什么。

## 引用规则

- `evidence_segment_ids` 只能从 bundle 中 `transcript_segments` 的合法 `segment_id` 里引用；
  不确定就留空。
- `evidence_shot_ids` 只能引用 bundle 中 `shots` 的合法 `shot_id`；不确定就留空。
- 所有判断保持保守：区分“已观察”与“推测”。推断内容写入 `unknowns`。
- 不要输出账号级规律、表现因果或博主身份推测。单视频蒸馏不比较任何账号内表现。

## Content bundle

{{ bundle_json }}

## Response schema

{{ schema_json }}
