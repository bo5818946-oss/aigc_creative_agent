import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, ArrowUpRight, Sparkles } from "lucide-react";
import { listProjects, mediaUrl, type ProjectSummary } from "../lib/api";
import { useHealth } from "../lib/health";
import { routeLabel } from "../lib/format";
import { usePageTitle } from "../lib/usePageTitle";
import { Reveal } from "../components/Reveal";
import { StarButton } from "../components/StarButton";
import CircularGalleryBand from "../components/reactbits/CircularGalleryBand";
import { useSpotlight } from "../lib/useSpotlight";
import TechText from "../components/reactbits/TechWordmark";
import TextLoop from "../components/reactbits/TextLoopBand";
import CountUp from "../components/reactbits/CountUp";
import GradientASCII from "../components/reactbits/GradientAsciiBackground";

const HERO_COLORS = ["#04060f", "#16265f", "#3d55d6", "#2fbfae", "#7f9cf5"];

const ROUTES = [
  {
    mode: "cinema",
    index: "01",
    title: "影视图",
    copy: "把故事拆成能独立生成的镜头：先定机位、连续性和可见动作，再写提示词。1 / 3 / 9 镜，电影画幅。",
    skill: "Cinema DNA",
    to: "/new?mode=cinema",
  },
  {
    mode: "ecommerce",
    index: "02",
    title: "电商图",
    copy: "按主图与详情页的任务排图：一套图共用同一个视觉系统，12 张固定 5 张 1:1 + 7 张 2:3。",
    skill: "E-commerce Visual",
    to: "/new?mode=ecommerce",
  },
  {
    mode: "auto",
    index: "03",
    title: "自主决策",
    copy: "只描述目标，Agent 判断走影视还是电商，并替你定下数量、画幅与平台策略。",
    skill: "Agent 路由",
    to: "/new?mode=auto",
  },
  {
    mode: "video",
    index: "04",
    title: "视频",
    copy: "一条 5 秒或 10 秒的单镜片：Agent 先给 4 个方向，你选一个或写自己的想法，本机 H3 出片带声音。",
    skill: "Video Clip",
    to: "/new?video=1",
  },
];

type Route = (typeof ROUTES)[number];

function RouteCard({ item, delay }: { item: Route; delay: number }) {
  const spot = useSpotlight<HTMLAnchorElement>(true);

  return (
    <Reveal delay={delay}>
      <Link
        to={item.to}
        className="lp-card"
        ref={spot.ref}
        onPointerMove={spot.onPointerMove}
        onPointerLeave={spot.onPointerLeave}
      >
        <span className="lp-card-index">{item.index}</span>
        <h3 className="lp-card-title">{item.title}</h3>
        <p className="lp-card-copy">{item.copy}</p>
        <div className="lp-card-foot">
          <span>{item.skill}</span>
          <ArrowUpRight size={15} strokeWidth={1.8} aria-hidden="true" />
        </div>
      </Link>
    </Reveal>
  );
}

function Stat({
  value,
  suffix,
  label,
}: {
  value: number;
  suffix?: string;
  label: string;
}) {
  return (
    <div className="lp-stat">
      <div className="lp-stat-value">
        <CountUp to={value} duration={1.6} separator="," />
        {suffix ? <span className="lp-stat-suffix">{suffix}</span> : null}
      </div>
      <div className="lp-stat-label">{label}</div>
    </div>
  );
}

