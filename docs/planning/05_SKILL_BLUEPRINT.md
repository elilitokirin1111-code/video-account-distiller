# Agent Skill 设计蓝图

## 1. Skill 形态

首版建议采用“一个根路由 Skill + 内部命令模块”，而不是立即拆成十几个独立安装 Skill。

原因：

- 用户只需要安装一个 Skill。
- 账号上下文、规则库和运行状态可共享。
- 避免多个子 Skill 激活冲突。
- 稳定后再把数据采集、视频多模态分析等拆成独立 Skill。

根目录：

```text
skills/video-account-distiller/
├── SKILL.md
├── references/
├── scripts/
└── assets/
```

## 2. SKILL.md Frontmatter

建议：

```yaml
---
name: video-account-distiller
description: >
  Analyze, benchmark, and distill short-form or long-form video accounts from
  account exports, video metadata, transcripts, comments, and media files.
  Use when the user asks to 拆解视频账号、蒸馏账号、分析对标账号、分析爆款视频、
  分析账号数据、提炼内容规律、建立内容评分标准、预测脚本表现、复盘已发布视频，
  or compare creator accounts across Douyin, Xiaohongshu, WeChat Channels,
  Bilibili, TikTok, YouTube, or Instagram Reels.
license: MIT
compatibility: Requires Python 3.11+. Optional FFmpeg and model provider credentials.
metadata:
  author: your-team
  version: "0.1.0"
---
```

## 3. SKILL.md 内容结构

主文件控制在 500 行以内：

1. 目标和边界。
2. 何时激活。
3. 任务路由。
4. 前置数据检查。
5. 标准工作流。
6. 关键禁止项。
7. 输出合同。
8. 引用文件索引。
9. 脚本命令索引。
10. 错误与降级。

## 4. 任务路由

### `初始化项目`

触发：

- 初始化视频账号分析项目。
- 建一个账号蒸馏项目。
- 开始竞品研究。

动作：

1. 创建目录。
2. 创建配置。
3. 询问或读取目标平台、账号、自有账号、业务目标和可用数据。
4. 生成导入模板。
5. 输出下一步命令。

### `导入数据`

触发：

- 导入账号数据。
- 导入视频数据。
- 读取导出的 CSV。
- 添加评论或字幕。

动作：

1. 识别文件。
2. 映射字段。
3. 数据校验。
4. 保存原始数据。
5. 生成质量报告。
6. 不直接进入结论。

### `账号体检`

动作：

1. 数据质量检查。
2. 指标计算。
3. 分层采样。
4. 账号级基础统计。
5. 选取深度分析样本。
6. 输出体检报告。

### `拆解单条视频`

动作：

1. 构建分析 Bundle。
2. 先盲分析内容。
3. 再合并表现数据。
4. 输出时间轴和证据。
5. 写入视频分析记录。

### `蒸馏账号`

动作：

1. 确保样本覆盖。
2. 聚类内容。
3. 识别高低表现差异。
4. 建立 Pattern。
5. 找反例和混杂因素。
6. 输出蒸馏报告。
7. 更新账号知识库。

### `对标分析`

动作：

1. 分别建立各账号基线。
2. 禁止原始播放量简单比较。
3. 对比定位、结构、表现稳定性和模式。
4. 生成迁移矩阵。
5. 输出本账号行动方案。

### `分析评论`

动作：

1. 去重与清洗。
2. 隐私处理。
3. 意图分类。
4. 需求聚类。
5. 输出证据评论和内容机会。
6. 标记偏差。

### `给脚本打分`

动作：

1. 读取当前账号 Rubric。
2. 读取有效规则。
3. 逐维度打分。
4. 输出必改、建议改和风险。
5. 不写预测日志。

### `预测表现`

动作：

1. 先运行评分。
2. 保存不可变预测。
3. 输出分位数区间。
4. 保存假设、版本和输入哈希。

### `登记发布`

动作：

1. 关联预测。
2. 保存平台 URL 和时间。
3. 建立快照计划。
4. 不伪造实际指标。

### `复盘`

动作：

1. 读取实际数据快照。
2. 对比预测。
3. 更新证据。
4. 生成规则变更建议。
5. 默认不自动批准高权重变更。

### `状态`

输出：

- 已导入账号。
- 视频数。
- 数据质量。
- 待分析样本。
- 待复盘内容。
- 最新规则。
- 低置信度结论。
- 下一步推荐动作。

## 5. 标准执行协议

每项分析遵循：

```text
A. 明确目标
B. 检查输入
C. 生成运行 ID
D. 保存原始输入索引
E. 执行确定性处理
F. 执行模型标注
G. Schema 校验
H. 证据与反例检查
I. 生成报告
J. 更新知识库
K. 输出警告和下一步
```

## 6. 关键行为规则

### 必须

- 明确数据范围。
- 明确样本量。
- 明确缺失字段。
- 区分事实与推断。
- 强结论带支持样本和反例。
- 账号内归一化。
- 记录模型和 Prompt 版本。
- 任何预测都保存版本和输入哈希。
- 数据不足时降级，不虚构。

### 禁止

- 把点赞高直接解释成“内容好”。
- 把一个爆款当成稳定规律。
- 混用不同平台原始指标。
- 把当前粉丝数当发布时间粉丝数而不标记。
- 根据表现结果反推内容标签。
- 复制原文、原镜头或受保护素材。
- 承诺爆款或固定播放量。
- 自动执行违反平台条款的抓取。
- 覆盖人工修订而不保留历史。

## 7. 模型 Prompt 资产

建议提供：

```text
assets/prompts/
├── video-fact-extraction.md
├── video-semantic-labeling.md
├── account-positioning.md
├── comment-intent.md
├── cluster-naming.md
├── pattern-hypothesis.md
├── counterexample-review.md
├── transferability-review.md
├── content-scoring.md
└── account-report.md
```

每个 Prompt 包含：

- 角色。
- 输入合同。
- 输出 Schema。
- 允许推断。
- 禁止推断。
- 缺失值规则。
- 反例要求。
- 示例。
- 版本。

## 8. 报告模板

```text
assets/templates/
├── account-health-report.md.j2
├── account-distillation-report.md.j2
├── benchmark-report.md.j2
├── video-breakdown.md.j2
├── comment-insight-report.md.j2
├── scoring-report.md.j2
├── prediction-report.md.j2
└── retro-report.md.j2
```

## 9. 知识库规则

### Account Profile

`knowledge-base/accounts/<account-id>.md`

保存相对稳定的信息，不保存一次性猜测。

### Pattern

`knowledge-base/patterns/<pattern-id>.json`

必须带证据和反例。

### Rule

`knowledge-base/rules/<rule-id>.json`

只保存成熟度明确的结论。

### Experiment

`knowledge-base/experiments/<experiment-id>.md`

记录假设、变量、目标指标、样本和结果。

### Review

`knowledge-base/reviews/<publication-id>.md`

记录每次复盘。

## 10. Skill 输出风格

分析结果默认先给：

1. 一句话结论。
2. 最重要的 3 个发现。
3. 数据范围和可信度。
4. 行动建议。
5. 详细报告路径。

不要先输出数千字泛泛而谈。

## 11. 安装与兼容

建议支持：

- 仓库内 `.codex/skills/video-account-distiller/`
- 用户级 `~/.codex/skills/video-account-distiller/`
- 标准 Agent Skill 目录复制安装
- `skills-ref validate`

安装脚本必须：

- 支持 copy 和 symlink。
- 不覆盖用户数据。
- 显示安装路径。
- 提供卸载脚本。
- Windows 下给出 PowerShell 替代命令。
