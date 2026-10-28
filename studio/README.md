# Lunar Studio / 露娜

图像优先的本地创作台：用一句需求，让 DeepSeek 规划镜头与提示词，再由本机 ComfyUI 真正出图。影视图走 Cinema DNA，电商图走 e-commerce visual；自动决策会根据需求选择路线、数量和画幅，并把判断理由写在项目页上。

新应用完全独立于仓库原有的 Streamlit 工作台：它使用自己的 SQLite 数据库、上传目录和输出目录，不读写旧数据库，也不改动 `app.py` 与 `ui/`。

## 当前范围

- **影视图**：1 / 3 / 9 镜，2.39:1 等电影画幅，Cinema DNA 风格约束。
- **电商图**：1 / 5 / 12 张。12 张固定为 5 张 1:1 主图 + 7 张 2:3 详情页，不允许改比例；1 / 5 张沿用所选画幅。
- **自主决策**：只有在用户没有明确约束时才补全路线、数量、画幅、平台和商品信息；用户明确填写的内容不会被覆盖。
- **参考图**：参考图会上传到 ComfyUI，并作为 `TextEncodeZImageOmni` 的 image latent 条件参与采样，不只是展示。
- **视频**：一条片子只出一段 5 秒或 10 秒的单镜；Agent 先给 4 个方向（也能按你自己的想法改写），选定后本机 MiniMax H3 出片，带模型自己合成的环境声。
- **真实性**：没有写死的兜底方案、假进度、占位图或假成功。模型、ComfyUI、参考图出错时，界面保留真实错误文本。

## 环境

- Windows + PowerShell（当前开发环境）
- Python 3.13（`.venv`）
- Node.js 22+
- 本机 ComfyUI（默认 `http://127.0.0.1:8188`）
- ComfyUI 模型：Z-Image Turbo（图片）、MiniMax H3 + Turbo LoRA（视频）、Qwen 3 4B 文本编码器、`ae.safetensors` VAE
- 仓库根目录 `.env` 中配置 `DEEPSEEK_API_KEY`（不要把密钥写进前端或提交到仓库）

Python 依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r studio\requirements.txt
```

前端依赖：

```powershell
cd studio\frontend
npm install
```

## 界面

视觉方向是**暗色工作室**：近黑底 + 玻璃面板 + 蓝紫青渐变强调色。首屏是一整屏的动态字符墙（React Bits 的 `Gradient ASCII`，WebGL 实时渲染，鼠标划过会打散字符、点击有水波），上面压 React Bits 的 `Tech Text` 大字标题 `把一句话 / 变成能用的画面`——逐字母像素组装入场、悬停字母会变成虚线描边并带选择框、字母可拖动并回弹；下面接滚动计数、滚动进度条，再往下是一条 React Bits `Text Loop` 的斜向缎带（拖动可以擦洗）。路由切换用 `AnimatePresence` 淡入淡出，卡片悬停有渐变描边。所有动效都尊重 `prefers-reduced-motion`。

组件源码在 `studio/frontend/src/components/reactbits/`（`GradientASCII`、`TechText`、`TextLoop`、`Crosshair`、`ElectricBorder`、`StarBorder`、`BlurText`、`CountUp`，MIT + Commons Clause，许可见同目录 `LICENSE-reactbits.txt`）。上游都是无类型 JSX，因此统一加 `@ts-nocheck`，再用 `GradientAsciiBackground` / `TechWordmark` / `TextLoopBand` 三个薄包装补上缺失的可选 props；`Crosshair` / `ElectricBorder` / `StarBorder` 由 `CrosshairLayer`、`ElectricField`、`StarButton` 三个带主题的包装调用。`TextLoop` 依赖 `gsap`（已写进 `package.json`）。暗色皮肤集中在 `src/styles/dark.css`，加载在 `global.css` 之后，靠覆盖 token 与少量组件规则实现，不重写旧样式表（旧的 `home.css` 已删除）。

交互层：新建创作、项目列表、设置三页铺了一整屏的 `Crosshair`（十字准星贯穿顶栏与页面边缘，带坐标标签，指到按钮/输入框/卡片上会锁框并标尺寸）；新建页的需求输入框包了 `ElectricBorder`，只在聚焦时通电，鼠标靠近时电光会朝指针聚；主操作按钮统一换成 `StarBorder`（沿边框跑的光点，悬停变亮、点击会有一圈光沿着边跑）。`src/components/` 下的 `CrosshairLayer`、`ElectricField`、`StarButton` 负责主题与默认参数。

首页三个区块（路线 / 技能 / 出图）不是静态列表：区块右上角有 01–03 的水印编号和顶部渐变细线；路线卡片会跟鼠标做轻微 3D 倾斜，光斑随指针在卡面上移动；技能表悬停有从左侧展开的渐变光条、箭头滑入，整块还有跟随指针的聚光；出图墙支持图片拖尾——指针扫过时会把缩略图甩出来（`ImageTrail` 组件，尊重 reduced-motion）。

首屏截图：`../docs/screenshots/studio_home.png`（整页：`studio_home_full.png`）。

## 启动

### 开发模式（Vite + 热更新）

先构建一次或直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File studio\dev.ps1
```

