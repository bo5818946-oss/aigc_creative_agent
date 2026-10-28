const VIDEO = /\.(mp4|webm|mov|mkv)$/i;

/**
 * Covers can be images or clips. A clip renders as a muted video element so the
 * browser paints its first frame instead of a broken image icon.
 */
export function MediaThumb({
  src,
  alt,
  className,
}: {
  src: string;
  alt?: string;
  className?: string;
}) {
  if (VIDEO.test(src)) {
    return (
      <video
        className={className}
        src={src}
        muted
        playsInline
        preload="metadata"
        aria-label={alt}
      />
    );
  }
  return <img className={className} src={src} alt={alt ?? ""} loading="lazy" />;
}

export function isVideoUrl(url: string): boolean {
  return VIDEO.test(url);
}

export default MediaThumb;
