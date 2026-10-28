# 本地生成工作流（ComfyUI API 格式）

工作室不内置任何工作流：用哪个模型、哪个 VAE、几步采样，都是你这台机器的事。
这里放的是**可提交**的 API 格式图，`本地生成` 页面会把每一镜的提示词和片段长度填进去。

## 怎么加一个工作流

1. 在 ComfyUI 里打开（或搭好）一条能跑通的图，先手动生成一次，确认结果正确。
2. 菜单 **Workflow → Export (API)**，导出成 JSON。
3. 把 JSON 放进这个目录（或用环境变量 `AIGC_WORKFLOW_DIR` 指向别处）。
4. 刷新 `本地生成` 页面，下拉框里就会出现它。

`Workflow → Save` 存的是 **UI 格式**（带 `nodes` / `links`），提交不了；
导入时会直接报错提示你改用 Export (API)，不会假装成功。

## 绑定规则

提示词、时长、分辨率、种子按两步填入：

1. **显式占位符**（推荐）：字符串里写 `{{prompt}}` `{{negative}}` `{{seconds}}`
   `{{width}}` `{{height}}` `{{seed}}` `{{project}}` `{{shot}}`，提交前直接替换。
2. **按图结构猜测**（没有占位符时）：顺着采样器的 `positive` / `negative`
   连线找到文本编码节点；输入名是 `prompt` 的节点也会被填；
   `seconds` / `duration` 直接写秒，`length` / `num_frames` 按 `fps` 换算成帧。

## 时长怎么看

片段长度取自工作流里的时长输入（`seconds` 或 `length ÷ fps`），
`本地生成` 页面会显示出来，也可以覆盖。
**一次调用只产出一条片段**，90 秒的片子 = 若干条片段拼接，工作室会先算给你看。

视频工作流如果自己要把秒数换算成帧（17k+5 网格、fps 怪癖），别在 Python 里算，
把那个「秒数」节点标成 `Studio Duration`，工作室只改这一个浮点数，
其余换算留在图里：

```json
"10": {
  "class_type": "PrimitiveFloat",
  "_meta": {"title": "Studio Duration (seconds)", "studio_clips": [5, 10]},
  "inputs": {"value": 5.0}
}
```

- `studio_clips`：这条图验证过的单条秒数（不写就只用默认值）。
- `_meta.title` 里带 `turbo` 的布尔节点会被识别成「Turbo 开关」，
  页面会给一个复选框 —— 它决定单条是 4 分钟还是 25 分钟。

## 示例

**图片** `zimage_turbo.json`：`z_image_turbo_int8_convrot` + `qwen_3_4b_fp8_mixed`
（CLIPLoader type=`qwen_image`）+ `ae` VAE，8 步、CFG 1。本机实测出图。
换模型时改 `unet_name` / `clip_name` / `vae_name` 即可。

**视频** `minimax_h3_t2v.json`：从你保存的 UI 工作流
（`video_minimax_h3_t2v.json`，带 subgraph）手工展开成 API 格式，
节点和连线与原图一致，只去掉了 ResolutionSelector 和三个说明便签。

- 24 fps、`length` 由 `ComfyMathExpression` 从秒数换算并吸附到 17k+5 网格；
- 5 秒 → 124 帧（5.17 秒）；10 秒 → 243 帧（10.12 秒），仍在训练区间 124–362 内；
- 输出带音轨（`VAEDecodeAudio` + `CreateVideo`），AAC 32 kHz 立体声；
- 本机实测（Turbo 8 步 / 768×432 / 同提示词同种子）：

  | | 5 秒 | 10 秒 |
  |---|---|---|
  | 耗时 | 235.1 s | 581.9 s（2.48×） |
  | 首帧→末帧变化 | 24.71 | 30.87（+25%） |
  | 每帧运动量 | 1.559 | 0.696（−55%） |

  10 秒不是多演一个节拍，而是把同一段放慢，代价却接近 2.5 倍。
  所以 `studio_clips` 写 `[5, 10]`，但规划器优先 5 秒，10 秒留给确实需要一镜到底的慢镜头。
  你之前那次全量 20 步 / 1344×768 是 25 分 19 秒（ComfyUI 日志原文
  `Prompt executed in 00:25:19`）。

