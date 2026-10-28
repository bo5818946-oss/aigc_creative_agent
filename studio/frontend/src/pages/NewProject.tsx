import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Film, ImageUp, ShoppingBag, Sparkles, X } from "lucide-react";
import {
  streamPlan,
  uploadReference,
  type Mode,
  type PlanEvent,
  type PlanPayload,
  type UploadRecord,
} from "../lib/api";
import { useHealth } from "../lib/health";
import { usePageTitle } from "../lib/usePageTitle";
import { Callout } from "../components/Callout";
import { CrosshairLayer } from "../components/CrosshairLayer";
import { ElectricField } from "../components/ElectricField";
import { StarButton } from "../components/StarButton";
import { VideoComposer } from "../components/VideoComposer";
import { PlanTimeline } from "../components/PlanTimeline";

const CINEMA_ASPECTS = ["2.39:1", "21:9", "16:9", "4:3", "1:1"];
const ECOM_ASPECTS = ["1:1", "4:5", "3:4", "16:9"];
const ROLES = [
  { value: "auto", label: "自动判断" },
  { value: "product", label: "商品参考" },
  { value: "style", label: "画风参考" },
  { value: "character", label: "人物参考" },
  { value: "scene", label: "场景参考" },
  { value: "mood", label: "氛围参考" },
];

function parseMode(value: string | null): Mode {
  return value === "ecommerce" || value === "auto" ? value : "cinema";
}