export function HomePage() {
  const navigate = useNavigate();
  const { health } = useHealth();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  usePageTitle();

  useEffect(() => {
    const controller = new AbortController();
    listProjects(12, 0, controller.signal)
      .then((payload) => setProjects(payload.items))
      .catch(() => {
        /* the gallery is decoration; the rest of the page still works */
      });
    return () => controller.abort();
  }, []);

  const skillsSpot = useSpotlight<HTMLDivElement>(false);

  const images = useMemo(
    () => projects.reduce((sum, item) => sum + item.done_count, 0),
    [projects],
  );
  const galleryItems = useMemo(
    () =>
      projects
        // The circular gallery decodes stills only: a clip would never load.
        .filter((item) => item.route !== "video")
        .filter((item) => item.cover_urls.length > 0)
        // Legacy e-commerce prompts carried the style-lock text into the image
        // itself (hex codes painted on the picture); keep the showcase clean.
        .filter(
          (item) =>
            !item.plan.shots.some((shot) =>
              shot.prompt.includes("Campaign Style Lock"),
            ),
        )
        .flatMap((item) =>
          item.cover_urls.slice(0, 4).map((url, position) => ({
            image: mediaUrl(url),
            text: item.title,
            description: `${routeLabel(item.route)} · 第 ${position + 1} 张`,
            alt: item.title,
            projectId: item.project_id,
          })),
        )
        .slice(0, 12),
    [projects],
  );

  return (
    <div className="lp">
      <div className="lp-noise" aria-hidden="true" />

      <section className="lp-hero">
        <div className="lp-hero-bg" aria-hidden="true">
          <GradientASCII
            colors={HERO_COLORS}
            shape="horizon"
            characters=" .:-=+*#%@"
            cellSize={22}
            density={0.5}
            glyphOpacity={0.62}
            glow={0.25}
            grain={0.14}
            speed={0.5}
            flow={0.85}
            softness={0.5}
            gradientOpacity={0.45}
            mouseInteraction
            clickEffect="wave"
            intro
          />
        </div>
        <div className="lp-hero-veil" aria-hidden="true" />

        <div className="lp-hero-inner">
          <Reveal>
            <span className="lp-eyebrow">
              <i aria-hidden="true" />
              本地图像工作台 · 规划在云端，出图在本机
            </span>
          </Reveal>

          <h1 className="lp-title" aria-label="把一句话变成能用的画面">
            <TechText
              text="把一句话"
              className="lp-tech"
              fontWeight={400}
              fontFamily='"Songti SC", "SimSun", "STSong", "Noto Serif CJK SC", serif'
              fontSize={170}
              letterSpacing={0.055}
              color="#f8faff"
              accentColor="#8ea9ff"
              reveal="letter"
              specks={20}
              labels={false}
              dashLength={3}
              dashGap={3}
              strokeWidth={1.2}
              intro="assemble"
              introDuration={2.2}
              speed={0.8}
              sweep={false}
            />
            <TechText
              text="变成能用的画面"
              className="lp-tech"
              fontWeight={400}
              fontFamily='"Songti SC", "SimSun", "STSong", "Noto Serif CJK SC", serif'
              fontSize={170}
              letterSpacing={0.055}
              color="#d9c7ff"
              accentColor="#5eead4"
              reveal="letter"
              specks={26}
              labels={false}
              dashLength={3}
              dashGap={3}
              strokeWidth={1.2}
              intro="assemble"
              introDuration={2.6}
              speed={0.9}
              sweep={false}
            />
          </h1>

          <Reveal delay={0.18}>
            <p className="lp-sub">
              影视分镜、电商图包，或者直接交给 Agent 判断。
              规划层把技能文档的规范原文交给模型，出图层交给你这张显卡——
              不排队、不虚构，失败就显示真实错误。
            </p>
          </Reveal>

          <Reveal delay={0.28}>
            <div className="lp-cta">
              <StarButton as={Link} to="/new">
                开始创作
                <ArrowRight size={16} strokeWidth={1.8} aria-hidden="true" />
              </StarButton>
              <StarButton as={Link} to="/library" variant="secondary">
                看已有项目
              </StarButton>
            </div>
          </Reveal>

          <Reveal delay={0.36}>
            <div className="lp-stats">
              <Stat value={health?.project_count ?? projects.length} label="项目" />
              <Stat value={images} label="本机出图" />
              <Stat value={health?.skills.length ?? 3} label="规划技能" />
              <Stat
                value={Math.round(health?.comfyui_vram_gb ?? 0)}
                suffix=" GB"
                label="显存"
              />
            </div>
          </Reveal>

          <span className="lp-hint">
            {health?.comfyui_reachable
              ? `ComfyUI ${health.comfyui_version} 在线 · ${health.deepseek_model} 规划`
              : "ComfyUI 未连接 · 设置页可以一键启动"}
          </span>

          <div className="lp-scroll" aria-hidden="true">
            <span />
            scroll
          </div>
        </div>
      </section>

      <div className="lp-loop" aria-hidden="true">
        <TextLoop
          text="Cinema DNA ✦ E-commerce Visual ✦ Agent Routing ✦ Local ComfyUI ✦ Z-Image Turbo ✦ 8 GB 显存"
          shape="line"
          speed={130}
          fontSize={30}
          fontWeight={700}
          letterSpacing={2}
          separator="✦"
          ribbon
          ribbonColor="#191d33"
          ribbonWidth={58}
          tilt={-1.2}
          edgeFade={0.5}
          color="#d3e1ff"
          draggable
          pauseOnHover={false}
        />
      </div>

      <section className="lp-section" data-ghost="01">
        <Reveal>
          <div className="lp-section-head">
            <span className="lp-kicker">Routes</span>
            <h2 className="lp-section-title">四种走法，同一种交付</h2>
            <p className="lp-section-copy">
              不管走哪条路，产出的都是一份可编辑的方案：提示词、负向词、画幅、状态，
              以及真正落在磁盘上的图片或视频。
            </p>
          </div>
        </Reveal>

        <div className="lp-grid">
          {ROUTES.map((item, index) => (
            <RouteCard key={item.mode} item={item} delay={0.06 * index} />
          ))}
        </div>
      </section>

      <section className="lp-section" data-ghost="02">
        <Reveal>
          <div className="lp-section-head">
            <span className="lp-kicker">Skills</span>
            <h2 className="lp-section-title">提示词不是模板，是技能</h2>
            <p className="lp-section-copy">
              仓库里随包的是三份真实技能文档，规划时把规范原文交给模型，
              而不是让 Python 拼一段看起来专业的句子。
            </p>
          </div>
        </Reveal>
        <Reveal>
          <div
            className="lp-skills"
            ref={skillsSpot.ref}
            onPointerMove={skillsSpot.onPointerMove}
            onPointerLeave={skillsSpot.onPointerLeave}
          >
            <div className="lp-skills-head">
              <span>已加载 {health?.skills.length ?? 0} 份技能</span>
              <span>SKILL.md · 运行时读取</span>
            </div>
            {(health?.skills ?? []).map((skill, index) => (
              <div className="lp-skill" key={skill.id}>
                <span className="lp-skill-index">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span className="lp-skill-name">{skill.label}</span>
                <span className="lp-skill-src">{skill.source || "本地技能"}</span>
                <span className="lp-skill-ver">{skill.version}</span>
                <span className="lp-skill-arrow" aria-hidden="true">
                  <ArrowUpRight size={14} strokeWidth={1.8} />
                </span>
              </div>
            ))}
          </div>
        </Reveal>
      </section>

      <section className="lp-section" data-ghost="03">
        <Reveal>
          <div className="lp-section-head">
            <span className="lp-kicker">Output</span>
            <h2 className="lp-section-title">这张显卡出过的图</h2>
            <p className="lp-section-copy">
              每一张都是本机 ComfyUI 跑出来的原图，失败的那几张也在项目里留着真实报错。
            </p>
          </div>
        </Reveal>

        {galleryItems.length > 0 ? (
          <Reveal>
            <div className="lp-carousel">
              <CircularGalleryBand
                items={galleryItems}
                bend={2.6}
                itemSize={0.92}
                itemAspect={0.8}
                gap={0.22}
                borderRadius={0.055}
                wave={0.8}
                fadeEdges={0.13}
                shadow={0.35}
                scrollEase={0.06}
                autoScroll={0.18}
                openOnClick={false}
                textColor="#e9eefc"
                font="500 26px 'Instrument Serif', 'Songti SC', serif"
                onItemClick={(item: { projectId: string }) =>
                  navigate(`/projects/${item.projectId}`)
                }
              />
            </div>
          </Reveal>
        ) : (
          <div className="lp-gallery">
            {[0, 1, 2, 3].map((index) => (
              <div className="lp-tile lp-tile-empty" key={index}>
                还没有成品图
              </div>
            ))}
          </div>
        )}
      </section>

      <Reveal>
        <section className="lp-band">
          <span className="lp-kicker">Start</span>
          <h2 className="lp-band-title">下一步，从一句话开始。</h2>
          <p className="lp-band-copy">
            写清楚要什么、给谁看、在哪个平台用。剩下的路线、数量、画幅和提示词，
            交给技能和 Agent。
          </p>
          <StarButton as={Link} to="/new">
            <Sparkles size={16} strokeWidth={1.8} aria-hidden="true" />
            写第一句话
          </StarButton>
        </section>
      </Reveal>

      <div className="lp-foot">
        <span>Lunar Studio · 露娜</span>
        <span>规划在云端，出图在本机</span>
      </div>
    </div>
  );
}
