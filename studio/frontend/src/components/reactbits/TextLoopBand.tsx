// @ts-nocheck
// Typed entry point for the vendored TextLoop band. Upstream is untyped and
// exposes two props without defaults; this wrapper supplies them.
import TextLoop from "./TextLoop";

export function TextLoopBand(props: Record<string, unknown>) {
  return <TextLoop {...props} crossColor={undefined} path={undefined} />;
}

export default TextLoopBand;
