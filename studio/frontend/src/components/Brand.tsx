import { Link } from "react-router-dom";

export function Brand() {
  return (
    <Link to="/" className="brand" aria-label="Lunar Studio 首页">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" role="presentation">
          <defs>
            <linearGradient
              id="lunar-mark-fill"
              x1="4"
              y1="4"
              x2="28"
              y2="28"
              gradientUnits="userSpaceOnUse"
            >
              <stop offset="0" stopColor="#a9bcff" />
              <stop offset="0.55" stopColor="#b388ff" />
              <stop offset="1" stopColor="#5eead4" />
            </linearGradient>
            <mask id="lunar-mark-cut">
              <rect width="32" height="32" fill="#ffffff" />
              <circle cx="22.5" cy="9.5" r="10.5" fill="#000000" />
            </mask>
          </defs>
          <circle
            cx="16"
            cy="16"
            r="11.5"
            fill="url(#lunar-mark-fill)"
            mask="url(#lunar-mark-cut)"
          />
          <circle cx="23.4" cy="23.2" r="1.2" fill="#9fb7ff" />
        </svg>
      </span>
      <span className="brand-name">Lunar</span>
      <span className="brand-sub">露娜</span>
    </Link>
  );
}
