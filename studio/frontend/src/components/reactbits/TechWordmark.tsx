// @ts-nocheck
// Typed entry point for the vendored TechText wordmark. Upstream is untyped and
// exposes two props without defaults, which makes the inferred signature demand
// them; this wrapper keeps the call sites clean.
import TechText from "./TechText";

export function TechWordmark(props: Record<string, unknown>) {
  return <TechText {...props} style={undefined} />;
}

export default TechWordmark;
