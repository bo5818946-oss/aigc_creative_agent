import type { ReactNode } from "react";
import { AlertCircle, AlertTriangle, Info } from "lucide-react";

type Tone = "error" | "warning" | "info";

export function Callout({
  tone = "error",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: ReactNode;
}) {
  const Icon =
    tone === "error" ? AlertCircle : tone === "warning" ? AlertTriangle : Info;
  return (
    <div className={`callout callout-${tone}`} role={tone === "error" ? "alert" : undefined}>
      <Icon size={16} strokeWidth={1.7} aria-hidden="true" />
      <div className="callout-body">
        {title ? <p className="callout-title">{title}</p> : null}
        <div className="callout-text">{children}</div>
      </div>
    </div>
  );
}
