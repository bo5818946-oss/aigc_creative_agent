import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Search } from "lucide-react";
import {
  listProjects,
  mediaUrl,
  type Mode,
  type ProjectSummary,
} from "../lib/api";
import { formatDateTime, formatNumber, routeLabel, shotUnit } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";
import { Callout } from "../components/Callout";
import { CrosshairLayer } from "../components/CrosshairLayer";
import { MediaThumb } from "../components/MediaThumb";
import { getProjectProgress } from "../lib/api";
import { StarButton } from "../components/StarButton";
import { StatusPill } from "../components/StatusPill";

type Filter = "all" | Mode;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "cinema", label: "影视图" },
  { value: "ecommerce", label: "电商图" },
  { value: "auto", label: "自主决策" },
  { value: "video", label: "视频" },
];

const START_ROUTES = [
  {
    mode: "cinema",
    title: "影视图",
    skill: "Cinema DNA",
    copy: "单帧、三联或九镜。先定事件与连续性，再写机位、光线和动作。",
  },
  {
    mode: "ecommerce",
    title: "电商图",
    skill: "ecom-details-image",
    copy: "1、5 或 12 张主图与详情页，整套共用一份风格合同。",
  },
  {
    mode: "auto",
    title: "自主决策",
    skill: "Agent 路由",
    copy: "只写目标。Agent 判断路线，并替你决定数量、画幅和平台策略。",
  },
] as const;