脚本会在 8600 启动 FastAPI、在 5173 启动 Vite；打开 <http://127.0.0.1:5173>。Vite 会把 `/api` 和 `/media` 代理到 FastAPI。

### 本地生产模式

```powershell
cd studio\frontend
npm run build
cd ..\..
powershell -ExecutionPolicy Bypass -File studio\start.ps1
```

`start.ps1` 只启动 FastAPI。构建后的 React SPA 由 FastAPI 在 <http://127.0.0.1:8600> 直接提供。

### 单独启动 API

```powershell
.\.venv\Scripts\python.exe -m uvicorn studio.api.main:app --host 127.0.0.1 --port 8600
```

## 本地数据

| 内容 | 位置 |
| --- | --- |
| SQLite | `studio/data/lumen.sqlite3` |
| 上传的参考图 | `studio/data/uploads/` |
| 实际出图 | `output/studio/<project_id>/` |
| 规划技能 | `studio/skills/` |
| ComfyUI 工作流 | `studio/workflows/` |

`studio/data/`、`studio/frontend/node_modules/` 和 `studio/frontend/dist/` 都是本地产物，不提交。旧数据库、旧上传目录和旧 Streamlit 页面不在这些路径内。

## 打开与分享

本机打开：

```powershell
powershell -ExecutionPolicy Bypass -File studio\start.ps1
# 浏览器打开 http://127.0.0.1:8600
```

同一个 Wi-Fi 下的手机/另一台电脑：

```powershell
powershell -ExecutionPolicy Bypass -File studio\start.ps1 -Lan
# 脚本会打印 http://192.168.x.x:8600，第一次会弹防火墙提示，选“允许（专用网络）”
```

外网任何人访问（带密码，临时公网地址）：

```powershell
powershell -ExecutionPolicy Bypass -File studio\share.ps1
# 打印 https://xxx.trycloudflare.com + 用户名 lunar + 随机密码
```

- `share.ps1` 会用 `STUDIO_PASSWORD` 启动一个带 Basic 认证的 API，再用 Cloudflare 快速隧道暴露出去；没设密码的实例不会公网暴露。
- 生成始终跑在这台机器的显卡上：电脑不能休眠，ComfyUI 要开着，关掉窗口就断。
- `trycloudflare.com` 域名每次重启都会变；要固定域名需要 Cloudflare 账号 + 命名隧道。
## 实时进度

出图/出片时，项目页有一条真进度条，不是估算出来的：

- 后端 `studio/api/progress.py` 常开一条到 ComfyUI 的 websocket，client_id 是**每进程唯一**的（`lunar-studio-<pid>`，必须与排队时用的完全一致；两个 API 进程用同一个 id 会互相把对方的 socket 顶掉，表现为进度永远 0%）；
- 采样器每走一步推 `progress {value, max}`，后端按 `prompt_id` 存下来；
- `GET /api/projects/{id}/progress` 返回当前任务的阶段、第几步/共几步、百分比、已用时间，以及第 2 步之后才计算的 ETA（避开模型加载那一段）；
- 前端每秒轮询一次，显示「第 3 / 8 步 · 已用 1:33 · 预计还要 2:35」；还没收到步数时显示扫描态，不假装百分比。
## 视频模块

