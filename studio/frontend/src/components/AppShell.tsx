import type { ReactNode } from "react";
import { NavLink, Link, useLocation } from "react-router-dom";
import { Menu, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion, useScroll, useSpring } from "motion/react";
import { useHealth } from "../lib/health";
import { Brand } from "./Brand";

const NAV = [
  { to: "/", label: "首页", end: true },
  { to: "/library", label: "项目", end: false },
  { to: "/settings", label: "设置", end: false },
];

function modelLabel(
  loading: boolean,
  reachable: boolean | undefined,
  failed: boolean,
): string {
  if (loading) return "检查模型";
  if (failed) return "API 未连接";
  return reachable ? "本地模型在线" : "本地模型离线";
}

export function AppShell({ children }: { children: ReactNode }) {
  const { health, loading, error } = useHealth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const location = useLocation();
  const isHome = location.pathname === "/";
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, {
    stiffness: 140,
    damping: 30,
    restDelta: 0.001,
  });

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);

  useEffect(() => {
    if (!isHome) {
      setScrolled(false);
      return;
    }
    const onScroll = () => setScrolled(window.scrollY > 18);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [isHome]);

  useEffect(() => {
    if (!menuOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const online = health?.comfyui_reachable;
  const dotClass = error
    ? "dot dot-neutral"
    : online
      ? "dot dot-on"
      : loading
        ? "dot dot-neutral"
        : "dot dot-off";
  const label = modelLabel(loading, online, Boolean(error));
  const topbarClass = [
    "topbar",
    isHome ? "topbar-home" : "",
    isHome && !scrolled && !menuOpen ? "is-overlay" : "",
    menuOpen ? "topbar-menu" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={`shell${isHome ? " shell-home" : ""}`}>
      <motion.div
        className="scroll-progress"
        style={{ scaleX: progress }}
        aria-hidden="true"
      />
      <header className={topbarClass}>
        <div className="topbar-inner">
          <Brand />
          <nav className="nav" aria-label="主导航">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? "active" : "")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="topbar-actions">
            <span className="model-status" title={health?.comfyui_error || label}>
              <span className={dotClass} aria-hidden="true" />
              <span className="model-status-label">{label}</span>
            </span>
            <Link to="/new" className="btn btn-secondary btn-sm topbar-new">
              <Plus size={15} strokeWidth={1.8} aria-hidden="true" />
              新建创作
            </Link>
            <button
              type="button"
              className="menu-button"
              aria-label={menuOpen ? "关闭菜单" : "打开菜单"}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((value) => !value)}
            >
              {menuOpen ? (
                <X size={20} strokeWidth={1.8} />
              ) : (
                <Menu size={20} strokeWidth={1.8} />
              )}
            </button>
          </div>
        </div>
      </header>

      {menuOpen ? (
        <div className="menu-sheet">
          <nav className="menu-nav" aria-label="移动导航">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => (isActive ? "active" : "")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <Link to="/new" className="btn btn-primary menu-cta">
            <Plus size={16} strokeWidth={1.8} aria-hidden="true" />
            新建创作
          </Link>
          <div className="menu-foot">
            <p className="menu-status">
              <span className={dotClass} aria-hidden="true" />
              {label}
            </p>
            <p className="menu-status">规划在云端，出图在本机</p>
          </div>
        </div>
      ) : null}

      <main className={isHome ? "main main-home" : "main"}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={reduced ? false : { opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? undefined : { opacity: 0, y: -12 }}
            transition={{ duration: 0.38, ease: [0.22, 1, 0.36, 1] }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </main>

      {!isHome ? (
        <footer className="footer">
          <span>Lunar Studio · 露娜</span>
          <span>规划在云端，出图在本机</span>
        </footer>
      ) : null}
    </div>
  );
}
