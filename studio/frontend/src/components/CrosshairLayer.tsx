// @ts-nocheck
// Crosshair overlay themed for Lunar. Rendered without a container ref, so the
// reticle covers the whole viewport instead of a single content box.
import Crosshair from "./reactbits/Crosshair";

export function CrosshairLayer() {
  return (
    <Crosshair
      color="#8ea9ff"
      thickness={1}
      opacity={0.6}
      gap={10}
      fade={0.25}
      smoothing={0.26}
      showCoordinates
      targetEffect="lock"
      targetSelector="a, button, input, textarea, .lp-card, .lp-tile, [data-crosshair-target]"
      blendMode="normal"
      style={undefined}
    />
  );
}

export default CrosshairLayer;
