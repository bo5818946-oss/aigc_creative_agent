// @ts-nocheck
// Typed entry point for the vendored CircularGallery. Upstream exposes `style`
// without a default, which makes the inferred signature demand it.
import CircularGallery from "./CircularGallery";

export function CircularGalleryBand(props: Record<string, unknown>) {
  return <CircularGallery {...props} style={undefined} />;
}

export default CircularGalleryBand;
