import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Check,
  Clapperboard,
  Loader2,
  PenLine,
  Sparkles,
  Wand2,
} from "lucide-react";
import {
  createVideoProject,
  startRender,
  draftVideoConcept,
  proposeVideoConcepts,
  type VideoConcept,
  type VideoSeconds,
} from "../lib/api";
import { Callout } from "./Callout";
import { ElectricField } from "./ElectricField";
import { StarButton } from "./StarButton";

const DURATIONS: { value: VideoSeconds; label: string; note: string }[] = [
  { value: 5, label: "5 秒", note: "一个动作" },
  { value: 10, label: "10 秒", note: "最多两拍" },
];

const ASPECTS = ["16:9", "2.39:1", "9:16", "1:1", "4:3"];

const ASPECT_NOTE: Record<string, string> = {
  "16:9": "横屏 768×432（10 秒 640×368）",
  "2.39:1": "宽银幕 768×320（10 秒 640×272）",
  "9:16": "竖屏 432×768（10 秒 368×640）",
  "1:1": "方形 576×576（10 秒 480×480）",
  "4:3": "复古 640×480（10 秒 544×400）",
};

export function VideoComposer() {
  const navigate = useNavigate();
  const [brief, setBrief] = useState("");
  const [focused, setFocused] = useState(false);
  const [duration, setDuration] = useState<VideoSeconds>(5);
  const [aspect, setAspect] = useState("16:9");
  const [concepts, setConcepts] = useState<VideoConcept[]>([]);
  const [picked, setPicked] = useState("");
  const [custom, setCustom] = useState("");
  const [customOpen, setCustomOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [drafting, setDrafting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const chosen = concepts.find((item) => item.concept_id === picked) || null;
  const canPropose = brief.trim().length >= 2 && !loading;

  async function propose() {
    setLoading(true);
    setError("");
    try {
      const result = await proposeVideoConcepts({
        brief: brief.trim(),
        duration,
        aspect,
      });
      setConcepts(result.concepts);
      setPicked(result.concepts[0]?.concept_id ?? "");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "规划失败。");
      setConcepts([]);
      setPicked("");
    } finally {
      setLoading(false);
    }
  }

  async function draft() {
    if (custom.trim().length < 2) {
      setError("先写几句你自己的想法。");
      return;
    }
    setDrafting(true);
    setError("");
    try {
      const concept = await draftVideoConcept({
        brief: brief.trim() || custom.trim(),
        direction: custom.trim(),
        duration,
        aspect,
      });
      setConcepts([concept]);
      setPicked(concept.concept_id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "改写失败。");
    } finally {
      setDrafting(false);
    }
  }

  async function create() {
    if (!chosen) return;
    setCreating(true);
    setError("");
    try {
      const project = await createVideoProject({
        brief: brief.trim() || chosen.logline,
        duration,
        aspect,
        concept: chosen,
      });
      // The direction is already settled, so queue the clip right away: the
      // project page then opens with a live progress bar instead of an idle
      // placeholder and a second "生成视频" click.
      await startRender(project.project_id, null).catch(() => {
        /* ComfyUI offline lands on the project page with its own warning */
      });
      navigate(`/projects/${project.project_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "创建失败。");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="grid12 composer-grid video-composer">
      <section className="panel span-7" aria-labelledby="video-brief-title">
        <div className="panel-head">
          <h2 id="video-brief-title" className="section-title">
            视频需求
          </h2>
          <span className="meta">一镜到底</span>
        </div>

        <label className="field" htmlFor="video-brief">
          <span className="field-label">想拍什么、给谁看、要什么情绪</span>
          <ElectricField active={focused}>
            <textarea
              id="video-brief"
              className="textarea brief-input"
              value={brief}
              maxLength={6000}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onChange={(event) => setBrief(event.target.value)}
              placeholder="例：凌晨的城中村早餐铺，一个刚下夜班的护士坐下来喝一口热粥，蒸汽升起来。要安静、疲惫但有温度。"
            />
          </ElectricField>
        </label>

        <div className="video-params">
          <div className="field">
            <span className="field-label">时长</span>
            <div className="choice-row" role="group" aria-label="视频时长">
              {DURATIONS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  className="choice"
                  aria-pressed={duration === item.value}
                  onClick={() => setDuration(item.value)}
                >
                  <span>{item.label}</span>
                  <span className="choice-note">{item.note}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="field">
            <span className="field-label">画幅</span>
            <div className="choice-row" role="group" aria-label="视频画幅">
              {ASPECTS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className="choice"
                  aria-pressed={aspect === item}
                  onClick={() => setAspect(item)}
                >
                  <span>{item}</span>
                </button>
              ))}
            </div>
            <p className="help">{ASPECT_NOTE[aspect]}</p>
          </div>
        </div>

        <div className="video-actions">
          <StarButton
            as="button"
            type="button"
            onClick={() => void propose()}
            disabled={!canPropose}
          >
            {loading ? (
              <Loader2 size={16} className="spin" aria-hidden="true" />
            ) : (
              <Sparkles size={16} strokeWidth={1.8} aria-hidden="true" />
            )}
            {loading ? "Agent 正在想方向…" : "让 Agent 出 4 个方向"}
          </StarButton>
          <button
            type="button"
            className="link-button"
            onClick={() => setCustomOpen((value) => !value)}
          >
            <PenLine size={14} aria-hidden="true" />
            {customOpen ? "收起我自己的想法" : "或者按我自己的想法"}
          </button>
        </div>

        {customOpen ? (
          <div className="video-custom">
            <label className="field" htmlFor="video-custom">
              <span className="field-label">你自己的想法</span>
              <textarea
                id="video-custom"
                className="textarea"
                value={custom}
                maxLength={1200}
                onChange={(event) => setCustom(event.target.value)}
                placeholder="例：不要早餐铺了，拍雨夜里一个骑手停在便利店门口，头盔上全是水，镜头跟着他下车。"
              />
            </label>
            <StarButton
              as="button"
              type="button"
              variant="secondary"
              onClick={() => void draft()}
              disabled={drafting || custom.trim().length < 2}
            >
              {drafting ? (
                <Loader2 size={15} className="spin" aria-hidden="true" />
              ) : (
                <Wand2 size={15} strokeWidth={1.8} aria-hidden="true" />
              )}
              {drafting ? "正在写成提示词…" : "按这个想法写成提示词"}
            </StarButton>
          </div>
        ) : null}

        {error ? (
          <Callout tone="warning" title="没有拿到方案">
            {error}
          </Callout>
        ) : null}

        {concepts.length > 0 ? (
          <div className="concept-block">
            <div className="concept-head">
              <span>选一个方向</span>
              <span>4 条·都是 5/10 秒单镜</span>
            </div>
            <div className="concept-grid">
              {concepts.map((concept) => {
                const active = concept.concept_id === picked;
                return (
                  <button
                    key={concept.concept_id}
                    type="button"
                    className="concept"
                    aria-pressed={active}
                    onClick={() => setPicked(concept.concept_id)}
                  >
                    <span className="concept-top">
                      <span className="concept-title">{concept.title}</span>
                      {active ? (
                        <span className="concept-check" aria-hidden="true">
                          <Check size={12} strokeWidth={2.4} />
                        </span>
                      ) : null}
                    </span>
                    <span className="concept-logline">{concept.logline}</span>
                    <span className="concept-treatment">{concept.treatment}</span>
                    {concept.sound ? (
                      <span className="concept-sound">声音：{concept.sound}</span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}
      </section>

      <aside className="span-5">
        <section className="panel video-side" aria-labelledby="video-side-title">
          <div className="panel-head">
            <h2 id="video-side-title" className="section-title">
              这条片子
            </h2>
            <span className="meta">{duration} 秒</span>
          </div>

          <dl className="video-facts">
            <div>
              <dt>模型</dt>
              <dd>MiniMax H3 · 本地</dd>
            </div>
            <div>
              <dt>时长</dt>
              <dd>{duration} 秒</dd>
            </div>
            <div>
              <dt>画幅</dt>
              <dd>{aspect}</dd>
            </div>
            <div>
              <dt>参考图</dt>
              <dd>视频支持单向生成，暂不接受参考图</dd>
            </div>
          </dl>

          {chosen ? (
            <div className="video-picked">
              <span className="video-picked-label">已选方向</span>
              <strong>{chosen.title}</strong>
              <p>{chosen.logline}</p>
              {chosen.risk ? <p className="video-risk">风险：{chosen.risk}</p> : null}
            </div>
          ) : (
            <p className="help">
              先让 Agent 出方向，或写你自己的想法。方向选定后才能生成。
            </p>
          )}

          <StarButton
            as="button"
            type="button"
            onClick={() => void create()}
            disabled={!chosen || creating}
          >
            {creating ? (
              <Loader2 size={16} className="spin" aria-hidden="true" />
            ) : (
              <Clapperboard size={16} strokeWidth={1.8} aria-hidden="true" />
            )}
            {creating ? "正在创建并排队…" : "生成视频"}
            {!creating ? <ArrowRight size={15} aria-hidden="true" /> : null}
          </StarButton>
          <p className="help">
            创建后到项目页点生成；本地 8 GB 下 5 秒通常 3–6 分钟，10 秒更久。
          </p>
        </section>
      </aside>
    </div>
  );
}
