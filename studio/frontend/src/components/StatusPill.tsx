import type {
  ProjectStatus,
  RenderStatus,
  ShotStatus,
} from "../lib/api";
import { statusLabel, statusTone } from "../lib/format";

type AnyStatus = ProjectStatus | ShotStatus | RenderStatus;

export function StatusPill({
  status,
  label,
}: {
  status: AnyStatus;
  label?: string;
}) {
  const tone = statusTone(status);
  return (
    <span className={`pill pill-${tone}`}>
      {tone === "working" ? (
        <span className="pill-dot" aria-hidden="true" />
      ) : null}
      {label ?? statusLabel(status)}
    </span>
  );
}
