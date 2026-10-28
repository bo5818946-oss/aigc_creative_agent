// @ts-nocheck
// Typed entry point for the vendored React Bits StarBorder, themed for Lunar.
// `style` has no default upstream, so the wrapper supplies it.
import type { ReactNode } from "react";
import StarBorder from "./reactbits/StarBorder";

type StarButtonProps = {
  children: ReactNode;
  variant?: "primary" | "secondary";
  className?: string;
  as?: unknown;
} & Record<string, unknown>;

export function StarButton({
  children,
  variant = "primary",
  className = "",
  ...rest
}: StarButtonProps) {
  return (
    <StarBorder
      className={`star-btn star-btn-${variant} ${className}`.trim()}
      color={variant === "primary" ? "#ffffff" : "#dbe4ff"}
      trailColor={variant === "primary" ? "#ffffff" : "#8ea9ff"}
      duration={4.5}
      stars={1}
      trailLength={0.34}
      thickness={1}
      radius={999}
      glow={variant === "primary" ? 0.7 : 0.4}
      hover="brighten"
      sparkle={variant === "primary"}
      theme="dark"
      backgroundColor={variant === "primary" ? "linear-gradient(135deg, #8ea9ff 0%, #b388ff 52%, #5eead4 100%)" : "rgba(255,255,255,0.04)"}
      textColor={variant === "primary" ? "#0a0b12" : "#f8faff"}
      borderColor="rgba(255, 255, 255, 0.16)"
      style={undefined}
      {...rest}
    >
      {children}
    </StarBorder>
  );
}

export default StarButton;
