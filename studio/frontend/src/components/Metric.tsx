import type { ReactNode } from "react";

export function Metric({
  label,
  value,
  caption,
  status,
}: {
  label: string;
  value: string;
  caption: ReactNode;
  status?: "online" | "offline" | "unknown";
}) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value${status ? " metric-value-status" : ""}`}>
        {status ? (
          <span
            className={`dot ${
              status === "online"
                ? "dot-on"
                : status === "offline"
                  ? "dot-off"
                  : "dot-neutral"
            }`}
            aria-hidden="true"
          />
        ) : null}
        {value}
      </span>
      <span className="metric-caption">{caption}</span>
    </div>
  );
}
