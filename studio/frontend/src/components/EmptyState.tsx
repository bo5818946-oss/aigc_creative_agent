import type { ReactNode } from "react";
import { Link } from "react-router-dom";

export function EmptyState({
  title,
  children,
  actionLabel,
  actionTo,
  after,
  className,
}: {
  title: string;
  children: ReactNode;
  actionLabel?: string;
  actionTo?: string;
  after?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`empty-state${className ? ` ${className}` : ""}`}>
      <p className="empty-title">{title}</p>
      <div className="empty-copy">{children}</div>
      {actionLabel && actionTo ? (
        <Link to={actionTo} className="btn btn-secondary btn-sm">
          {actionLabel}
        </Link>
      ) : null}
      {after}
    </div>
  );
}
