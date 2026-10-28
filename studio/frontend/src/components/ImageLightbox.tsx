import { useEffect } from "react";
import { ChevronLeft, ChevronRight, Download, X } from "lucide-react";

export type LightboxItem = {
  shotIndex: number;
  src: string;
  title: string;
  caption: string;
  download: string;
};

export function ImageLightbox({
  items,
  index,
  onIndex,
  onClose,
}: {
  items: LightboxItem[];
  index: number;
  onIndex: (next: number) => void;
  onClose: () => void;
}) {
  const item = items[index];
  const count = items.length;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "ArrowLeft" && count > 1) {
        onIndex((index - 1 + count) % count);
      } else if (event.key === "ArrowRight" && count > 1) {
        onIndex((index + 1) % count);
      }
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [count, index, onClose, onIndex]);

  if (!item) return null;

  return (
    <div
      className="lightbox"
      role="dialog"
      aria-modal="true"
      aria-label={item.title}
      onClick={onClose}
    >
      <div
        className="lightbox-inner"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="lightbox-bar">
          <div className="lightbox-heading">
            <strong>{item.title}</strong>
            <span>{item.caption}</span>
          </div>
          <div className="lightbox-actions">
            {count > 1 ? (
              <span className="lightbox-count tnum">
                {index + 1} / {count}
              </span>
            ) : null}
            <a className="lightbox-btn" href={item.src} download={item.download}>
              <Download size={15} strokeWidth={1.8} aria-hidden="true" />
              下载这张
            </a>
            <button
              type="button"
              className="lightbox-btn is-icon"
              onClick={onClose}
              aria-label="关闭"
            >
              <X size={16} strokeWidth={1.8} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="lightbox-stage">
          {count > 1 ? (
            <button
              type="button"
              className="lightbox-nav is-prev"
              onClick={() => onIndex((index - 1 + count) % count)}
              aria-label="上一张"
            >
              <ChevronLeft size={22} strokeWidth={1.6} aria-hidden="true" />
            </button>
          ) : null}
          <img src={item.src} alt={item.title} />
          {count > 1 ? (
            <button
              type="button"
              className="lightbox-nav is-next"
              onClick={() => onIndex((index + 1) % count)}
              aria-label="下一张"
            >
              <ChevronRight size={22} strokeWidth={1.6} aria-hidden="true" />
            </button>
          ) : null}
        </div>

        <p className="lightbox-hint">
          点空白处或按 Esc 关闭 · ← → 切换 · 下载只保存这一张
        </p>
      </div>
    </div>
  );
}

export default ImageLightbox;
