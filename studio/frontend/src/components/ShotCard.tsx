import { mediaUrl, type Project, type RenderRecord, type Shot } from "../lib/api";
import { aspectRatio, shotState, shotUnit } from "../lib/format";
import { StatusPill } from "./StatusPill";

export function ShotCard({
  project,
  shot,
  render,
  onOpen,
  onPreview,
}: {
  project: Project;
  shot: Shot;
  render?: RenderRecord;
  onOpen: () => void;
  onPreview: () => void;
}) {
  const state = shotState(shot, render);
  const done = state === "done" && render?.file_url;
  const failed = state === "failed";
  const pending = state === "running" || state === "queued";
  const aspect = shot.aspect || project.plan.aspect;
  const frameNo = String(shot.index).padStart(2, "0");
  const unit = shotUnit(project.route);
  const sub = failed
    ? render?.error || "生成失败"
    : done
      ? render?.width && render?.height
        ? `${render.width} × ${render.height}`
        : "已出图"
      : pending
        ? "ComfyUI 正在处理"
        : `${aspect} · ${shot.camera || "提示词已就绪"}`;
  const suffix = (render?.file_url.match(/\.[a-z0-9]+$/i) || [".png"])[0];
  const fileName = `${project.title || "画面"}-${frameNo}${suffix}`;

  return (
    <div className={`shot-card${failed ? " shot-card-failed" : ""}`}>
      <div className="shot-frame-wrap">
        <button
          type="button"
          className={`shot-frame shot-frame-btn${done ? "" : " shot-frame-pending"}`}
          style={{
            aspectRatio: aspectRatio(shot.aspect || project.plan.aspect),
          }}
          onClick={done ? onPreview : onOpen}
          aria-label={done ? "放大查看这张图" : "查看画面详情"}
        >
          {done ? (
            <img
              src={mediaUrl(render.file_url)}
              alt={`${shot.title || "画面"}，第 ${shot.index} ${unit}`}
              loading="lazy"
            />
          ) : (
            <>
              <span className="shot-slate-field" aria-hidden="true" />
              <span className="shot-slate-top">
                <span className="shot-slate-label">
                  {project.route === "cinema" ? "FRAME" : "IMAGE"} {frameNo}
                </span>
                <span className="shot-slate-aspect">{aspect}</span>
              </span>
              <span className="shot-slate-center">
                <span className="shot-slate-index tnum">{frameNo}</span>
                <span className="shot-placeholder">
                  {failed
                    ? "没有生成图片"
                    : pending
                      ? "ComfyUI 正在处理"
                      : "等待生成"}
                </span>
              </span>
              <span className="shot-slate-bottom">
                <span>
                  {failed
                    ? "原始错误已保留"
                    : pending
                      ? "进度会自动刷新"
                      : "提示词已就绪"}
                </span>
                <span>点击查看</span>
              </span>
            </>
          )}
          {done ? <span className="shot-hover">放大查看</span> : null}
        </button>

        {done ? (
          <a
            className="shot-dl"
            href={mediaUrl(render.file_url)}
            download={fileName}
            onClick={(event) => event.stopPropagation()}
            title="只下载这张图"
            aria-label="只下载这张图"
          >
            下载
          </a>
        ) : null}
      </div>

      <button type="button" className="shot-info" onClick={onOpen}>
        <span className="shot-row">
          <span className="shot-index">{shot.index}</span>
          <span className="shot-title">{shot.title || "未命名画面"}</span>
          <StatusPill status={state} />
        </span>
        <span
          className={`shot-sub${failed ? " shot-sub-error" : ""}`}
          title={failed ? render?.error || "生成失败" : undefined}
        >
          {sub}
        </span>
      </button>
    </div>
  );
}
