import { useEffect, useState } from "react";
import {
  patchShot,
  startRender,
  type Project,
  type RenderRecord,
  type Shot,
} from "../lib/api";
import { aspectRatio, shotState, shotUnit } from "../lib/format";
import { Callout } from "./Callout";
import { Drawer } from "./Drawer";
import { StatusPill } from "./StatusPill";

interface FormState {
  title: string;
  purpose: string;
  prompt: string;
  negative: string;
  camera: string;
  caption: string;
  notes: string;
}

function formFromShot(shot: Shot): FormState {
  return {
    title: shot.title,
    purpose: shot.purpose,
    prompt: shot.prompt,
    negative: shot.negative,
    camera: shot.camera,
    caption: shot.caption,
    notes: shot.notes,
  };
}

export function ShotInspector({
  project,
  shot,
  render,
  onClose,
  onProjectUpdate,
}: {
  project: Project;
  shot: Shot;
  render?: RenderRecord;
  onClose: () => void;
  onProjectUpdate: (project: Project) => void;
}) {
  const [form, setForm] = useState<FormState>(() => formFromShot(shot));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [renderBusy, setRenderBusy] = useState(false);
  const [renderError, setRenderError] = useState("");
  const [renderNote, setRenderNote] = useState("");

  useEffect(() => {
    setForm(formFromShot(shot));
    setSaved(false);
    setSaveError("");
    setRenderError("");
    setRenderNote("");
    // Reset only when the inspector switches to another shot. A save updates
    // the same shot's props and must not wipe the "已保存" stamp.
  }, [shot.index, project.project_id]);

  useEffect(() => {
    if (render?.status === "queued" || render?.status === "running") {
      setRenderNote("已加入渲染队列，进度会自动刷新。");
    }
    if (render?.status === "done" || render?.status === "failed") {
      setRenderNote("");
    }
  }, [render?.status]);

  const state = shotState(shot, render);
  const done = render?.status === "done" && render.file_url;
  const busy = project.status === "rendering";
  const unit = shotUnit(project.route);
  const dirty =
    form.title !== shot.title ||
    form.purpose !== shot.purpose ||
    form.prompt !== shot.prompt ||
    form.negative !== shot.negative ||
    form.camera !== shot.camera ||
    form.caption !== shot.caption ||
    form.notes !== shot.notes;

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setSaved(false);
  }

  function attemptClose() {
    if (dirty && !window.confirm("有未保存的修改，仍要关闭吗？")) return;
    onClose();
  }

  async function save() {
    setSaving(true);
    setSaveError("");
    try {
      const updated = await patchShot(project.project_id, shot.index, form);
      onProjectUpdate(updated);
      setSaved(true);
    } catch (exc) {
      setSaveError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  }

  async function regenerate() {
    setRenderBusy(true);
    setRenderError("");
    setRenderNote("");
    try {
      const response = await startRender(project.project_id, [shot.index]);
      if (response.project) onProjectUpdate(response.project);
      setRenderNote("已加入渲染队列，进度会自动刷新。");
    } catch (exc) {
      setRenderError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRenderBusy(false);
    }
  }

  return (
    <Drawer
      open
      onClose={attemptClose}
      title={shot.title || "未命名画面"}
      meta={
        <span className="drawer-meta-line">
          第 {shot.index} {unit} · {shot.aspect || project.plan.aspect}
          <StatusPill status={state} />
        </span>
      }
      footer={
        <div className="inspector-footer">
          <span className="inspector-footnote">
            {saved
              ? "已保存"
              : dirty
                ? "有未保存修改"
                : busy
                  ? "生成中，暂时不能保存"
                  : `修改会清除这一${unit}的旧图`}
          </span>
          <div className="inspector-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => void regenerate()}
              disabled={renderBusy || busy}
            >
              {renderBusy ? "正在提交…" : `重新生成这一${unit}`}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void save()}
              disabled={!dirty || saving || busy}
            >
              {saving ? "保存中…" : "保存修改"}
            </button>
          </div>
        </div>
      }
    >
      <div
        className="inspector-frame"
        style={{ aspectRatio: aspectRatio(shot.aspect || project.plan.aspect) }}
      >
        {done ? (
          <img src={render.file_url} alt={`${shot.title}，第 ${shot.index} ${unit}`} />
        ) : (
          <span className="inspector-placeholder">
            {state === "failed" ? `这一${unit}没有生成图片` : "还没有图片"}
          </span>
        )}
      </div>

      {render?.error ? (
        <Callout title="ComfyUI 返回的错误">
          <span className="pre-wrap">{render.error}</span>
        </Callout>
      ) : null}
      {renderError ? (
        <Callout title="无法开始生成">
          <span className="pre-wrap">{renderError}</span>
        </Callout>
      ) : null}
      {saveError ? (
        <Callout title="保存失败">
          <span className="pre-wrap">{saveError}</span>
        </Callout>
      ) : null}
      {renderNote ? <p className="quiet-stamp">{renderNote}</p> : null}

      <div className="inspector-facts">
        <div>
          <span className="fact-label">用途</span>
          <span>{shot.purpose || "—"}</span>
        </div>
        <div>
          <span className="fact-label">
            {project.route === "cinema" ? "机位" : "视角"}
          </span>
          <span>{shot.camera || "—"}</span>
        </div>
        <div>
          <span className="fact-label">尺寸</span>
          <span>
            {render?.width && render?.height
              ? `${render.width} × ${render.height}`
              : "—"}
          </span>
        </div>
      </div>

      <div className="inspector-form">
        <label className="field" htmlFor="shot-title">
          <span className="field-label">标题</span>
          <input
            id="shot-title"
            className="input"
            value={form.title}
            onChange={(event) => update("title", event.target.value)}
          />
        </label>

        <label className="field" htmlFor="shot-prompt">
          <span className="field-label">
            最终提示词
            <span className="field-count">{form.prompt.length} 字</span>
          </span>
          <textarea
            id="shot-prompt"
            className="textarea prompt-input"
            value={form.prompt}
            onChange={(event) => update("prompt", event.target.value)}
          />
        </label>
        <p className="help">这段文本会原样提交给本地图像模型。</p>

        <label className="field" htmlFor="shot-negative">
          <span className="field-label">负面提示词</span>
          <textarea
            id="shot-negative"
            className="textarea"
            rows={3}
            value={form.negative}
            onChange={(event) => update("negative", event.target.value)}
          />
        </label>
        <p className="help">
          Z-Image Turbo 以 CFG 1.0 采样，负面提示词对结果的影响有限；真正的约束应写进正面提示词。
        </p>

        <label className="field" htmlFor="shot-purpose">
          <span className="field-label">用途</span>
          <textarea
            id="shot-purpose"
            className="textarea"
            rows={2}
            value={form.purpose}
            onChange={(event) => update("purpose", event.target.value)}
          />
        </label>

        <div className="field-row">
          <label className="field" htmlFor="shot-camera">
            <span className="field-label">
              {project.route === "cinema" ? "机位" : "视角"}
            </span>
            <input
              id="shot-camera"
              className="input"
              value={form.camera}
              onChange={(event) => update("camera", event.target.value)}
            />
          </label>
          <label className="field" htmlFor="shot-caption">
            <span className="field-label">图片内文案建议</span>
            <input
              id="shot-caption"
              className="input"
              value={form.caption}
              onChange={(event) => update("caption", event.target.value)}
              placeholder="没有就留空"
            />
          </label>
        </div>

        <label className="field" htmlFor="shot-notes">
          <span className="field-label">
            {project.route === "cinema" ? "连续性备注" : "一致性备注"}
          </span>
          <textarea
            id="shot-notes"
            className="textarea"
            rows={3}
            value={form.notes}
            onChange={(event) => update("notes", event.target.value)}
          />
        </label>
      </div>
    </Drawer>
  );
}
