import { useRef } from "react";

type SpotlightHandlers<T extends HTMLElement> = {
  ref: React.RefObject<T | null>;
  onPointerMove: (event: React.PointerEvent<T>) => void;
  onPointerLeave: () => void;
};

/**
 * Feed a card the pointer position as CSS variables so a radial highlight can
 * follow the cursor, optionally tilting the card in 3D.
 */
export function useSpotlight<T extends HTMLElement = HTMLDivElement>(
  tilt = true,
): SpotlightHandlers<T> {
  const ref = useRef<T>(null);

  const onPointerMove = (event: React.PointerEvent<T>) => {
    const node = ref.current;
    if (!node) return;
    const rect = node.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    node.style.setProperty("--mx", `${x}px`);
    node.style.setProperty("--my", `${y}px`);
    if (tilt) {
      node.style.setProperty("--rx", `${(0.5 - y / rect.height) * 6}deg`);
      node.style.setProperty("--ry", `${(x / rect.width - 0.5) * 8}deg`);
    }
  };

  const onPointerLeave = () => {
    const node = ref.current;
    if (!node) return;
    node.style.setProperty("--rx", "0deg");
    node.style.setProperty("--ry", "0deg");
  };

  return { ref, onPointerMove, onPointerLeave };
}
