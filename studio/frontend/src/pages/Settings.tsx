import { useState } from "react";
import { ExternalLink, Play, RefreshCw } from "lucide-react";
import { startComfy } from "../lib/api";
import { useHealth } from "../lib/health";
import { formatNumber } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";
import { Callout } from "../components/Callout";
import { CrosshairLayer } from "../components/CrosshairLayer";
import { StarButton } from "../components/StarButton";

function StatusDot({ on, unknown }: { on: boolean; unknown?: boolean }) {
  return (
    <span
      className={`dot ${unknown ? "dot-neutral" : on ? "dot-on" : "dot-off"}`}
      aria-hidden="true"
    />
  );
}

export function SettingsPage() {
  usePageTitle("设置");
  const { health, error, loading, refresh } = useHealth();
  const [refreshing, setRefreshing] = useState(false);
  const [starting, setStarting] = useState(false);
  const [startMessage, setStartMessage] = useState("");
  const [startError, setStartError] = useState("");

  const comfyOnline = Boolean(health?.comfyui_reachable);

  async function checkAgain() {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  }

  async function startLocalModel() {
    setStarting(true);
    setStartError("");
    setStartMessage("正在启动 ComfyUI，并等待端口响应。通常需要 1–3 分钟…");
    try {
      const result = await startComfy();
      if (!result.ok) {
        throw new Error(result.message || "启动器没有返回成功。");
      }
      setStartMessage(result.message || "ComfyUI 已启动。");
      await refresh();
    } catch (exc) {
      setStartMessage("");
      setStartError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="settings-page">
      <CrosshairLayer />
      <header className="page-head">
        <div>
          <h1 className="h1">设置</h1>
          <p className="sub">
            本机模型、规划服务与技能版本。这里的每项状态都来自后端实时探测。
          </p>
        </div>
        <StarButton
          as="button"
          type="button"
          variant="secondary"
          onClick={() => void checkAgain()}
          disabled={refreshing}
        >
          <RefreshCw
            size={15}
            strokeWidth={1.8}
            className={refreshing ? "spin" : undefined}
            aria-hidden="true"
          />
          {refreshing ? "正在检测…" : "重新检测"}
        </StarButton>
      </header>

      {error ? (
        <Callout title="本地 API 没有响应">
          <span className="pre-wrap">{error}</span>
        </Callout>
      ) : null}

      <div className="settings-list">
        <section className="settings-row" aria-labelledby="planner-title">
          <div className="settings-label">
            <h2 id="planner-title">规划服务</h2>
            <p>
              DeepSeek 只负责把技能规则变成方案与逐条提示词，不接触图片，也不接收密钥以外的本机信息。
            </p>
          </div>
          <div className="settings-panel">
            <dl className="data-list">
              <div className="data-row">
                <dt>状态</dt>
                <dd>
                  <span className="status-inline">
                    <StatusDot
                      on={Boolean(health?.deepseek_configured)}
                      unknown={!health}
                    />
                    {loading && !health
                      ? "正在检测"
                      : health?.deepseek_configured
                        ? "已配置"
                        : "未配置"}
                  </span>
                </dd>
              </div>
              <div className="data-row">
                <dt>模型</dt>
                <dd>{health?.deepseek_model || "—"}</dd>
              </div>
              <div className="data-row">
                <dt>调用位置</dt>
                <dd>服务端 · api.deepseek.com</dd>
              </div>
            </dl>
            {health && !health.deepseek_configured ? (
              <Callout tone="warning" title="缺少 DeepSeek 密钥">
                在仓库根目录的 .env 中设置 DEEPSEEK_API_KEY
                后重启后端。密钥不会发送到浏览器。
              </Callout>
            ) : (
              <p className="settings-note">
                规划结果会校验镜头或图片数量、画幅与字段契约；不合格的响应会直接报错，不会用占位方案补齐。
              </p>
            )}
          </div>
        </section>

        <section className="settings-row" aria-labelledby="comfy-title">
          <div className="settings-label">
            <h2 id="comfy-title">本地图像模型</h2>
            <p>
              ComfyUI 在本机生成图片。规划和提示词不依赖它，出图与参考图条件输入依赖它。
            </p>
          </div>
          <div className="settings-panel">
            <dl className="data-list">
              <div className="data-row">
                <dt>状态</dt>
                <dd>
                  <span className="status-inline">
                    <StatusDot on={comfyOnline} unknown={!health} />
                    {loading && !health
                      ? "正在检测"
                      : comfyOnline
                        ? "在线"
                        : health
                          ? "离线"
                          : "未知"}
                  </span>
                </dd>
              </div>
              <div className="data-row">
                <dt>地址</dt>
                <dd>
                  {health?.comfyui_url ? (
                    <a
                      className="inline-link"
                      href={health.comfyui_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {health.comfyui_url}
                      <ExternalLink
                        size={12}
                        strokeWidth={1.8}
                        aria-hidden="true"
                      />
                    </a>
                  ) : (
                    "—"
                  )}
                </dd>
              </div>
              <div className="data-row">
                <dt>版本</dt>
                <dd>{health?.comfyui_version || "—"}</dd>
              </div>
              <div className="data-row">
                <dt>设备</dt>
                <dd>{health?.comfyui_devices.join(" · ") || "—"}</dd>
              </div>
              <div className="data-row">
                <dt>显存</dt>
                <dd>
                  {health?.comfyui_vram_gb
                    ? `${health.comfyui_vram_gb} GB`
                    : "—"}
                </dd>
              </div>
            </dl>

            <div className="settings-actions">
              {!comfyOnline ? (
                <StarButton
                  as="button"
                  type="button"
                  onClick={() => void startLocalModel()}
                  disabled={
                    starting || loading || !health?.launch_configured
                  }
                  title={
                    health && !health.launch_configured
                      ? "启动器路径尚未配置"
                      : undefined
                  }
                >
                  <Play size={15} strokeWidth={1.8} aria-hidden="true" />
                  {starting ? "正在启动…" : "启动本地模型"}
                </StarButton>
              ) : (
                <StarButton
                  as="a"
                  variant="secondary"
                  href={health?.comfyui_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <ExternalLink
                    size={15}
                    strokeWidth={1.8}
                    aria-hidden="true"
                  />
                  打开 ComfyUI
                </StarButton>
              )}
            </div>

            {starting ? (
              <p className="settings-note">
                启动请求会一直等到 ComfyUI 端口可用或超时；这期间可以先留在本页。
              </p>
            ) : null}
            {startMessage && !startError ? (
              <p className="settings-note">{startMessage}</p>
            ) : null}
            {startError ? (
              <Callout title="启动没有完成">
                <span className="pre-wrap">{startError}</span>
              </Callout>
            ) : null}
            {health && !health.launch_configured ? (
              <p className="settings-note">
                启动器路径尚未配置。请在 .env 设置 AIGC_COMFYUI_PYTHON 与
                AIGC_COMFYUI_HOME，或手动启动 ComfyUI 后刷新状态。
              </p>
            ) : null}
            {health && !comfyOnline && health.comfyui_error && !startError ? (
              <Callout title="最近一次探测的原始错误">
                <span className="pre-wrap">{health.comfyui_error}</span>
              </Callout>
            ) : null}
          </div>
        </section>

        <section className="settings-row" aria-labelledby="skills-title">
          <div className="settings-label">
            <h2 id="skills-title">技能</h2>
            <p>
              技能文本在运行时从仓库读取，规划时作为系统指令；版本号来自各自的 SKILL.md。
            </p>
          </div>
          <div className="settings-panel">
            {health?.skills.length ? (
              <div className="settings-skills">
                {health.skills.map((skill) => (
                  <div className="settings-skill" key={skill.id}>
                    <div className="settings-skill-main">
                      <p className="settings-skill-name">{skill.label}</p>
                      <a
                        className="settings-skill-source"
                        href={skill.source}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {skill.source.replace("https://github.com/", "")}
                      </a>
                    </div>
                    <span className="settings-skill-version">
                      {skill.version}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="settings-empty">
                {loading ? "正在读取技能版本…" : "没有读到可用技能。"}
              </p>
            )}
            <p className="settings-note">
              影视图使用 Cinema DNA；电商图使用 ecom-details-image；自主决策先判断路线，再调用对应技能。
            </p>
          </div>
        </section>

        <section className="settings-row" aria-labelledby="data-title">
          <div className="settings-label">
            <h2 id="data-title">本地数据</h2>
            <p>
              新应用使用自己的 SQLite 数据库与媒体目录，不读写旧版 Streamlit 的数据。
            </p>
          </div>
          <div className="settings-panel">
            <dl className="data-list">
              <div className="data-row">
                <dt>项目</dt>
                <dd className="tnum">
                  {health ? formatNumber(health.project_count) : "—"}
                </dd>
              </div>
              <div className="data-row">
                <dt>数据库</dt>
                <dd className="data-url">studio/data/lumen.sqlite3</dd>
              </div>
              <div className="data-row">
                <dt>媒体</dt>
                <dd className="data-url">studio/data/uploads · studio/data/renders</dd>
              </div>
              <div className="data-row">
                <dt>导出</dt>
                <dd>plan.json · prompts.md · 已生成图片</dd>
              </div>
            </dl>
            <p className="settings-note">
              导出只收录真实生成成功的图片；未完成或失败的镜头或图片会在 README.txt
              中标注状态，不会放入占位图。
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
