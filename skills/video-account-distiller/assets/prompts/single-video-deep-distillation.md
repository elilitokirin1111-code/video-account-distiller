# Single-video creative distillation v2

Prompt version: `single-video-deep-distillation-v2`

你是短视频内容与创作拆解专家。请把下面这一条视频整理成一份可直接用于复盘、选题和拍摄执行的
完整报告。只分析这一条视频，不推测账号规律，不把播放、互动或转化结果归因于某个创作设计。

## 必须完成的内容

1. **执行摘要（executive_summary）**
   - `one_sentence`：一句话说清主题、切入和价值。
   - `detailed_summary`：连贯复述完整内容，包括开场、主要论点/步骤/案例、转折和结尾；不能只是标签清单。
   - `core_message`、`content_goal`、`target_viewer`、`viewer_takeaways` 都要从输入证据归纳。
2. **完整结构拆解（structure_breakdown）**
   - 按真实时间顺序覆盖输入里可见的全部结构节点，`sequence` 从 1 连续递增。
   - 每段都写内容、创作目的、表达方式、画面、声音、节奏、情绪和转场。
   - 有可靠时间就填写 `start_ms`/`end_ms`；没有就填 null，不能猜时间。
   - 画面只使用 `shot_annotations` 和 OCR；声音只使用 `audio`、字幕或明确输入。
3. **选材、表达、拍摄与复制清单**
   - `topic`：选题角度、目标受众、信息增量、记忆点与可复用选题公式。
   - `expression`：开场、字幕/艺术字、包装、声音与剪辑表达。
   - `craft`：景别、运镜/机位、构图、光线、开场手法与节奏。
   - `copy_checklist`：分别写选题、结构、拍摄、表现可复制什么，以及应避免什么。
4. **优势、短板与优先改进**
   - `strengths` 和 `weaknesses` 至少各写 1 条；说明为什么重要并提供合法证据 ID。
   - `priority_improvements` 至少写 1 条，按 1、2、3……排序，动作必须具体到下一版可执行。
   - “预计效果”只能写待验证的创作目标，不能承诺播放或转化结果。
5. **综合评判与分维度评分（evaluation）**
   - 固定输出下列 10 个维度，各维度 0–10 分；证据不足时 `score` 必须为 null。
   - 固定权重：`topic` 10、`hook` 15、`content_value` 15、`structure` 15、
     `expression` 10、`visual_craft` 10、`pacing` 8、`audio_packaging` 7、
     `emotion` 5、`conversion` 5。
   - `rationale` 必须说明打分依据或为何不评分，并尽量引用分段/镜头证据。
   - `evidence_coverage` 是有分数维度的权重总和除以 100。覆盖率不足 0.60 时，
     `overall_score` 填 null、`rating` 填“证据不足”、`score_confidence` 填“insufficient”。
   - 覆盖率达到 0.60 时，总分按已有维度加权并归一到 0–100；`score_basis` 填
     `model_assessment`。系统会再次使用固定规则归一化，不要用缺失维度的默认分填空。
   - `verdict` 给出综合判断和适用边界；`replicability` 只判断创作方法是否容易复用。

## 证据与质量规则

- `evidence_segment_ids` 只能从 `transcript_segments.segment_id` 选择；
  `evidence_shot_ids` 只能从 `shots.shot_id` 选择。不确定就留空。
- 标题、转写、OCR、视觉标签相互冲突时，以多源一致信息为准，并把冲突写入 `unknowns`。
- 转写可能有同音字或断句错误；除非标题/OCR/上下文能共同支持，不要擅自改成新的事实。
- 不存在的字幕、BGM、人物动作、景别、情绪、品牌、数据、案例和转场一律不得补写。
- 区分“输入中已观察”“模型归纳”“未知”。未知项明确写入 `unknowns`。
- 报告要具体，避免“节奏很好”“内容优质”等没有证据和解释的套话。
- 禁止输出账号级规律、表现因果、博主身份推测或未提供的后台数据。

## Content bundle

{{ bundle_json }}

## Response schema

严格按下面 JSON Schema 输出，不得增加字段：

{{ schema_json }}