视频不是“图片加个播放器”，它有自己的合同：

1. **4 个方向**：`POST /api/video/concepts` 让 DeepSeek 按 `skills/video-h3/SKILL.md` 的规范给出正好 4 条彼此不同的单镜方案（标题、一句话、机位说明、英文提示词、声音、风险）。prompt 必须是英文，否则按合同错误拒绝，不会送到模型。
2. **自己写**：`POST /api/video/draft` 把用户自己写的中文想法改写成同一种结构的一条方案，不改变用户定下的人物、地点和动作。
3. **落库**：`POST /api/video/projects` 把选中的方向存成 `kind=video` 的方案（一个 shot，`seconds` 只能是 5 或 10）。
4. **出片**：项目页点「生成视频」，走 `studio/workflows/minimax_h3_t2v.json`（从仓库根的 `workflows/` 复制而来）。绑定时按节点角色填 prompt、`Studio Duration`、宽高、`noise_seed`、Turbo 开关；帧数由图里的 `17k+5` 表达式自己算。
5. **持续跟进**：`POST /api/projects/{id}/video/revise` 接受一句追加要求，改写英文提示词并清掉旧片；项目页有「追加要求」输入框。

尺寸按显存让步：5 秒 16:9 是 768×432，10 秒降到 640×368（8 GB 卡在 1344×768 会 OOM）。默认开 Turbo LoRA（8 步）；想要更高质量可以设 `STUDIO_VIDEO_TURBO=false` 走 20 步，代价是时间翻几倍。
## ComfyUI 工作流

- `studio/workflows/zimage_turbo.json`：纯文生图。
- `studio/workflows/zimage_turbo_ref.json`：参考图条件生成。

参考图在进入 ComfyUI 前会由后端归一化到约 1 MP，并保证宽高都是 16 的倍数。Z-Image 的 latent 以 2×2 patch 处理，VAE 下采样 8 倍，因此参考图像素边必须是 16 的倍数；否则会出现 `KSampler` 的 `shape ... is invalid for input of size ...` 错误。工作流里的 `auto_resize_images` 已关闭，避免 ComfyUI 只按 8 的倍数缩放后产生奇数 latent。

默认出图尺寸（适配 8 GB 显存）：

| 画幅 | 尺寸 |
| --- | --- |
| 2.39:1 | 1024 × 432 |
| 16:9 | 1024 × 576 |
| 1:1 | 1024 × 1024 |
| 4:5 | 896 × 1120 |
| 2:3 | 832 × 1248 |

## 验证

后端契约与存储测试：

```powershell
.\.venv\Scripts\python.exe -m pytest studio\tests -q
```

前端类型检查与构建：

```powershell
cd studio\frontend
npm run build
```

当前测试覆盖：路线/数量/画幅契约、12 张固定结构、自动决策参数、参考图提示词约束、工作流占位符绑定、参考图尺寸归一化、SQLite 渲染状态、API 与 ZIP 导出。

## 旧应用

原有 Streamlit 工作台仍可按仓库根目录的说明启动：

```powershell
streamlit run app.py
```

它使用旧的 `database/`、`data/` 与 `output/` 路径；Lunar Studio 不会迁移、覆盖或删除这些内容。

## 已知限制

- 视频生成尚未接入。
- ComfyUI 单卡串行出图；生成期间项目页会显示真实队列/运行状态。
- 规划层不会对参考图做视觉识别；参考图只作为生成条件，商品细节是否一致需要用户核对。
- 本地模型渲染中文文字可能出错，界面会在方案里提示后期叠加与逐字核对。
- 自动决策需要可用的 DeepSeek；不可用时直接显示错误，不会退回写死方案。
