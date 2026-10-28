// @ts-nocheck
// ElectricBorder wrapper for form fields: the current only runs while the field
// has focus, so idle inputs stay quiet.
import type { ReactNode } from "react";
import ElectricBorder from "./reactbits/ElectricBorder";

type ElectricFieldProps = {
  children: ReactNode;
  active?: boolean;
  className?: string;
};

export function ElectricField({ children, active = true, className = "" }: ElectricFieldProps) {
  return (
    <ElectricBorder
      color="#8ea9ff"
      glowColor="#b388ff"
      speed={1.1}
      chaos={0.5}
      spread={0.55}
      strands={3}
      thickness={1.4}
      glow={0.6}
      intensity={0.75}
      arcs={0.7}
      flicker={0.4}
      borderRadius={14}
      offset={2}
      active={active}
      intro
      interactive
      theme="dark"
      className={`electric-field ${className}`.trim()}
      style={undefined}
    >
      {children}
    </ElectricBorder>
  );
}

export default ElectricField;
