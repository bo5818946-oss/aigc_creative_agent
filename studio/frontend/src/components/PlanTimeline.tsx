import { Check } from "lucide-react";
import type { PlanEvent } from "../lib/api";
import { Callout } from "./Callout";

export function PlanTimeline({
  events,
  error,
  running,
}: {
  events: PlanEvent[];
  error: string;
  running: boolean;
}) {
  return (
    <div className="plan-timeline" aria-live="polite">
      <ol className="timeline">
        {events.length === 0 && running ? (
          <li className="timeline-item timeline-active">
            <span className="timeline-dot" aria-hidden="true" />
            <span>正在建立规划通道</span>
          </li>
        ) : null}
        {events.map((event, index) => {
          const active = running && index === events.length - 1;
          return (
            <li
              className={`timeline-item${active ? " timeline-active" : ""}`}
              key={`${event.stage}-${index}`}
            >
              <span className="timeline-marker" aria-hidden="true">
                {active ? (
                  <span className="timeline-dot" />
                ) : (
                  <Check size={13} strokeWidth={2} />
                )}
              </span>
              <span>
                <span className="timeline-message">{event.message}</span>
                {event.stage === "routing" && event.reasoning ? (
                  <span className="timeline-detail">{event.reasoning}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ol>
      {running ? (
        <p className="timeline-wait">
          正在等待模型返回。规划通常需要几十秒，这里只显示后端真实回传的阶段。
        </p>
      ) : null}
      {error ? (
        <Callout title="规划没有完成">
          <span className="pre-wrap">{error}</span>
        </Callout>
      ) : null}
    </div>
  );
}
