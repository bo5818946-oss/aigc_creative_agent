import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Clapperboard, Download, Loader2 } from "lucide-react";
import {
  exportUrl,
  getProject,
  getProjectProgress,
  mediaUrl,
  reviseVideo,
  repromptProject,
  startRender,
  type Project,
  type RenderProgressItem,
  type Shot,
} from "../lib/api";
import { useHealth } from "../lib/health";
import {
  formatDateTime,
  formatDuration,
  modeLabel,
  renderFor,
  routeLabel,
  shotNoun,
  shotUnit,
} from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";
import { Callout } from "../components/Callout";
import { StarButton } from "../components/StarButton";
import { ShotCard } from "../components/ShotCard";
import { ImageLightbox, type LightboxItem } from "../components/ImageLightbox";
import { ShotInspector } from "../components/ShotInspector";
import { StatusPill } from "../components/StatusPill";

type Filter = "all" | "done" | "open";

function decisionParams(project: Project) {
  const params = project.plan.agent_decision?.params ?? {};
  const items: { label: string; value: string }[] = [];
  if (project.route === "cinema") {
    items.push({ label: "镜头", value: `${project.plan.shots.length} 镜` });
  } else {
    items.push({ label: "图片包", value: `${project.plan.shots.length} 张` });
  }
  if (project.plan.aspect) {
    items.push({ label: "画幅", value: project.plan.aspect });
  }
  if (project.route === "ecommerce") {
    for (const [key, label] of [
      ["product_name", "商品"],
      ["platform", "平台"],
    ] as const) {
      const value = params[key];
      if (value !== null && value !== undefined && String(value).trim()) {
        items.push({ label, value: String(value) });
      }
    }
  }
  return items;
}

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const { health } = useHealth();
  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [syncError, setSyncError] = useState("");
  const [starting, setStarting] = useState(false);
  const [reprompting, setReprompting] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [progress, setProgress] = useState<RenderProgressItem | null>(null);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [confirmReprompt, setConfirmReprompt] = useState(false);
  const [preview, setPreview] = useState<number | null>(null);
  const [repromptNote, setRepromptNote] = useState("");
  const wasRunning = useRef(false);
  const lastElapsed = useRef(0);
  const [revising, setRevising] = useState(false);

  usePageTitle(project?.title ?? "项目");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const next = await getProject(projectId, signal);
      setProject(next);
      return next;
    },
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError("");
    load(controller.signal)
      .catch((exc: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [load]);

  const rendering = project?.status === "rendering";


  useEffect(() => {
    if (!rendering) return;
    const timer = window.setInterval(() => {
      load()
        .then(() => setSyncError(""))
        .catch((exc: unknown) =>
          setSyncError(exc instanceof Error ? exc.message : String(exc)),
        );
    }, 1800);
    return () => window.clearInterval(timer);
  }, [rendering, load]);

  useEffect(() => {
    if (!rendering) {
      setProgress(null);
      return undefined;
    }
    let cancelled = false;
    const tick = () => {
      getProjectProgress(projectId)
        .then((snapshot) => {
          if (cancelled) return;
          setProgress(snapshot.items[0] ?? null);
        })
        .catch(() => {
          /* the coarse project poll is still running; keep the bar honest */
        });
    };
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [rendering, projectId]);

  const total = project?.plan.shots.length ?? 0;
  const done = project?.done_count ?? 0;
  const failed = project?.failed_count ?? 0;
  const running = project?.status === "rendering";
  useEffect(() => {
    if (progress) lastElapsed.current = progress.elapsed_seconds;
  }, [progress]);

  useEffect(() => {
    if (running) {
      wasRunning.current = true;
      setFinishedAt(null);
      return undefined;
    }
    if (!wasRunning.current) return undefined;
    wasRunning.current = false;
    setFinishedAt(Date.now());
    const timer = window.setTimeout(() => setFinishedAt(null), 8000);
    return () => window.clearTimeout(timer);
  }, [running]);

  const allDone = total > 0 && done === total;
  const missing = useMemo(() => {
    if (!project) return [];
    return project.plan.shots
      .filter((shot) => renderFor(project, shot.index)?.status !== "done")
      .map((shot) => shot.index);
  }, [project]);
  const failedIndices = useMemo(() => {
    if (!project) return [];
    return project.renders
      .filter((render) => render.status === "failed")
      .map((render) => render.shot_index);
  }, [project]);

  const currentRender = project?.renders.find(
    (render) => render.status === "running",
  ) ?? project?.renders.find((render) => render.status === "queued");
  const currentShot = currentRender
    ? project?.plan.shots.find((shot) => shot.index === currentRender.shot_index)
    : undefined;
  const donePercent = total ? Math.round((done / total) * 100) : 0;
  const stepLive =
    progress && progress.max > 0
      ? Math.min(100, Math.round(progress.percent))
      : null;
  const stepLabel =
    progress && progress.max > 0
      ? `第 ${progress.value} / ${progress.max} 步`
      : progress?.phase === "finishing"
        ? "正在封装文件"
        : progress?.phase === "running"
          ? progress.elapsed_seconds > 20
            ? "模型加载中，首次会比较慢"
            : "正在启动采样"
          : "排队中";
  const elapsedLabel = progress ? formatDuration(progress.elapsed_seconds) : "";
  const etaLabel =
    progress &&
    progress.value >= 2 &&
    progress.eta_seconds &&
    progress.eta_seconds > 1
      ? formatDuration(progress.eta_seconds)
      : "";

  const isVideo = project?.plan.kind === "video";
  const clip = isVideo ? project?.plan.shots[0] : undefined;
  const clipRender = isVideo
    ? project?.renders.find((render) => render.shot_index === 1)
    : undefined;

  const visibleShots = useMemo(() => {
    if (!project) return [];
    return project.plan.shots.filter((shot) => {
      const state = renderFor(project, shot.index)?.status;
      if (filter === "done") return state === "done";
      if (filter === "open") return state !== "done";
      return true;
    });
  }, [project, filter]);

  const previewItems = useMemo<LightboxItem[]>(() => {
    if (!project) return [];
    return project.plan.shots.flatMap((shot) => {
      const render = renderFor(project, shot.index);
      if (!render || render.status !== "done" || !render.file_url) return [];
      const suffix = (render.file_url.match(/\.[a-z0-9]+$/i) || [".png"])[0];
      return [
        {
          shotIndex: shot.index,
          src: mediaUrl(render.file_url),
          title: shot.title || `第 ${shot.index} ${shotUnit(project.route)}`,
          caption: [
            project.title,
            render.width && render.height
              ? `${render.width} × ${render.height}`
              : "",
          ]
            .filter(Boolean)
            .join(" · "),
          download: `${project.title}-${String(shot.index).padStart(2, "0")}${suffix}`,
        },
      ];
    });
  }, [project]);

  const visibleGroups = useMemo(() => {
    const groups: { aspect: string; shots: Shot[] }[] = [];
    for (const shot of visibleShots) {
      const aspect = shot.aspect || project?.plan.aspect || "";
      const last = groups[groups.length - 1];
      if (last && last.aspect === aspect) {
        last.shots.push(shot);
      } else {
        groups.push({ aspect, shots: [shot] });
      }
    }
    return groups;
  }, [visibleShots, project]);

  const selectedShot = project?.plan.shots.find(
    (shot) => shot.index === selected,
  );
  const selectedRender =
    project && selected ? renderFor(project, selected) : undefined;

  async function runRender(indices: number[] | null) {
    if (!project) return;
    setStarting(true);
    setActionError("");
    try {
      const response = await startRender(project.project_id, indices);
      if (response.project) setProject(response.project);
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setStarting(false);
    }
  }

  function generateLabel() {
    if (running) return "正在生成…";
    if (starting) return "正在提交…";
    if (isVideo) return done > 0 ? "重新生成视频" : "生成视频";
    if (allDone) return "重新生成全部";
    if (done === 0 && failed > 0)
      return `重试失败${project?.route === "cinema" ? "镜头" : "图片"}`;
    if (done > 0) return "继续生成";
    return "生成全部";
  }

  async function runRevise() {
    if (!project || !feedback.trim()) return;
    setRevising(true);
    setActionError("");
    try {
      const next = await reviseVideo(project.project_id, feedback.trim());
      setProject(next);
      setFeedback("");
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRevising(false);
    }
  }

  async function runReprompt() {
    if (!project) return;
    setConfirmReprompt(false);
    setReprompting(true);
    setActionError("");
    setRepromptNote("");
    try {
      const next = await repromptProject(project.project_id);
      setProject(next);
      setRepromptNote("提示词已重写，旧的生成结果已清除。");
      window.setTimeout(() => setRepromptNote(""), 8000);
    } catch (exc) {
      setActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setReprompting(false);
    }
  }

  function generateIndices(): number[] | null {
    if (allDone) return null;
    if (done === 0 && failed > 0) return failedIndices;
    if (done > 0) return missing;
    return null;
  }

  function openShot(index: number) {
    setSelected(index);
    setInspectorOpen(true);
  }

  function closeInspector() {
    setInspectorOpen(false);
    setSelected(null);
  }

  if (loading) {
    return <p className="loading-line">正在读取项目…</p>;
  }

  if (!project) {
    return (
      <div>
        <p className="back-link">
          <Link to="/library">
            <ArrowLeft size={14} strokeWidth={1.8} aria-hidden="true" />
            项目
          </Link>
        </p>
        <Callout title="项目没有打开">
          <span className="pre-wrap">{loadError || "项目不存在。"}</span>
        </Callout>
      </div>
    );
  }

  const decision = project.plan.agent_decision ?? {};
  const params = decisionParams(project);
  const primaryIsExport = allDone && !running;
  const firstFailure = project.renders.find((render) => render.error)?.error;
  const unit = shotUnit(project.route);
  const noun = shotNoun(project.route);

  return (
    <div>
      <p className="back-link">
        <Link to="/library">
          <ArrowLeft size={14} strokeWidth={1.8} aria-hidden="true" />
          项目
        </Link>
      </p>

      <header className="project-head">
        <div className="project-title-block">
          <div className="project-context">
            <span>{routeLabel(project.route)}</span>
            {project.mode === "auto" ? (
              <span className="context-sep">自主决策</span>
            ) : null}
            <StatusPill status={project.status} />
          </div>
          <h1 className="h1">{project.title}</h1>
          {project.plan.summary ? (
            <p className="sub">{project.plan.summary}</p>
          ) : null}
          <p className="meta">
            更新于 {formatDateTime(project.updated_at)} · {project.plan.skill}{" "}
            {project.plan.skill_version} · 画幅 {project.plan.aspect} · 参考图{" "}
            {project.reference_id ? "已上传" : "无"}
          </p>
        </div>
        <div className="project-actions">
          {isVideo ? null : (
            <StarButton
              as="button"
              type="button"
              variant="secondary"
              onClick={() => setConfirmReprompt(true)}
              disabled={running || reprompting}
              title="按当前规则重写全部提示词；已生成的图片会一并清除"
            >
              {reprompting ? "正在重写…" : "重写提示词"}
            </StarButton>
          )}
          <StarButton
            as="button"
            type="button"
            variant={primaryIsExport ? "secondary" : "primary"}
            onClick={() => void runRender(generateIndices())}
            disabled={starting || running}
          >
            {running ? <span className="working-dot" aria-hidden="true" /> : null}
            {generateLabel()}
          </StarButton>
          <StarButton
            as="a"
            variant={primaryIsExport ? "primary" : "secondary"}
            href={exportUrl(project.project_id)}
            download
          >
            <Download size={15} strokeWidth={1.8} aria-hidden="true" />
            导出 ZIP
          </StarButton>
        </div>
      </header>

      {confirmReprompt ? (
        <section className="confirm-bar" role="alertdialog" aria-label="确认重写提示词">
          <p>
            重写会用当前技能规则重新生成全部提示词，并删除已生成的
            {isVideo ? "视频" : "图片"}（提示词变了，旧文件不再对应）。
          </p>
          <div className="confirm-actions">
            <button
              type="button"
              className="link-button"
              onClick={() => setConfirmReprompt(false)}
            >
              取消
            </button>
            <StarButton as="button" type="button" onClick={() => void runReprompt()}>
              确认重写
            </StarButton>
          </div>
        </section>
      ) : null}

      {repromptNote ? <p className="sync-note is-ok">{repromptNote}</p> : null}

      {running ? (
        <section className="render-strip" role="status" aria-live="polite">
          <div className="render-strip-head">
            <span className="section-title">
              {isVideo ? "正在渲染本地视频" : "正在生成本地图像"}
            </span>
            <span className="render-percent tnum">
              {stepLive !== null ? `${stepLive}%` : `${donePercent}%`}
            </span>
          </div>
          <div
            className="progress-track"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={stepLive ?? donePercent}
            aria-label="渲染进度"
          >
            <div
              className={`progress-fill${
                stepLive === null ? " is-scanning" : ""
              }`}
              style={{ width: `${stepLive ?? 100}%` }}
            />
          </div>
          <div className="render-meta tnum">
            <span className="render-step">{stepLabel}</span>
            <span className="render-clock">
              {elapsedLabel ? `已用 ${elapsedLabel}` : "刚刚提交"}
              {etaLabel ? ` · 预计还要 ${etaLabel}` : ""}
            </span>
          </div>
          <p className="render-current">
            {currentShot
              ? `第 ${currentShot.index} ${unit} · ${currentShot.title || "未命名画面"}`
              : "等待 ComfyUI 接收任务"}
          </p>
        </section>
      ) : null}

      {!running && finishedAt ? (
        <section className="render-strip is-done" role="status">
          <div className="render-strip-head">
            <span className="section-title">
              {isVideo ? "视频已生成" : "图像已生成"}
            </span>
            <span className="render-percent tnum">100%</span>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: "100%" }} />
          </div>
          <div className="render-meta tnum">
            <span className="render-step">完成</span>
            <span>
              用时 {formatDuration(lastElapsed.current)}
              {isVideo ? " · 可以播放了" : " · 可以在画面里查看"}
            </span>
          </div>
        </section>
      ) : null}

      {health && !health.comfyui_reachable && !running ? (
        <Callout tone="warning" title="本地模型离线">
          出图前请先在设置页启动 ComfyUI。规划和修改提示词仍然可用。
        </Callout>
      ) : null}

      {actionError ? (
        <Callout title="操作没有完成">
          <span className="pre-wrap">{actionError}</span>
        </Callout>
      ) : null}

      {syncError ? (
        <p className="sync-note">状态刷新失败：{syncError}</p>
      ) : null}

      {!running && failed > 0 && firstFailure ? (
        <Callout
          title={
            project.route === "video"
              ? `${failed} 条视频生成失败`
              : project.route === "cinema"
                ? `${failed} 个镜头生成失败`
                : `${failed} 张图片生成失败`
          }
        >
          <span className="pre-wrap">{firstFailure}</span>
          <span className="callout-hint">
            可以修改提示词后重新生成，或点「继续生成」只补未完成的{noun}。
          </span>
        </Callout>
      ) : null}

      {project.mode === "auto" ? (
        <section
          className="panel decision-panel"
          aria-labelledby="decision-title"
        >
          <div className="panel-head">
            <h2 id="decision-title" className="section-title">
              Agent 判断
            </h2>
            <span className="meta">
              {routeLabel(project.route)} · {modeLabel(project.mode)}
            </span>
          </div>
          <p className="decision-reason">
            {decision.reasoning || "没有单独返回判断理由。"}
          </p>
          {params.length ? (
            <div className="decision-params">
              {params.map((item) => (
                <span className="decision-param" key={item.label}>
                  <span className="decision-param-label">{item.label}</span>
                  {item.value}
                </span>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {isVideo ? (
        <section className="video-stage" aria-labelledby="clip-title">
          <div className="video-stage-head">
            <h2 id="clip-title" className="section-title">
              成片
            </h2>
            <span className="meta">
              {clip ? `${clip.seconds} 秒` : ""} · {project.plan.aspect}
              {clipRender?.status === "done" && clipRender.file_url ? (
                <a
                  className="video-dl"
                  href={mediaUrl(clipRender.file_url)}
                  download={`${project.title}.mp4`}
                >
                  下载视频
                </a>
              ) : null}
            </span>
          </div>

          <div className="video-frame">
            {clipRender?.status === "done" && clipRender.file_url ? (
              <video
                className="video-player"
                src={mediaUrl(clipRender.file_url)}
                controls
                playsInline
                preload="metadata"
              />
            ) : (
              <div
                className={`video-placeholder${clipRender ? ` is-${clipRender.status}` : ""}`}
              >
                <Clapperboard size={26} strokeWidth={1.6} aria-hidden="true" />
                <span>
                  {running
                    ? "正在渲染，先别关页面"
                    : clipRender?.status === "failed"
                      ? "这条失败了，下面是模型给的报错"
                      : "还没有成片"}
                </span>
                {clipRender?.error ? (
                  <p className="pre-wrap video-error">{clipRender.error}</p>
                ) : null}
              </div>
            )}
          </div>

          <div className="video-copy">
            <p className="video-logline">{project.plan.summary}</p>
            <p className="meta">{project.plan.reasoning}</p>
            {clip?.notes ? <p className="meta">声音：{clip.notes}</p> : null}
          </div>

          <div className="panel revise-panel">
            <div className="panel-head">
              <h3 className="section-title">追加要求</h3>
              <span className="meta">改写提示词，旧片会被清掉</span>
            </div>
            <textarea
              className="textarea"
              value={feedback}
              maxLength={800}
              onChange={(event) => setFeedback(event.target.value)}
              placeholder="例：再暖一点，镜头别动，结尾多留半秒空白。"
              aria-label="对这条视频的追加要求"
            />
            <StarButton
              as="button"
              type="button"
              variant="secondary"
              onClick={() => void runRevise()}
              disabled={revising || running || feedback.trim().length < 2}
            >
              {revising ? (
                <Loader2 size={15} className="spin" aria-hidden="true" />
              ) : null}
              {revising ? "正在改写…" : "按这个要求改写"}
            </StarButton>
          </div>
        </section>
      ) : null}

      {!isVideo ? (
      <section className="frames-section" aria-labelledby="frames-title">
        <div className="frames-head">
          <div className="panel-head">
            <h2 id="frames-title" className="section-title">
              画面
            </h2>
            <span className="meta">
              {visibleShots.length} / {total}
            </span>
          </div>
          <div className="filter-tabs" role="group" aria-label="筛选画面">
            <button
              type="button"
              aria-pressed={filter === "all"}
              onClick={() => setFilter("all")}
            >
              全部 <span className="tab-count">{total}</span>
            </button>
            <button
              type="button"
              aria-pressed={filter === "done"}
              onClick={() => setFilter("done")}
            >
              已出图 <span className="tab-count">{done}</span>
            </button>
            <button
              type="button"
              aria-pressed={filter === "open"}
              onClick={() => setFilter("open")}
            >
              未完成 <span className="tab-count">{total - done}</span>
            </button>
          </div>
        </div>

        {visibleShots.length ? (
          <div className="frame-groups">
            {visibleGroups.map((group, groupIndex) => {
              const splitPack =
                project.route === "ecommerce" &&
                project.plan.shots.length === 12;
              const title = splitPack
                ? group.aspect === "1:1"
                  ? "主图"
                  : group.aspect === "2:3"
                    ? "详情页"
                    : "画面"
                : "画面";
              return (
                <div className="frame-group" key={`${group.aspect}-${groupIndex}`}>
                  {visibleGroups.length > 1 ? (
                    <div className="frame-group-head">
                      <h3 className="frame-group-title">
                        {title}
                        {splitPack ? ` · ${group.aspect}` : ""}
                      </h3>
                      <span className="meta tnum">{group.shots.length} {unit}</span>
                    </div>
                  ) : null}
                  <div className="shot-grid">
                    {group.shots.map((shot) => (
                      <ShotCard
                        key={shot.index}
                        project={project}
                        shot={shot}
                        render={renderFor(project, shot.index)}
                        onOpen={() => openShot(shot.index)}
                        onPreview={() => {
                          const position = previewItems.findIndex(
                            (item) => item.shotIndex === shot.index,
                          );
                          if (position >= 0) setPreview(position);
                        }}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="empty-inline">
            {filter === "done"
              ? `还没有已出图的${noun}。`
              : `这个筛选下没有${noun}。`}
          </p>
        )}
      </section>
      ) : null}

      <section className="project-plan" aria-labelledby="plan-title">
        <div className="project-plan-head">
          <h2 id="plan-title" className="section-title">
            方案
          </h2>
          <span className="meta">
            规划于 {formatDateTime(project.plan.created_at)}
          </span>
        </div>

        <div className="grid12 plan-grid">
          {project.plan.reasoning ? (
            <section
              className={`panel ${
                project.plan.warnings.length ? "span-7" : "span-12"
              }`}
              aria-labelledby="reasoning-title"
            >
              <div className="panel-head">
                <h2 id="reasoning-title" className="section-title">
                  {project.route === "cinema" ? "排镜理由" : "排图理由"}
                </h2>
              </div>
              <p className="decision-reason">{project.plan.reasoning}</p>
            </section>
          ) : null}

          {project.plan.warnings.length ? (
            <section
              className={`panel warning-panel ${
                project.plan.reasoning ? "span-5" : "span-12"
              }`}
              aria-labelledby="warnings-title"
            >
              <div className="panel-head">
                <h2 id="warnings-title" className="section-title">
                  待确认与风险
                </h2>
              </div>
              <ul className="warning-list">
                {project.plan.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section
            className="panel span-12 plan-fold"
            aria-labelledby="details-title"
          >
            <div className="panel-head">
              <h2 id="details-title" className="section-title">
                方案细节
              </h2>
            </div>
            <div className="detail-grid">
              <details className="detail">
                <summary>Style Lock</summary>
                <p className="detail-text">
                  {project.plan.style_lock || "—"}
                </p>
              </details>
              <details className="detail">
                <summary>连续性</summary>
                <p className="detail-text">
                  {project.plan.continuity || "—"}
                </p>
              </details>
              <details className="detail">
                <summary>原始需求</summary>
                <p className="detail-text pre-wrap">{project.brief}</p>
              </details>
            </div>
          </section>
        </div>
      </section>


      {preview !== null && previewItems[preview] ? (
        <ImageLightbox
          items={previewItems}
          index={preview}
          onIndex={setPreview}
          onClose={() => setPreview(null)}
        />
      ) : null}

      {selectedShot && inspectorOpen ? (
        <ShotInspector
          project={project}
          shot={selectedShot}
          render={selectedRender}
          onClose={closeInspector}
          onProjectUpdate={(updated) => {
            setProject(updated);
            setActionError("");
          }}
        />
      ) : null}
    </div>
  );
}
