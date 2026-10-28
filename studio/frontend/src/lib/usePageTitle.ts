import { useEffect } from "react";

export function usePageTitle(title?: string): void {
  useEffect(() => {
    document.title = title
      ? `${title} · Lunar Studio`
      : "Lunar Studio · 露娜";
  }, [title]);
}