export function LibraryPage() {
  usePageTitle("项目");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [livePercent, setLivePercent] = useState<Record<string, number>>({});
  const [query, setQuery] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listProjects(100, 0, controller.signal)
      .then((payload) => {
        setProjects(payload.items);
        setTotal(payload.total);
        setError("");
      })
      .catch((exc: unknown) => {
        if (controller.signal.aborted) return;
        setError(exc instanceof Error ? exc.message : String(exc));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const counts = useMemo(() => {
    return {
      all: projects.length,
      cinema: projects.filter((item) => item.mode === "cinema").length,
      ecommerce: projects.filter((item) => item.mode === "ecommerce").length,
      auto: projects.filter((item) => item.mode === "auto").length,
  video: projects.filter((item) => item.mode === "video").length,
    };
  }, [projects]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return projects.filter((project) => {
      if (filter !== "all" && project.mode !== filter) return false;
      if (!needle) return true;
      const haystack = `${project.title} ${project.brief} ${project.plan.summary}`;
      return haystack.toLowerCase().includes(needle);
    });
  }, [projects, filter, query]);

  const renderingIds = useMemo(
    () =>
      projects
        .filter((item) => item.status === "rendering")
        .map((item) => item.project_id),
    [projects],
  );

  useEffect(() => {
    if (renderingIds.length === 0) {
      setLivePercent({});
      return undefined;
    }
    let cancelled = false;
    const tick = () => {
      Promise.all(
        renderingIds.map((id) =>
          getProjectProgress(id)
            .then((snapshot) => [id, snapshot.items[0]?.percent ?? 0] as const)
            .catch(() => null),
        ),
      ).then((entries) => {
        if (cancelled) return;
        const next: Record<string, number> = {};
        for (const entry of entries) {
          if (entry) next[entry[0]] = Math.round(entry[1]);
        }
        setLivePercent(next);
      });
    };
    tick();
    const timer = window.setInterval(tick, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [renderingIds]);

  const truncated = total > projects.length;

  return (
    <div className="library-page">
      <CrosshairLayer />
      <header className="page-head">
        <div>
          <h1 className="h1">项目</h1>
          <p className="sub">
            {total
              ? `${formatNumber(total)} 个本地项目，最近更新在前。`
              : "本地保存的创作项目。"}
          </p>
        </div>
        <StarButton as={Link} to="/new">
          新建创作
        </StarButton>
      </header>

      {error ? (
        <Callout title="无法读取项目">
          <span className="pre-wrap">{error}</span>
        </Callout>
      ) : null}

      {!loading && projects.length > 0 ? (
        <div className="lib-toolbar">
          <div className="filter-tabs" role="group" aria-label="按路线筛选">
            {FILTERS.map((item) => (
              <button
                key={item.value}
                type="button"
                aria-pressed={filter === item.value}
                onClick={() => setFilter(item.value)}
              >
                {item.label}
                <span className="tab-count">{counts[item.value]}</span>
              </button>
            ))}
          </div>
          <label className="search-field" htmlFor="project-search">
            <Search size={15} strokeWidth={1.8} aria-hidden="true" />
            <input
              id="project-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索标题或需求"
            />
          </label>
        </div>
      ) : null}

      {loading ? (
        <p className="loading-line">正在读取项目…</p>
      ) : projects.length === 0 ? (
        <>
          <section
            className="library-empty"
            aria-labelledby="library-empty-title"
          >
            <div className="library-empty-intro">
              <h2 id="library-empty-title" className="library-empty-title">
                还没有项目
              </h2>
              <p className="library-empty-copy">
                先从一条路线开始。Agent 会先给出镜头或图片清单与逐条提示词，确认后再在本机出图。
              </p>
              <dl className="library-empty-facts">
                <div>
                  <dt>存储</dt>
                  <dd>本机 SQLite，不读写旧版数据</dd>
                </div>
                <div>
                  <dt>导出</dt>
                  <dd>plan.json · prompts.md · 已出图片</dd>
                </div>
              </dl>
            </div>

            <div className="library-empty-routes">
              <p className="library-empty-label">从一条路线开始</p>
              {START_ROUTES.map((route, index) => (
                <Link
                  key={route.mode}
                  to={`/new?mode=${route.mode}`}
                  className="library-start"
                >
                  <span className="library-start-num tnum">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="library-start-copy">
                    <span className="library-start-line">
                      <span className="library-start-name">{route.title}</span>
                      <span className="library-start-skill">{route.skill}</span>
                    </span>
                    <span className="library-start-note">{route.copy}</span>
                  </span>
                  <ArrowRight
                    size={16}
                    strokeWidth={1.8}
                    className="library-start-arrow"
                    aria-hidden="true"
                  />
                </Link>
              ))}
            </div>
          </section>

          <section
            className="library-output"
            aria-labelledby="library-output-title"
          >
            <h2 id="library-output-title" className="library-output-title">
              规划完成后，先看方案再出图
            </h2>
            <div className="library-output-grid">
              <div className="library-output-item">
                <span className="library-output-index tnum">01</span>
                <span className="library-output-name">镜头与图片契约</span>
                <p className="library-output-copy">
                  数量、画幅、连续性，以及自主决策选择这条路线的原因。
                </p>
              </div>
              <div className="library-output-item">
                <span className="library-output-index tnum">02</span>
                <span className="library-output-name">逐条提示词</span>
                <p className="library-output-copy">
                  英文提示词与中文导演注记；出图前可以逐条修改。
                </p>
              </div>
              <div className="library-output-item">
                <span className="library-output-index tnum">03</span>
                <span className="library-output-name">真实文件</span>
                <p className="library-output-copy">
                  plan.json、prompts.md 与已生成图片；失败保留原始错误。
                </p>
              </div>
            </div>
          </section>
        </>
      ) : visible.length === 0 ? (
        <div className="empty-inline">
          <p>没有符合条件的项目。</p>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setFilter("all");
              setQuery("");
            }}
          >
            清除筛选
          </button>
        </div>
      ) : (
        <div className="lib-table">
          <div className="lib-head" aria-hidden="true">
            <span>项目</span>
            <span>路线</span>
            <span className="right">已出图</span>
            <span className="right">失败</span>
            <span className="right">更新</span>
          </div>
          {visible.map((project) => {
            const shots = project.plan.shots.length;
            const covers = project.cover_urls.slice(0, 3);
            return (
              <Link
                key={project.project_id}
                to={`/projects/${project.project_id}`}
                className="lib-row"
              >
                {livePercent[project.project_id] !== undefined ? (
                  <span className="lib-row-bar" aria-hidden="true">
                    <span
                      style={{ width: `${livePercent[project.project_id]}%` }}
                    />
                  </span>
                ) : null}
                <span className="lib-project">
                  <span className="lib-covers">
                    {covers.length ? (
                      covers.map((url) => (
                        <span className="lib-cover" key={url}>
                          <MediaThumb src={mediaUrl(url)} />
                        </span>
                      ))
                    ) : (
                      <span className="lib-cover lib-cover-empty">未出图</span>
                    )}
                  </span>
                  <span className="lib-title-block">
                    <span className="lib-title-line">
                      <span className="lib-title">{project.title}</span>
                      <StatusPill status={project.status} />
                    {livePercent[project.project_id] !== undefined ? (
                      <span className="lib-live tnum">
                        {livePercent[project.project_id] > 0
                          ? `${livePercent[project.project_id]}%`
                          : "启动中"}
                      </span>
                    ) : null}
                    </span>
                    <span className="lib-sub">
                      {shots} {shotUnit(project.route)} · {project.plan.skill} · 更新于{" "}
                      {formatDateTime(project.updated_at)}
                    </span>
                  </span>
                </span>
                <span className="lib-route" data-label="路线">
                  {routeLabel(project.route)}
                  {project.mode === "auto" ? " · 自主" : ""}
                </span>
                <span className="lib-num tnum" data-label="已出图">
                  {project.done_count} / {shots}
                </span>
                <span
                  className={`lib-num tnum${
                    project.failed_count ? " value-negative" : ""
                  }`}
                  data-label="失败"
                >
                  {project.failed_count}
                </span>
                <span
                  className="lib-updated"
                  data-label="更新"
                >
                  {formatDateTime(project.updated_at)}
                </span>
              </Link>
            );
          })}
        </div>
      )}

      {truncated && !loading ? (
        <p className="lib-note">
          当前显示最近 {projects.length} 个项目；本地共有 {total} 个。
        </p>
      ) : null}
    </div>
  );
}
