export type Mode = "cinema" | "ecommerce" | "auto" | "video";
export type Route = "cinema" | "ecommerce" | "video";
export type VideoSeconds = 5 | 10;
export type ShotStatus = "planned" | "queued" | "running" | "done" | "failed";
export type ProjectStatus =
  | "planned"
  | "rendering"
  | "done"
  | "partial"
  | "failed";
export type RenderStatus = "queued" | "running" | "done" | "failed";

export interface Shot {
  index: number;
  title: string;
  purpose: string;
  prompt: string;
  negative: string;
  camera: string;
  caption: string;
  notes: string;
  aspect: string;
  seconds: number;
  status: ShotStatus;
}

export interface AgentDecision {
  route?: Route;
  reasoning?: string;
  params?: Record<string, unknown>;
  title_hint?: string;
  warnings?: string[];
  [key: string]: unknown;
}

export interface Plan {
  kind: "image" | "video";
  mode: Mode;
  route: Route;
  title: string;
  summary: string;
  reasoning: string;
  style_lock: string;
  continuity: string;
  aspect: string;
  shots: Shot[];
  warnings: string[];
  skill: string;
  skill_version: string;
  template: string;
  agent_decision: AgentDecision;
  created_at: string;
}

export interface RenderRecord {
  render_id: string;
  project_id: string;
  shot_index: number;
  status: RenderStatus;
  file_url: string;
  error: string;
  prompt_id: string;
  width: number;
  height: number;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Project {
  project_id: string;
  title: string;
  mode: Mode;
  route: Route;
  brief: string;
  plan: Plan;
  reference_id: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  render_count: number;
  done_count: number;
  failed_count: number;
  cover_urls: string[];
  renders: RenderRecord[];
}

export type ProjectSummary = Omit<Project, "renders">;

export interface ProjectList {
  items: ProjectSummary[];
  total: number;
}

export interface UploadRecord {
  upload_id: string;
  filename: string;
  mime: string;
  url: string;
  created_at: string;
}

export interface SkillInfo {
  id: string;
  label: string;
  version: string;
  source: string;
}

export interface Health {
  deepseek_configured: boolean;
  deepseek_model: string;
  comfyui_configured: boolean;
  comfyui_url: string;
  comfyui_reachable: boolean;
  comfyui_version: string;
  comfyui_devices: string[];
  comfyui_vram_gb: number;
  comfyui_error: string;
  skills: SkillInfo[];
  project_count: number;
  launch_configured: boolean;
}

export interface PlanPayload {
  mode: Mode;
  brief: string;
  reference_id: string | null;
  reference_role: string;
  aspect: string | null;
  shot_count: number | null;
  pack_size: number | null;
  product_name: string | null;
  platform: string | null;
  language: "zh";
}

export interface PlanEvent {
  stage: string;
  message: string;
  route?: Route;
  reasoning?: string;
  params?: Record<string, unknown>;
  project?: Project;
  usage?: Record<string, number>;
  kind?: string;
}

export interface RenderStartResponse {
  project_id: string;
  queued: number[];
  project: Project | null;
}

export interface ComfyStartResponse {
  ok: boolean;
  message: string;
  pid?: number | null;
}

export interface ShotPatch {
  title?: string;
  purpose?: string;
  prompt?: string;
  negative?: string;
  camera?: string;
  caption?: string;
  notes?: string;
}

async function readError(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const payload = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
    };
    const detail = payload.detail ?? payload.message;
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (item && typeof item === "object") {
            const record = item as { loc?: unknown[]; msg?: string };
            const location = Array.isArray(record.loc)
              ? record.loc.filter((part) => part !== "body").join(".")
              : "";
            return [location, record.msg].filter(Boolean).join(": ");
          }
          return String(item);
        })
        .filter(Boolean)
        .join("；");
    }
    if (detail !== undefined && detail !== null) return String(detail);
    return text || `HTTP ${response.status}`;
  } catch {
    return text || `HTTP ${response.status}`;
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

async function sendJson<T>(
  path: string,
  method: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return getJson<Health>("/api/health", signal);
}

export function listProjects(
  limit = 100,
  offset = 0,
  signal?: AbortSignal,
): Promise<ProjectList> {
  return getJson<ProjectList>(
    `/api/projects?limit=${limit}&offset=${offset}`,
    signal,
  );
}

export function getProject(
  projectId: string,
  signal?: AbortSignal,
): Promise<Project> {
  return getJson<Project>(
    `/api/projects/${encodeURIComponent(projectId)}`,
    signal,
  );
}

export async function uploadReference(
  file: File,
  signal?: AbortSignal,
): Promise<UploadRecord> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/uploads", {
    method: "POST",
    body: form,
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as UploadRecord;
}