function Choice({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string; note?: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="choice-row" role="group" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            className="choice"
            aria-pressed={value === option.value}
            onClick={() => onChange(option.value)}
          >
            <span>{option.label}</span>
            {option.note ? (
              <span className="choice-note">{option.note}</span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

export function NewProjectPage() {
  usePageTitle("新建创作");
  const { health } = useHealth();
  const [params] = useSearchParams();
  const navigate = useNavigate();

  const [domain, setDomain] = useState<"image" | "video">(
    params.get("video") ? "video" : "image",
  );
  const [mode, setMode] = useState<Mode>(parseMode(params.get("mode")));
  const [brief, setBrief] = useState("");
  const [briefFocused, setBriefFocused] = useState(false);
  const [shotCount, setShotCount] = useState<1 | 3 | 9>(3);
  const [aspect, setAspect] = useState("2.39:1");
  const [packSize, setPackSize] = useState<1 | 5 | 12>(5);
  const [productName, setProductName] = useState("");
  const [platform, setPlatform] = useState("");

  const [reference, setReference] = useState<UploadRecord | null>(null);
  const [role, setRole] = useState("auto");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [planning, setPlanning] = useState(false);
  const [events, setEvents] = useState<PlanEvent[]>([]);
  const [planError, setPlanError] = useState("");

  useEffect(() => {
    const next = parseMode(params.get("mode"));
    setMode(next);
  }, [params]);

  useEffect(() => {
    if (mode === "cinema" && !CINEMA_ASPECTS.includes(aspect)) setAspect("2.39:1");
    if (mode === "ecommerce" && !ECOM_ASPECTS.includes(aspect)) setAspect("1:1");
  }, [mode, aspect]);

  const deepseekReady = health ? health.deepseek_configured : true;
  const canSubmit =
    brief.trim().length >= 2 &&
    !planning &&
    !uploading &&
    deepseekReady;

  async function handleFile(file: File) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      setUploadError("只支持 PNG、JPG/JPEG 或 WebP 参考图。");
      return;
    }
    if (file.size > 16 * 1024 * 1024) {
      setUploadError("参考图不能超过 16 MB。");
      return;
    }
    setUploadError("");
    setUploading(true);
    try {
      const record = await uploadReference(file);
      setReference(record);
    } catch (exc) {
      setUploadError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function removeReference() {
    setReference(null);
    setRole("auto");
    setUploadError("");
  }

  async function submit() {
    const text = brief.trim();
    if (text.length < 2) {
      setPlanError("先写一句具体的需求，至少两个字。");
      return;
    }
    const payload: PlanPayload = {
      mode,
      brief: text,
      reference_id: reference?.upload_id ?? null,
      reference_role: reference ? role : "auto",
      aspect:
        mode === "cinema"
          ? aspect
          : mode === "ecommerce" && packSize !== 12
            ? aspect
            : null,
      shot_count: mode === "cinema" ? shotCount : null,
      pack_size: mode === "ecommerce" ? packSize : null,
      product_name:
        mode === "ecommerce" ? productName.trim() || null : null,
      platform: mode === "ecommerce" ? platform.trim() || null : null,
      language: "zh",
    };
    setPlanning(true);
    setEvents([]);
    setPlanError("");
    try {
      const project = await streamPlan(payload, (event) => {
        if (event.stage === "open" || event.stage === "result") return;
        setEvents((current) => [
          ...current,
          {
            stage: event.stage,
            message: event.message,
            route: event.route,
            reasoning: event.reasoning,
          },
        ]);
      });
      navigate(`/projects/${project.project_id}`);
    } catch (exc) {
      setPlanError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setPlanning(false);
    }
  }

  return (
    <div className="composer-page">
      <CrosshairLayer />
      <header className="page-head composer-head">
        <div>
          <span className="lp-kicker">Compose</span>
          <h1 className="h1">新建创作</h1>
          <p className="sub">
            先选路线，再写需求。Agent 只使用技能规则和你的输入，不补造事实。
          </p>
        </div>
        <div className="composer-steps" aria-hidden="true">
          {["路线", "需求", "参数", "规划"].map((label, index) => (
            <span
              className={`composer-step${
                index < (planning ? 4 : brief.trim().length > 10 ? 2 : 1)
                  ? " is-on"
                  : ""
              }`}
              key={label}
            >
              <i>{String(index + 1).padStart(2, "0")}</i>
              {label}
            </span>
          ))}
        </div>
      </header>

      {health && !health.deepseek_configured ? (
        <Callout tone="warning" title="DeepSeek 未配置">
          在仓库根目录的 .env 中设置 DEEPSEEK_API_KEY 后才能规划。密钥不会发送到浏览器。
        </Callout>
      ) : null}

      {planning || planError ? (
        <section className="panel planning-panel" aria-labelledby="planning-title">
          <div className="panel-head">
            <h2 id="planning-title" className="section-title">
              {planning ? "Agent 正在工作" : "规划没有完成"}
            </h2>
            {planning ? <span className="meta">实时阶段</span> : null}
          </div>
          <PlanTimeline events={events} error={planError} running={planning} />
          {planError ? (
            <p className="planning-retry">
              修改需求或参考图后，再点一次「让 Agent 规划」。
            </p>
          ) : null}
        </section>
      ) : null}

      <div className="domain-row">
        <div className="segmented" role="group" aria-label="创作领域">
          <button
            type="button"
            aria-pressed={domain === "image"}
            onClick={() => setDomain("image")}
          >
            图片
          </button>
          <button
            type="button"
            aria-pressed={domain === "video"}
            onClick={() => setDomain("video")}
          >
            视频
            <span className="mini-tag">5 / 10 秒</span>
          </button>
        </div>
        <p className="meta">
          {domain === "video"
            ? "视频只出一条 5 秒或 10 秒的单镜片，先出 4 个方向，再由你定。"
            : "当前版本先完成图片三支：影视图、电商图、自主决策。"}
        </p>
      </div>

      {domain === "video" ? <VideoComposer /> : null}

      <div className={domain === "image" ? "grid12 composer-grid" : "hidden"}>
        <section className="panel span-7" aria-labelledby="brief-title">
          <div className="panel-head">
            <h2 id="brief-title" className="section-title">
              路线
            </h2>
            <span className="meta">三选一</span>
          </div>
          <div className="mode-grid" role="group" aria-label="创作路线">
            <button
              type="button"
              className="mode-option"
              aria-pressed={mode === "cinema"}
              onClick={() => setMode("cinema")}
            >
              <span className="mode-name"><Film size={15} strokeWidth={1.7} aria-hidden="true" />影视图</span>
              <span className="mode-copy">
                单帧、三联或九镜。先定事件与连续性，再写机位、光线和动作。
              </span>
              <span className="mode-skill">Cinema DNA</span>
            </button>
            <button
              type="button"
              className="mode-option"
              aria-pressed={mode === "ecommerce"}
              onClick={() => setMode("ecommerce")}
            >
              <span className="mode-name"><ShoppingBag size={15} strokeWidth={1.7} aria-hidden="true" />电商图</span>
              <span className="mode-copy">
                主图与详情页按转化任务排布，整套共用同一份风格合同。
              </span>
              <span className="mode-skill">ecom-details-image</span>
            </button>
            <button
              type="button"
              className="mode-option"
              aria-pressed={mode === "auto"}
              onClick={() => setMode("auto")}
            >
              <span className="mode-name"><Sparkles size={15} strokeWidth={1.7} aria-hidden="true" />自主决策</span>
              <span className="mode-copy">
                只写目标。Agent 判断路线，并决定数量、画幅、平台与商品信息。
              </span>
              <span className="mode-skill">Agent 路由</span>
            </button>
          </div>
          {mode === "auto" ? (
            <p className="mode-hint">
              当前为自主决策：下面的数量与画幅不会提交，由 Agent 自己决定。你仍可上传一张参考图。
            </p>
          ) : null}

          <hr className="rule" />

          <div className="panel-head">
            <h2 id="request-title" className="section-title">
              需求
            </h2>
            <span className="meta">{brief.length} / 6000</span>
          </div>
          <label className="field" htmlFor="brief">
            <span className="field-label">
              {mode === "ecommerce"
                ? "商品、卖点与使用场景"
                : mode === "cinema"
                  ? "故事、人物、场景与想要的情绪"
                  : "你想完成的目标"}
            </span>
            <ElectricField active={briefFocused}>
              <textarea
                id="brief"
                className="textarea brief-input"
                value={brief}
                maxLength={6000}
                onFocus={() => setBriefFocused(true)}
                onBlur={() => setBriefFocused(false)}
                onChange={(event) => setBrief(event.target.value)}
              placeholder={
                mode === "ecommerce"
                  ? "例：一款 316 不锈钢保温杯，500ml，哑光沙色，目标人群是通勤上班族。要 5 张天猫主图，强调 12 小时保温、单手开盖和杯口不烫。没有真实检测报告，不要编造数据。"
                  : mode === "cinema"
                    ? "例：凌晨四点的城中村早餐铺，一个刚下夜班的年轻护士坐下来吃一碗热粥。想要安静、疲惫但有温度，不要台词，不要海报感。"
                    : "例：帮我做一组能放在品牌官网首屏的视觉，主题是雨后的城市和骑车的人。还没有想好是卖产品还是讲故事。"
              }
                aria-describedby="brief-help"
              />
            </ElectricField>
          </label>
          <p id="brief-help" className="help">
            写清楚已知事实、必须保留的细节和不能出现的内容。缺失的关键信息会进入待确认项，不会被悄悄补上。
          </p>

          {mode === "ecommerce" ? (
            <div className="field-row">
              <label className="field" htmlFor="product-name">
                <span className="field-label">商品名（可选）</span>
                <input
                  id="product-name"
                  className="input"
                  value={productName}
                  onChange={(event) => setProductName(event.target.value)}
                  placeholder="未填写时从需求中提取"
                />
              </label>
              <label className="field" htmlFor="platform">
                <span className="field-label">平台 / 用途（可选）</span>
                <input
                  id="platform"
                  className="input"
                  value={platform}
                  onChange={(event) => setPlatform(event.target.value)}
                  placeholder="淘宝、京东、抖音商城、独立站…"
                />
              </label>
            </div>
          ) : null}
        </section>

        <aside className="span-5 rail composer-rail">
          <section className="panel" aria-labelledby="reference-title">
            <div className="panel-head">
              <h2 id="reference-title" className="section-title">
                参考图
              </h2>
              <span className="meta">可选</span>
            </div>

            {reference ? (
              <div className="reference-card">
                <img src={reference.url} alt="已上传的参考图预览" />
                <div className="reference-meta">
                  <span className="reference-name">{reference.filename}</span>
                  <span className="meta">已上传到本机</span>
                  <button
                    type="button"
                    className="text-button"
                    onClick={removeReference}
                  >
                    <X size={13} strokeWidth={1.8} aria-hidden="true" />
                    移除
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className={`dropzone${dragging ? " dropzone-active" : ""}`}
                onClick={() => fileRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  const file = event.dataTransfer.files[0];
                  if (file) void handleFile(file);
                }}
                disabled={uploading}
              >
                <ImageUp size={20} strokeWidth={1.6} aria-hidden="true" />
                <span>{uploading ? "正在上传…" : "拖入参考图，或选择文件"}</span>
                <span className="dropzone-note">PNG、JPG、WebP · 最大 16 MB</span>
              </button>
            )}
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="visually-hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void handleFile(file);
              }}
            />

            {uploadError ? <Callout>{uploadError}</Callout> : null}

            {reference ? (
              <label className="field reference-role" htmlFor="role">
                <span className="field-label">用途</span>
                <select
                  id="role"
                  className="input"
                  value={role}
                  onChange={(event) => setRole(event.target.value)}
                >
                  {ROLES.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            <p className="help">
              参考图会真正作为 ComfyUI 的条件输入。规划层不做视觉识别，所以不会描述图里的具体内容。
            </p>
          </section>

          <section className="panel" aria-labelledby="params-title">
            <div className="panel-head">
              <h2 id="params-title" className="section-title">
                参数
              </h2>
            </div>

            {mode === "cinema" ? (
              <>
                <Choice
                  label="镜头数量"
                  value={String(shotCount)}
                  onChange={(value) =>
                    setShotCount(Number(value) as 1 | 3 | 9)
                  }
                  options={[
                    { value: "1", label: "1 镜", note: "单帧" },
                    { value: "3", label: "3 镜", note: "默认" },
                    { value: "9", label: "9 镜", note: "故事" },
                  ]}
                />
                <Choice
                  label="画幅"
                  value={aspect}
                  onChange={setAspect}
                  options={CINEMA_ASPECTS.map((item) => ({
                    value: item,
                    label: item,
                  }))}
                />
                <p className="help">
                  2.39:1 在本机以 1024 × 432 出图，接近 2.37:1；导出时不会拉伸。
                </p>
              </>
            ) : null}

            {mode === "ecommerce" ? (
              <>
                <Choice
                  label="图片包"
                  value={String(packSize)}
                  onChange={(value) =>
                    setPackSize(Number(value) as 1 | 5 | 12)
                  }
                  options={[
                    { value: "1", label: "1 张", note: "单图" },
                    { value: "5", label: "5 张", note: "主图" },
                    { value: "12", label: "12 张", note: "主图 + 详情" },
                  ]}
                />
                {packSize === 12 ? (
                  <div className="fixed-note">
                    <span className="fixed-note-title">固定结构</span>
                    <span>5 张 1:1 主图 + 7 张 2:3 详情页，不允许改比例。</span>
                  </div>
                ) : (
                  <Choice
                    label="画幅"
                    value={aspect}
                    onChange={setAspect}
                    options={ECOM_ASPECTS.map((item) => ({
                      value: item,
                      label: item,
                    }))}
                  />
                )}
                <p className="help">
                  商品外观一致性取决于参考图和提示词；没有商品参考图时会明确警告。
                </p>
              </>
            ) : null}

            {mode === "auto" ? (
              <div className="auto-note">
                <p className="auto-note-title">Agent 会决定这些参数</p>
                <ul>
                  <li>走影视图还是电商图，并给出判断理由</li>
                  <li>镜头数或图片包大小、画幅、平台策略</li>
                  <li>商品名与用途（当需求里能确定时）</li>
                </ul>
                <p className="help">
                  你不需要先选数量。方案生成后仍可逐条修改提示词并重新出图。
                </p>
              </div>
            ) : null}

            <div className="submit-block">
              <StarButton
                as="button"
                type="button"
                className="submit-button"
                onClick={() => void submit()}
                disabled={!canSubmit}
              >
                {uploading
                  ? "参考图上传中"
                  : planning
                    ? "正在规划…"
                    : "让 Agent 规划"}
                {!planning && !uploading ? (
                  <ArrowRight size={16} strokeWidth={1.8} aria-hidden="true" />
                ) : null}
              </StarButton>
              <p className="help submit-help">
                规划只产生方案与提示词，不会自动出图。
                {health && !health.comfyui_reachable
                  ? " 本地模型当前离线，出图前需要启动 ComfyUI。"
                  : ""}
              </p>
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
