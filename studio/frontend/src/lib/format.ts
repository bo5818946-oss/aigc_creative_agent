import type {
  Mode,
  Project,
  ProjectStatus,
  RenderRecord,
  RenderStatus,
  Route,
  Shot,
  ShotStatus,
} from "./api";

const NUMBER = new Intl.NumberFormat("zh-CN");

const DATE_TIME = new Intl.DateTimeFormat("zh-CN", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const DATE_LONG = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "long",
});

export function formatNumber(value: number): string {
  return NUMBER.format(value);
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return DATE_TIME.format(date);
}

export function formatDateLong(date = new Date()): string {
  return DATE_LONG.format(date);
}

export function greetingWord(date = new Date()): string {
  const hour = date.getHours();
  if (hour >= 5 && hour < 11) return "早上好";
  if (hour >= 11 && hour < 13) return "中午好";
  if (hour >= 13 && hour < 18) return "下午好";
  return "晚上好";
}

export function routeLabel(route: Route): string {
  if (route === "video") return "视频";
  return route === "cinema" ? "影视图" : "电商图";
}

export function shotUnit(route: Route): string {
  if (route === "video") return "条";
  return route === "cinema" ? "镜" : "张";
}

export function shotNoun(route: Route): string {
  if (route === "video") return "片段";
  return route === "cinema" ? "镜头" : "图片";
}

export function modeLabel(mode: Mode): string {
  if (mode === "auto") return "自主决策";
  if (mode === "cinema") return "影视图";
  return "电商图";
}

type AnyStatus = ProjectStatus | ShotStatus | RenderStatus;

export function statusLabel(status: AnyStatus): string {
  switch (status) {
    case "planned":
      return "待生成";
    case "queued":
      return "排队中";
    case "running":
      return "生成中";
    case "rendering":
      return "生成中";
    case "done":
      return "已出图";
    case "partial":
      return "部分完成";
    case "failed":
      return "失败";
    default:
      return status;
  }
}

export function statusTone(
  status: AnyStatus,
): "positive" | "negative" | "working" | "neutral" {
  if (status === "done") return "positive";
  if (status === "failed") return "negative";
  if (status === "rendering" || status === "queued" || status === "running")
    return "working";
  return "neutral";
}

export function projectStatusLabel(status: ProjectStatus): string {
  switch (status) {
    case "planned":
      return "待生成";
    case "rendering":
      return "生成中";
    case "done":
      return "已完成";
    case "partial":
      return "部分完成";
    case "failed":
      return "全部失败";
    default:
      return status;
  }
}

const ASPECT_RATIOS: Record<string, string> = {
  "2.39:1": "2.39 / 1",
  "21:9": "21 / 9",
  "16:9": "16 / 9",
  "4:3": "4 / 3",
  "1:1": "1 / 1",
  "4:5": "4 / 5",
  "3:4": "3 / 4",
  "2:3": "2 / 3",
  "9:16": "9 / 16",
};

export function aspectRatio(aspect: string): string {
  return ASPECT_RATIOS[aspect] ?? "1 / 1";
}

export function renderFor(
  project: Project,
  shotIndex: number,
): RenderRecord | undefined {
  return project.renders.find((render) => render.shot_index === shotIndex);
}

export function shotState(
  shot: Shot,
  render: RenderRecord | undefined,
): ShotStatus | RenderStatus {
  return render?.status ?? shot.status;
}

export function errorFromProject(project: Project): string {
  return (
    project.renders.find((render) => render.error)?.error ??
    project.plan.warnings[0] ??
    ""
  );
}

/** 数字秒 -> m:ss，用于渲染计时。 */
export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}