export function createPlan(payload: PlanPayload): Promise<Project> {
  return sendJson<Project>("/api/plan", "POST", payload);
}

export async function streamPlan(
  payload: PlanPayload,
  onEvent: (event: PlanEvent) => void,
  signal?: AbortSignal,
): Promise<Project> {
  const response = await fetch("/api/plan/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) throw new Error(await readError(response));
  if (!response.body) throw new Error("当前浏览器不支持流式响应。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let project: Project | null = null;
  let failure = "";

  const handleBlock = (block: string) => {
    if (!block.trim()) return;
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (!data.length) return;
    let parsed: PlanEvent;
    try {
      parsed = JSON.parse(data.join("\n")) as PlanEvent;
    } catch {
      return;
    }
    if (event === "error") {
      failure = parsed.message || "规划失败，但没有返回原因。";
      return;
    }
    if (event === "result" && parsed.project) {
      project = parsed.project;
      onEvent(parsed);
      return;
    }
    if (event === "status" || event === "open") onEvent(parsed);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf("\n\n");
    while (cut >= 0) {
      handleBlock(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      cut = buffer.indexOf("\n\n");
    }
    if (failure) {
      await reader.cancel().catch(() => undefined);
      break;
    }
  }

  if (failure) throw new Error(failure);
  if (!project) throw new Error("规划流已经结束，但没有收到项目结果。");
  return project;
}

export async function startRender(
  projectId: string,
  shotIndices: number[] | null,
): Promise<RenderStartResponse> {
  return sendJson<RenderStartResponse>(
    `/api/projects/${encodeURIComponent(projectId)}/render`,
    "POST",
    { shot_indices: shotIndices },
  );
}

export function patchShot(
  projectId: string,
  shotIndex: number,
  patch: ShotPatch,
): Promise<Project> {
  return sendJson<Project>(
    `/api/projects/${encodeURIComponent(projectId)}/shots/${shotIndex}`,
    "PATCH",
    patch,
  );
}

export function repromptProject(projectId: string): Promise<Project> {
  return sendJson<Project>(
    `/api/projects/${encodeURIComponent(projectId)}/reprompt`,
    "POST",
    {},
  );
}

export async function startComfy(): Promise<ComfyStartResponse> {
  const response = await fetch("/api/comfy/start", { method: "POST" });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as ComfyStartResponse;
}

export function exportUrl(projectId: string): string {
  return `/api/projects/${encodeURIComponent(projectId)}/export`;
}

export function mediaUrl(url: string): string {
  return url || "";
}

// ---------------------------------------------------------------------------
// Video: four directions, one clip
// ---------------------------------------------------------------------------

export interface VideoConcept {
  concept_id: string;
  title: string;
  logline: string;
  treatment: string;
  prompt: string;
  negative: string;
  sound: string;
  risk: string;
}

export interface ConceptList {
  concepts: VideoConcept[];
  duration: VideoSeconds;
  aspect: string;
  skill: string;
  skill_version: string;
}

export interface ConceptPayload {
  brief: string;
  duration: VideoSeconds;
  aspect: string;
}

export function proposeVideoConcepts(
  payload: ConceptPayload,
  signal?: AbortSignal,
): Promise<ConceptList> {
  return sendJson<ConceptList>("/api/video/concepts", "POST", payload, signal);
}

export interface CustomConceptPayload extends ConceptPayload {
  direction: string;
}

export function draftVideoConcept(
  payload: CustomConceptPayload,
): Promise<VideoConcept> {
  return sendJson<VideoConcept>("/api/video/draft", "POST", payload);
}

export interface VideoProjectPayload extends ConceptPayload {
  concept: VideoConcept;
}

export function createVideoProject(
  payload: VideoProjectPayload,
): Promise<Project> {
  return sendJson<Project>("/api/video/projects", "POST", payload);
}

export function reviseVideo(
  projectId: string,
  feedback: string,
): Promise<Project> {
  return sendJson<Project>(
    `/api/projects/${encodeURIComponent(projectId)}/video/revise`,
    "POST",
    { feedback },
  );
}
// ---------------------------------------------------------------------------
// Live render progress
// ---------------------------------------------------------------------------

export interface RenderProgressItem {
  shot_index: number;
  status: "queued" | "running" | "done" | "failed";
  phase: "queued" | "running" | "finishing";
  value: number;
  max: number;
  percent: number;
  elapsed_seconds: number;
  eta_seconds: number | null;
  connected: boolean;
}

export interface RenderProgress {
  active: boolean;
  items: RenderProgressItem[];
}

export function getProjectProgress(
  projectId: string,
  signal?: AbortSignal,
): Promise<RenderProgress> {
  return getJson<RenderProgress>(
    `/api/projects/${encodeURIComponent(projectId)}/progress`,
    signal,
  );
}