# 外部参考资料与借鉴边界

调研日期：2026-10-19。Star 数通过 GitHub API 实时查询，会随时间变化；许可证以仓库当时显示的 `LICENSE` 和 GitHub API 返回值为准。

本项目的专业词表、分镜字段和检查规则由项目自行整理。下列资料用于校准术语、结构和工作流，**没有复制其代码或大段文字**。MIT / Apache-2.0 资料可以在保留归属信息的前提下借鉴；AGPL-3.0 和无许可证资料只借鉴思想。

---

## 一、直接参考

| 仓库 | Star | 许可证 | 我们借鉴了什么 | 实际阅读的文件 |
|---|---:|---|---|---|
| [zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills) | 3055 | MIT | 镜头唯一职责；“起点 → 唯一动作 → 终点”；连续性锁；参考图用途分类；屏幕方向与持物连续性；机械核对思路 | `README.md`、`skills/short-drama-storyboard/SKILL.md`、`skills/short-drama-video-prompts/SKILL.md`、`skills/short-drama-image-prompts/SKILL.md` |
| [eternityspring/shuohao-skills](https://github.com/eternityspring/shuohao-skills) | 4789 | Apache-2.0 | 段（一次生成 ≤15 秒）→ 切（2–5 秒）→ 关键帧；节拍覆盖；台词时长检查；画幅合同；确定性质量门思路 | `README.md`、`skills/novel-storyboard/SKILL.md` |
| [cclank/lanshu-awesome-ai-video-kit](https://github.com/cclank/lanshu-awesome-ai-video-kit) | 422 | MIT | Seedance 8 要素公式；4 维分镜组织；景别/运镜/灯光/色彩词表；矛盾约束清单；多模型公式速查 | `methodology/02-进阶公式.md`、`03-分镜时序.md`、`05-运镜词典.md`、`06-约束词清单.md`、`13-六大模型公式速查.md`、`skills/seedance-storyboard/SKILL.md` |
| [jnMetaCode/ai-shortfilm-prompts](https://github.com/jnMetaCode/ai-shortfilm-prompts) | 475 | MIT | 5 段式提示词结构；逐秒/逐镜分镜；真实摄影机与镜头写法；瑕疵与留白原则；不同模型的负向提示词差异 | `methodology.zh.md`、`cheatsheet.zh.md`、`README.md` |
| [ZeroLu/awesome-seedance](https://github.com/ZeroLu/awesome-seedance) | 2739 | MIT | 时间码分镜案例；广告/产品/剧情提示词结构；评测用例灵感 | `README.md` |
| [LearnPrompt/awesome-seedance](https://github.com/LearnPrompt/awesome-seedance) | 2143 | MIT | 27 类模板；逐秒时间线；参考图身份锁；分镜九宫格转视频 | `README.md` |
| [Forget-C/Jellyfish](https://github.com/Forget-C/Jellyfish) | 6775 | Apache-2.0 | 剧本拆解 → 分镜准备 → 候选确认 → 生成；角色/场景/道具/服装资产一致性；异步任务中心 | `README.md` |
| [yi1108/printfilm](https://github.com/yi1108/printfilm) | 5179 | MIT | AI 漫剧/短视频的分层流水线和工具中心设计 | `README.md` |

## 二、架构参考（不复制代码）

| 仓库 | Star | 许可证 | 参考内容 | 使用边界 |
|---|---:|---|---|---|
| [ArcReel/ArcReel](https://github.com/ArcReel/ArcReel) | 5580 | AGPL-3.0 | 内容分析 → 资产 → 剧本 → 分镜 → 视频 → 费用追踪 → 导出的流水线；跨分镜资产复用 | 只借鉴流程和数据模型；**不复制代码或文档正文** |
| [HBAI-Ltd/Toonflow-app](https://github.com/HBAI-Ltd/Toonflow-app) | 18199 | MIT | 应用级 AI 短剧/漫剧工作台的产品组织方式 | 产品层参考，不直接引入 |
| [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | 132940 | MIT | 高 star 工程结构、供应商抽象、任务流水线 | 与专业分镜/运镜核心不直接相关，仅作工程参考 |
| [linyqh/NarratoAI](https://github.com/linyqh/NarratoAI) | 11459 | MIT | 解说文案、配音、剪辑流水线 | 偏后期，不进入核心分镜模块 |
| [HVision-NKU/StoryDiffusion](https://github.com/HVISION-NKU/StoryDiffusion) | 6478 | Apache-2.0 | 角色与故事一致性研究 | 研究参考，不直接集成 |
| [shanghaicellcenter/shotblock](https://github.com/shanghaicellcenter/shotblock) | 5 | 无 | 180° 轴线规则、镜头焦距计算、3D 预演概念 | Star 低且无许可证；**只借鉴“轴线/屏幕方向”概念，不复制代码或文字** |

## 三、查看过但未作为核心参考

| 仓库 | Star | 许可证 | 不采用的原因 |
|---|---:|---|---|
| [waooAI/waoowaoo](https://github.com/waooAI/waoowaoo) | 14587 | NOASSERTION | 许可证状态不明确，不适合直接复用 |
| [Narcooo/inkos](https://github.com/Narcooo/inkos) | 10384 | AGPL-3.0 | 偏小说创作 Agent，不是分镜/运镜核心；且为 AGPL |
| [f/prompts.chat](https://github.com/f/prompts.chat) | 173487 | NOASSERTION | 通用聊天提示词，不是 AIGC 视频分镜专业资料 |
| [dair-ai/Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) | 79324 | MIT | 通用提示词工程背景，不作为专业分镜词表来源 |
| [hpcaitech/Open-Sora](https://github.com/hpcaitech/Open-Sora) | 29868 | Apache-2.0 | 视频生成模型代码，不是提示词/分镜规范 |
| [Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1) | 17241 | Apache-2.0 | 视频生成模型代码，不是提示词/分镜规范 |
| [RayVentura/ShortGPT](https://github.com/RayVentura/ShortGPT) | 8044 | MIT | 最后推送时间为 2025-02，实验性较强，未作为核心依据 |

## 四、许可证与引用策略

| 许可证 | 处理方式 |
|---|---|
| MIT / Apache-2.0 | 可借鉴结构和术语；如直接复用代码或模板，保留版权与许可证声明，并在本文件登记来源 |
| AGPL-3.0 | 只借鉴架构思想；不复制代码、脚本或大段文档正文，避免给课程项目引入 AGPL 传染义务 |
| NOASSERTION / 无许可证 | 不复制代码或文字；只使用行业通用术语和抽象概念 |
| CC0 | 可复用，但仍建议注明来源 |

行业通用术语（EWS、dolly in、golden hour、180° rule 等）不属于某个仓库的专有表达，可以自由使用；具体模板、脚本和长篇说明属于各自作者的表达，本项目不整段照搬。

## 五、已经落到代码中的映射

| 项目文件 | 内容 | 对应参考 |
|---|---|---|
| `schemas/cinematography.py` | 景别、机位角度、运镜、灯光、色彩、转场、特效、屏幕方向枚举；`CinematographySpec` | cclank 运镜词典；zenstory 镜头字段；行业通用术语 |
| `config/cinematography.py` | 中英文标签、模型能力档案、矛盾约束规则、运镜关键词、专业镜头必填字段 | cclank 公式与约束；jnMetaCode 模型差异；shuohao 质量门 |
| `schemas/storyboard.py` | 镜头新增叙事职责、起止状态、声音、负向提示词、连续性锁、参考图用途、结构化摄影参数；`ShotDraft`/`StoryboardDraft` 容忍模型输出 | zenstory 分镜字段；shuohao 段/切结构 |
| `tools/storyboard_tool.py` | LLM/确定性分镜生成与草稿转换 | zenstory 起点→动作→终点；shuohao 段/切时长；cclank 4 维分镜；jnMetaCode 5 段式 |
| `tools/prompt_builder.py` | 从结构化字段确定性拼装图片/视频提示词，按模型档案处理负向约束 | cclank 8 要素公式；jnMetaCode 摄影机/留白；jnMetaCode 模型差异表 |
| `tools/cinematography_checker.py` | 提示词矛盾检查、单镜头多运镜检查、专业镜头字段完整性检查 | cclank 约束词清单；shuohao 确定性质量门 |
| `tools/scene_checker.py` | 必需场景覆盖、缺失场景、重复场景警告 | shuohao 节拍/场景覆盖质量门 |
| `tools/consistency_checker.py` | 连续性锁、主体描述、车辆方向、屏幕方向和文本方向矛盾 | zenstory 连续性与屏幕方向；cclank 主体一致性约束 |
| `tools/prompt_checker.py` | 提示词必要字段、矛盾约束、多运镜和模型差异检查 | cclank 公式与约束；jnMetaCode 模型差异表 |
| `tools/validation_pipeline.py` | 聚合时长、场景、一致性、提示词四类校验 | 项目自行设计；参考 shuohao 质量门组织方式 |
| `tools/revision_tool.py` | LLM 修正和确定性时长修正；方向审计 | zenstory 起点→动作→终点；shuohao 时长与节拍门 |
| `tests/test_cinematography.py` | 11 条确定性测试 | 项目自行编写 |

## 六、重要限制

1. 模型能力档案是**参考值**，不是 API 合同。真正调用图片/视频模型前，必须按供应商当前文档复核时长、负向提示词、语言和过滤规则。
2. 关键词检查是确定性的，但只能发现“明确写出的矛盾”，不能判断镜头是否好看、主体是否真的保持一致。
3. 本项目当前只生成提示词和校验报告，不调用图片/视频生成 API；不能声称已经生成真实视频。
4. Star 数和许可证会变化；课程报告中引用时应注明查询日期。
